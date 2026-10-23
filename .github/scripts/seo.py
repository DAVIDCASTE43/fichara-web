"""Tareas SEO automáticas de fichara.com (se ejecuta en GitHub Actions).

1. Actualiza <lastmod> en sitemap.xml con la fecha del último cambio de cada página.
2. Avisa a IndexNow (Bing, Yandex, etc.) de las páginas que han cambiado en este push.
"""
import json, os, re, subprocess, sys, urllib.request

SITE = "https://fichara.com"
KEY = "88b0b0cf79ab81131463bbf8d183fa49"


def git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True).stdout.strip()


def url_to_file(url):
    path = url.replace(SITE + "/", "", 1)
    if path == "" or path.endswith("/"):
        return path + "index.html"
    return path


def file_to_url(path):
    if path == "index.html":
        return SITE + "/"
    if path.endswith("/index.html"):
        return SITE + "/" + path[: -len("index.html")]
    return SITE + "/" + path


def update_sitemap():
    text = open("sitemap.xml", encoding="utf-8").read()

    def repl(m):
        block = m.group(0)
        loc = re.search(r"<loc>(.*?)</loc>", block).group(1)
        date = git("log", "-1", "--format=%cs", "--", url_to_file(loc))
        if not date:
            return block
        block = re.sub(r"\s*<lastmod>.*?</lastmod>", "", block)
        return block.replace("</loc>", f"</loc>\n    <lastmod>{date}</lastmod>", 1)

    new = re.sub(r"<url>.*?</url>", repl, text, flags=re.S)
    if new != text:
        open("sitemap.xml", "w", encoding="utf-8").write(new)
        print("sitemap.xml actualizado")
    else:
        print("sitemap.xml sin cambios")


def ping_indexnow(before, after):
    if not before or set(before) == {"0"}:
        print("Primer push o rama nueva: no se avisa a IndexNow")
        return
    changed = git("diff", "--name-only", before, after).splitlines()
    sitemap_urls = set(re.findall(r"<loc>(.*?)</loc>", open("sitemap.xml", encoding="utf-8").read()))
    urls = sorted({file_to_url(f) for f in changed if f.endswith(".html")} & sitemap_urls)
    if not urls:
        print("No hay páginas del sitemap modificadas")
        return
    body = json.dumps({
        "host": "fichara.com",
        "key": KEY,
        "keyLocation": f"{SITE}/{KEY}.txt",
        "urlList": urls,
    }).encode()
    req = urllib.request.Request("https://api.indexnow.org/indexnow", data=body,
                                 headers={"Content-Type": "application/json; charset=utf-8"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            print(f"IndexNow: {r.status} — {len(urls)} URL(s) enviadas:", *urls, sep="\n  ")
    except Exception as e:  # no rompe el despliegue si IndexNow falla
        print("IndexNow no respondió bien:", e)


if __name__ == "__main__":
    mode = sys.argv[1]
    if mode == "sitemap":
        update_sitemap()
    elif mode == "indexnow":
        ping_indexnow(os.environ.get("BEFORE", ""), os.environ.get("AFTER", "HEAD"))
