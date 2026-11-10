"""Deterministic editorial queue. No models, purchases or network requests.
Default: dry-run. Exactly one ready article per invocation.
"""
import argparse
import csv
import io
import json
import re
from datetime import date
from html import escape
from pathlib import Path
from urllib.parse import urlparse
import xml.etree.ElementTree as ET

SITE = 'https://fichara.com'
QUEUE = '.github/content-queue.json'
RECEIPTS = '.github/content-published.json'


def read_json(path, default=None):
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default


def safe_url(url):
    parsed = urlparse(url)
    if parsed.scheme != 'https' or parsed.username or parsed.password or parsed.hostname not in {'fichara.com', 'www.boe.es'}:
        raise ValueError('URL externa no permitida')
    return escape(url, quote=True)


def validate(article):
    slug = article.get('slug', '')
    if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', slug):
        raise ValueError('Slug no válido')
    for field in ('title', 'description', 'category'):
        if not isinstance(article.get(field), str) or not article[field].strip():
            raise ValueError('Falta un campo editorial')
    if len(article['description']) > 170:
        raise ValueError('Descripción demasiado larga')
    if not article.get('intro') or not article.get('sections') or not article.get('sources'):
        raise ValueError('Contenido sin introducción, secciones o fuentes')
    for link in article['sources'] + article.get('related', []):
        safe_url(link['url'])
    sheet = article.get('worksheet')
    if sheet and not re.fullmatch(r'[a-z0-9-]+\.csv', sheet['filename']):
        raise ValueError('Nombre de descarga no válido')


def render(article, published):
    e = lambda text: escape(str(text), quote=True)
    url = f"{SITE}/blog/{article['slug']}/"
    body = ''.join(f'<p>{e(p)}</p>' for p in article['intro'])
    for section in article['sections']:
        body += f"<section><h2>{e(section['heading'])}</h2>"
        body += ''.join(f'<p>{e(p)}</p>' for p in section.get('paragraphs', []))
        if section.get('bullets'):
            body += '<ul>' + ''.join(f'<li>{e(p)}</li>' for p in section['bullets']) + '</ul>'
        body += '</section>'
    sheet = article.get('worksheet')
    if sheet:
        body += f"<aside><h2>Plantilla de trabajo gratuita</h2><p>Lista organizativa orientativa, no un formulario oficial ni un sustituto del registro de jornada.</p><a download href=\"{e(sheet['filename'])}\">Descargar lista en CSV</a></aside>"
    body += '<section><h2>Fuentes y lecturas relacionadas</h2><ol>'
    for link in article['sources'] + article.get('related', []):
        body += f"<li><a href=\"{safe_url(link['url'])}\">{e(link['title'])}</a></li>"
    body += '</ol></section>'
    schema = json.dumps({'@context': 'https://schema.org', '@type': 'Article', 'headline': article['title'], 'description': article['description'], 'datePublished': published, 'dateModified': published, 'mainEntityOfPage': url, 'author': {'@type': 'Organization', 'name': 'FichaRA'}, 'publisher': {'@type': 'Organization', 'name': 'FichaRA', 'url': SITE}}, ensure_ascii=False).replace('<', '\\u003c')
    css = "*{box-sizing:border-box}body{margin:0;font:18px/1.75 system-ui,sans-serif;color:#292929}nav,footer{background:#0f0f0f;color:#fff;padding:20px 5vw}nav a,footer a{color:#fff;margin-right:24px}header{background:#0f0f0f;color:#fff;padding:54px max(5vw,calc((100vw - 900px)/2))}h1{font-size:clamp(30px,5vw,48px);line-height:1.15}main{max-width:900px;margin:auto;padding:30px 5vw 60px}h2{line-height:1.3;margin-top:40px;border-left:5px solid #cc1b1b;padding-left:14px}a{color:#ac1616}li{margin-bottom:9px}aside,.cta{border:1px solid #ddd;border-radius:12px;padding:24px;margin-top:32px}.tag{color:#ff9494;font-size:14px}small{font-size:14px}a:focus-visible{outline:3px solid #cc1b1b;outline-offset:4px}.skip{position:absolute;top:-100px}.skip:focus{top:0;background:white;padding:12px}"
    return f'''<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(article['title'])} | FichaRA</title><meta name="description" content="{e(article['description'])}"><meta name="robots" content="index,follow"><link rel="canonical" href="{url}"><meta property="og:type" content="article"><meta property="og:title" content="{e(article['title'])}"><meta property="og:description" content="{e(article['description'])}"><meta property="og:url" content="{url}"><meta property="og:image" content="{SITE}/logo192.png"><script type="application/ld+json">{schema}</script><style>{css}</style></head><body><a class="skip" href="#contenido">Saltar al contenido</a><nav aria-label="Principal"><a href="/">FichaRA</a><a href="/blog/">Blog</a><a href="/reuniones.html">Pedir demostración</a></nav><header><p class="tag">{e(article['category'])}</p><h1>{e(article['title'])}</h1><p><small>Equipo FichaRA · <time datetime="{published}">{published}</time></small></p></header><main id="contenido"><article>{body}<section class="cta"><h2>¿Encaja FichaRA en tu empresa?</h2><p>Comprueba en una demostración cómo se adapta el fichaje y la gestión de personal a tu forma de trabajar. No todas las empresas necesitan el mismo proceso.</p><p><a href="/reuniones.html">Solicitar una demostración sin compromiso</a> · <a href="/#funciones">Consultar las funciones de FichaRA</a></p></section></article></main><footer><p>FichaRA · Utrera, Sevilla</p><a href="/aviso-legal.html">Aviso legal</a><a href="/privacidad.html">Privacidad</a><a href="/condiciones.html">Condiciones</a></footer></body></html>'''


