"""Verify a prepared article's public HTML, not merely a Git commit or queued build."""
import hashlib
import json
from pathlib import Path
import sys
import time
from urllib.parse import urlparse
from urllib.request import Request, urlopen


def fetch_public(url):
    request = Request(url, headers={'User-Agent': 'FichaRA-publication-check', 'Cache-Control': 'no-cache'})
    with urlopen(request, timeout=20) as response:
        final = urlparse(response.url)
        if final.scheme != 'https' or final.hostname != 'fichara.com':
            raise ValueError('Redirección inesperada')
        if response.status != 200:
            raise RuntimeError('La página no respondió correctamente')
        return response.read()


def verify(url, expected, fetch=fetch_public, attempts=12, pause=15):
    parsed = urlparse(url)
    if parsed.scheme != 'https' or parsed.hostname != 'fichara.com' or parsed.username or parsed.password or not parsed.path.startswith('/blog/'):
        raise ValueError('Solo se verifica el blog de FichaRA')
    expected_hash = hashlib.sha256(expected).digest()
    for attempt in range(attempts):
        try:
            separator = '&' if '?' in url else '?'
            body = fetch(url + separator + 'verification=' + str(time.time_ns()))
            if hashlib.sha256(body).digest() == expected_hash:
                return True
        except (OSError, RuntimeError):
            pass
        if attempt + 1 < attempts:
            time.sleep(pause)
    raise RuntimeError('El HTML público todavía no coincide; no se declara publicación verificada')


if __name__ == '__main__':
    data = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
    if data.get('status') != 'published_to_repository':
        raise SystemExit('No hay una publicación nueva que verificar')
    path = Path('blog') / data['slug'] / 'index.html'
    verify(data['url'], path.read_bytes())
    print('PUBLICACIÓN PÚBLICA VERIFICADA:', data['url'])
