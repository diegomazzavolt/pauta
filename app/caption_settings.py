"""YouTube connection settings, kept outside source control and API responses."""
import json
import os
from urllib.parse import urlparse
from .settings import path


def proxy_url():
    if os.getenv('YOUTUBE_PROXY_URL'):
        return os.environ['YOUTUBE_PROXY_URL']
    try:
        return json.loads(path().with_name('caption-settings.json').read_text(encoding='utf-8')).get('proxy', '')
    except (OSError, ValueError):
        return ''


def status():
    return {'proxy_configured': bool(proxy_url()), 'managed_by_environment': bool(os.getenv('YOUTUBE_PROXY_URL'))}


def save(proxy):
    if os.getenv('YOUTUBE_PROXY_URL'):
        raise ValueError('A conexão está definida por YOUTUBE_PROXY_URL no servidor. Altere essa variável para mudar a conexão.')
    proxy = proxy.strip()
    if proxy:
        try:
            parsed = urlparse(proxy)
            valid = (parsed.scheme in {'http', 'https'} and parsed.hostname and parsed.port
                     and parsed.path in {'', '/'} and not parsed.query and not parsed.fragment
                     and not any(c.isspace() or ord(c) < 32 for c in proxy))
        except ValueError:
            valid = False
        if not valid:
            raise ValueError('Informe um proxy HTTP ou HTTPS com endereço e porta, sem caminho ou parâmetros.')
    target = path().with_name('caption-settings.json')
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix('.tmp')
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
        json.dump({'proxy': proxy}, stream)
    temporary.replace(target)
