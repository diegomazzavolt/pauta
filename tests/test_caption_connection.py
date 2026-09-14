import time
import pytest
import requests
from youtube_transcript_api._errors import PoTokenRequired, IpBlocked
from app import caption_settings, providers, database, monitor, settings
from tests.test_journal import db, imported, NEW, CHANNEL


def test_error_classification_does_not_confuse_token_with_rate_limit():
    assert providers.classify_error(PoTokenRequired(NEW))[0] == 'CAPTION_TOKEN_REQUIRED'
    assert providers.classify_error(IpBlocked(NEW))[0] == 'YOUTUBE_BLOCKED'
    assert providers.classify_error(RuntimeError('robotics subtitle parser failed'))[0] == 'EXTRACTION_FAILED'
    response = requests.Response(); response.status_code = 429
    assert 'HTTP 429' in providers.classify_error(requests.HTTPError(response=response))[1]


def test_proxy_save_preserves_editorial_secret_and_resumes_only_on_change(db, monkeypatch):
    monkeypatch.delenv('YOUTUBE_PROXY_URL', raising=False)
    settings.save('editorial-test-key', 'test-model')
    with database.connect() as conn:
        conn.execute('UPDATE worker_state SET caption_next=?,caption_blocks=2', (time.time()+900,))
    proxy='http://test-user:test-secret@proxy.example:8080'
    result=db.post('/api/journal/caption-connection',json={'proxy':proxy})
    assert result.status_code==200 and result.json()['proxy_configured']
    assert caption_settings.proxy_url()==proxy and settings.read()['key']=='editorial-test-key'
    data=db.get('/api/journal/dashboard')
    assert 'test-secret' not in data.text and 'test-user' not in data.text and 'proxy.example' not in data.text
    assert data.json()['worker']['caption_next']==0
    with database.connect() as conn:conn.execute('UPDATE worker_state SET caption_next=12345,caption_blocks=2')
    db.post('/api/journal/caption-connection',json={'proxy':proxy})
    assert db.get('/api/journal/dashboard').json()['worker']['caption_next']==12345
    assert db.post('/api/journal/caption-connection',json={'direct':True}).status_code==200
    assert not caption_settings.proxy_url()


@pytest.mark.parametrize('proxy',['file:///tmp/x','http://host','https://host:123/path','http://host:bad','http://host:123?x=y','http://a\n:123'])
def test_invalid_proxy_rejected(db, monkeypatch, proxy):
    monkeypatch.delenv('YOUTUBE_PROXY_URL', raising=False)
    assert db.post('/api/journal/caption-connection',json={'proxy':proxy}).status_code==422


def test_environment_proxy_is_not_overwritten(db, monkeypatch):
    monkeypatch.setenv('YOUTUBE_PROXY_URL','http://env.example:8080')
    assert db.post('/api/journal/caption-connection',json={'direct':True}).status_code==422
    assert caption_settings.proxy_url()=='http://env.example:8080'
    assert providers.session().proxies['https']=='http://env.example:8080'


def test_fetch_failure_records_stage_and_token_does_not_pause_queue(db, monkeypatch):
    imported(db)
    with database.connect() as conn:
        conn.execute('INSERT INTO videos(id,channel_id,title,published,discovered) VALUES(?,?,?,?,?)',(NEW,CHANNEL,'Test',time.time(),time.time()))
        video=dict(conn.execute('SELECT * FROM videos WHERE id=?',(NEW,)).fetchone())
    monkeypatch.setattr(providers,'discover',lambda id:('Test','Test',[{'kind':'automatic','code':'pt'}]))
    def failed(track):raise PoTokenRequired(NEW)
    monkeypatch.setattr(providers,'fetch_track',failed)
    monitor.collect(video)
    with database.connect() as conn:
        row=conn.execute('SELECT error_stage,error_code FROM videos WHERE id=?',(NEW,)).fetchone()
        assert dict(row)=={'error_stage':'fetch','error_code':'CAPTION_TOKEN_REQUIRED'}
        assert conn.execute('SELECT caption_blocks FROM worker_state').fetchone()[0]==0
