from io import BytesIO
from PIL import Image
from app import workflow, store
import pytest

@pytest.fixture(autouse=True)
def isolated_database(monkeypatch, tmp_path):
    monkeypatch.setattr(store, "DB", tmp_path / "test.sqlite3")
    store.init()

class Fake:
    def __init__(self, fail_at=None): self.calls = 0; self.fail_at = fail_at; self.prompts = []
    def chat(self, system, prompt):
        self.calls += 1; self.prompts.append(prompt)
        if self.calls == self.fail_at: raise RuntimeError("模拟失败")
        if '格式为' in prompt and 'question' in prompt: return '{"items":[{"question":"容量是多少？","answer":"容量是500ml。"}]}'
        if "只输出 JSON 对象" in prompt: return '{"title":"雾蓝随行杯","subtitle":"500ml · 79元","reason":"简洁"}'
        if "结合初版任务单" in prompt: return "调整为突出500ml容量"
        if "模拟潜在客户" in prompt: return "模拟客户关心容量"
        return "突出已知容量和杯身颜色"
    def image(self, prompt, reference=None):
        output = BytesIO(); Image.new("RGB", (64, 64), "blue").save(output, format="PNG"); return output.getvalue()

def test_feedback_reaches_lead_and_downstream(monkeypatch, tmp_path):
    monkeypatch.setattr(store, "DATA", tmp_path)
    provider=Fake()
    state=workflow.run(workflow.create(), provider)
    assert state["status"] == "review", state.get("error")
    lead_prompt=next(p for p in provider.prompts if "结合初版任务单" in p)
    assert "模拟客户关心容量" in lead_prompt
    art_prompt=next(p for p in provider.prompts if "写出主图标题" in p)
    assert "调整为突出500ml容量" in art_prompt
    assert len([a for a in state["artifacts"] if a["type"] == "image"]) == 7

def test_failure_stops_at_failed_step():
    state=workflow.run(workflow.create(), Fake(fail_at=4))
    assert state["status"] == "failed"
    assert state["step"] == 1
    assert state["error"] == "模拟失败"

def test_example_is_labeled_after_compositing(monkeypatch, tmp_path):
    monkeypatch.setattr(store, "DATA", tmp_path)
    class ImageFailure(Fake):
        def image(self, prompt): raise RuntimeError("image failed")
    state=workflow.run(workflow.create(), ImageFailure())
    assert state['step'] == 4 and state['status'] == 'failed'
    workflow.use_example(state)
    state=workflow.run(state, Fake())
    poster=next(a for a in state['artifacts'] if a.get('category') == 'poster')
    assert '示例' in poster['source']

def test_retry_retains_previously_recorded_opinion():
    state=workflow.run(workflow.create(), Fake(fail_at=2))
    assert state['status'] == 'failed'
    assert len(state['events']) == 1
    first=state['events'][0]['id']
    state=workflow.run(state, Fake(fail_at=1))
    assert state['events'][0]['id'] == first
    assert len(state['events']) == 1
from app.workflow import parse_poster_copy
import pytest

def test_poster_copy_parses_json_and_ignores_reasons():
    title, subtitle = parse_poster_copy('```json\n{"title":"雾蓝不锈钢随行杯","subtitle":"500ml · 79元","reason":"讨论理由"}\n```')
    assert title == '雾蓝不锈钢随行杯'
    assert subtitle == '500ml · 79元'

def test_poster_copy_rejects_unstructured_output():
    with pytest.raises(ValueError): parse_poster_copy('### 主图标题：请查看方案')
from app.workflow import parse_inquiries

def test_question_can_mention_unconfirmed_feature():
    result = parse_inquiries('{"items":[{"question":"杯子防漏吗？","answer":"商品资料未提供防漏信息。"}]}')
    assert '防漏吗' in result

def test_inquiry_answer_cannot_assert_unconfirmed_grade():
    with pytest.raises(ValueError):
        parse_inquiries('{"items":[{"question":"材质是什么？","answer":"采用304不锈钢。"}]}')

