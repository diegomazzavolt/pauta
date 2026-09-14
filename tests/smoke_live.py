"""Explicit opt-in integration check against the running app and public YouTube."""
import json
import re
from urllib.request import Request, urlopen

BASE = "http://127.0.0.1:8000"
request = Request(BASE + "/api/videos", data=json.dumps({"url": "https://www.youtube.com/watch?v=aircAruvnKk"}).encode(), headers={"Content-Type": "application/json"})
with urlopen(request, timeout=110) as response:
    data = json.load(response)
track = next(t for t in data["tracks"] if t["kind"] == "automatic")
path = BASE + f"/api/videos/{data['token']}/tracks/{track['id']}"
with urlopen(path, timeout=90) as response:
    cues = json.load(response)["cues"]
assert len(cues) > 300
result = {"video": data["videoId"], "title": data["title"], "kind": track["kind"], "language": track["code"], "cues": len(cues), "files": {}}
for format in ["srt", "vtt", "txt"]:
    with urlopen(path + f"/download?format={format}", timeout=30) as response:
        content = response.read().decode("utf-8")
        assert "attachment;" in response.headers["Content-Disposition"]
    assert cues[-1]["text"] in content
    if format in {"srt", "vtt"}:
        assert content.count(" --> ") == len(cues)
    if format == "vtt":
        assert content.startswith("WEBVTT\n")
    result["files"][format] = {"bytes": len(content.encode("utf-8")), "complete": True}
print(json.dumps(result, ensure_ascii=True, indent=2))
