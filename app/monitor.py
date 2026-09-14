"""Restart-safe polling and caption/editorial queues. Runs while the application runs."""
import json
import os
import time
from datetime import datetime
from threading import Event, Thread

from . import channels, editorial, providers
from .caption_settings import proxy_url
from .database import connect, init

INTERVAL = max(60, int(os.getenv('MONITOR_INTERVAL_SECONDS', '600')))
CAPTION_INTERVAL = max(20, int(os.getenv('CAPTION_INTERVAL_SECONDS', '45')))
wake = Event()
stopping = Event()
thread = None


def state(message=None, error=None):
    with connect() as db:
        db.execute('UPDATE worker_state SET heartbeat=? WHERE id=1', (time.time(),))
        if message is not None:
            db.execute('UPDATE worker_state SET message=? WHERE id=1', (message,))
        if error is not None:
            db.execute('UPDATE worker_state SET error=? WHERE id=1', (error,))


def poll_channel(channel):
    now = time.time()
    try:
        id = channel['youtube_id'] or channels.resolve(channel['url'])
        with connect() as db:
            db.execute('UPDATE channels SET youtube_id=? WHERE id=?', (id, channel['id']))
        title, entries = channels.feed(id)
        coverage_error = ''
        recovered = []
        if channel['last_video'] and entries and channel['last_video'] not in {e['id'] for e in entries}:
            state('Recuperando publicações fora do feed recente…')
            try:
                recovered = channels.catch_up(id, channel['last_video'])
            except Exception as exc:
                coverage_error = str(exc) if isinstance(exc, ValueError) else 'Recuperação de publicações antigas pendente. Nova tentativa programada.'
        with connect() as db:
            current = db.execute('SELECT active FROM channels WHERE id=?', (channel['id'],)).fetchone()
            if not current or not current['active']:
                return
            existing = db.execute('SELECT id FROM channels WHERE topic_id=? AND youtube_id=? AND id<>?', (channel['topic_id'], id, channel['id'])).fetchone()
            if existing:
                db.execute("UPDATE channels SET youtube_id=?,title=?,active=0,status='duplicate',error=? WHERE id=?", (id, title, 'Este canal já está cadastrado neste assunto.', channel['id']))
                return
            seen = {r['video_id'] for r in db.execute('SELECT video_id FROM channel_seen WHERE channel_id=?', (channel['id'],))}
            first = not channel.get('bootstrapped', 0) or not channel['last_video']
            latest = next((e['id'] for e in entries if e.get('live_status') not in {'is_upcoming','is_live'} and (e.get('published') is None or e['published']<=now)), None)
            boundary = next((i for i,e in enumerate(entries) if e['id']==channel['last_video']),len(entries))
            newer = {e['id'] for e in entries[:boundary]} if channel['last_video'] else set()
            recovered_ids = {e['id'] for e in recovered}
            for entry in recovered + entries:
                published = entry.get('published')
                initial_latest = first and entry['id']==latest
                after_signup = published is not None and published>=channel['created']
                eligible = initial_latest or (first and channel['include_recent']) or after_signup or (entry['id'] in recovered_ids) or (not first and entry['id'] in newer)
                if (entry['id'] in seen and not initial_latest) or not eligible:
                    continue
                db.execute('''INSERT OR IGNORE INTO videos(id,channel_id,title,published,discovered,next_attempt)
                              VALUES(?,?,?,?,?,?)''', (entry['id'], id, entry['title'], published or now, now, max(now, published or now)))
                if published is None:
                    db.execute('UPDATE videos SET published_known=0 WHERE id=? AND discovered=?', (entry['id'],now))
                if initial_latest:
                    db.execute('UPDATE videos SET capture_priority=1,next_attempt=0 WHERE id=? AND status!=?', (entry['id'],'ready'))
                db.execute('INSERT OR IGNORE INTO video_topics VALUES(?,?)', (entry['id'], channel['topic_id']))
                analyzed = db.execute("SELECT collected FROM videos WHERE id=? AND analysis_status='ready'", (entry['id'],)).fetchone()
                if analyzed:
                    day = datetime.fromtimestamp(analyzed['collected'], editorial.TZ).date().isoformat()
                    db.execute('INSERT OR IGNORE INTO dirty_editions VALUES(?)', (day,))
            for entry in entries + recovered:
                db.execute('INSERT OR IGNORE INTO channel_seen VALUES(?,?)', (channel['id'],entry['id']))
            # Keep recovery cursor on failure; previously inserted videos are deduplicated.
            cursor = channel['last_video'] if coverage_error else (entries[0]['id'] if entries else channel['last_video'])
            db.execute('''UPDATE channels SET youtube_id=?,title=?,status=?,checked=?,next_check=?,error=?,last_video=?,failures=0,bootstrapped=1 WHERE id=?''',
                       (id, title, 'catchup_pending' if coverage_error else 'watching', now, now + INTERVAL, coverage_error, cursor, channel['id']))
    except Exception as exc:
        if isinstance(exc, ValueError):
            message = str(exc)
        elif getattr(exc, 'response', None) is not None:
            message = f'O YouTube retornou HTTP {exc.response.status_code}. Nova tentativa programada.'
        elif isinstance(exc, (TimeoutError,)) or 'timeout' in type(exc).__name__.lower():
            message = 'O YouTube demorou a responder. Nova tentativa programada.'
        else:
            message = 'Falha de conexão com o YouTube. Nova tentativa programada.'
        with connect() as db:
            db.execute("UPDATE channels SET status='error',checked=?,next_check=?,error=?,failures=failures+1 WHERE id=?",
                       (now, now + min(21600, 60 * 2 ** min(channel['failures'], 8)), message, channel['id']))


