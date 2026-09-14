"""Independent YouTube extraction; never calls DownSub or downloads video/audio."""
import json
import os
import subprocess
import sys
from urllib.parse import urlparse

import requests
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api.proxies import GenericProxyConfig

from .subtitles import from_json3, normalize


class TimedSession(requests.Session):
    def request(self, *args, **kwargs):
        kwargs.setdefault("timeout", (8, 20))
        return super().request(*args, **kwargs)


def session():
    client = TimedSession()
    proxy = os.getenv("YOUTUBE_PROXY_URL")
    if proxy:
        client.proxies.update({"https": proxy, "http": proxy})
    return client


def classify_error(exc):
    message = str(exc).lower()
    name = type(exc).__name__
    if name in {"RequestBlocked", "IpBlocked", "PoTokenRequired"} or any(x in message for x in ["sign in to confirm", "429", "too many requests", "bot", "po token"]):
        return "YOUTUBE_BLOCKED", "O YouTube bloqueou a consulta nesta conexão. Aguarde e tente novamente; em hospedagens, o administrador pode configurar outra conexão de saída."
    if name in {"VideoUnavailable", "VideoUnplayable", "AgeRestricted"} or any(x in message for x in ["unavailable", "private video", "age-restricted"]):
        return "VIDEO_UNAVAILABLE", "Este vídeo está indisponível, é privado ou exige acesso à conta."
    if name == "TranscriptsDisabled":
        return "NO_CAPTIONS", "Não encontramos legendas disponíveis neste vídeo."
    return "EXTRACTION_FAILED", "Não foi possível consultar as legendas agora. Verifique o vídeo e tente novamente."


def discover(id):
    proxy = os.getenv("YOUTUBE_PROXY_URL")
    client = YouTubeTranscriptApi(http_client=session(), proxy_config=GenericProxyConfig(https_url=proxy, http_url=proxy) if proxy else None)
    try:
        transcripts = list(client.list(id))
        tracks = [{"language": t.language, "code": t.language_code,
                   "kind": "automatic" if t.is_generated else "manual", "provider": "transcript", "source": t} for t in transcripts]
        title, author = metadata(id)
        return title, author, tracks
    except Exception as primary:
        # Do not retry access restrictions via another extractor.
        if classify_error(primary)[0] in {"YOUTUBE_BLOCKED", "VIDEO_UNAVAILABLE"}:
            raise primary
        try:
            return discover_ytdlp(id)
        except Exception as fallback:
            if classify_error(fallback)[0] in {"YOUTUBE_BLOCKED", "VIDEO_UNAVAILABLE"}:
                raise fallback
            raise primary


def metadata(id):
    try:
        with session() as client:
            response = client.get("https://www.youtube.com/oembed", params={"url": f"https://www.youtube.com/watch?v={id}", "format": "json"}, timeout=(4, 5))
            response.raise_for_status()
            data = response.json()
            return data.get("title", f"Vídeo {id}"), data.get("author_name", "YouTube")
    except Exception:
        return f"Vídeo {id}", "YouTube"


def discover_ytdlp(id):
    args = [sys.executable, "-m", "yt_dlp", "--ignore-config", "--skip-download", "--no-playlist", "--no-warnings", "--socket-timeout", "15", "--retries", "0", "--extractor-retries", "0", "--dump-single-json"]
    if os.getenv("YOUTUBE_PROXY_URL"):
        args += ["--proxy", os.environ["YOUTUBE_PROXY_URL"]]
    args += ["--", f"https://www.youtube.com/watch?v={id}"]
    result = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", timeout=55, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    if result.returncode:
        raise RuntimeError(result.stderr)
    data = json.loads(result.stdout)
    tracks = []
    for source, kind in [("automatic_captions", "automatic"), ("subtitles", "manual")]:
        for code, formats in data.get(source, {}).items():
            entry = next((f for f in formats if f.get("ext") == "json3"), None)
            if entry and "tlang=" not in entry["url"]:
                tracks.append({"language": entry.get("name", code), "code": code, "kind": kind, "provider": "ytdlp", "source": entry["url"]})
    return data.get("title", id), data.get("uploader", "YouTube"), tracks


def fetch_track(track):
    if track["provider"] == "transcript":
        return normalize(track["source"].fetch().to_raw_data())
    url = urlparse(track["source"])
    if url.scheme != "https" or url.hostname not in {"www.youtube.com", "youtube.com", "video.google.com"} or url.path != "/api/timedtext":
        raise ValueError("Endpoint de legenda inesperado.")
    with session() as client:
        response = client.get(track["source"], allow_redirects=False)
        response.raise_for_status()
        return from_json3(response.json())