def test_image_set_has_three_distinct_individual_files_and_shared_reference(monkeypatch, tmp_path):
    monkeypatch.setattr(store, 'DATA', tmp_path)
    class Recording(Fake):
        def __init__(self): super().__init__(); self.images=[]
        def image(self, prompt, reference=None):
            self.images.append((prompt, reference))
            return super().image(prompt)
    provider=Recording(); state=workflow.run(workflow.create(), provider)
    assert state['status']=='review', state.get('error')
    originals=[a for a in state['artifacts'] if a.get('category')=='original']
    posters=[a for a in state['artifacts'] if a.get('category')=='poster']
    assert len(originals)==4 and len(posters)==3
    assert len({a['url'] for a in posters})==3
    assert provider.images[0][1] is None and all(p[1] for p in provider.images[1:])
    assert all('no collage' in p[0].lower() for p in provider.images)

def test_failed_image_generation_reuses_successful_images(monkeypatch, tmp_path):
    monkeypatch.setattr(store, 'DATA', tmp_path)
    class Flaky(Fake):
        def __init__(self): super().__init__(); self.calls_img=0
        def image(self, prompt, reference=None):
            self.calls_img+=1
            if self.calls_img==2: raise RuntimeError('image interrupted')
            return super().image(prompt)
    provider=Flaky(); s=workflow.run(workflow.create(),provider)
    assert s['status']=='failed' and s['step']==4 and provider.calls_img==2
    s=workflow.run(s,provider)
    assert s['status']=='review' and provider.calls_img==5

def test_personas_drive_specialist_prompts_and_activity_is_saved(monkeypatch, tmp_path):
    monkeypatch.setattr(store, 'DATA', tmp_path)
    observed=[]
    class Observe(Fake):
        def chat(self, system, prompt):
            current=store.latest()
            observed.append((system, current.get('active_agent'), current.get('transfer')))
            return super().chat(system,prompt)
    s=workflow.run(workflow.create(),Observe())
    assert s['status']=='review', s.get('error')
    assert any('决策' in system and '用户' in system for system, _, _ in observed)
    assert any(agent and agent['room']=='运营群' for _,agent,_ in observed)
    assert any(t and t['from']=='运营群' and t['to']=='作图群' for _,_,t in observed)
    assert not s.get('active_agent')

def test_3d_render_is_an_individual_asset_not_a_model_file(monkeypatch, tmp_path):
    monkeypatch.setattr(store,'DATA',tmp_path)
    s=workflow.run(workflow.create(),Fake())
    renders=[a for a in s['artifacts'] if a.get('slot')=='model3d']
    assert len(renders)==1 and renders[0]['category']=='original'
    assert '3D内部结构拆解图' in renders[0]['title'] and renders[0]['url'].endswith('.png')

def test_lead_can_revise_once_after_unsupported_claim(monkeypatch, tmp_path):
    monkeypatch.setattr(store, 'DATA', tmp_path)
    class Revise(Fake):
        def __init__(self): super().__init__(); self.lead_attempts=0
        def chat(self, system, prompt):
            if '结合初版任务单' in prompt and '请综合意见' in prompt:
                self.lead_attempts+=1
                if self.lead_attempts==1: return '主打食品级304不锈钢。'
                return '突出500ml容量和雾蓝色。'
            return super().chat(system,prompt)
    provider=Revise();s=workflow.run(workflow.create(),provider)
    assert s['status']=='review', s.get('error')
    assert provider.lead_attempts==2

def test_message_posted_between_speakers_reaches_next_speaker(monkeypatch, tmp_path):
    monkeypatch.setattr(store,'DATA',tmp_path)
    seen=[]
    class MidDiscussion(Fake):
        def chat(self, system, prompt):
            seen.append(prompt)
            if len(seen)==1:
                current=store.latest()
                store.add_room_message(current['id'],'运营群','你','user','希望重点强调容量')
            return super().chat(system,prompt)
    state=workflow.run(workflow.create(),MidDiscussion())
    assert state['status']=='review', state.get('error')
    assert '希望重点强调容量' in seen[1]

def test_image_lead_message_is_user_facing_not_raw_generation_prompt(monkeypatch, tmp_path):
    monkeypatch.setattr(store,'DATA',tmp_path)
    state=workflow.run(workflow.create(),Fake())
    event=next(e for e in state['events'] if e.get('role')=='作图 Lead' and e.get('stage')=='图片生成')
    assert '结构' in event['content']
    assert 'no collage' not in event['content'].lower()