def collect(video):
    connection = proxy_url()
    stage = 'list'
    now = time.time()
    with connect() as db:
        db.execute("UPDATE videos SET status='collecting',next_attempt=?,attempts=attempts+1 WHERE id=?", (now + 240, video['id']))
        db.execute('UPDATE worker_state SET caption_next=? WHERE id=1', (now+CAPTION_INTERVAL,))
    try:
        _, _, tracks = providers.discover(video['id'])
        auto = [t for t in tracks if t['kind'] == 'automatic']
        if not auto:
            raise ValueError('A legenda automática ainda não está disponível. O vídeo continuará sendo verificado.')
        auto.sort(key=lambda t: (not t['code'].startswith('pt'), t['code'] != 'en'))
        stage = 'fetch'
        cues = providers.fetch_track(auto[0])
        if not cues:
            raise ValueError('A legenda automática retornou vazia. Nova tentativa programada.')
        if len(cues) > 30000 or sum(len(c['text']) for c in cues) > 2000000:
            raise ValueError('Legenda maior que o limite de processamento (2 milhões de caracteres).')
        treated = editorial.treat(cues)
        if not treated.strip():
            raise ValueError('A legenda não contém fala utilizável. Nova tentativa programada.')
        with connect() as db:
            db.execute("UPDATE videos SET status='ready',collected=?,language=?,cues=?,cleaned_text=?,error='',error_stage='',error_code='' WHERE id=?",
                       (time.time(), auto[0]['code'], json.dumps(cues, ensure_ascii=False), treated, video['id']))
            if connection == proxy_url():
                db.execute('UPDATE worker_state SET caption_blocks=0,caption_next=? WHERE id=1', (time.time()+CAPTION_INTERVAL,))
    except Exception as exc:
        message = str(exc) if isinstance(exc, ValueError) else providers.classify_error(exc)[1]
        delay = min(86400, 300 * 2 ** min(video['attempts'], 9))
        with connect() as db:
            code = providers.classify_error(exc)[0]
            db.execute("UPDATE videos SET status='waiting',next_attempt=?,error=?,error_stage=?,error_code=? WHERE id=?", (now + delay, message, stage, code, video['id']))
            if code=='YOUTUBE_BLOCKED' and connection == proxy_url():
                blocks=db.execute('SELECT caption_blocks FROM worker_state WHERE id=1').fetchone()['caption_blocks']
                cooldown=min(21600,900*2**min(blocks,5))
                db.execute('UPDATE worker_state SET caption_next=?,caption_blocks=caption_blocks+1 WHERE id=1', (time.time()+cooldown,))


