import json
import os
import re
import subprocess
import sys
from datetime import datetime
from urllib.parse import unquote, urlparse

from defusedxml import ElementTree
from .providers import session

CHANNEL_ID = re.compile(r'UC[A-Za-z0-9_-]{22}')
NS = {'a': 'http://www.w3.org/2005/Atom', 'yt': 'http://www.youtube.com/xml/schemas/2015'}


def channel_url(value):
    value = value.strip().lstrip('\ufeff')
    if value.startswith('@'):
        value = 'https://www.youtube.com/' + value
    if not value.startswith(('https://', 'http://')):
        value = 'https://' + value
    url = urlparse(value)
    if url.hostname not in {'youtube.com', 'www.youtube.com', 'm.youtube.com'} or url.username or url.password or url.port not in {None, 443, 80}:
        raise ValueError('Use um link de canal do YouTube.')
    parts = unquote(url.path).strip('/').split('/')
    if parts and parts[-1] in {'videos', 'shorts', 'streams', 'featured', 'playlists'}:
        parts.pop()
    valid = (len(parts) == 1 and re.fullmatch(r'@[\w.\-]{2,100}', parts[0])) or (len(parts) == 2 and ((parts[0] == 'channel' and CHANNEL_ID.fullmatch(parts[1])) or (parts[0] in {'c', 'user'} and re.fullmatch(r'[\w.\-]{1,100}', parts[1]))))
    if not valid:
        raise ValueError('Esperado um canal (@nome ou /channel/UC…), não um vídeo.')
    return 'https://www.youtube.com/' + '/'.join(parts)


def parse_import(text):
    if len(text.encode('utf-8')) > 128000:
        raise ValueError('O TXT deve ter até 128 KB.')
    links, errors, duplicates = [], [], 0
    seen = set()
    for line, value in enumerate(text.splitlines(), 1):
        value = value.strip().lstrip('\ufeff')
        if not value or value.startswith('#'):
            continue
        try:
            url = channel_url(value)
            key = url.casefold() if '/channel/' not in url else url
            if key in seen:
                duplicates += 1
            else:
                links.append(url); seen.add(key)
        except ValueError as exc:
            errors.append({'line': line, 'value': value[:160], 'message': str(exc)})
    if len(links) > 500:
        raise ValueError('Importe no máximo 500 canais por assunto de cada vez.')
    return links, errors, duplicates


def resolve(url):
    tail = url.rsplit('/', 1)[-1]
    if '/channel/' in url and CHANNEL_ID.fullmatch(tail):
        return tail
    patterns = [r'"externalId"\s*:\s*"(UC[A-Za-z0-9_-]{22})"', r'<meta[^>]*itemprop="channelId"[^>]*content="(UC[A-Za-z0-9_-]{22})"', r'https://www.youtube.com/feeds/videos.xml\?channel_id=(UC[A-Za-z0-9_-]{22})']
    with session() as client:
        for _ in range(2):
            with client.get(url, allow_redirects=False, stream=True) as response:
                response.raise_for_status()
                if response.is_redirect:
                    url = channel_url(response.headers.get('Location', ''))
                    continue
                page = ''
                for chunk in response.iter_content(8192):
                    page += chunk.decode('utf-8', errors='replace')
                    for pattern in patterns:
                        match = re.search(pattern, page)
                        if match:
                            return match.group(1)
                    if len(page) > 8000000:
                        break
                break
    raise ValueError('Não foi possível identificar este canal. Tente o endereço /channel/UC… ou verifique o @nome.')


def feed(channel_id):
    if not CHANNEL_ID.fullmatch(channel_id):
        raise ValueError('ID de canal inválido.')
    with session() as client:
        response = client.get('https://www.youtube.com/feeds/videos.xml', params={'channel_id': channel_id}, allow_redirects=False)
        response.raise_for_status()
        if len(response.content) > 2000000:
            raise ValueError('Resposta do canal muito grande.')
    root = ElementTree.fromstring(response.content)
    # YouTube currently omits the UC prefix on the feed root, but not on entries.
    if root.findtext('yt:channelId', namespaces=NS) not in {channel_id, channel_id[2:]}:
        raise ValueError('A resposta não corresponde ao canal solicitado.')
    entries = []
    for entry in root.findall('a:entry', NS):
        if entry.findtext('yt:channelId', namespaces=NS) != channel_id:
            raise ValueError('Vídeo de outro canal na resposta do feed.')
        id = entry.findtext('yt:videoId', namespaces=NS)
        if id and re.fullmatch(r'[\w-]{11}', id):
            entries.append({'id': id, 'title': entry.findtext('a:title', default=id, namespaces=NS),
                            'published': datetime.fromisoformat(entry.findtext('a:published', namespaces=NS).replace('Z', '+00:00')).timestamp()})
    entries.sort(key=lambda e: e['published'], reverse=True)
    return root.findtext('a:title', default=channel_id, namespaces=NS), entries


def catch_up(channel_id, stop_id):
    """Reconcile beyond RSS window. Failure keeps the old cursor and a visible warning."""
    result = subprocess.run([sys.executable, '-m', 'app.reconcile', channel_id, stop_id], capture_output=True,
        text=True, encoding='utf-8', timeout=180,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    if result.returncode:
        raise ValueError('A recuperação de vídeos fora do feed está pendente. O ponto de acompanhamento foi preservado para nova tentativa.')
    return json.loads(result.stdout)
