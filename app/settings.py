import json
import os
from pathlib import Path


def path():
    return Path(os.getenv('JOURNAL_DB', str(Path(__file__).resolve().parent.parent / 'data/journal.sqlite3'))).parent / 'editorial-settings.json'


def read():
    try:
        data = json.loads(path().read_text(encoding='utf-8'))
    except (OSError, ValueError):
        data = {}
    return {'key': os.getenv('OPENAI_API_KEY') or data.get('key', ''), 'model': os.getenv('OPENAI_MODEL') or data.get('model', '')}


def save(key, model):
    target = path()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix('.tmp')
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
        json.dump({'key': key or read()['key'], 'model': model}, stream)
    temporary.replace(target)
