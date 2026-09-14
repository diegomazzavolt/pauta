import os
from contextlib import asynccontextmanager
import re
import secrets
import time
from collections import OrderedDict, defaultdict, deque
from pathlib import Path
from threading import Lock, BoundedSemaphore
from typing import Literal
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import providers
from . import monitor
from .journal_api import router as journal_router
from .subtitles import export, video_id

ROOT = Path(__file__).resolve().parent.parent
@asynccontextmanager
async def lifespan(app):
    monitor.start()
    yield
    monitor.stop()

app = FastAPI(title="Pauta — Jornal dos seus canais", docs_url=None, redoc_url=None, lifespan=lifespan)
app.include_router(journal_router)
lock = Lock()
slots = BoundedSemaphore(4)
cache = OrderedDict()
rate = defaultdict(deque)
TTL = 900


@app.middleware("http")
async def security(request: Request, call_next):
    if request.method == "POST":
        origin = request.headers.get("origin")
        if origin and origin != str(request.base_url).rstrip("/"):
            return JSONResponse({"detail": {"message": "Origem não autorizada."}}, status_code=403)
        try:
            limit = 160000 if request.url.path == '/api/journal/import' else 4096
            if int(request.headers.get("content-length", "0")) > limit:
                return JSONResponse({"detail": {"message": "Requisição muito grande."}}, status_code=413)
        except ValueError:
            return Response(status_code=400)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' data: https://i.ytimg.com; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    if request.url.path.startswith("/api"):
        response.headers["Cache-Control"] = "no-store"
    return response


class VideoRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2048)


def fail(code, message, status=422):
    raise HTTPException(status_code=status, detail={"code": code, "message": message})


def checked_action(action):
    if not slots.acquire(blocking=False):
        fail("BUSY", "Há consultas em andamento. Tente novamente em alguns segundos.", 503)
    try:
        return action()
    except HTTPException:
        raise
    except Exception as exc:
        code, message = providers.classify_error(exc)
        fail(code, message, 502 if code in {"EXTRACTION_FAILED", "YOUTUBE_BLOCKED"} else 422)
    finally:
        slots.release()


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/videos")
def find_video(body: VideoRequest, request: Request):
    try:
        id = video_id(body.url)
    except ValueError as exc:
        fail("INVALID_URL", str(exc))
    now = time.monotonic()
    ip = request.client.host if request.client else "local"
    with lock:
        for key in list(rate):
            if not rate[key] or rate[key][-1] < now - 60:
                del rate[key]
        if len(rate) >= 10000 and ip not in rate:
            fail("BUSY", "Tente novamente em um minuto.", 429)
        queue = rate[ip]
        while queue and queue[0] < now - 60:
            queue.popleft()
        if len(queue) >= 12:
            fail("RATE_LIMIT", "Muitas consultas. Aguarde um minuto e tente novamente.", 429)
        queue.append(now)
    title, author, tracks = checked_action(lambda: providers.discover(id))
    if not tracks:
        fail("NO_CAPTIONS", "Este vídeo não tem legendas disponíveis. Experimente outro link.")
    tracks.sort(key=lambda t: (t["kind"] != "automatic", not t["code"].startswith("pt"), t["language"]))
    token = secrets.token_urlsafe(24)
    item = {"id": id, "title": title, "author": author, "tracks": tracks, "expires": time.monotonic() + TTL, "cues": {}, "fetch_lock": Lock()}
    with lock:
        for key in list(cache):
            if cache[key]["expires"] < now:
                del cache[key]
        cache[token] = item
        while len(cache) > 48:
            cache.popitem(last=False)
    return {"token": token, "videoId": id, "title": title, "author": author,
            "tracks": [{"id": str(i), "language": t["language"], "code": t["code"], "kind": t["kind"]} for i, t in enumerate(tracks)]}


def transcript(token, track_id):
    with lock:
        item = cache.get(token)
    if not item or item["expires"] < time.monotonic():
        fail("EXPIRED", "Esta consulta expirou. Busque as legendas novamente.", 410)
    if not track_id.isdigit() or int(track_id) >= len(item["tracks"]):
        fail("TRACK_NOT_FOUND", "Idioma não encontrado.", 404)
    index = int(track_id)
    with item["fetch_lock"]:
        if index not in item["cues"]:
            cues = checked_action(lambda: providers.fetch_track(item["tracks"][index]))
            if not cues:
                fail("EMPTY_CAPTIONS", "O YouTube retornou uma legenda vazia. Tente novamente mais tarde.", 502)
            if len(cues) > 30000 or sum(len(c["text"]) for c in cues) > 2000000:
                fail("TOO_LARGE", "A legenda excede o tamanho suportado.", 413)
            item["cues"][index] = cues
    return item, index, item["cues"][index]


@app.get("/api/videos/{token}/tracks/{track_id}")
def preview(token: str, track_id: str):
    _, _, cues = transcript(token, track_id)
    return {"cues": cues}


@app.get("/api/videos/{token}/tracks/{track_id}/download")
def download(token: str, track_id: str, format: Literal["srt", "vtt", "txt"] = "srt"):
    item, index, cues = transcript(token, track_id)
    title = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", item["title"]).strip(" .")[:120] or item["id"]
    language = re.sub(r"[^a-zA-Z0-9_-]", "", item["tracks"][index]["code"])
    filename = f"{title}.{language}.{format}"
    return Response(export(cues, format), media_type="text/vtt" if format == "vtt" else "text/plain", headers={"Content-Disposition": f"attachment; filename=\"subtitles.{format}\"; filename*=UTF-8''{quote(filename)}"})


@app.get("/")
def home():
    return FileResponse(ROOT / "static/journal.html")


@app.get('/extrator')
def extractor():
    return FileResponse(ROOT / "static/index.html")


app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