def test_lead_final_recovery_excludes_unsupported_discussion(monkeypatch, tmp_path):
    monkeypatch.setattr(store, 'DATA', tmp_path)
    class Recover(Fake):
        def __init__(self): super().__init__(); self.recovery_prompt = None; self.decision_attempts = 0
        def chat(self, system, prompt):
            if '干净的讨论摘要' in prompt:
                self.recovery_prompt = prompt
                return '采纳容量卖点：500ml更容易展示。'
            if '结合初版任务单' in prompt and '请综合意见' in prompt:
                self.decision_attempts += 1
                return '这款商品绝对防漏。'
            return super().chat(system, prompt)
    provider = Recover()
    state = workflow.run(workflow.create(), provider)
    assert state['status'] == 'review', state.get('error')
    assert provider.decision_attempts == 2
    assert provider.recovery_prompt is not None
    assert '这款商品绝对防漏' not in provider.recovery_prompt

def test_recovery_still_stops_when_model_keeps_inventing(monkeypatch, tmp_path):
    monkeypatch.setattr(store, 'DATA', tmp_path)
    class Unsafe(Fake):
        def chat(self, system, prompt):
            if ('结合初版任务单' in prompt and '请综合意见' in prompt) or '干净的讨论摘要' in prompt:
                return '这款商品绝对防漏。'
            return super().chat(system, prompt)
    state = workflow.run(workflow.create(), Unsafe())
    assert state['status'] == 'failed' and state['step'] == 3
    assert not any(a.get('type') == 'image' for a in state['artifacts'])

def test_tote_run_uses_its_own_product_in_prompts_and_artifacts(monkeypatch, tmp_path):
    monkeypatch.setattr(store, 'DATA', tmp_path)
    class Recorder(Fake):
        def __init__(self): super().__init__(); self.image_prompts = []
        def image(self, prompt, reference=None):
            self.image_prompts.append(prompt)
            return super().image(prompt, reference)
        def chat(self, system, prompt):
            self.prompts.append(system + prompt)
            if '格式为' in prompt and 'question' in prompt: return '{"items":[{"question":"是什么颜色？","answer":"米色。"}]}'
            if '只输出 JSON 对象' in prompt: return '{"title":"米色帆布手提袋","subtitle":"日常搭配","reason":"已知颜色材质"}'
            return '突出米色帆布外观和手提设计。'
    provider=Recorder()
    state=workflow.run(workflow.create('tote'), provider)
    assert state['status']=='review', state.get('error')
    assert len(provider.image_prompts)==4
    import re
    assert all(not re.search(r'\bcup\b', p.lower()) and '500ml' not in p.lower() for p in provider.image_prompts)
    assert all('保温杯' not in p and '500ml' not in p for p in provider.prompts)
    assert '帆布' in state['product']['名称']

def test_tote_cannot_use_cup_example():
    state=workflow.create('tote')
    state.update(status='failed', step=4)
    with pytest.raises(ValueError, match='帆布袋'):
        workflow.use_example(state)

def test_custom_product_flows_through_images_and_discussion(monkeypatch, tmp_path):
    monkeypatch.setattr(store, 'DATA', tmp_path)
    class Recorder(Fake):
        def __init__(self): super().__init__(); self.images=[]; self.systems=[]
        def chat(self, system, prompt):
            self.systems.append(system)
            if '格式为' in prompt and 'question' in prompt: return '{"items":[{"question":"什么颜色？","answer":"绿色。"}]}'
            if '只输出 JSON 对象' in prompt: return '{"title":"绿色台灯","subtitle":"桌面照明","reason":"商品设定"}'
            return '展示绿色台灯的桌面照明场景。'
        def image(self, prompt, reference=None):
            self.images.append(prompt)
            return super().image(prompt, reference)
    product={'名称':'绿色台灯','已知信息':'绿色，可用于桌面照明。'}
    provider=Recorder()
    state=workflow.run(workflow.create('custom', product), provider)
    assert state['status']=='review', state.get('error')
    assert len(provider.images)==4 and all('绿色台灯' in x for x in provider.images)
    assert all('保温杯' not in x and '500ml' not in x for x in provider.images)
    assert all('杯盖结构' not in x for x in provider.systems)
    assert state['product']['名称']=='绿色台灯'

def test_custom_product_number_validation():
    from app.quality import check_claims
    product={'名称':'茶','已知信息':'净含量250g'}
    assert not check_claims('净含量250g', product)
    assert check_claims('净含量500g', product)
