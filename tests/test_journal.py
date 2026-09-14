"""Offline pipeline tests; fixtures are synthetic and never enter the live database."""
import json
import time
from datetime import datetime
import pytest
from fastapi.testclient import TestClient
from app import database, channels, monitor, providers, editorial, settings
from app.main import app

CHANNEL='UC1234567890123456789012'
OLD='abcdefghijk'
NEW='lmnopqrstuv'


@pytest.fixture
def db(tmp_path,monkeypatch):
    monkeypatch.setenv('JOURNAL_DB',str(tmp_path/'journal.sqlite3'))
    monkeypatch.setenv('MONITOR_ENABLED','0')
    monkeypatch.delenv('OPENAI_API_KEY',raising=False)
    monkeypatch.delenv('OPENAI_MODEL',raising=False)
    database.init();monitor.stopping.clear()
    monkeypatch.setattr(providers,'discover',lambda id:('Synthetic','Synthetic',[]))
    yield TestClient(app)


def imported(db,recent=False,name='Tecnologia'):
    return db.post('/api/journal/import',json={'topic':name,'text':f'https://youtube.com/channel/{CHANNEL}', 'include_recent':recent}).json()


def test_import_validation_persistence_and_duplicates(db):
    result=db.post('/api/journal/import',json={'topic':'Tecnologia','text':'\ufeffhttps://youtube.com/@CanalUm\nhttps://youtube.com/@CanalUm/videos\nhttps://evil.com/a\nhttps://youtube.com/watch?v=abcdefghijk\n\n# comentário\nhttps://youtube.com/@CanalDois','priority':5}).json()
    assert result['added']==2 and result['duplicates']==1 and len(result['errors'])==2
    database.init() # restart preserves all durable rows
    data=db.get('/api/journal/dashboard').json()
    assert len(data['channels'])==2 and data['topics'][0]['priority']==5
    result=db.post('/api/journal/import',json={'topic':'tecnologia','text':'https://youtube.com/@CanalUm'}).json()
    assert result['added']==0 and result['duplicates']==1
    assert len(db.get('/api/journal/dashboard').json()['topics'])==1
    assert db.post('/api/journal/import',json={'topic':'  ','text':'@canal'}).status_code==422


@pytest.mark.parametrize('url',['http://127.0.0.1/channel/abc','https://youtube.com@evil.com/@abc','https://youtube.com.evil.com/@abc','https://youtube.com:9000/@abc','https://youtube.com/playlist?list=abc'])
def test_channel_ssrf(url):
    with pytest.raises(ValueError):channels.channel_url(url)


def test_new_video_auto_only_retries_and_idempotency(db,monkeypatch):
    imported(db)
    now=time.time()
    monkeypatch.setattr(channels,'feed',lambda id:('Meu canal',[{'id':OLD,'title':'Anterior','published':now-3600}]))
    monitor.cycle()
    assert db.get('/api/journal/videos').json()['total']==1
    with database.connect() as conn:
        conn.execute('UPDATE channels SET next_check=0')
        conn.execute('UPDATE worker_state SET caption_next=0')
    monkeypatch.setattr(channels,'feed',lambda id:('Meu canal',[{'id':NEW,'title':'Novo','published':now+0.01},{'id':OLD,'title':'Anterior','published':now-3600}]))
    monkeypatch.setattr(providers,'discover',lambda id:('Novo','Canal',[{'kind':'manual','code':'pt'}]))
    monitor.cycle()
    data=db.get('/api/journal/videos').json()
    assert data['total']==2 and data['items'][0]['status']=='waiting'
    assert 'automática' in data['items'][0]['error']
    monkeypatch.setattr(providers,'discover',lambda id:('Novo','Canal',[{'kind':'manual','code':'pt'},{'kind':'automatic','code':'en'}]))
    def fetch(track):
        assert track['kind']=='automatic'
        return [{'start':0,'end':2000,'text':'Uma informação nova.'}]
    monkeypatch.setattr(providers,'fetch_track',fetch)
    db.post(f'/api/journal/videos/{NEW}/retry',json={})
    with database.connect() as conn:
        conn.execute('UPDATE channels SET next_check=0')
        conn.execute('UPDATE worker_state SET caption_next=0')
    monitor.cycle()
    video=db.get(f'/api/journal/videos/{NEW}').json()
    assert video['status']=='ready' and video['cleaned_text']=='Uma informação nova.'
    assert video['analysis_status']=='pending' and video['analysis'] is None
    assert db.get('/api/journal/videos').json()['total']==2


