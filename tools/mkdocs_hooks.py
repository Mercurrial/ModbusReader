# tools/mkdocs_hooks.py
"""MkDocs hook for the project site (mkdocs.yml → hooks).

The site states the current version and release date — on the home page and
in the schema.org data search engines read. Both come from app/version.py, the
single source tools/release.py writes, so a release never has to touch the
site. The file is read as text: importing the app package would pull in Qt.

Pictures: docs/images holds the README's PNGs (2× screenshots, up to 1.3 MB).
The site serves them as WebP no wider than WEBP_MAX_W, lazily loaded, with
their size in the tag (no layout jump) — made at build time, so the
repository keeps one copy of every picture.
"""
import hashlib
import os
import re
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

WEBP_MAX_W = 1600        # twice the widest content column — sharp on HiDPI
WEBP_MIN_BYTES = 40_000  # icons and small pictures stay PNG
WEBP_QUALITY = 82
# Encoded pictures are kept between builds (CI restores this folder too).
_CACHE = os.environ.get("MKDOCS_WEBP_CACHE") or os.path.join(
    tempfile.gettempdir(), "modbusreader-site-webp")
_IMG = re.compile(r"<img\b[^>]*>")
_SRC = re.compile(r'\bsrc="([^"]+\.png)"')


def read_version(root: str = ROOT) -> dict:
    with open(os.path.join(root, "app", "version.py"), encoding="utf-8") as f:
        text = f.read()

    def field(name):
        m = re.search(rf'^{name} = "([^"]*)"', text, re.M)
        return m.group(1) if m else ""
    return {"app_version": field("APP_VERSION"),
            "release_date": field("RELEASE_DATE")}


def on_config(config, **_kwargs):
    config.extra.update(read_version())
    return config


def on_page_markdown(markdown, config, **_kwargs):
    """``{{ app_version }}`` in a page → the current version."""
    return markdown.replace("{{ app_version }}", config.extra["app_version"])


def on_page_context(context, page, **_kwargs):
    """The home pages are the product's front door, not documentation: no
    "edit this page" pencil there."""
    if page.url in ("", "en/"):
        page.edit_url = None
    return context


# ── pictures ────────────────────────────────────────────────────────────
def to_webp(png_path: str) -> tuple:
    """A WebP twin of *png_path* (next to it): resized to WEBP_MAX_W,
    animation kept. Returns (webp_path, width, height), or None when the PNG
    is small enough to leave alone. Encoded once per picture content —
    `mkdocs serve` rebuilds on every edit."""
    from PIL import Image
    if os.path.getsize(png_path) < WEBP_MIN_BYTES:
        return None
    data = open(png_path, "rb").read()
    settings = ("%d/%d/4" % (WEBP_MAX_W, WEBP_QUALITY)).encode()
    key = hashlib.sha1(data + settings).hexdigest()
    os.makedirs(_CACHE, exist_ok=True)
    cached = os.path.join(_CACHE, key + ".webp")
    dims = os.path.join(_CACHE, key + ".size")
    if not (os.path.exists(cached) and os.path.exists(dims)):
        with Image.open(png_path) as im:
            w, h = im.size
            scale = min(1.0, WEBP_MAX_W / w)
            size = (round(w * scale), round(h * scale))
            frames = getattr(im, "n_frames", 1)
            if frames > 1:                         # the animated trend (APNG)
                out, durations = [], []
                for i in range(frames):
                    im.seek(i)
                    out.append(im.convert("RGBA").resize(size, Image.LANCZOS))
                    durations.append(im.info.get("duration", 100))
                out[0].save(cached, "WEBP", save_all=True, append_images=out[1:],
                            duration=durations, loop=0, quality=WEBP_QUALITY,
                            method=4)
            else:
                im.convert("RGBA").resize(size, Image.LANCZOS).save(
                    cached, "WEBP", quality=WEBP_QUALITY, method=4)
        with open(dims, "w") as f:
            f.write("%d %d" % size)
    webp = os.path.splitext(png_path)[0] + ".webp"
    with open(cached, "rb") as src, open(webp, "wb") as dst:
        dst.write(src.read())
    w, h = (int(x) for x in open(dims).read().split())
    return webp, w, h


def _rewrite(html: str, html_path: str, made: dict) -> str:
    """Point every big PNG <img> of one page at its WebP: lazy, sized."""
    first = [True]

    def one(m):
        tag = m.group(0)
        src = _SRC.search(tag)
        if not src or src.group(1).startswith(("http:", "https:", "data:")):
            return tag
        png = os.path.normpath(os.path.join(os.path.dirname(html_path),
                                            src.group(1).split("#")[0]))
        if not os.path.isfile(png):
            return tag
        if png not in made:
            made[png] = to_webp(png)
        if made[png] is None:
            return tag
        _webp, w, h = made[png]
        tag = tag.replace(src.group(0), 'src="%s.webp"' % src.group(1)[:-4])
        extra = ""
        if " width=" not in tag and " height=" not in tag:
            extra += ' width="%d" height="%d"' % (w, h)
        # The first picture is the one above the fold: load it at once.
        extra += ' decoding="async"' if first[0] else ' loading="lazy" decoding="async"'
        first[0] = False
        return tag[:-2].rstrip() + extra + " />" if tag.endswith("/>") \
            else tag[:-1].rstrip() + extra + ">"
    return _IMG.sub(one, html)


def on_post_build(config, **_kwargs):
    made = {}
    for folder, _dirs, files in os.walk(config["site_dir"]):
        for name in files:
            if not name.endswith(".html"):
                continue
            path = os.path.join(folder, name)
            html = open(path, encoding="utf-8").read()
            new = _rewrite(html, path, made)
            if new != html:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(new)
