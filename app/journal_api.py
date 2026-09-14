import json
import time
from datetime import date
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from . import channels, editorial, monitor
from . import settings
from .database import connect

router = APIRouter(prefix='/api/journal')


class ImportBody(BaseModel):
    topic: str = Field(min_length=1, max_length=80)
    text: str = Field(min_length=1, max_length=128000)
    priority: int = Field(default=3, ge=1, le=5)
    include_recent: bool = False


class PriorityBody(BaseModel):
    priority: int = Field(ge=1, le=5)


class ActiveBody(BaseModel):
    active: bool


class EditorialBody(BaseModel):
    key: str = Field(default='', max_length=500)
    model: str = Field(min_length=1, max_length=100, pattern=r'^[a-zA-Z0-9._:-]+$')


@router.post('/editorial')
def editorial_settings(body: EditorialBody):
    if not (body.key.strip() or settings.read()['key']):
        bad('Informe a chave da API para ativar a redação.')
    settings.save(body.key.strip(), body.model.strip())
    monitor.wake.set()
    return {'ok': True}


def bad(message, status=422):
    raise HTTPException(status_code=status, detail={'message': message})


@router.post('/import')
def import_channels(body: ImportBody):
    name = body.topic.strip()
    if not name:
        bad('Dê um nome ao assunto deste bloco de canais.')
    try:
        links, errors, duplicates = channels.parse_import(body.text)
    except ValueError as exc:
        bad(str(exc))
    if not links:
        return {'added': 0, 'duplicates': duplicates, 'errors': errors, 'topic_id': None}
    with connect() as db:
        db.execute('INSERT OR IGNORE INTO topics(name,priority,created) VALUES(?,?,?)', (name, body.priority, time.time()))
        topic = db.execute('SELECT id FROM topics WHERE name=? COLLATE NOCASE', (name,)).fetchone()
        added = 0
        for url in links:
            count = db.execute('INSERT OR IGNORE INTO channels(topic_id,url,created,include_recent) VALUES(?,?,?,?)',
                               (topic['id'], url, time.time(), int(body.include_recent))).rowcount
            added += count
            if not count: duplicates += 1
    monitor.wake.set()
    return {'added': added, 'duplicates': duplicates, 'errors': errors, 'topic_id': topic['id']}


@router.get('/dashboard')
def dashboard():
    with connect() as db:
        topics = [dict(r) for r in db.execute('SELECT * FROM topics ORDER BY priority DESC,name')]
        channel_rows = [dict(r) for r in db.execute('SELECT * FROM channels ORDER BY id')]
        counts = {r['status']: r['n'] for r in db.execute('SELECT status,COUNT(*) n FROM videos GROUP BY status')}
        pending_analysis = db.execute("SELECT COUNT(*) n FROM videos WHERE status='ready' AND analysis_status!='ready'").fetchone()['n']
        worker = dict(db.execute('SELECT * FROM worker_state WHERE id=1').fetchone())
        editions = [r['day'] for r in db.execute('SELECT day FROM editions ORDER BY day DESC')]
    return {'topics': topics, 'channels': channel_rows, 'counts': counts, 'pending_analysis': pending_analysis,
            'worker': worker, 'ai_configured': editorial.configured(), 'model': settings.read()['model'], 'interval': monitor.INTERVAL,
            'today': editorial.today(), 'editions': editions}


@router.post('/topics/{topic_id}/priority')
def priority(topic_id: int, body: PriorityBody):
    with connect() as db:
        if not db.execute('UPDATE topics SET priority=? WHERE id=?', (body.priority, topic_id)).rowcount:
            bad('Assunto não encontrado.', 404)
        db.execute('INSERT OR IGNORE INTO dirty_editions VALUES(?)', (editorial.today(),))
    monitor.wake.set()
    return {'ok': True}


@router.post('/channels/{channel_id}/active')
def active(channel_id: int, body: ActiveBody):
    with connect() as db:
        if not db.execute('UPDATE channels SET active=?,next_check=0 WHERE id=?', (int(body.active), channel_id)).rowcount:
            bad('Canal não encontrado.', 404)
    monitor.wake.set()
    return {'ok': True}


@router.post('/check')
def check():
    with connect() as db:
        # Avoid bypassing platform backoff by repeated button clicks.
        db.execute("UPDATE channels SET next_check=0 WHERE active=1 AND (checked IS NULL OR checked<?)", (time.time()-60,))
    monitor.wake.set()
    return {'queued': True}


@router.get('/videos')
def videos(offset: int = 0, topic_id: int | None = None):
    if offset < 0: bad('Página inválida.')
    where = 'WHERE EXISTS(SELECT 1 FROM video_topics vt WHERE vt.video_id=v.id AND vt.topic_id=?)' if topic_id else ''
    params = [topic_id] if topic_id else []
    with connect() as db:
        total = db.execute(f'SELECT COUNT(*) n FROM videos v {where}', params).fetchone()['n']
        rows = [dict(r) for r in db.execute(f'''SELECT id,title,channel_id,published,published_known,discovered,collected,status,attempts,error,
            next_attempt,language,analysis_status,analysis_error FROM videos v {where} ORDER BY discovered DESC LIMIT 50 OFFSET ?''', params+[offset])]
    return {'items': rows, 'total': total, 'offset': offset}


@router.get('/videos/{id}')
def video(id: str):
    with connect() as db:
        row = db.execute('SELECT * FROM videos WHERE id=?', (id,)).fetchone()
    if not row: bad('Vídeo não encontrado.', 404)
    result = dict(row)
    result['analysis'] = json.loads(result['analysis']) if result['analysis'] else None
    result.pop('cues', None)
    return result


@router.post('/videos/{id}/retry')
def retry(id: str):
    with connect() as db:
        if not db.execute('SELECT id FROM videos WHERE id=?', (id,)).fetchone(): bad('Vídeo não encontrado.', 404)
        db.execute("UPDATE videos SET next_attempt=0,analysis_retry=0,capture_priority=1 WHERE id=? AND status!='collecting'", (id,))
    monitor.wake.set()
    return {'queued': True}


@router.get('/editions/{day}')
def edition(day: str):
    try: date.fromisoformat(day)
    except ValueError: bad('Data inválida.')
    with connect() as db:
        row = db.execute('SELECT content FROM editions WHERE day=?', (day,)).fetchone()
    return {'edition': json.loads(row['content']) if row else None}
