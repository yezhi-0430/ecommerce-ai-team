import json
import uuid
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont, ImageOps
from pathlib import Path
from . import store
from .providers import OpenRouter
from .quality import check_claims, risky_design_claims
from .personas import persona_instruction

PRODUCT = {"名称":"云行办公保温杯（虚构样品）", "容量":"500ml", "颜色":"雾蓝色", "材质":"不锈钢杯身", "价格":"79元", "已知信息":"圆柱形杯身，带杯盖；面向办公桌日常饮水的虚构样品。", "未知信息":"杯盖结构及开合方式、色号、保温时长、重量、是否防漏及认证均未知，禁止编造。"}
TOTE_PRODUCT = {"名称":"米色帆布手提袋（虚构样品）", "颜色":"米色", "材质":"帆布", "已知信息":"简洁袋身与手提带，适合日常搭配。", "未知信息":"尺寸、承重、内袋、拉链及洗涤方式均未知。"}
STAGES = ["运营初议", "作图反馈", "询盘反馈", "运营决策", "图片生成", "美工排版", "询盘回复", "交付质检"]
ROOMS = ["运营群", "作图群", "询盘群", "运营群", "作图群", "美工群", "询盘群", "美工群"]
ROLES = ["运营策划", "视觉策划", "询盘顾问", "运营 Lead", "作图 Lead", "美工 Lead", "客服 Lead", "质检员"]
TASKS = [
 "提出商品定位和两个卖点，形成初版任务单。只用已知事实，避免编造。",
 "审阅初版任务单，指出卖点能否被画面直观表现，必要时提出具体反对理由和改进建议。",
 "模拟潜在客户关心的问题，针对初版卖点提出不同意见。强调这是虚构假设，不是真实调查。",
 "结合初版任务单及作图、询盘反馈，决定维持还是调整卖点，解释取舍并输出最终任务单，明确商品事实、视觉方向及禁止的无依据宣传。不能为了制造冲突而强行修改。",
 "根据最终任务单写一段商品视觉风格方向，要求高级商业摄影、暗色背景和轮廓光；每张是单一画面，不拼图，不编造商品结构和参数。",
 "依据最终任务单和商品资料，写出主图标题（不超过12字）及简短说明，绝不增加未经证实的参数。",
 "根据最终任务单和商品事实生成三组模拟客户问答，未知答案应明确告知未知，不编造。",
 "检查最终任务单、主图文案和问答是否引用了未提供的参数或功效，指出需要人工核实的问题。"
]
SYSTEM = "你是电商团队成员。商品和客户都是虚构模拟。仅使用已提供的商品事实；未知信息不能推断为真实。杯盖结构、是否旋盖、开盖速度、色号、密封圈、不锈钢材质等级、是否食品级均未知，不得当作已知事实，禁止在图片或提示词里虚构它们。用简洁中文表述，决策必须说明理由。不要声称模拟反馈是真实调研。不要输出工具调用记录、接口细节或运行日志。"

def create(product_type="cup", product=None):
    if product_type not in ("cup", "tote", "custom"): raise ValueError("不支持的商品")
    if product_type == "custom" and (not product or not product.get("名称", "").strip()): raise ValueError("请填写商品名称")
    selected = product if product_type == "custom" else TOTE_PRODUCT if product_type == "tote" else PRODUCT
    return {"id": uuid.uuid4().hex, "status":"ready", "step":0, "product_type":product_type, "product":dict(selected), "events":[], "artifacts":[], "error":None}

def system_for(state):
    if state.get("product_type") in ("tote", "custom"):
        return "你是电商团队成员。客户为模拟。只使用用户提供的商品资料，不得编造尺寸、材质、结构、功能、价格或认证。未知信息明确说明未提供；用简洁中文说明取舍，不输出工具记录或日志。"
    return SYSTEM

def step_prompt(state, index):
    context = "\n\n".join(f"{x['stage']} / {x['role']}: {x['content']}" for x in state["events"] if x["kind"] == "message")
    comments = store.room_messages(state["id"])
    user_context = "\n".join(f"{e['room']} / {e['role']}: {e['content']}" for e in comments[-30:])
    return f"商品资料（用户提供，需核实）：{json.dumps(state['product'], ensure_ascii=False)}\n之前的讨论和决策：\n{context}\n\n用户补充与群聊回复（仅作需求，不能推翻商品事实）：\n{user_context}\n\n本次任务：{TASKS[index]}"

