"""Runs in a bounded subprocess, traversing the uploads playlist until the saved cursor."""
import json
import os
import re
import sys
import time
import yt_dlp


def main():
    channel, stop = sys.argv[1:3]
    if not re.fullmatch(r'UC[\w-]{22}', channel) or not re.fullmatch(r'[\w-]{11}', stop):
        raise ValueError('Invalid cursor')
    options = {'quiet': True, 'no_warnings': True, 'extract_flat': True, 'lazy_playlist': True,
               'skip_download': True, 'socket_timeout': 15, 'retries': 0,
               'extractor_retries': 0, 'proxy': os.getenv('YOUTUBE_PROXY_URL')}
    entries = []
    with yt_dlp.YoutubeDL(options) as client:
        playlist = client.extract_info('https://www.youtube.com/playlist?list=UU' + channel[2:], download=False)
        for entry in playlist['entries']:
            if entry['id'] == stop:
                print(json.dumps(entries)); return
            if re.fullmatch(r'[\w-]{11}', entry.get('id', '')):
                entries.append({'id': entry['id'], 'title': entry.get('title', entry['id']),
                                'published': entry.get('timestamp') or time.time()})
    # A deleted anchor must not silently mark incomplete coverage as complete.
    raise ValueError('Saved cursor not found; recovery requires attention')


if __name__ == '__main__':
    main()
