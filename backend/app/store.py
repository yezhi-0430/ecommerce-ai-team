import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)
LOCK = threading.RLock()
DB = DATA / "runs.sqlite3"

def init():
    with sqlite3.connect(DB) as db:
        db.execute("CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, state TEXT NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS room_messages (id TEXT PRIMARY KEY, run_id TEXT NOT NULL, room TEXT NOT NULL, role TEXT NOT NULL, kind TEXT NOT NULL, content TEXT NOT NULL, created_at INTEGER NOT NULL)")

def save(state):
    for event in state.get("events", []):
        event.setdefault("created_at", time.time_ns())
    with LOCK, sqlite3.connect(DB) as db:
        db.execute("INSERT OR REPLACE INTO runs VALUES (?, ?)", (state["id"], json.dumps(state, ensure_ascii=False)))

def get(run_id):
    with LOCK, sqlite3.connect(DB) as db:
        row = db.execute("SELECT state FROM runs WHERE id=?", (run_id,)).fetchone()
    return json.loads(row[0]) if row else None

def latest():
    with LOCK, sqlite3.connect(DB) as db:
        row = db.execute("SELECT state FROM runs ORDER BY rowid DESC LIMIT 1").fetchone()
    return json.loads(row[0]) if row else None

def add_room_message(run_id, room, role, kind, content):
    event = {"id":uuid.uuid4().hex, "room":room, "role":role, "kind":kind, "content":content, "created_at":time.time_ns(), "stage":"补充交流", "version":1, "simulated":False}
    with LOCK, sqlite3.connect(DB) as db:
        db.execute("INSERT INTO room_messages VALUES (?,?,?,?,?,?,?)", (event["id"], run_id, room, role, kind, content, event["created_at"]))
    return event

def room_messages(run_id, room=None):
    query = "SELECT id,room,role,kind,content,created_at FROM room_messages WHERE run_id=?"
    args = [run_id]
    if room is not None:
        query += " AND room=?"
        args.append(room)
    query += " ORDER BY created_at"
    with LOCK, sqlite3.connect(DB) as db:
        rows = db.execute(query, args).fetchall()
    return [{"id":r[0],"room":r[1],"role":r[2],"kind":r[3],"content":r[4],"created_at":r[5],"stage":"补充交流","version":1,"simulated":False} for r in rows]

def with_messages(state):
    if state is None:
        return None
    view = dict(state)
    events = list(state.get("events", [])) + room_messages(state["id"])
    view["events"] = sorted(events, key=lambda e: e.get("created_at", 0))
    return view

def recent(limit=20):
    with LOCK, sqlite3.connect(DB) as db:
        rows = db.execute("SELECT state FROM runs ORDER BY rowid DESC LIMIT ?", (min(max(limit, 1), 100),)).fetchall()
    states = [json.loads(row[0]) for row in rows]
    return [{"id":s["id"], "status":s.get("status"), "stage":s.get("stage"), "visual_test":bool(s.get("visual_test")), "product_name":s.get("product", {}).get("名称", "未命名商品")} for s in states]

init()
