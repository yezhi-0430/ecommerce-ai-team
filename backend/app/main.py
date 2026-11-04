import threading
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
from . import store, workflow
from .providers import OpenRouter
from .personas import persona_instruction
from .quality import check_claims, risky_design_claims

load_dotenv(Path(__file__).resolve().parents[2] / ".env")
app = FastAPI(title="电商 AI 团队")
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "testserver"])
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"], allow_methods=["GET", "POST"], allow_headers=["*"])
app.mount("/assets", StaticFiles(directory=store.DATA), name="assets")
@app.middleware("http")
async def protect_mutations(request: Request, call_next):
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        origin = request.headers.get("origin", "")
        if origin not in ("http://localhost:5173", "http://127.0.0.1:5173") or request.headers.get("x-local-app") != "ecommerce-team":
            return JSONResponse(status_code=403, content={"detail":"只允许本地工作台操作任务"})
    return await call_next(request)

RUNNING = set()
LOCK = threading.Lock()
PENDING = {}
LEADS = {"运营群":"运营 Lead", "作图群":"作图 Lead", "美工群":"美工 Lead", "询盘群":"客服 Lead"}

class ProductInput(BaseModel):
    name: str
    details: str = ""

class UserMessage(BaseModel):
    room: str
    content: str

def display_state(state):
    view = store.with_messages(state)
    if view:
        with LOCK:
            view["chat_pending"] = {room: count for (run_id, room), count in PENDING.items() if run_id == view["id"] and count}
    return view

def reply_to_user(run_id, room):
    key=(run_id, room)
    try:
        state=store.get(run_id)
        if not state: return
        combined=store.with_messages(state)
        messages=[e for e in combined.get("events", []) if e.get("room")==room and e.get("kind") in ("message", "user", "chat")]
        context="\n".join(f"{e['role']}: {e['content']}" for e in messages[-12:])
        role=LEADS[room]
        prompt=("这是用户在群聊中的补充交流。请回应用户当前想法，简洁说明建议；"
                "这只是交流，不代表修改了既有成果。用户的建议不能被当作已验证的商品事实。\n"
                f"商品资料：{state.get('product', {})}\n本群最近讨论：\n{context}")
        provider=OpenRouter()
        answer=provider.chat(workflow.system_for(state) + "\n" + persona_instruction(role), prompt)
        if not isinstance(answer, str) or not answer.strip(): raise ValueError("empty")
        risks=check_claims(answer, state["product"] if state.get("product_type") in ("tote", "custom") else None) + risky_design_claims(answer)
        if risks:
            answer=provider.chat(workflow.system_for(state) + "\n" + persona_instruction(role), prompt + "\n上一版包含未确认的信息，请只使用已知商品资料重答，未知信息明确说明尚未核实。不要杜撰任何对比数据、认证或承诺。")
            if not isinstance(answer,str) or not answer.strip() or check_claims(answer, state["product"] if state.get("product_type") in ("tote", "custom") else None) or risky_design_claims(answer):
                answer="你的想法已记录。部分商品信息仍需核实；我会以已确认的商品资料为依据，已生成的成果不会自动修改。"
        store.add_room_message(run_id, room, role, "chat", answer)
    except Exception:
        store.add_room_message(run_id, room, LEADS[room], "chat", "抱歉，我暂时无法回复，请稍后再试。已有消息已保存。")
    finally:
        with LOCK:
            PENDING[key]=max(0, PENDING.get(key,1)-1)

def launch(state):
    with LOCK:
        if state["id"] in RUNNING:
            raise HTTPException(409, "任务正在运行")
        RUNNING.add(state["id"])
        state["status"] = "running"
        store.save(state)
    def worker():
        try:
            workflow.run(state)
        finally:
            with LOCK:
                RUNNING.discard(state["id"])
    threading.Thread(target=worker, daemon=True).start()

def reconcile(state):
    if state and state["status"] == "running":
        with LOCK:
            if state["id"] not in RUNNING:
                state["status"] = "failed"
                state["error"] = "后台服务已重启，当前阶段中断，请重试。"
                store.save(state)
    return state

@app.get("/api/latest")
def latest():
    return display_state(reconcile(store.latest()))

@app.get("/api/runs")
def list_runs():
    return store.recent()

@app.get("/api/runs/{run_id}")
def get_run(run_id: str):
    state = store.get(run_id)
    if not state:
        raise HTTPException(404, "任务不存在")
    return display_state(reconcile(state))

@app.post("/api/runs")
def create_run():
    state = workflow.create()
    store.save(state)
    launch(state)
    return {"id":state["id"]}

@app.post("/api/custom-runs")
def create_custom_run(body: ProductInput):
    name, details = body.name.strip(), body.details.strip()
    if not name or len(name) > 80 or len(details) > 2000:
        raise HTTPException(422, "商品名称需为1到80字，商品信息最多2000字。")
    state = workflow.create("custom", {"名称":name, "已知信息":details or "未提供其他商品信息"})
    store.save(state)
    launch(state)
    return {"id":state["id"]}

@app.post("/api/demo/tote")
def create_tote_run():
    state = workflow.create("tote")
    store.save(state)
    launch(state)
    return {"id":state["id"]}

@app.post("/api/runs/{run_id}/retry")
def retry(run_id: str):
    state = store.get(run_id)
    if not state: raise HTTPException(404, "任务不存在")
    state = reconcile(state)
    if state["status"] != "failed":
        raise HTTPException(409, "只有失败的阶段可以重试")
    launch(state)
    return {"id":run_id}


@app.post("/api/runs/{run_id}/example")
def example(run_id: str):
    state = store.get(run_id)
    if not state: raise HTTPException(404, "任务不存在")
    try:
        workflow.use_example(state)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    launch(state)
    return {"id": run_id}


def start_reply(run_id, room):
    key=(run_id, room)
    with LOCK: PENDING[key]=PENDING.get(key,0)+1
    threading.Thread(target=reply_to_user,args=key,daemon=True).start()

@app.post("/api/runs/{run_id}/messages")
def send_message(run_id: str, body: UserMessage):
    state=store.get(run_id)
    if not state: raise HTTPException(404, "任务不存在")
    content=body.content.strip()
    if body.room not in LEADS or not content or len(content)>2000:
        raise HTTPException(422, "请选择群聊并输入 1 到 2000 字。")
    event=store.add_room_message(run_id, body.room, "你", "user", content)
    start_reply(run_id, body.room)
    return {"id":event["id"], "queued_for_workflow":state.get("status")=="running"}
