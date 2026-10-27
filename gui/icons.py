# gui/icons.py
"""Recolorable SVG icons ported 1:1 from the design prototype (data.jsx).

Each icon is a 16x16 stroke icon using `currentColor`; render() swaps the
color and rasterizes via QtSvg so icons stay crisp and match the design.
"""

import hashlib
import os
import sys
import tempfile

from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtGui import QIcon, QPixmap, QPainter
from PyQt6.QtCore import QByteArray, Qt

# Inner SVG markup (between <svg> tags). Stroke uses currentColor.
_PATHS = {
    "menu":    '<path d="M2.5 4h11M2.5 8h11M2.5 12h11"/>',
    "save":    '<path d="M3 2.5h7.5L13.5 5.5V13a.5.5 0 0 1-.5.5H3a.5.5 0 0 1-.5-.5V3a.5.5 0 0 1 .5-.5Z"/>'
               '<path d="M5 2.5v3h5v-3M5 13.5v-4h6v4"/>',
    "folder":  '<path d="M2 4a1 1 0 0 1 1-1h3l1.5 1.5H13a1 1 0 0 1 1 1V12a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1V4Z"/>',
    "sliders": '<path d="M2 4.5h7M12 4.5h2M2 11.5h2M7 11.5h7"/>'
               '<circle cx="10.5" cy="4.5" r="1.5"/><circle cx="5.5" cy="11.5" r="1.5"/>',
    "plug":    '<path d="M5 1.5v3M11 1.5v3M4 4.5h8v3a4 4 0 0 1-4 4 4 4 0 0 1-4-4v-3ZM8 11.5v3"/>',
    "help":    '<circle cx="8" cy="8" r="6.25"/>'
               '<path d="M6.25 6.25a1.75 1.75 0 1 1 2.6 1.52c-.45.27-.85.6-.85 1.23v.5"/>'
               '<circle cx="8" cy="11.5" r=".4" fill="currentColor"/>',
    "search":  '<circle cx="7" cy="7" r="4.5"/><path d="m10.5 10.5 3 3"/>',
    "edit":    '<path d="m11 2.5 2.5 2.5L6 12.5l-3 .5.5-3L11 2.5Z"/>',
    "network": '<rect x="2" y="2.5" width="12" height="7" rx="1"/><path d="M5 13.5h6M8 9.5v4"/>',
    "table":   '<rect x="2.5" y="3" width="11" height="10" rx="1"/><path d="M2.5 6.5h11M2.5 9.5h11M6 6.5v6.5"/>',
    "chart":   '<path d="M2.5 11.5 6 7l3 3 4.5-6"/><path d="M2.5 13.5h11"/>',
    "list":    '<path d="M5.5 4.5h8M5.5 8h8M5.5 11.5h8"/>'
               '<circle cx="3" cy="4.5" r=".7" fill="currentColor"/>'
               '<circle cx="3" cy="8" r=".7" fill="currentColor"/>'
               '<circle cx="3" cy="11.5" r=".7" fill="currentColor"/>',
    "sun":     '<circle cx="8" cy="8" r="2.5"/>'
               '<path d="M8 1.5V3M8 13v1.5M1.5 8H3M13 8h1.5M3.4 3.4l1 1M11.6 11.6l1 1M3.4 12.6l1-1M11.6 4.4l1-1"/>',
    "moon":    '<path d="M13 9.5A5.5 5.5 0 0 1 6.5 3 5.5 5.5 0 1 0 13 9.5Z"/>',
    "check":   '<path d="m3.5 8.5 3 3 6-6.5"/>',
    "x":       '<path d="m4 4 8 8M12 4l-8 8"/>',
    "focus":   '<circle cx="8" cy="8" r="3"/>'
               '<path d="M8 2v1.5M8 12.5V14M2 8h1.5M12.5 8H14"/>',
    "trash":   '<path d="M2.5 4.5h11M6 4.5V3a.5.5 0 0 1 .5-.5h3a.5.5 0 0 1 .5.5v1.5'
               'M4 4.5l.7 8.5a.5.5 0 0 0 .5.5h5.6a.5.5 0 0 0 .5-.5l.7-8.5"/>',
    "expand":  '<path d="M3 7V3h4M13 9v4H9M3 3l4 4M13 13l-4-4"/>',
    # filled icons (rendered with fill, no stroke)
    "pause":   '<rect x="5" y="3.5" width="2" height="9" rx=".5"/>'
               '<rect x="9" y="3.5" width="2" height="9" rx=".5"/>',
    "play":    '<path d="M5 3.5v9l8-4.5-8-4.5Z"/>',
    "grip":    '<circle cx="6" cy="3.5" r="1"/><circle cx="10" cy="3.5" r="1"/>'
               '<circle cx="6" cy="8" r="1"/><circle cx="10" cy="8" r="1"/>'
               '<circle cx="6" cy="12.5" r="1"/><circle cx="10" cy="12.5" r="1"/>',
    "terminal": '<rect x="2" y="3" width="12" height="10" rx="1.5"/>'
                '<path d="M4.5 6.5 6.5 8l-2 1.5M8.5 10h3"/>',
    "download": '<path d="M8 2.5v7M5 6.5 8 9.5l3-3M3.5 13h9"/>',
    "plus":     '<path d="M8 3.2v9.6M3.2 8h9.6"/>',
    # a cog with six teeth (the old eight rays read as a sun)
    "gear":     '<path d="M6.52 3.43 L6.85 1.50 L9.15 1.50 L9.48 3.43 L11.21 4.43 L13.06 3.76 L14.20 5.74 L12.70 7.00 L12.70 9.00 L14.20 10.26 L13.06 12.24 L11.21 11.57 L9.48 12.57 L9.15 14.50 L6.85 14.50 L6.52 12.57 L4.79 11.57 L2.94 12.24 L1.80 10.26 L3.30 9.00 L3.30 7.00 L1.80 5.74 L2.94 3.76 L4.79 4.43 Z"/>'
                '<circle cx="8" cy="8" r="2.2"/>',
    "contrast": '<circle cx="8" cy="8" r="6"/>'
                '<path d="M8 2a6 6 0 0 0 0 12Z" fill="currentColor" stroke="none"/>',
    "keyboard": '<rect x="1.5" y="4" width="13" height="8" rx="1.5"/>'
                '<path d="M4 6.7h.01M6.6 6.7h.01M9.2 6.7h.01M11.8 6.7h.01'
                'M4 9.2h.01M11.8 9.2h.01M6 9.3h4"/>',
    "info":     '<circle cx="8" cy="8" r="6.25"/>'
                '<path d="M8 7.2v3.6"/>'
                '<circle cx="8" cy="4.9" r=".55" fill="currentColor" stroke="none"/>',
    "warning":  '<path d="M8 2.2 14.4 13.3a.6.6 0 0 1-.52.9H2.12a.6.6 0 0 1-.52-.9L8 2.2Z"/>'
                '<path d="M8 6.4v3.4"/>'
                '<circle cx="8" cy="11.7" r=".55" fill="currentColor" stroke="none"/>',
    # filled icons (rendered with fill, no stroke)
    "stop":    '<rect x="4" y="4" width="8" height="8" rx="1.5"/>',
    # thin chevrons for combo/spin arrows (Qt can't do CSS border-triangles).
    "chevron":    '<path d="M4 6.5 8 10.5 12 6.5"/>',
    "chevron_up": '<path d="M4 9.5 8 5.5 12 9.5"/>',
    "cpu":        '<rect x="4.5" y="4.5" width="7" height="7" rx="1"/>'
                  '<path d="M6.5 1.5v3M9.5 1.5v3M6.5 11.5v3M9.5 11.5v3'
                  'M1.5 6.5h3M1.5 9.5h3M11.5 6.5h3M11.5 9.5h3"/>',
    # nav: scanner (radar sweep), sniffer (eye), dashboard (gauge)
    "radar":      '<circle cx="8" cy="8" r="6"/><circle cx="8" cy="8" r="2.6"/>'
                  '<path d="M8 8 12.3 3.8"/>'
                  '<circle cx="10.3" cy="9.8" r=".6" fill="currentColor" stroke="none"/>',
    "eye":        '<path d="M1.8 8s2.3-4.2 6.2-4.2S14.2 8 14.2 8s-2.3 4.2-6.2 4.2S1.8 8 1.8 8Z"/>'
                  '<circle cx="8" cy="8" r="2.1"/>',
    "gauge":      '<path d="M2.2 11.5a6.2 6.2 0 1 1 11.6 0"/>'
                  '<path d="M8 9.5 11 5.6"/>'
                  '<circle cx="8" cy="9.5" r="1" fill="currentColor" stroke="none"/>',
    "dots":       '<circle cx="3.4" cy="8" r="1.1" fill="currentColor" stroke="none"/>'
                  '<circle cx="8" cy="8" r="1.1" fill="currentColor" stroke="none"/>'
                  '<circle cx="12.6" cy="8" r="1.1" fill="currentColor" stroke="none"/>',
    # dashboard widget kinds (tile picker)
    "num":        '<rect x="2" y="3.5" width="12" height="9" rx="1.5"/>'
                  '<path d="M5 7.2v3.2M5 7.2h1.4M7.6 6.6h2.2v2.1H7.6v2.2h2.2"/>',
    "bars":       '<path d="M2.5 4.5h9M2.5 8h11.5M2.5 11.5h6"/>',
    "btn":        '<rect x="2" y="5" width="12" height="6.5" rx="3.25"/>'
                  '<circle cx="8" cy="8.2" r="1.1" fill="currentColor" stroke="none"/>',
    "field":      '<rect x="2" y="4.5" width="12" height="7" rx="1.5"/>'
                  '<path d="M5 6.6v2.8"/>',
    "switch":     '<rect x="1.8" y="5" width="12.4" height="6.5" rx="3.25"/>'
                  '<circle cx="10.9" cy="8.25" r="2.1" fill="currentColor" stroke="none"/>',
    "clock":      '<circle cx="8" cy="8" r="6"/><path d="M8 4.6V8l2.4 1.6"/>',
    "text":       '<path d="M3.5 4.5h9M8 4.5v7M6 11.5h4"/>',
    # a status word: two rows of bit cells, some set
    "bits":       '<rect x="1.6" y="4" width="12.8" height="8" rx="1.2"/>'
                  '<path d="M4.8 4v8M8 4v8M11.2 4v8M1.6 8h12.8"/>'
                  '<rect x="4.8" y="4" width="3.2" height="4" fill="currentColor"'
                  ' stroke="none"/>'
                  '<rect x="1.6" y="8" width="3.2" height="4" fill="currentColor"'
                  ' stroke="none"/>',
    # watch window: a short list under a magnifier
    "watch":      '<path d="M2.5 4h7M2.5 7.5h4.5M2.5 11h3"/>'
                  '<circle cx="11" cy="10" r="2.6"/><path d="m12.9 11.9 1.6 1.6"/>',
    # push-pin: "keep this window on top"
    "pin":        '<path d="M5.5 2.5h5M6.6 2.5v4L4.3 9h7.4L9.4 6.5v-4M8 9v4.5"/>',
    # slave / device simulator: a device answering (arrow back to the line)
    "reply":      '<rect x="7" y="2.5" width="6.5" height="11" rx="1.2"/>'
                  '<path d="M9 5.5h2.5M9 8h2.5"/><path d="M5.5 8H1.8M3.6 6.2 1.8 8l1.8 1.8"/>',
    "copy":       '<rect x="5.5" y="5.5" width="8" height="8.5" rx="1.5"/>'
                  '<path d="M10.5 5.5V3.3a1 1 0 0 0-1-1H3.3a1 1 0 0 0-1 1V9.5a1 1 0 0 0 1 1h2.2"/>',
    # macros: code brackets
    "code":       '<path d="M5.2 4.6 1.8 8l3.4 3.4M10.8 4.6 14.2 8l-3.4 3.4M9.1 2.8 6.9 13.2"/>',
    # compare: two columns with arrows between them
    "compare":    '<rect x="1.8" y="2.5" width="4.6" height="11" rx="1"/>'
                  '<rect x="9.6" y="2.5" width="4.6" height="11" rx="1"/>'
                  '<path d="M6.4 6h3.2M8.4 4.6 9.6 6 8.4 7.4M9.6 10H6.4M7.6 8.6 6.4 10l1.2 1.4"/>',
    # snapshots: a camera
    "camera":     '<path d="M2 5.6a1 1 0 0 1 1-1h1.9l1.1-1.6h4l1.1 1.6H13a1 1 0 0 1 1 1V12'
                  'a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1V5.6Z"/><circle cx="8" cy="8.7" r="2.3"/>',
    # logger: a sheet with a recording dot
    "logfile":    '<path d="M3.5 2.5a1 1 0 0 1 1-1h4.8l3.2 3.2V13.5a1 1 0 0 1-1 1h-7a1 1 0 0 1-1-1Z"/>'
                  '<path d="M9.2 1.5v3.3h3.3M5.6 8h3.2M5.6 10.6h2"/>'
                  '<circle cx="10.6" cy="11.4" r="1.3" fill="currentColor" stroke="none"/>',
    # rail collapse / expand
    "sidebar":    '<rect x="1.8" y="2.5" width="12.4" height="11" rx="1.6"/><path d="M6 2.5v11"/>',
    # project (a stack of sheets)
    "project":    '<path d="M2.5 5.5 8 2.6l5.5 2.9L8 8.4 2.5 5.5Z"/>'
                  '<path d="M2.5 8.2 8 11.1l5.5-2.9M2.5 10.9 8 13.8l5.5-2.9"/>',
    "dot":        '<circle cx="8" cy="8" r="4.2" fill="currentColor" stroke="none"/>',
    # refresh a list: a circular arrow
    "refresh":    '<path d="M13.2 8a5.2 5.2 0 1 1-1.6-3.75"/><path d="M13.3 2.6v3.1h-3.1"/>',
    # a condition gate: the pulse forks and only one branch continues
    "gate":       '<path d="M1.5 8h3.2"/><path d="M4.7 4.6h3.1l3 3.4-3 3.4H4.7Z"/>'
                  '<path d="M10.8 8h3.7"/>',
}

