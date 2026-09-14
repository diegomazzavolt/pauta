import json
import time
import pytest
import requests
from app import channels, database, monitor, providers
from tests.test_journal import db, imported, CHANNEL, OLD, NEW


def test_missing_rss_uses_uploads(monkeypatch):
    response=requests.Response();response.status_code=404
    def missing(cid):raise requests.HTTPError(response=response)
    monkeypatch.setattr(channels,'rss_feed',missing)
    monkeypatch.setattr(channels,'uploads',lambda cid:('Canal',[{'id':NEW,'published':None}]))
    assert channels.feed(CHANNEL)[1][0]['id']==NEW
    response.status_code=429
    with pytest.raises(requests.HTTPError):channels.feed(CHANNEL)


def test_initial_latest_only_without_dates_and_next_upload(db,monkeypatch):
    imported(db)
    monkeypatch.setattr(channels,'feed',lambda cid:('Canal',[{'id':NEW,'title':'Último','published':None},{'id':OLD,'title':'Anterior','published':None}]))
    monitor.cycle()
    data=db.get('/api/journal/videos').json()
    assert data['total']==1 and data['items'][0]['id']==NEW and data['items'][0]['published_known']==0
    with database.connect() as conn:conn.execute('UPDATE channels SET next_check=0')
    monitor.cycle()
    assert db.get('/api/journal/videos').json()['total']==1
    monkeypatch.setattr(channels,'feed',lambda cid:('Canal',[{'id':'12345678901','title':'Novo lançamento','published':None},{'id':NEW,'title':'Último','published':None},{'id':OLD,'title':'Anterior','published':None}]))
    with database.connect() as conn:conn.execute('UPDATE channels SET next_check=0')
    monitor.cycle()
    assert db.get('/api/journal/videos').json()['total']==2


def test_existing_channel_gets_latest_once_and_empty_channel_recovers(db,monkeypatch):
    imported(db)
    with database.connect() as conn:conn.execute('UPDATE channels SET last_video=?',(NEW,))
    monkeypatch.setattr(channels,'feed',lambda cid:('Canal',[{'id':NEW,'title':'Último','published':time.time()-86400}]))
    monitor.cycle()
    assert db.get('/api/journal/videos').json()['total']==1
    with database.connect() as conn:conn.execute('UPDATE channels SET next_check=0')
    monitor.cycle()
    assert db.get('/api/journal/videos').json()['total']==1


def test_block_pauses_entire_caption_queue(db,monkeypatch):
    imported(db,True)
    monkeypatch.setattr(channels,'feed',lambda cid:('Canal',[{'id':NEW,'title':'Novo','published':None},{'id':OLD,'title':'Anterior','published':None}]))
    calls=[]
    def blocked(id):calls.append(id);raise RuntimeError('Sign in to confirm you are not a bot')
    monkeypatch.setattr(providers,'discover',blocked)
    monitor.cycle();monitor.cycle()
    assert calls==[NEW]
    state=db.get('/api/journal/dashboard').json()['worker']
    assert state['caption_next']>time.time()+850 and state['caption_blocks']==1
    db.post(f'/api/journal/videos/{OLD}/retry',json={});monitor.cycle()
    assert calls==[NEW] # UI retry must not defeat the global platform cooldown.


def test_uploads_skip_live_upcoming_and_keep_timestamp_unknown(monkeypatch):
    monkeypatch.setattr(channels,'listing',lambda url,limit:{'channel_id':CHANNEL,'channel':'Canal','entries':[
        {'id':'12345678901','title':'Agendado','live_status':'is_upcoming'},
        {'id':NEW,'title':'Publicado','timestamp':None},
        {'id':OLD,'title':'Privado','availability':'private'}]})
    title,entries=channels.uploads(CHANNEL)
    assert title=='Canal' and len(entries)==1 and entries[0]['published'] is None