def analyze(video):
    try:
        analysis = editorial.analyze_video(video, heartbeat=lambda: state('Redigindo a partir das legendas…'))
        day = datetime.fromtimestamp(video['collected'], editorial.TZ).date().isoformat()
        with connect() as db:
            db.execute("UPDATE videos SET analysis=?,analysis_status='ready',analysis_error='' WHERE id=?", (json.dumps(analysis, ensure_ascii=False), video['id']))
            db.execute('INSERT OR IGNORE INTO dirty_editions VALUES(?)', (day,))
    except Exception as exc:
        message = str(exc) if isinstance(exc, ValueError) else 'A análise não foi concluída. Nova tentativa em uma hora.'
        with connect() as db:
            db.execute("UPDATE videos SET analysis_status='error',analysis_error=?,analysis_retry=? WHERE id=?", (message, time.time()+3600, video['id']))


def cycle():
    now = time.time()
    with connect() as db:
        # DB lease prevents duplicate schedulers when two app processes overlap.
        claimed = db.execute('UPDATE worker_state SET running=1,heartbeat=? WHERE id=1 AND (running=0 OR heartbeat<?)', (now, now-240)).rowcount
    if not claimed:
        return
    try:
        with connect() as db:
            pending_channels = [dict(x) for x in db.execute('SELECT * FROM channels WHERE active=1 AND next_check<=? ORDER BY next_check LIMIT 5', (now,))]
        for channel in pending_channels:
            if stopping.is_set(): return
            state('Consultando ' + (channel['title'] or channel['url']))
            poll_channel(channel)
        with connect() as db:
            caption_next=db.execute('SELECT caption_next FROM worker_state WHERE id=1').fetchone()['caption_next']
            pending_videos = [] if caption_next>time.time() else [dict(x) for x in db.execute('''SELECT v.* FROM videos v WHERE status!='ready' AND next_attempt<=?
                AND EXISTS(SELECT 1 FROM channels c JOIN video_topics vt ON vt.topic_id=c.topic_id
                    WHERE vt.video_id=v.id AND c.youtube_id=v.channel_id AND c.active=1)
                ORDER BY capture_priority DESC,next_attempt,discovered LIMIT 1''', (time.time(),))]
        for video in pending_videos:
            if stopping.is_set(): return
            state('Acessando a legenda: ' + video['title'])
            collect(video)
        if editorial.configured():
            with connect() as db:
                pending_analysis = [dict(x) for x in db.execute("SELECT * FROM videos WHERE status='ready' AND analysis_status!='ready' AND analysis_retry<=? ORDER BY collected LIMIT 2", (time.time(),))]
            for video in pending_analysis:
                if stopping.is_set(): return
                state('Preparando a análise: ' + video['title'])
                analyze(video)
            with connect() as db:
                days = [r['day'] for r in db.execute('SELECT day FROM dirty_editions ORDER BY day')]
            for day in days:
                if stopping.is_set(): return
                state('Montando a edição de ' + day)
                editorial.build_edition(day, heartbeat=lambda: state('Montando a edição de ' + day))
                with connect() as db:
                    db.execute('DELETE FROM dirty_editions WHERE day=?', (day,))
        state('Acompanhando os canais', error='')
    finally:
        with connect() as db:
            db.execute('UPDATE worker_state SET running=0,heartbeat=? WHERE id=1', (time.time(),))


def loop():
    while not stopping.is_set():
        wake.clear()
        try:
            cycle()
        except Exception as exc:
            state('Aguardando nova tentativa', error=str(exc) if isinstance(exc, ValueError) else 'Não foi possível concluir este ciclo. O acompanhamento será retomado.')
            # Back off journal errors instead of repeatedly spending on generation.
            stopping.wait(60)
        wake.wait(20)


def start():
    global thread
    init()
    if os.getenv('MONITOR_ENABLED', '1') == '0' or (thread and thread.is_alive()):
        return
    stopping.clear()
    thread = Thread(target=loop, name='journal-monitor', daemon=True)
    thread.start()


def stop():
    stopping.set(); wake.set()
    if thread:
        thread.join(timeout=3)
