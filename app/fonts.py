# app/fonts.py
"""Which system fonts are safe to dress the UI in.

The font picker lists what the machine has installed, and a machine has plenty
of families that turn an interface into confetti: Wingdings, Webdings, Marlett,
the Segoe icon fonts. Picking one used to be unrecoverable in practice — every
label, including the settings page you would fix it from, became dingbats.

So the list is filtered, and the *saved* value is validated on every start:
a font that vanished (profile moved to another PC) or that is a symbol font
silently falls back to the default instead of wrecking the window.

Qt's own metadata does the classifying — no hardcoded blacklist to maintain:
a symbol font reports only ``WritingSystem.Symbol`` / ``Other``.
"""

from PyQt6.QtGui import QFontDatabase

_WS = QFontDatabase.WritingSystem
DEFAULT_FAMILY = "Segoe UI"
# Tried in order when the saved family is unusable.
FALLBACKS = ("Segoe UI", "Inter", "Arial", "Helvetica", "DejaVu Sans")

_cache: dict = {}


def _systems(family: str):
    if family not in _cache:
        _cache[family] = set(QFontDatabase.writingSystems(family))
    return _cache[family]


def is_symbol_font(family: str) -> bool:
    """True for dingbat/icon families — the ones that make the UI unreadable."""
    ws = _systems(family)
    if not ws:
        return True                       # Qt knows nothing about it: don't risk it
    return ws <= {_WS.Symbol, _WS.Other, _WS.Any}


def has_cyrillic(family: str) -> bool:
    """The UI is Russian-first; a family without Cyrillic renders it through
    Qt's fallback, which mixes two typefaces on one line. Worth warning about,
    not worth forbidding."""
    return _WS.Cyrillic in _systems(family)


def ui_families() -> list:
    """Installed families that are safe to use for interface text."""
    return [f for f in QFontDatabase.families() if not is_symbol_font(f)]


def default_family() -> str:
    """First installed fallback — never returns a family that isn't there."""
    installed = set(QFontDatabase.families())
    for f in FALLBACKS:
        if f in installed and not is_symbol_font(f):
            return f
    safe = ui_families()
    return safe[0] if safe else DEFAULT_FAMILY


def safe_family(family: str, default: str = "") -> str:
    """Validate a saved font choice.

    Returns *family* when it is installed and usable, otherwise *default* (or
    the first working fallback). This is what stops a bad value in
    app_settings.json from being a one-way trip."""
    fam = str(family or "").strip()
    installed = QFontDatabase.families()
    if not installed:
        # No font database at all (offscreen/headless, or a broken X session).
        # Trust the saved value rather than rewriting the user's settings from
        # an environment that cannot judge them.
        return fam or DEFAULT_FAMILY
    if fam and fam in installed and not is_symbol_font(fam):
        return fam
    if default and default in installed and not is_symbol_font(default):
        return default
    return default_family()
