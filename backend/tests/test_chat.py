from app import store, workflow
from fastapi.testclient import TestClient
from app.main import app
import pytest

@pytest.fixture(autouse=True)
def isolated_store(monkeypatch, tmp_path):
    monkeypatch.setattr(store, 'DB', tmp_path / 'messages.sqlite3')
    monkeypatch.setattr(store, 'DATA', tmp_path)
    store.init()

HEADERS={'origin':'http://127.0.0.1:5173','x-local-app':'ecommerce-team'}

def test_custom_product_creation_and_validation(monkeypatch):
    import app.main as main
    monkeypatch.setattr(main, 'launch', lambda state: None)
    client=TestClient(app)
    assert client.post('/api/custom-runs', headers=HEADERS, json={'name':'  ','details':''}).status_code==422
    response=client.post('/api/custom-runs', headers=HEADERS, json={'name':'绿色台灯','details':'桌面照明'})
    assert response.status_code==200
    state=store.get(response.json()['id'])
    assert state['product_type']=='custom' and state['product']['名称']=='绿色台灯'
    assert state['product']['已知信息']=='桌面照明'

def test_user_message_survives_worker_state_save_and_is_seen_by_next_speaker(monkeypatch):
    state=workflow.create();state['status']='running';store.save(state)
    import app.main as main
    monkeypatch.setattr(main, 'start_reply', lambda *args: None)
    client=TestClient(app)
    response=client.post(f"/api/runs/{state['id']}/messages",headers=HEADERS,json={'room':'运营群','content':'希望突出容量'})
    assert response.status_code==200
    store.save(state)
    assert '希望突出容量' in workflow.step_prompt(state,0)
    merged=store.with_messages(store.get(state['id']))
    assert [e['content'] for e in merged['events'] if e['kind']=='user']==['希望突出容量']

def test_user_message_validation_and_room_isolation():
    state=workflow.create();store.save(state);client=TestClient(app)
    for body in ({'room':'不存在','content':'hello'},{'room':'运营群','content':'  '}):
        assert client.post(f"/api/runs/{state['id']}/messages",headers=HEADERS,json=body).status_code==422
    store.add_room_message(state['id'],'作图群','你','user','图片想要深色背景')
    assert store.room_messages(state['id'],'运营群')==[]
    assert store.room_messages(state['id'],'作图群')[0]['content']=='图片想要深色背景'

def test_concept_exploded_view_explicitly_describes_fictional_internal_parts():
    spec=next(x[2] for x in workflow.IMAGE_SLOTS if x[0]=='model3d')
    assert 'fictional' in spec.lower() and 'exploded' in spec.lower()
    assert 'inner liner' in spec.lower() and 'sealing ring' in spec.lower()

def test_paused_room_lead_reply_is_saved_without_changing_artifacts(monkeypatch):
    import app.main as main
    state=workflow.create();state['status']='failed';state['artifacts']=[{'id':'existing'}];store.save(state)
    store.add_room_message(state['id'],'运营群','你','user','我想突出容量')
    class Provider:
        def chat(self,system,prompt):
            assert '我想突出容量' in prompt
            return '可以优先突出500ml容量。'
    monkeypatch.setattr(main,'OpenRouter',lambda:Provider())
    main.reply_to_user(state['id'],'运营群')
    events=store.room_messages(state['id'],'运营群')
    assert [e['kind'] for e in events]==['user','chat']
    assert events[-1]['role']=='运营 Lead'
    assert store.get(state['id'])['artifacts']==[{'id':'existing'}]

def test_followup_never_sends_unsupported_claim_as_confirmed(monkeypatch):
    import app.main as main
    state=workflow.create();state['status']='failed';store.save(state)
    store.add_room_message(state['id'],'运营群','你','user','强调容量')
    class Provider:
        def chat(self,system,prompt): return '采用304不锈钢，食品级认证。'
    monkeypatch.setattr(main,'OpenRouter',lambda:Provider())
    main.reply_to_user(state['id'],'运营群')
    reply=store.room_messages(state['id'],'运营群')[-1]['content']
    assert '采用304不锈钢' not in reply
    assert '核实' in reply or '确认' in reply