def test_include_recent_pause_and_catchup(db,monkeypatch):
    imported(db,True)
    monkeypatch.setattr(channels,'feed',lambda id:('Canal',[{'id':OLD,'title':'Antigo','published':time.time()-5000}]))
    monkeypatch.setattr(providers,'discover',lambda id:('X','Y',[]))
    monitor.cycle()
    assert db.get('/api/journal/videos').json()['total']==1
    db.post('/api/journal/channels/1/active',json={'active':False})
    monkeypatch.setattr(channels,'feed',lambda id:pytest.fail('Paused channel must not be polled'))
    monitor.cycle()
    db.post('/api/journal/channels/1/active',json={'active':True})
    monkeypatch.setattr(channels,'feed',lambda id:('Canal',[{'id':NEW,'title':'Novo','published':time.time()-1}]))
    monkeypatch.setattr(channels,'catch_up',lambda id,stop:[{'id':'12345678901','title':'Fora do feed','published':time.time()-100}])
    monitor.cycle()
    assert db.get('/api/journal/videos').json()['total']==3


def test_caption_treatment_keeps_raw_and_drops_rolling_overlap():
    cues=[{'start':0,'end':1000,'text':'Hoje uma nova medida'}, {'start':900,'end':2000,'text':'uma nova medida foi anunciada.'}, {'start':9000,'end':10000,'text':'uma nova medida foi anunciada.'}]
    assert editorial.treat(cues)=='Hoje uma nova medida foi anunciada. uma nova medida foi anunciada.'
    assert cues[1]['text']=='uma nova medida foi anunciada.'


def test_editorial_config_secret_and_cover_priority(db,monkeypatch):
    result=db.post('/api/journal/editorial',json={'key':'test-only-secret','model':'test-model'})
    assert result.status_code==200
    data=db.get('/api/journal/dashboard')
    assert 'test-only-secret' not in data.text and data.json()['ai_configured']
    now=time.time()
    with database.connect() as conn:
        for i,name,priority in [(1,'Tecnologia',2),(2,'Economia',5)]:
            conn.execute('INSERT INTO topics VALUES(?,?,?,?)',(i,name,priority,now))
            id=OLD if i==1 else NEW
            analysis={'headline':'Notícia de teste','summary':f'Relato [{id}]','points':[f'Dado [{id}]'],'importance':3}
            conn.execute("INSERT INTO videos(id,channel_id,title,published,discovered,collected,status,analysis_status,analysis) VALUES(?,?,?,?,?,?,'ready','ready',?)",(id,CHANNEL,'Notícia de teste',now,now,now,json.dumps(analysis)))
            conn.execute('INSERT INTO video_topics VALUES(?,?)',(id,i))
    def fake_generate(material):
        id=NEW if NEW in material else OLD
        return {'headline':'Manchete sintética','summary':f'Relato sintético [{id}]','points':[f'Ponto sintético [{id}]'],'importance':3}
    monkeypatch.setattr(editorial,'generate',fake_generate)
    edition=editorial.build_edition()
    assert edition['sections'][0]['topic']=='Economia' and len(edition['sections'])==2
    assert edition['sections'][0]['sources'][0]['id']==NEW
    assert db.get('/api/journal/editions/'+editorial.today()).json()['edition']==edition
    monkeypatch.setattr(editorial,'generate',lambda x:pytest.fail('Unchanged edition must use persisted output'))
    assert editorial.build_edition()==edition


def test_oversized_import_and_no_empty_topic(db):
    result=db.post('/api/journal/import',json={'topic':'Invalid','text':'https://example.com'})
    assert result.json()['added']==0
    assert db.get('/api/journal/dashboard').json()['topics']==[]
    assert db.post('/api/journal/import',json={'topic':'Large','text':'a'*160001}).status_code==413


def test_channel_feed_parser_rejects_wrong_channel(monkeypatch):
    class Response:
        content=b'<feed xmlns="http://www.w3.org/2005/Atom" xmlns:yt="http://www.youtube.com/xml/schemas/2015"><yt:channelId>bad</yt:channelId></feed>'
        def raise_for_status(self):pass
    class Session:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def get(self,*args,**kwargs):return Response()
    monkeypatch.setattr(channels,'session',Session)
    with pytest.raises(ValueError):channels.rss_feed(CHANNEL)


def test_channel_feed_accepts_real_youtube_root_without_uc(monkeypatch):
    class Response:
        content=f'<feed xmlns="http://www.w3.org/2005/Atom" xmlns:yt="http://www.youtube.com/xml/schemas/2015"><yt:channelId>{CHANNEL[2:]}</yt:channelId><title>Canal</title><entry><yt:channelId>{CHANNEL}</yt:channelId><yt:videoId>{NEW}</yt:videoId><title>Vídeo</title><published>2026-09-14T00:00:00+00:00</published></entry></feed>'.encode()
        def raise_for_status(self):pass
    class Session:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def get(self,*args,**kwargs):return Response()
    monkeypatch.setattr(channels,'session',Session)
    title,entries=channels.feed(CHANNEL)
    assert title=='Canal' and entries[0]['id']==NEW
