# theme_manager.py
"""Theme/accent registry. Each theme is one entry in ``THEMES`` (a flat dict of
color tokens consumed by ``styles.get_stylesheet`` and the widgets). Accents
overlay a few tokens from ``ACCENT_PALETTES``.

``get_theme`` returns a deep copy so callers (and the accent overlay) can mutate
the result without corrupting the shared registry.

Descriptor + Registry style (mirrors datatypes.py): adding a theme = adding ONE
entry to ``THEMES`` — no branching in ``get_theme``. Token *keys* must match
across themes (the stylesheet reads the same names regardless of theme).
"""
import copy

# ── tiny colour maths (pure, no Qt) ─────────────────────────────────────
def _rgb(h: str) -> tuple:
    h = h.lstrip("#")
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _hex(rgb) -> str:
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(round(v)))) for v in rgb)


def _mix(a: str, b: str, t: float) -> str:
    """Blend *a* toward *b* by *t* (0..1)."""
    ra, rb = _rgb(a), _rgb(b)
    return _hex(ra[i] + (rb[i] - ra[i]) * t for i in range(3))


def _luma(h: str) -> float:
    """Perceived brightness 0..1 — decides whether text on this colour is
    black or white, so an accent can never end up unreadable on itself."""
    r, g, b = (v / 255 for v in _rgb(h))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _rel_luma(h: str) -> float:
    """WCAG relative luminance (gamma-corrected, unlike _luma)."""
    def lin(c):
        c /= 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (lin(v) for v in _rgb(h))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(a: str, b: str) -> float:
    """WCAG contrast ratio (1..21) — used to keep text legible on any accent."""
    la, lb = _rel_luma(a), _rel_luma(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _tint(h: str, alpha: float = 0.16) -> str:
    r, g, b = _rgb(h)
    return f"rgba({r},{g},{b},{alpha})"


# ── accents ─────────────────────────────────────────────────────────────
# One hue per entry, with a value tuned for each surface family: the same
# blue that reads well on near-black is far too light on paper. ``accent_fg``
# is derived from luminance, so a light accent gets dark text automatically.
ACCENT_PALETTES = {
    'neutral': {'dark': '#d8dfe6', 'light': '#232a30'},
    'blue':    {'dark': '#5dadec', 'light': '#1668b8'},
    'emerald': {'dark': '#4db888', 'light': '#0f7a52'},
    'amber':   {'dark': '#ddb855', 'light': '#96650a'},
    'violet':  {'dark': '#b85dec', 'light': '#7331ac'},
    'rose':    {'dark': '#ec5d8a', 'light': '#b81f52'},
    'cyan':    {'dark': '#3ec9d6', 'light': '#0b7683'},
    'teal':    {'dark': '#3fc2a8', 'light': '#0a7a68'},
    'lime':    {'dark': '#9ccc48', 'light': '#4f7511'},
    'orange':  {'dark': '#f0913f', 'light': '#a85504'},
    'coral':   {'dark': '#f2705f', 'light': '#bd3323'},
    'indigo':  {'dark': '#8b93f5', 'light': '#3b45c4'},
}


# ── theme registry (base tokens, before accent overlay) ──────────────────
THEMES = {
    "light": {
        # Surfaces — oklch warm-paper ramp from Claude Design
        "bg_0": "#fbfaf8",
        "bg_1": "#f5f3f0",
        "bg_2": "#edebe7",
        "bg_3": "#e0ddd9",
        "bg_4": "#d4d0ca",

        # Lines
        "line_soft": "#eae7e4",
        "line": "#d7d4ce",
        "line_strong": "#a8a49e",

        # Text
        "text_1": "#181b1e",
        "text_2": "#44484c",
        # Darkened from the design grays so captions/headers clear WCAG AA.
        "text_3": "#565a60",
        "text_4": "#696e74",

        # Accent
        "accent": "#232a30",
        "accent_fg": "#f9f8f6",
        "accent_soft": "#bec5cc",
        "accent_tint": "rgba(190,197,204,0.45)",

        # Semantic
        "ok": "#008135",
        "ok_soft": "#cfe6d6",
        "ok_tint": "rgba(0,129,53,0.10)",
        "warn": "#ae6800",
        "warn_soft": "#ecdcc0",
        "warn_tint": "rgba(174,104,0,0.10)",
        "error": "#c9222b",
        "error_soft": "#edd0d0",
        "error_tint": "rgba(201,34,43,0.10)",
        "info": "#007fa6",
        "info_tint": "rgba(0,127,166,0.10)",

        # Graph palette (light mode equivalents)
        "g_1": "#0074a1",
        "g_2": "#cf4232",
        "g_3": "#007f35",
        "g_4": "#734dbe",
        "g_5": "#ae7300",
        "g_6": "#ae388f",
        "g_7": "#00807b",
        "g_8": "#bc5d00",

        # Plot widget colors
        "plot_bg":     "#f5f3f0",
        "plot_axis":   "#d7d4ce",
        "plot_text":   "#565a60",
        "plot_colors": ["#0074a1","#cf4232","#007f35","#734dbe","#ae7300","#ae388f","#00807b","#bc5d00"],

        # Backward compatibility aliases
        "bg_card": "#edebe7",
        "border": "#d7d4ce",
        "bg_input": "#fbfaf8",
    },

    "dark": {
        # Surfaces — oklch neutral-blue ramp from Claude Design
        "bg_0": "#0a0c0f",
        "bg_1": "#101316",
        "bg_2": "#191c1f",
        "bg_3": "#23272b",
        "bg_4": "#2f3338",

        # Lines
        "line_soft": "#1c2023",
        "line": "#2a2e33",
        "line_strong": "#43484e",

        # Text — text_3/text_4 lifted above the design's decorative grays so
        # captions/headers/axis labels clear WCAG AA (≥4.5:1) on every surface.
        "text_1": "#f0f2f4",
        "text_2": "#b4b8bb",
        "text_3": "#a2a8b0",
        "text_4": "#868d97",

        # Accent
        "accent": "#d8dfe6",
        "accent_fg": "#08090b",
        "accent_soft": "#2e3944",
        "accent_tint": "rgba(33,42,50,0.45)",

        # Semantic
        "ok": "#42c070",
        "ok_soft": "#164f2b",
        "ok_tint": "rgba(66,192,112,0.14)",
        "warn": "#edb345",
        "warn_soft": "#624815",
        "warn_tint": "rgba(237,179,69,0.14)",
        "error": "#fc5855",
        "error_soft": "#6e2826",
        "error_tint": "rgba(252,88,85,0.14)",
        "info": "#2bc4ea",
        "info_tint": "rgba(43,196,234,0.14)",

        # Graph palette (8 distinct hues)
        "g_1": "#12cbf5",
        "g_2": "#ff9381",
        "g_3": "#6fd087",
        "g_4": "#bea4ff",
        "g_5": "#e6ac3d",
        "g_6": "#f292d3",
        "g_7": "#00d3cb",
        "g_8": "#f8a052",

        # Plot widget colors — deep neutral black plot area (matches bg_0), subtle grid
        "plot_bg":     "#0a0c0f",
        "plot_axis":   "#2a2e33",
        "plot_text":   "#a2a8b0",
        "plot_colors": ["#12cbf5","#ff9381","#6fd087","#bea4ff","#e6ac3d","#f292d3","#00d3cb","#f8a052"],

        # Backward compatibility aliases
        "bg_card": "#191c1f",
        "border": "#2a2e33",
        "bg_input": "#0a0c0f",
    },
}

DEFAULT_THEME = "dark"


# ═══════════════════════════════════════════════════════════════════════
#  SCHEMES — whole surface families, layered on top of a base theme
# ═══════════════════════════════════════════════════════════════════════
# A scheme only restates the SURFACE ramp (and the lines/text that must move
# with it). Semantics, graph colours and accents stay shared, so adding a
# scheme is one entry here — never a second copy of the whole token set.
SCHEMES = {
    # ── dark family ──
    # A scheme is only worth having if you can SEE it. Measured against the
    # rendered window, the first attempt changed 0–2 % of pixels because every
    # dark ramp sat within a few RGB steps of the others. These are pulled
    # deliberately far apart — in lightness AND in hue — and each one carries
    # its own text ramp, because text is most of what you actually look at.
    "graphite": {"base": "dark", "tokens": {}},          # the original look
    "carbon": {"base": "dark", "tokens": {              # true black, neutral
        "bg_0": "#000000", "bg_1": "#0c0c0c", "bg_2": "#171717",
        "bg_3": "#242424", "bg_4": "#343434",
        "line_soft": "#1a1a1a", "line": "#303030", "line_strong": "#565656",
        "text_1": "#ffffff", "text_2": "#cfcfcf",
        "text_3": "#b4b4b4", "text_4": "#949494",
    }},
    "midnight": {"base": "dark", "tokens": {            # unmistakably blue
        "bg_0": "#050a1c", "bg_1": "#0b1533", "bg_2": "#132048",
        "bg_3": "#1d2e60", "bg_4": "#2a3f7d",
        "line_soft": "#101c3c", "line": "#26365f", "line_strong": "#47598c",
        "text_1": "#f2f6ff", "text_2": "#c3cff2",
        "text_3": "#adbcea", "text_4": "#8e9dd4",
    }},
    "slate": {"base": "dark", "tokens": {               # softer dark, less glare
        "bg_0": "#1a1e23", "bg_1": "#232830", "bg_2": "#2d333c",
        "bg_3": "#3a424c", "bg_4": "#49525e",
        "line_soft": "#2a3039", "line": "#3d4550", "line_strong": "#606b7a",
        "text_1": "#ffffff", "text_2": "#cdd4dd",
        "text_3": "#bac2cd", "text_4": "#9aa3b0",
    }},
    # ── light family ──
    "paper": {"base": "light", "tokens": {}},            # the original look
    "snow": {"base": "light", "tokens": {                # cool, crisp white
        "bg_0": "#ffffff", "bg_1": "#f2f5fa", "bg_2": "#e5eaf3",
        "bg_3": "#d4dbe8", "bg_4": "#bfc8d9",
        "line_soft": "#e5eaf3", "line": "#c8d1e0", "line_strong": "#8e9aad",
        "text_1": "#080b12", "text_2": "#333a47",
        "text_3": "#434b5a", "text_4": "#565f70",
    }},
    "sand": {"base": "light", "tokens": {                # warm, low-glare paper
        "bg_0": "#fffdf6", "bg_1": "#f4ecd9", "bg_2": "#e9dec3",
        "bg_3": "#dbcca8", "bg_4": "#c9b88c",
        "line_soft": "#eae0c8", "line": "#d2c19c", "line_strong": "#94825c",
        "text_1": "#1a1409", "text_2": "#453a24",
        "text_3": "#54472c", "text_4": "#655739",
    }},
}

DEFAULT_SCHEME = {"dark": "graphite", "light": "paper"}

# Convenience tokens that duplicate a ramp token. Which one they mirror is a
# per-theme decision (the light theme puts its plot area on bg_1, the dark one
# on bg_0), so it is discovered rather than assumed.
_ALIASES = ("bg_card", "border", "bg_input", "plot_bg", "plot_axis", "plot_text")
_RAMP = ("bg_0", "bg_1", "bg_2", "bg_3", "bg_4",
         "line_soft", "line", "line_strong", "text_1", "text_2", "text_3", "text_4")
_ALIAS_CACHE: dict = {}


def _alias_sources(theme: str) -> dict:
    if theme not in _ALIAS_CACHE:
        base = THEMES[theme]
        _ALIAS_CACHE[theme] = {
            a: next((r for r in _RAMP if base.get(r) == base.get(a)), None)
            for a in _ALIASES if any(base.get(r) == base.get(a) for r in _RAMP)
        }
    return _ALIAS_CACHE[theme]


def schemes_for(theme: str) -> tuple:
    """Scheme keys valid for this base theme (Light schemes on a dark theme
    would be unreadable, so the picker only ever offers the right family)."""
    base = (theme or DEFAULT_THEME).lower()
    return tuple(k for k, s in SCHEMES.items() if s["base"] == base)


# ═══════════════════════════════════════════════════════════════════════
#  CONTRAST — one knob that pushes surfaces and text apart
# ═══════════════════════════════════════════════════════════════════════
CONTRAST_LEVELS = ("soft", "normal", "high")
_CONTRAST_K = {"soft": 0.0, "normal": 0.45, "high": 1.0}

# token -> how far it travels at k = 1.0. Surfaces move away from mid-grey,
# text and lines move toward the extreme.
#
# TEXT carries this control. A dark background is already almost black, so
# darkening it further is imperceptible — the first attempt moved surfaces
# hardest and changed 2 % of the screen. Secondary text is where "dull" lives,
# so text_2/3/4 travel furthest, and text_1 moves too (it used to be frozen).
_SURFACE_SHIFT = (("bg_0", 0.30), ("bg_1", 0.24), ("bg_2", 0.18),
                  ("bg_3", 0.12), ("bg_4", 0.06),
                  ("bg_card", 0.18), ("bg_input", 0.30), ("plot_bg", 0.26))
#
# LINES barely move, and that is deliberate. Contrast is a legibility control:
# it exists so text stops being dull. Dragging the chrome along with it made
# every divider glare — on carbon+high a "soft" line landed at #4c4c4c, a
# brighter separator than the text it separated. The only line that earns real
# travel is line_strong, because that one draws input borders: someone who
# asked for high contrast does want to see where a field begins.
_INK_SHIFT = (("text_1", 0.34), ("text_2", 0.55), ("text_3", 0.66),
              ("text_4", 0.72), ("plot_text", 0.66),
              ("line_soft", 0.06), ("line", 0.16), ("line_strong", 0.30),
              ("border", 0.16), ("plot_axis", 0.22))


def _apply_contrast(p: dict, level: str, is_dark: bool) -> dict:
    k = _CONTRAST_K.get(level or "normal", _CONTRAST_K["normal"])
    if k <= 0:
        return p
    deep = "#000000" if is_dark else "#ffffff"      # surfaces head this way
    ink = "#ffffff" if is_dark else "#000000"       # text/lines head this way
    for tok, amt in _SURFACE_SHIFT:
        if tok in p:
            p[tok] = _mix(p[tok], deep, amt * k)
    for tok, amt in _INK_SHIFT:
        if tok in p:
            p[tok] = _mix(p[tok], ink, amt * k)
    return p


def _apply_accent(palette: dict, accent: str | None, is_dark: bool) -> dict:
    """Overlay the accent hue for this surface family.

    ``accent_fg`` is derived from the accent's luminance instead of being
    stored, so a bright accent can never end up with white text on it."""
    entry = ACCENT_PALETTES.get(accent or "neutral")
    if not entry:
        return palette
    col = entry["dark" if is_dark else "light"]
    palette["accent"] = col
    # Pick whichever of dark/light text actually contrasts better against this
    # hue. A fixed luminance threshold left violet at 3.4:1 — below AA.
    palette["accent_fg"] = max(("#0a0c0f", "#f7f8fa"),
                               key=lambda fg: _contrast(fg, col))
    palette["accent_soft"] = _mix(col, palette["bg_1"], 0.55 if is_dark else 0.6)
    palette["accent_tint"] = _tint(col, 0.20 if is_dark else 0.14)
    return palette


# The appearance the app is currently wearing. ~20 call sites ask for a
# palette with nothing but a theme name (a dialog only knows "Dark"); without
# this they would render the base ramp and visibly disagree with the rest of
# the window. One writer — the settings apply path — keeps it in sync.
_ACTIVE = {"scheme": None, "contrast": "normal", "accent": None}


def set_active(scheme=None, contrast=None, accent=None):
    """Record the appearance so palette lookups elsewhere stay consistent."""
    if scheme is not None:
        _ACTIVE["scheme"] = scheme or None
    if contrast is not None:
        _ACTIVE["contrast"] = contrast or "normal"
    if accent is not None:
        _ACTIVE["accent"] = accent or None


def active() -> dict:
    return dict(_ACTIVE)


def get_theme(name: str = "Dark", accent: str | None = None,
              scheme: str | None = None, contrast: str | None = None) -> dict:
    """Palette for theme *name*, optionally re-skinned by *scheme*, pushed by
    *contrast*, and tinted by *accent*.

    Order matters: scheme sets the surfaces, contrast moves them, then the
    accent is derived FROM the finished surfaces (so accent_soft blends with
    the real background rather than the original one). The result is a fresh
    copy; callers may mutate it freely.
    """
    base_name = (name or DEFAULT_THEME).lower()
    if base_name not in THEMES:
        base_name = DEFAULT_THEME
    p = copy.deepcopy(THEMES[base_name])
    if scheme is None:
        scheme = _ACTIVE["scheme"]
    if contrast is None:
        contrast = _ACTIVE["contrast"]
    if accent is None:
        accent = _ACTIVE["accent"]

    entry = SCHEMES.get(scheme or "")
    if entry and entry["base"] == base_name:
        p.update(copy.deepcopy(entry["tokens"]))
        # Aliases follow whichever ramp token they mirrored in the BASE theme.
        # Hardcoding them (plot_bg = bg_0) silently changed the light theme,
        # whose plot area deliberately sits on bg_1.
        for alias, source in _alias_sources(base_name).items():
            p[alias] = p[source]

    is_dark = base_name == "dark"
    _apply_contrast(p, contrast, is_dark)
    return _apply_accent(p, accent, is_dark)