def asset_path(name: str) -> str:
    """A file from assets/, found both from source and in the PyInstaller
    bundle (where data files are unpacked under sys._MEIPASS)."""
    from app.paths import resource
    return resource("assets", name)


def app_icon() -> QIcon:
    """The application icon (generated by tools/make_icon.py)."""
    icon = QIcon()
    for name in ("app.ico", "app.png"):
        path = asset_path(name)
        if os.path.exists(path):
            icon.addFile(path)
    return icon


# Icons drawn with fill instead of stroke.
_FILLED = {"pause", "play", "grip", "stop"}


def _svg(name: str, color: str) -> bytes:
    inner = _PATHS[name].replace("currentColor", color)
    if name in _FILLED:
        attrs = f'fill="{color}" stroke="none"'
    else:
        attrs = (f'fill="none" stroke="{color}" stroke-width="1.4" '
                 f'stroke-linecap="round" stroke-linejoin="round"')
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" {attrs}>'
        f'{inner}</svg>'
    ).encode("utf-8")


# (name, color, size, dpr) -> QPixmap. An icon is a pure function of its key,
# and the same handful of keys is asked for over and over: every theme change
# re-colours the whole toolbar, every retranslate rebuilds its buttons. Qt
# pixmaps are implicitly shared and nothing here mutates one, so handing back
# the same object is safe. Bounded because the key space grows with the accent
# palette; the cap is far above the ~60 icons a session actually uses.
_PM_CACHE: dict = {}
_PM_CACHE_MAX = 400


