"""Subtitle parsing and export. All times are integer milliseconds."""
import html
import re
from urllib.parse import parse_qs, urlparse


def video_id(value: str) -> str:
    value = value.strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", value):
        return value
    if not value.startswith(("https://", "http://")):
        value = "https://" + value
    url = urlparse(value)
    if url.username or url.password or url.port not in (None, 80, 443):
        raise ValueError("Cole um link válido de um vídeo do YouTube.")
    host = (url.hostname or "").lower()
    parts = url.path.strip("/").split("/")
    result = ""
    if host in {"youtu.be", "www.youtu.be"} and len(parts) == 1:
        result = parts[0]
    elif host in {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}:
        if url.path == "/watch":
            result = parse_qs(url.query).get("v", [""])[0]
        elif len(parts) == 2 and parts[0] in {"shorts", "embed", "live"}:
            result = parts[1]
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", result):
        raise ValueError("Cole o link de um vídeo do YouTube, Shorts ou youtu.be.")
    return result


def clean_text(text: str) -> str:
    return html.unescape(re.sub(r"<[^>]*>", "", text)).replace("\r", "").strip()


def normalize(snippets) -> list[dict]:
    result = []
    for snippet in snippets:
        text = clean_text(snippet["text"])
        start = max(0, round(float(snippet["start"]) * 1000))
        duration = max(1, round(float(snippet["duration"]) * 1000))
        if text:
            result.append({"start": start, "end": start + duration, "text": text})
    result.sort(key=lambda x: x["start"])
    return result


def from_json3(data: dict) -> list[dict]:
    snippets = []
    for event in data.get("events", []):
        text = "".join(s.get("utf8", "") for s in event.get("segs", []))
        if text.strip():
            snippets.append({"text": text, "start": event.get("tStartMs", 0) / 1000,
                             "duration": event.get("dDurationMs", 0) / 1000})
    return normalize(snippets)


def timestamp(ms: int, separator=",") -> str:
    seconds, millis = divmod(ms, 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02}:{minutes:02}:{seconds:02}{separator}{millis:03}"


def export(cues: list[dict], format: str) -> str:
    if format == "txt":
        return "\n".join(c["text"] for c in cues) + "\n"
    if format not in {"srt", "vtt"}:
        raise ValueError("Formato inválido.")
    blocks = []
    for i, cue in enumerate(cues, 1):
        separator = "." if format == "vtt" else ","
        # Escape text so literal angle brackets cannot become WebVTT markup.
        text = html.escape(cue["text"], quote=False) if format == "vtt" else cue["text"]
        prefix = f"{i}\n" if format == "srt" else ""
        blocks.append(f"{prefix}{timestamp(cue['start'], separator)} --> {timestamp(cue['end'], separator)}\n{text}")
    return ("WEBVTT\n\n" if format == "vtt" else "") + "\n\n".join(blocks) + "\n"
