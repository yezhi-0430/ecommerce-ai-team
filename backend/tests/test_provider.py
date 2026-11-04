from app.providers import OpenRouter, ProviderError
import pytest

def test_missing_key_is_clear(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(ProviderError, match="OPENROUTER_API_KEY"):
        OpenRouter().chat("system", "test")

def test_image_decodes_response(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "fake")
    provider = OpenRouter()
    monkeypatch.setattr(provider, "_post", lambda *args, **kwargs: {"data": [{"b64_json": "aGVsbG8="}]})
    assert provider.image("test") == b"hello"

def test_transient_connection_is_retried(monkeypatch):
    import httpx
    monkeypatch.setenv('OPENROUTER_API_KEY', 'fake')
    calls = []
    def fake_post(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1: raise httpx.ConnectError('transient')
        return httpx.Response(200, json={'choices':[{'message':{'content':'ok'}}]}, request=httpx.Request('POST','https://openrouter.ai'))
    monkeypatch.setattr(httpx, 'post', fake_post)
    assert OpenRouter().chat('system', 'user') == 'ok'
    assert len(calls) == 2

def test_image_reference_is_passed_as_data_url(monkeypatch):
    monkeypatch.setenv('OPENROUTER_API_KEY', 'fake')
    provider=OpenRouter(); captured={}
    def post(path, payload, timeout):
        captured.update(payload)
        return {'data':[{'b64_json':'aGVsbG8='}]}
    monkeypatch.setattr(provider, '_post', post)
    assert provider.image('single image', reference=b'original') == b'hello'
    assert captured['n']==1
    assert captured['input_references'][0]['image_url']['url'].startswith('data:image/png;base64,')