def pixmap(name: str, color: str, size: int = 16, dpr: float = 2.0) -> QPixmap:
    key = (name, color, size, dpr)
    hit = _PM_CACHE.get(key)
    if hit is not None:
        return hit
    renderer = QSvgRenderer(QByteArray(_svg(name, color)))
    px = int(size * dpr)
    pm = QPixmap(px, px)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    renderer.render(p)
    p.end()
    pm.setDevicePixelRatio(dpr)
    if len(_PM_CACHE) >= _PM_CACHE_MAX:
        _PM_CACHE.clear()          # cheap eviction: rebuilding costs ~0.1 ms
    _PM_CACHE[key] = pm
    return pm


def icon(name: str, color: str, size: int = 16) -> QIcon:
    return QIcon(pixmap(name, color, size))


_CACHE_DIR = os.path.join(tempfile.gettempdir(), "modbusregreader_icons")


def icon_url(name: str, color: str, size: int = 12) -> str:
    """Render a themed icon to a cached PNG and return a QSS-ready url().

    Qt QSS cannot draw a CSS border-triangle (it renders a filled box instead),
    so combo/spin arrows need a real ``image: url(...)``. The PNG is rendered at
    2x for crispness and cached by (name, color, size) so themes don't rewrite
    it every restyle. Returns a forward-slashed absolute path wrapped in url().
    """
    os.makedirs(_CACHE_DIR, exist_ok=True)
    key = hashlib.md5(f"{name}:{color}:{size}".encode()).hexdigest()[:12]
    path = os.path.join(_CACHE_DIR, f"{name}_{key}.png")
    if not os.path.exists(path):
        # Render at 2x physical pixels for a crisp downscale by QSS.
        renderer = QSvgRenderer(QByteArray(_svg(name, color)))
        px = size * 2
        hi = QPixmap(px, px)
        hi.fill(Qt.GlobalColor.transparent)
        p = QPainter(hi)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        renderer.render(p)
        p.end()
        hi.save(path, "PNG")
    return "url(%s)" % path.replace("\\", "/")
