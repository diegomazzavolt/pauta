import pytest
from fastapi.testclient import TestClient
from app import main
from app.subtitles import video_id, normalize, export, from_json3


@pytest.mark.parametrize("url", ["https://youtu.be/jNQXAC9IVRw?t=3", "https://www.youtube.com/watch?v=jNQXAC9IVRw&list=abc", "youtube.com/shorts/jNQXAC9IVRw", "https://m.youtube.com/live/jNQXAC9IVRw", "jNQXAC9IVRw"])
def test_valid_url(url):
    assert video_id(url) == "jNQXAC9IVRw"


@pytest.mark.parametrize("url", ["https://youtube.com.evil.com/watch?v=jNQXAC9IVRw", "http://127.0.0.1/", "https://youtube.com/playlist?list=abc", "https://youtube.com@evil.com/watch?v=jNQXAC9IVRw", "https://youtube.com:1234/watch?v=jNQXAC9IVRw", "bad", "file:///etc/passwd"])
def test_reject_urls(url):
    with pytest.raises(ValueError):
        video_id(url)


def test_exports_preserve_text_unicode_and_times():
    cues = normalize([{"text": "<b>Olá &amp; mundo</b>", "start": 61.23, "duration": 1.5}])
    assert export(cues, "srt") == "1\n00:01:01,230 --> 00:01:02,730\nOlá & mundo\n"
    assert export(cues, "vtt").startswith("WEBVTT\n\n00:01:01.230 --> 00:01:02.730")
    assert export(cues, "txt") == "Olá & mundo\n"
    assert from_json3({"events": [{"tStartMs": 50, "dDurationMs": 1200, "segs": [{"utf8": "olá "}, {"utf8": "mundo"}]}]}) == [{"start": 50, "end": 1250, "text": "olá mundo"}]


@pytest.fixture
def client(monkeypatch):
    main.cache.clear(); main.rate.clear()
    monkeypatch.setattr(main.providers, "discover", lambda id: ("Vídeo / teste", "Autor", [
        {"language": "Português", "code": "pt", "kind": "manual"},
        {"language": "Português (gerada automaticamente)", "code": "pt", "kind": "automatic"}]))
    monkeypatch.setattr(main.providers, "fetch_track", lambda t: [{"start": 1000, "end": 2500, "text": "Olá mundo"}])
    return TestClient(main.app)


def test_full_flow_and_cache(client, monkeypatch):
    result = client.post("/api/videos", json={"url": "https://youtu.be/jNQXAC9IVRw"})
    assert result.status_code == 200
    data = result.json()
    assert data["tracks"][0]["kind"] == "automatic"
    assert "source" not in data["tracks"][0]
    path = f"/api/videos/{data['token']}/tracks/0"
    assert client.get(path).json()["cues"][0]["text"] == "Olá mundo"
    monkeypatch.setattr(main.providers, "fetch_track", lambda t: pytest.fail("Must reuse cached cues"))
    for format in ("srt", "vtt", "txt"):
        response = client.get(path + f"/download?format={format}")
        assert response.status_code == 200
        assert "Olá mundo" in response.text
        assert "attachment;" in response.headers["content-disposition"]
        assert "no-store" in response.headers["cache-control"]
    assert client.get(path + "/download?format=exe").status_code == 422
    assert client.get(f"/api/videos/{data['token']}/tracks/99").status_code == 404
    main.cache[data["token"]]["expires"] = 0
    assert client.get(path).status_code == 410


def test_errors_and_origin(client, monkeypatch):
    assert client.post("/api/videos", json={"url": "http://localhost/secret"}).status_code == 422
    assert client.post("/api/videos", json={"url": "jNQXAC9IVRw"}, headers={"Origin": "https://evil.com"}).status_code == 403
    monkeypatch.setattr(main.providers, "discover", lambda id: ("Empty", "Author", []))
    result = client.post("/api/videos", json={"url": "jNQXAC9IVRw"})
    assert result.json()["detail"]["code"] == "NO_CAPTIONS"
    def blocked(id):
        raise RuntimeError("Sign in to confirm you are not a bot")
    monkeypatch.setattr(main.providers, "discover", blocked)
    assert client.post("/api/videos", json={"url": "jNQXAC9IVRw"}).json()["detail"]["code"] == "YOUTUBE_BLOCKED"


def test_rate_limit(client):
    for _ in range(12):
        assert client.post("/api/videos", json={"url": "jNQXAC9IVRw"}).status_code == 200
    assert client.post("/api/videos", json={"url": "jNQXAC9IVRw"}).status_code == 429


def test_home_and_security(client):
    response = client.get("/")
    assert response.status_code == 200
    assert 'lang="pt-BR"' in response.text
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert client.get("/static/app.js").status_code == 200