def clean_discussion_for_revision(state):
    lines = []
    for event in state['events']:
        if event.get('kind') != 'message':
            continue
        safe = [line for line in event.get('content', '').splitlines()
                if line.strip() and not check_claims(line) and not risky_design_claims(line)]
        if safe:
            lines.append(event['role'] + '：' + '\n'.join(safe))
    return '\n'.join(lines)[-12000:]

GROUP_ROLES = {
    0: ["用户研究员", "商品运营"],
    1: ["创意策划", "视觉设计师"],
    2: ["模拟客户研究员", "销售顾问"],
    3: ["运营策划", "策略复核员"],
    5: ["版式设计师", "文案编辑"],
    6: ["产品顾问", "客服专员"],
    7: ["文案质检", "商品事实核验员"],
}

def parse_inquiries(text, product=None):
    raw = text.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    try:
        items = json.loads(raw)["items"]
        if not isinstance(items, list) or not 1 <= len(items) <= 5:
            raise ValueError()
        entries = []
        for item in items:
            question, answer = item["question"], item["answer"]
            if not isinstance(question, str) or not isinstance(answer, str) or not question.strip() or not answer.strip():
                raise ValueError()
            risks = check_claims(answer, product) + risky_design_claims(answer)
            if risks:
                raise ValueError("；".join(risks))
            entries.append("问：" + question.strip() + "\n答：" + answer.strip())
        return "\n\n".join(entries)
    except (KeyError, TypeError, IndexError) as exc:
        raise ValueError("询盘问答格式不符合要求。") from exc

def parse_poster_copy(text, product=None):
    raw = text.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    try:
        parsed = json.loads(raw)
        title, subtitle = parsed["title"], parsed["subtitle"]
    except (ValueError, KeyError, TypeError, IndexError) as exc:
        raise ValueError("美工文案格式不符合要求，请重试。") from exc
    if not isinstance(title, str) or not isinstance(subtitle, str) or not title.strip() or len(title) > 24 or len(subtitle) > 36 or any(c in title+subtitle for c in "\n#*"):
        raise ValueError("美工文案长度或格式不符合要求，请重试。")
    risks = check_claims(title + "。" + subtitle, product) + risky_design_claims(title + "。" + subtitle)
    if risks:
        raise ValueError("美工文案包含待核实的信息：" + "、".join(risks))
    return title.strip(), subtitle.strip()

