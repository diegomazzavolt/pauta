"""Durable application data. One connection per operation, WAL and foreign keys."""
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def connect():
    path = Path(os.getenv('JOURNAL_DB', str(Path(__file__).resolve().parent.parent / 'data/journal.sqlite3')))
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=20)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init():
    with connect() as db:
        db.execute('PRAGMA journal_mode=WAL')
        db.executescript('''
        CREATE TABLE IF NOT EXISTS topics (
          id INTEGER PRIMARY KEY, name TEXT NOT NULL COLLATE NOCASE UNIQUE,
          priority INTEGER NOT NULL DEFAULT 3 CHECK(priority BETWEEN 1 AND 5), created REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS channels (
          id INTEGER PRIMARY KEY, topic_id INTEGER NOT NULL REFERENCES topics(id),
          url TEXT NOT NULL, youtube_id TEXT, title TEXT NOT NULL DEFAULT '',
          active INTEGER NOT NULL DEFAULT 1, status TEXT NOT NULL DEFAULT 'queued',
          created REAL NOT NULL, include_recent INTEGER NOT NULL DEFAULT 0,
          checked REAL, next_check REAL NOT NULL DEFAULT 0, error TEXT NOT NULL DEFAULT '',
          last_video TEXT, failures INTEGER NOT NULL DEFAULT 0,
          UNIQUE(topic_id, url));
        CREATE TABLE IF NOT EXISTS videos (
          id TEXT PRIMARY KEY, channel_id TEXT NOT NULL, title TEXT NOT NULL,
          published REAL NOT NULL, discovered REAL NOT NULL, collected REAL,
          status TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
          next_attempt REAL NOT NULL DEFAULT 0, error TEXT NOT NULL DEFAULT '',
          language TEXT, cues TEXT, cleaned_text TEXT,
          analysis TEXT, analysis_status TEXT NOT NULL DEFAULT 'pending',
          analysis_error TEXT NOT NULL DEFAULT '', analysis_retry REAL NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS video_topics (
          video_id TEXT NOT NULL REFERENCES videos(id), topic_id INTEGER NOT NULL REFERENCES topics(id),
          PRIMARY KEY(video_id, topic_id));
        CREATE TABLE IF NOT EXISTS ai_cache (
          fingerprint TEXT PRIMARY KEY, content TEXT NOT NULL, created REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS editions (
          day TEXT PRIMARY KEY, content TEXT NOT NULL, fingerprint TEXT NOT NULL,
          updated REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS dirty_editions (day TEXT PRIMARY KEY);
        CREATE TABLE IF NOT EXISTS worker_state (
          id INTEGER PRIMARY KEY CHECK(id=1), heartbeat REAL NOT NULL DEFAULT 0,
          running INTEGER NOT NULL DEFAULT 0, message TEXT NOT NULL DEFAULT '',
          error TEXT NOT NULL DEFAULT '');
        INSERT OR IGNORE INTO worker_state(id) VALUES(1);
        CREATE INDEX IF NOT EXISTS video_due ON videos(status,next_attempt);
        CREATE INDEX IF NOT EXISTS channel_due ON channels(active,next_check);
        ''')