def worksheet_bytes(sheet):
    stream = io.StringIO(newline='')
    writer = csv.writer(stream, quoting=csv.QUOTE_ALL)
    for row in sheet['rows']:
        cells = []
        for value in row:
            text = str(value)
            cells.append("'" + text if text.lstrip().startswith(('=', '+', '-', '@')) else text)
        writer.writerow(cells)
    return ('\ufeff' + stream.getvalue()).encode('utf-8')


def run(root, published, apply=False):
    root = Path(root)
    date.fromisoformat(published)
    queue = read_json(root / QUEUE)
    if not queue or queue.get('version') != 1:
        raise ValueError('Cola no válida')
    articles = queue['articles']
    slugs = [a.get('slug') for a in articles]
    if len(slugs) != len(set(slugs)):
        raise ValueError('Slugs duplicados')
    if any(a.get('published_on') == published for a in articles):
        return {'status': 'already_ran_today', 'date': published}
    ready = next((a for a in articles if a.get('status') == 'ready'), None)
    if ready is None:
        return {'status': 'empty', 'message': 'Sin artículos preparados; no se inventa contenido ni se publica nada.'}
    validate(ready)
    path = root / 'blog' / ready['slug'] / 'index.html'
    if path.exists():
        raise ValueError('La URL ya existe; se requiere revisión manual')
    html = render(ready, published)
    url = f"{SITE}/blog/{ready['slug']}/"
    index_path = root / 'blog/index.html'
    index = index_path.read_text(encoding='utf-8')
    marker = '<div class="blog-grid">'
    if index.count(marker) != 1 or url in index:
        raise ValueError('Índice incompatible o enlace ya existente')
    card = f'''\n<a href="{url}" class="article-card"><div class="card-img"><div class="card-icon" aria-hidden="true">📋</div></div><div class="card-body"><span class="card-tag">{escape(ready['category'])}</span><div class="card-title">{escape(ready['title'])}</div><div class="card-desc">{escape(ready['description'])}</div><div class="card-leer">Leer guía y descargar lista</div></div></a>\n'''
    index = index.replace(marker, marker + card, 1)
    sitemap_path = root / 'sitemap.xml'
    sitemap = sitemap_path.read_text(encoding='utf-8')
    ET.fromstring(sitemap)
    if sitemap.count('</urlset>') != 1 or url in sitemap:
        raise ValueError('Sitemap incompatible o URL duplicada')
    def update_blog_date(match):
        block = match.group(0)
        if re.search(r'<loc>\s*https://fichara\.com/blog/\s*</loc>', block):
            block = re.sub(r'\s*<lastmod>.*?</lastmod>', '', block, flags=re.S)
            block = block.replace('</loc>', f'</loc><lastmod>{published}</lastmod>', 1)
        return block
    sitemap = re.sub(r'<url>.*?</url>', update_blog_date, sitemap, flags=re.S)
    sitemap = sitemap.replace('</urlset>', f'<url><loc>{url}</loc><lastmod>{published}</lastmod></url>\n</urlset>')
    ET.fromstring(sitemap)
    llms_path = root / 'llms.txt'
    llms = llms_path.read_text(encoding='utf-8')
    llms += f"\n- [{ready['title']}]({url}): {ready['description']}\n"
    ready['status'] = 'published'
    ready['published_on'] = published
    receipt = {'slug': ready['slug'], 'url': url, 'date': published, 'deployment': 'not_verified'}
    receipts = read_json(root / RECEIPTS, {'articles': []})
    receipts['articles'].append(receipt)
    files = {
        path: html.encode('utf-8'),
        index_path: index.encode('utf-8'),
        sitemap_path: sitemap.encode('utf-8'),
        llms_path: llms.encode('utf-8'),
    }
    sheet = ready.get('worksheet')
    if sheet:
        files[path.parent / sheet['filename']] = worksheet_bytes(sheet)
    files[root / QUEUE] = (json.dumps(queue, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    files[root / RECEIPTS] = (json.dumps(receipts, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    if apply:
        import os
        import tempfile
        for target, data in files.items():
            target.parent.mkdir(parents=True, exist_ok=True)
            fd, temporary_name = tempfile.mkstemp(prefix='.content-', dir=target.parent)
            temporary = Path(temporary_name)
            try:
                with os.fdopen(fd, 'wb') as handle:
                    handle.write(data)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)
    return {'status': 'published_to_repository' if apply else 'ready', 'slug': ready['slug'], 'url': url, 'date': published, 'deployment': 'not_verified', 'files_planned': [str(p.relative_to(root)).replace('\\', '/') for p in files]}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', default='.')
    parser.add_argument('--date', default=date.today().isoformat())
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    print(json.dumps(run(args.root, args.date, args.apply), ensure_ascii=False))