def compose_poster(image_path, copy, output_path, slot=None):
    source = Image.open(image_path).convert("RGB")
    poster = ImageOps.fit(source, (1024, 1024), method=Image.Resampling.LANCZOS).convert("RGBA")
    font_path = next((p for p in ("C:/Windows/Fonts/msyhbd.ttc", "C:/Windows/Fonts/msyh.ttc", "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc") if Path(p).exists()), None)
    if not font_path:
        raise ValueError("缺少中文字体，无法制作商品图。")
    title_font = ImageFont.truetype(font_path, 100 if slot == "capacity" else 59)
    body_font = ImageFont.truetype(font_path, 27)
    small_font = ImageFont.truetype(font_path, 21)
    overlay = Image.new("RGBA", poster.size, (0,0,0,0))
    shade = ImageDraw.Draw(overlay)
    for x in range(650):
        alpha = int(215 * max(0, 1 - x / 650) ** 0.6)
        shade.line((x, 0, x, 1024), fill=(10,14,18,alpha))
    poster = Image.alpha_composite(poster, overlay)
    draw = ImageDraw.Draw(poster)
    parts = copy.splitlines()
    title = parts[0] if parts else ""
    subtitle = parts[1] if len(parts) > 1 else ""
    draw.text((68, 70), "CLOUD / EVERYDAY", font=small_font, fill="#d9c8a3")
    draw.rectangle((68, 112, 140, 116), fill="#d9c8a3")
    for index in range(0, len(title), 8):
        draw.text((66, 158+(index//8)*82), title[index:index+8], font=title_font, fill="white", stroke_width=1, stroke_fill="#1b2224")
    subtitle_y = 310 if slot == "capacity" else 180 + ((len(title)+7)//8)*82
    draw.text((69, subtitle_y), subtitle, font=body_font, fill="#e4d7bd", stroke_width=1, stroke_fill="#222")
    draw.rounded_rectangle((65, 895, 378, 947), radius=10, fill=(15,20,21,200))
    draw.text((80, 907), "AI生成示意 · 请核实", font=small_font, fill="#e8e8df")
    poster.convert("RGB").save(output_path, "PNG")

IMAGE_SLOTS = [
    ("hero", "商品主视觉", "A single full-length premium vacuum cup as the clear hero, upright on a sculptural dark reflective pedestal, bold cinematic side lighting, luminous blue edge light, deep shadows and polished luxury advertising photography. Keep the product silhouette clear and visually dominant."),
    ("capacity", "容量主题图", "A single full-length SAME CLOSED cup positioned on the right, premium dramatic commercial studio photography, low angle, luminous blue rim light and refined reflections. Keep the entire cup visible and leave the left side clean and dark for an oversized capacity label added later. No other objects or comparisons."),
    ("lifestyle", "日常场景图", "A premium lifestyle photograph, a real person's hand gently holding the SAME CLOSED cup at a sophisticated office desk, natural human scale, warm cinematic practical light and authentic depth. Crop to show the hand and cup prominently, not a standalone studio product shot. Leave dark negative space at left for a headline."),
    ("model3d", "3D内部结构拆解图（虚构示意）", "A single cinematic exploded 3D concept illustration of a FICTIONAL insulated cup using the same outer silhouette and color as the reference. Clearly separate lid, a hypothetical sealing ring, inner liner, outer shell and base along one central vertical axis; show the hollow interior and double-wall concept with spacious gaps and realistic studio lighting. The components are only an imagined demonstration, not measured, not an actual product specification. No multi-panel layout, no captions, no dimensions or text."),
]

TOTE_SLOTS = [
    ("hero", "商品主视觉", "Single beige canvas tote bag with two handles, full view on a sculptural pedestal, premium cinematic studio lighting."),
    ("detail", "材质细节图", "Single continuous macro photograph of beige canvas fabric and one handle of the SAME bag, dramatic directional lighting."),
    ("lifestyle", "日常场景图", "Single lifestyle photograph of a person holding the SAME beige canvas tote bag, tasteful city setting and cinematic light."),
    ("model3d", "3D结构示意图（虚构示意）", "Single conceptual 3D cutaway of a fictional beige canvas tote bag, showing the open bag cavity and handles; imagined construction only, no claim of real seams or inner pockets."),
]


CUSTOM_SLOTS = [
    ("hero", "商品主视觉", "Single product hero photograph, premium dramatic commercial studio light, full product in a single composition."),
    ("detail", "商品细节图", "Single close-up focusing on visually available exterior detail of the same product, premium lighting, no unsupported components."),
    ("lifestyle", "日常场景图", "Single plausible lifestyle scene featuring the same product, consistent appearance, cinematic natural light."),
    ("model3d", "3D结构概念图（虚构示意）", "Single fictional conceptual 3D cutaway or exploded illustration suitable for this product, imagined components only; do not imply real verified construction."),
]

def image_slots(state):
    return CUSTOM_SLOTS if state.get("product_type") == "custom" else TOTE_SLOTS if state.get("product_type") == "tote" else IMAGE_SLOTS

def label_concept_image(image):
    image = image.convert("RGBA")
    if image.width < 480:
        return image.convert("RGB")
    font_path = next((p for p in ("C:/Windows/Fonts/msyh.ttc", "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc") if Path(p).exists()), None)
    if not font_path:
        raise ValueError("缺少中文字体，无法标识虚构结构示意图。")
    font = ImageFont.truetype(font_path, max(18, image.width//48))
    overlay = Image.new("RGBA", image.size, (0,0,0,0))
    draw = ImageDraw.Draw(overlay)
    text = "虚构结构示意 · 非实物依据"
    bbox = draw.textbbox((0,0), text, font=font)
    pad = max(12,image.width//80)
    left = pad; top = image.height - (bbox[3]-bbox[1]) - pad*3
    draw.rounded_rectangle((left,top,left+(bbox[2]-bbox[0])+pad*2,image.height-pad),radius=8,fill=(0,0,0,190))
    draw.text((left+pad,top+pad-bbox[1]//2),text,font=font,fill="white")
    return Image.alpha_composite(image,overlay).convert("RGB")

def run(state, provider=None):
    provider = provider or OpenRouter()
    state["status"] = "running"
    state["error"] = None
    store.save(state)
    while state["step"] < len(STAGES):
        i = state["step"]
        state["stage"] = STAGES[i]
        previous_room = state.get("current_room")
        if previous_room and previous_room != ROOMS[i]:
            state["transfer"] = {"from":previous_room, "to":ROOMS[i], "stage":STAGES[i]}
        state["current_room"] = ROOMS[i]
        store.save(state)
        try:
            prompt = step_prompt(state, i)
            preliminary = [(e["role"], e["content"]) for e in state["events"] if e.get("step_index") == i and e.get("preliminary")]
            for role in GROUP_ROLES.get(i, []):
                if any(r == role for r, _ in preliminary):
                    continue
                prior = "\n".join(f"{r}: {content}" for r, content in preliminary)
                state["active_agent"] = {"room":ROOMS[i], "name":role, "stage":STAGES[i]}
                store.save(state)
                prompt = step_prompt(state, i)
                opinion = provider.chat(system_for(state) + "\n" + persona_instruction(role), prompt + f"\n你的角色：{role}。阅读前面同事意见，提出具体补充或有理由的异议。\n本群已有意见：{prior}")
                if not isinstance(opinion, str) or not opinion.strip():
                    raise ValueError("模型返回空内容，请重试。")
                preliminary.append((role, opinion))
                state["events"].append({"id":uuid.uuid4().hex, "kind":"message", "stage":STAGES[i], "room":ROOMS[i], "role":role, "content":opinion, "simulated":i in (2, 6), "version":1 if i > 3 else 0, "step_index":i, "preliminary":True})
                store.save(state)
            group_context = "\n".join(f"{r}: {content}" for r, content in preliminary)
            instruction = "仅输出英文图片提示词，不要解释。" if i == 4 else ("只输出 JSON 对象，包含 title（不超过12字）、subtitle（不超过20字）和 reason（简短理由）三个字符串字段。不要 Markdown，不要输出其他内容；标题与副标题只能包含商品已知事实。" if i == 5 else ("只输出 JSON 对象，格式为 {\"items\":[{\"question\":\"客户问题\",\"answer\":\"客服答复\"}]}。给出3组问答，不要 Markdown；只在答复中使用已知事实，未知问题回答资料未提供。" if i == 6 else "请综合意见，明确采纳或取舍及理由。"))
            result = state.get("pending_image_prompt") if i == 4 else None
            if not result:
                state["active_agent"] = {"room":ROOMS[i], "name":ROLES[i], "stage":STAGES[i]}
                store.save(state)
                prompt = step_prompt(state, i)
                result = provider.chat(system_for(state) + "\n" + persona_instruction(ROLES[i]), prompt + "\n本群成员意见：\n" + group_context + "\n" + instruction)
            if not isinstance(result, str) or not result.strip():
                raise ValueError("模型返回空内容，请重试。")
            if i in (3, 4):
                risks = check_claims(result, state["product"] if state.get("product_type") in ("tote", "custom") else None) + risky_design_claims(result)
                if risks:
                    state["events"].append({"id":uuid.uuid4().hex, "kind":"validation", "stage":STAGES[i], "room":ROOMS[i], "role":"事实检查", "content":"发现待核实信息，正在要求负责人修订：" + "、".join(risks), "simulated":False, "version":0})
                    store.save(state)
                    result = provider.chat(system_for(state) + "\n" + persona_instruction(ROLES[i]), prompt + "\n本群成员意见：\n" + group_context + "\n" + instruction + "\n上一版因以下内容未获确认而未通过：" + "、".join(risks) + "。请删除未经确认的属性、数字和功能；不要列出禁用词或未知信息，最终答复中完全不要出现上述被拦截的词语，即使是提醒或否定句也不要出现。只写已知事实和基于事实的方案。")
                    risks = check_claims(result, state["product"] if state.get("product_type") in ("tote", "custom") else None) + risky_design_claims(result)
                    if risks and i == 3:
                        state['events'].append({"id":uuid.uuid4().hex, "kind":"validation", "stage":STAGES[i], "room":ROOMS[i], "role":"事实检查", "content":"修订仍含待核实信息，正在根据已知资料和筛选后的讨论重新决策。", "simulated":False, "version":0})
                        store.save(state)
                        known = {k:v for k,v in state['product'].items() if k != '未知信息'}
                        clean = clean_discussion_for_revision(state)
                        result = provider.chat(system_for(state) + "\n" + persona_instruction(ROLES[i]), "商品已知资料：" + json.dumps(known, ensure_ascii=False) + "\n干净的讨论摘要（仅供参考，仍须核实）：\n" + clean + "\n请作简短运营决策，指出采纳的意见和理由。商品参数只能使用已知资料，不列举未知事项，不添加参数或功效。")
                        risks = check_claims(result, state["product"] if state.get("product_type") in ("tote", "custom") else None) + risky_design_claims(result)
                    if risks:
                        raise ValueError("修订后仍有未经设定支持的信息，已阻止继续：" + "、".join(risks))
            if i == 4:
                state["pending_image_prompt"] = result
                store.save(state)
            if i == 6:
                try:
                    result = parse_inquiries(result, state["product"] if state.get("product_type") in ("tote", "custom") else None)
                except ValueError as first_error:
                    result = provider.chat(system_for(state) + "\n" + persona_instruction(ROLES[i]), prompt + "\n" + instruction + "\n上次回复未通过检查：" + str(first_error) + "。请删除未经确认的信息，未知问题直接回答资料未提供，不作售后、认证、测试或材质等级承诺，只返回 JSON。")
                    result = parse_inquiries(result, state["product"] if state.get("product_type") in ("tote", "custom") else None)
            assets = []
            if i == 4:
                slots = state.setdefault("image_slots", {})
                for index, (slot, label, direction) in enumerate(image_slots(state)):
                    if slot in slots and (store.DATA / slots[slot]["filename"]).is_file():
                        continue
                    reference = (store.DATA / slots["hero"]["filename"]).read_bytes() if index else None
                    full_prompt = ("Create premium Chinese ecommerce product photography. " + result + "\n" + direction +
                        "\nFinal mandatory constraints: single image, single uninterrupted scene, one composition, no collage, no grid, no panels, no inset images, no split screen, no comparisons. " +
                        ("No text, letters, numbers, logos or watermarks. Product details supplied by user: " + json.dumps(state["product"], ensure_ascii=False) + ". No unconfirmed features. " if state.get("product_type") == "custom" else "No text, letters, numbers, logos or watermarks. Fictional beige canvas tote bag, two handles. No dimensions, load capacity, inner pockets or unverified features. " if state.get("product_type") == "tote" else "No text, letters, numbers, logos or watermarks. Fog-blue stainless cup, 500ml; lid details unspecified. Do not suggest steel grade, waterproofing, tea filters, temperature display or certifications. ") +
                        "The 3D slot is explicitly a fictional imagined structure and must never be described as verified. " +
                        "Product should occupy the right half; leave the left 40 percent dark and uncluttered for later typography. "
                        "If a reference is provided, keep the same outer style and color. For the exploded concept image, separate the fictional parts as requested; for other slots, change only composition and surroundings.")
                    state["active_agent"] = {"room":ROOMS[i], "name":"作图 Lead", "stage":"正在生成" + label}
                    store.save(state)
                    image_data = provider.image(full_prompt, reference=reference) if reference else provider.image(full_prompt)
                    filename = state["id"] + "-" + slot + ".png"
                    try:
                        picture = Image.open(BytesIO(image_data)).convert("RGB")
                        if slot == "model3d":
                            picture = label_concept_image(picture)
                        picture.save(store.DATA / filename, "PNG")
                    except (OSError, ValueError) as exc:
                        raise ValueError("图片服务返回了无法打开的图片。") from exc
                    slots[slot] = {"filename":filename, "label":label, "source":"OpenRouter / " + getattr(provider, "image_model", "image model")}
                    state["artifacts"].append({"id":uuid.uuid4().hex, "type":"image", "category":"original", "slot":slot, "title":label if slot == "model3d" else label + " · 素材", "url":"/assets/"+filename, "source":slots[slot]["source"], "version":1})
                    store.save(state)
            if i == 5:
                try:
                    title, subtitle = parse_poster_copy(result, state["product"] if state.get("product_type") in ("tote", "custom") else None)
                except ValueError as first_error:
                    result = provider.chat(system_for(state) + "\n" + persona_instruction(ROLES[i]), prompt + "\n" + instruction + "\n上一次文案被拦截：" + str(first_error) + "。请删除未经确认的描述并重新输出 JSON。")
                    title, subtitle = parse_poster_copy(result, state["product"] if state.get("product_type") in ("tote", "custom") else None)
                slots = state.get("image_slots", {})
                if not slots:
                    legacy = store.DATA / (state["id"] + "-product.png")
                    if not legacy.exists():
                        raise ValueError("未找到图片素材，请重新运行作图阶段。")
                    slots = {"hero":{"filename":legacy.name, "label":"商品主视觉", "source":"历史素材"}}
                copies = ({"hero": (title, subtitle), "detail": (title, subtitle), "lifestyle": (title, subtitle)} if state.get("product_type") == "custom" else {"hero": (title, subtitle), "detail": ("帆布纹理", "米色 · 日常搭配"), "lifestyle": ("米色帆布手提袋", "简洁外观 · 日常搭配")} if state.get("product_type") == "tote" else {"hero": (title, subtitle), "capacity": ("500ml", "容量 · 日常饮水"), "lifestyle": ("雾蓝色不锈钢杯", "简洁外观 · 日常饮水")})
                for slot, label, _ in (image_slots(state)):
                    if slot not in slots or slot not in copies: continue
                    original = store.DATA / slots[slot]["filename"]
                    poster = store.DATA / (state["id"] + "-" + slot + "-poster.png")
                    compose_poster(original, "\n".join(copies[slot]), poster, slot=slot)
                    assets.append({"id":uuid.uuid4().hex, "type":"image", "category":"poster", "slot":slot, "title":label + " · 成品", "url":"/assets/" + poster.name, "source":slots[slot]["source"] + " · 程序排版", "version":1})
            if i == 4:
                state["image_plan"] = result
            public_result = ("作图方案已确定：依次制作商品主视觉、外观细节、场景图和虚构结构概念图。" if state.get("product_type") in ("tote", "custom") else "作图方案已确定：依次制作商品主视觉、容量主题、日常场景图和内部结构拆解图。拆解结构为虚构示意。") if i == 4 else result
            event = {"id":uuid.uuid4().hex, "kind":"message", "stage":STAGES[i], "room":ROOMS[i], "role":ROLES[i], "content":public_result, "simulated": i in (2,6), "version": 1 if i > 3 else 0}
            state["events"].append(event)
            if i in (0,3,5,6,7):
                state["artifacts"].append({"id":uuid.uuid4().hex,"type":"text", "title": STAGES[i], "content": result, "event_id":event["id"], "version":event["version"]})
            if i == 7:
                checked_text = "\n".join(a.get("content", "") for a in state["artifacts"] if a.get("title") in ("运营决策", "美工排版", "询盘回复"))
                findings = check_claims(checked_text, state["product"] if state.get("product_type") in ("tote", "custom") else None)
                summary = "\n".join(findings) if findings else "基础规则未发现待核实的数字或关键词。"
                summary += "\n此检查不覆盖全部表述，不核验图片，所有成果仍须人工审核。"
                state["artifacts"].append({"id":uuid.uuid4().hex, "type":"text", "title":"基础规则检查", "content":summary, "event_id":event["id"], "version":1})
            if i == 4:
                for a in state["artifacts"]:
                    if a.get("category") == "original" and not a.get("event_id"):
                        a["event_id"] = event["id"]
            for asset in assets:
                asset["event_id"] = event["id"]
                state["artifacts"].append(asset)
            state.pop("pending_image_prompt", None)
            state["step"] += 1
            store.save(state)
        except Exception as exc:
            state["status"] = "failed"
            state["active_agent"] = None
            state["error"] = str(exc)[:300]
            store.save(state)
            return state
    state["status"] = "review"
    state["active_agent"] = None
    state["stage"] = "等待人工审核"
    store.save(state)
    return state


def use_example(state):
    if state.get("status") != "failed" or state.get("step") != 4:
        raise ValueError("仅图片生成阶段失败时可使用示例素材。")
    if state.get("product_type") in ("tote", "custom"):
        raise ValueError("帆布袋或自定义商品暂无示例素材，请重试图片生成。")
    image = Image.new("RGB", (800, 800), "#e8eee4")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((290, 145, 510, 650), radius=55, fill="#90aeb3", outline="#6f8c91", width=6)
    draw.rounded_rectangle((300, 120, 500, 190), radius=16, fill="#526f70")
    slots = state.setdefault("image_slots", {})
    event_id = uuid.uuid4().hex
    state["events"].append({"id":event_id, "kind":"message", "stage":"图片生成", "room":"作图群", "role":"作图 Lead", "content":"用户选择使用示例插画补齐未完成素材，示例不是 AI 生成图片。", "simulated":True, "version":1})
    for slot, label, _ in IMAGE_SLOTS:
        if slot in slots: continue
        filename = state["id"] + "-" + slot + ".png"
        image.save(store.DATA / filename, "PNG")
        slots[slot] = {"filename":filename, "label":label, "source":"本地示例插画"}
        state["artifacts"].append({"id":uuid.uuid4().hex, "type":"image", "category":"original", "slot":slot, "title":label + " · 示例插画", "url":"/assets/" + filename, "source":"本地示例插画", "version":1, "event_id":event_id})
    state["step"] = 5
    state["error"] = None
    store.save(state)
    return state
