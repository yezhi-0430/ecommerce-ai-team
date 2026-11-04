from fastapi.testclient import TestClient
from app.main import app

def test_cross_site_post_rejected():
    client=TestClient(app)
    assert client.post('/api/runs', headers={'origin':'https://evil.example'}).status_code == 403
    assert client.post('/api/runs').status_code == 403

def test_recent_runs_include_visual_sample(monkeypatch, tmp_path):
    from app import store
    monkeypatch.setattr(store, 'DB', tmp_path / 'runs.sqlite3')
    store.init()
    store.save({'id':'example', 'status':'visual_test', 'stage':'视觉样张', 'visual_test':True})
    assert store.recent()[0]['id']=='example'
    assert store.recent()[0]['visual_test'] is True
