# app/settings_schema.py
"""Declarative schema for the Settings dialog — the single source of truth for
*what* settings exist, how they are grouped into pages/sections, and how each one
maps to a control.

Descriptor + Registry style (mirrors datatypes.py): every editable setting is one
frozen `Field` descriptor; fields group into `Section`s, sections into `Page`s,
and `PAGES` is the registry the dialog renders itself from. The dialog
(gui/settings.py) contains *no per-setting code* — it walks this schema.

To add a setting:
    1. add its key + default to settings_manager.DEFAULT_SETTINGS;
    2. add ONE Field(...) to the relevant Section here (+ i18n keys if needed).
Nothing in gui/settings.py changes.

Text is an ``i18n.STRINGS`` key resolved by `tr()`; a string that is not a key
is used literally (brand names, "9600", " px"). Legacy ``(ru, en)`` tuples are
still resolved for backward compatibility.
"""

from dataclasses import dataclass
from typing import Callable, Optional

from app.i18n import STRINGS


# ── value <-> settings maps reused by individual fields ──────────────
# Interface-font choice → concrete CSS font stack (legacy 3-way tokens; the
# picker now stores a real family name, these keep old saved values working).
FONT_CHOICES = {
    "inter":  "Inter, Segoe UI, system-ui, sans-serif",
    "ibm":    "IBM Plex Sans, Segoe UI, sans-serif",
    "system": "system-ui, Segoe UI, sans-serif",
}

# Legacy token → representative family for the system-font picker.
_FONT_LEGACY_FAMILY = {"inter": "Inter", "ibm": "IBM Plex Sans",
                       "system": "Segoe UI"}

# Accent swatches shown in Appearance: (key, preview hex).
# Keys match theme_manager.ACCENT_PALETTES.
ACCENT_SWATCHES = (
    ("neutral", "#dee2ee"), ("blue", "#5dadec"), ("cyan", "#3ec9d6"),
    ("teal", "#3fc2a8"), ("emerald", "#4db888"), ("lime", "#9ccc48"),
    ("amber", "#ddb855"), ("orange", "#f0913f"), ("coral", "#f2705f"),
    ("rose", "#ec5d8a"), ("violet", "#b85dec"), ("indigo", "#8b93f5"),
)

# Colour schemes offered in Appearance: (value, i18n label key). The combo is
# filtered to the current theme's family at render time.
SCHEME_LABELS = (
    ("graphite", "schemeGraphite"), ("carbon", "schemeCarbon"),
    ("midnight", "schemeMidnight"), ("slate", "schemeSlate"),
    ("paper", "schemePaper"), ("snow", "schemeSnow"), ("sand", "schemeSand"),
)

# Stored parity may be a raw code ("N") or a legacy label; normalise to the
# segmented control's value ("None (N)" / "Even (E)" / "Odd (O)").
_PARITY_NORM = {
    "None": "None (N)", "N": "None (N)", "None (N)": "None (N)",
    "Even": "Even (E)", "E": "Even (E)", "Even (E)": "Even (E)",
    "Odd":  "Odd (O)",  "O": "Odd (O)",  "Odd (O)":  "Odd (O)",
}


# ── small transform helpers (module-level so the dataclass stays frozen) ──
def _identity(v):
    return v


def _strip(v):
    return str(v).strip()


def _norm_parity(v):
    return _PARITY_NORM.get(str(v), str(v))


def _font_to_family(value):
    """Stored font_choice → a family name the picker can select.
    Accepts both legacy tokens ("inter"/"ibm"/"system") and real family names."""
    v = str(value)
    return _FONT_LEGACY_FAMILY.get(v, v)


def _font_from_widget(family):
    """Picked family → stored font_choice. Families that correspond to a
    legacy token are stored as that token, so a saved "inter" that round-trips
    through the picker unchanged doesn't read back as a modification."""
    fam = str(family).strip()
    for token, legacy_family in _FONT_LEGACY_FAMILY.items():
        if fam == legacy_family:
            return token
    return fam


def _derive_font_family(choice):
    """font_choice → also write the concrete font_family stack (QSS uses it).

    The chosen family is validated first: a symbol font (Wingdings and friends)
    or one that is not installed would turn every label — including this
    settings page — into dingbats, with no way back."""
    if choice in FONT_CHOICES:                       # legacy token
        return {"font_family": FONT_CHOICES[choice]}
    from app import fonts
    family = fonts.safe_family(str(choice).strip())
    return {"font_family": f'"{family}", Segoe UI, system-ui, sans-serif'}


def _tcp_port_to_widget(v):
    from core.transports import tcp_port_value
    return str(tcp_port_value(v))


def _tcp_port_from_widget(v):
    from core.transports import tcp_port_value
    return tcp_port_value(v)


def _com_ports() -> tuple:
    """Serial ports detected on this machine — items for the Port dropdown.
    The combo stays editable, so an undetected/remote port can still be typed."""
    try:
        from serial.tools import list_ports
        return tuple(sorted(p.device for p in list_ports.comports()))
    except Exception:
        return ()


def tr(text, lang: str = "ru") -> str:
    """Resolve *text* for *lang*: an ``i18n.STRINGS`` key → its translation
    (English fallback); an unknown string → itself (literal); a legacy
    ``(ru, en)`` tuple → the language's element."""
    if isinstance(text, (tuple, list)):
        return text[0] if lang == "ru" else text[1]
    lang_map = STRINGS.get(lang) or STRINGS["en"]
    hit = lang_map.get(text)
    if hit is not None:
        return hit
    hit = STRINGS["en"].get(text)
    return hit if hit is not None else text


# ── descriptors ──────────────────────────────────────────────────────
@dataclass(frozen=True)
class Field:
    """One editable setting → one control in the dialog.

    key         settings-dict key
    kind        "toggle" | "segmented" | "slider" | "swatch" | "text" | "combo"
    label       i18n key (or literal / legacy tuple) — field label
    hint        i18n key — helper text under the label (optional)
    options     segmented: ((value, label), ...) — label may be an i18n key;
                combo:     (item, ...)
    options_fn  combo: callable returning items at render time (dynamic lists,
                e.g. detected COM ports); overrides ``options``
    editable    combo: allow typing a value not present in the list
    minimum/maximum/step/unit   slider params (unit: i18n key or literal)
    width       pixel width for text / combo controls
    swatches    ((key, hex), ...) for swatch
    default     fallback used if the key is missing from settings
    to_widget   settings value -> the control's initial value
    from_widget control value  -> the value stored back into settings
    derive      control value  -> dict of *extra* settings keys to also set
    """
    key: str
    kind: str
    label: object = ""
    hint: object = ""
    options: tuple = ()
    options_fn: Optional[Callable] = None
    editable: bool = False
    minimum: int = 0
    maximum: int = 100
    step: int = 1
    unit: object = ""
    width: int = 160
    swatches: tuple = ()
    default: object = None
    to_widget: Callable = _identity
    from_widget: Callable = _identity
    derive: Optional[Callable] = None


@dataclass(frozen=True)
class Section:
    """A titled group of fields inside a page.

    show_if  (key, (values…)): the section is on screen only while the
             control for *key* (on the same page) holds one of *values* —
             the serial fields for a COM port, host/port for TCP."""
    title: object
    desc: object = ""
    fields: tuple = ()
    show_if: tuple = ()


@dataclass(frozen=True)
class Page:
    """One sidebar category. Data pages declare ``sections``; informational
    pages (Shortcuts / About) declare ``static`` = the name of a dialog method
    that fills the page layout."""
    key: str
    glyph: str
    title: object
    sections: tuple = ()
    static: Optional[str] = None


# ── field factories (keep the registry below terse and uniform) ──────────
def _toggle(key, label, hint="", default=True) -> Field:
    return Field(key, "toggle", label, hint, default=default,
                 to_widget=bool, from_widget=bool)


def _slider(key, label, minimum, maximum, default, step=1,
            unit="", hint="") -> Field:
    return Field(key, "slider", label, hint, minimum=minimum, maximum=maximum,
                 step=step, unit=unit, default=default, to_widget=int)


def _seg(key, label, options, default, hint="",
         to_widget=_identity, from_widget=_identity, derive=None) -> Field:
    return Field(key, "segmented", label, hint, options=tuple(options),
                 default=default, to_widget=to_widget, from_widget=from_widget,
                 derive=derive)


# ── the registry (sidebar order == declaration order) ────────────────────
# Connection first — it's the most-used page.
PAGES: tuple = (
    Page("connection", "plug", "connectionSettings", sections=(
        Section("linkTitle", "linkDesc",
                fields=(
                    _seg("transport", "transportLbl",
                         [("serial", "connSerial"), ("tcp", "connTcp"),
                          ("rtu_tcp", "connRtuTcp")], default="serial"),
                )),
        Section("tcpTitle", "tcpDesc", show_if=("transport", ("tcp", "rtu_tcp")),
                fields=(
                    Field("host", "text", "connHost", width=200, default="",
                          to_widget=str, from_widget=_strip),
                    Field("tcp_port", "text", "connTcpPort", width=90, default=502,
                          to_widget=_tcp_port_to_widget,
                          from_widget=_tcp_port_from_widget),
                )),
        Section("Serial / RTU", "serialDesc", show_if=("transport", ("serial",)),
                fields=(
                    Field("port", "combo", "port",
                          options_fn=_com_ports, editable=True,
                          width=140, default="COM1", to_widget=str, from_widget=_strip),
                    Field("baudrate", "combo", "baudrate",
                          options=("9600", "19200", "38400", "57600", "115200", "230400"),
                          width=140, default="115200", to_widget=str),
                    _seg("parity", "parity",
                         [("None (N)", "N"), ("Even (E)", "E"), ("Odd (O)", "O")],
                         default="None (N)", to_widget=_norm_parity),
                    _seg("stopbits", "stopbits",
                         [("1", "1"), ("2", "2")], default="1", to_widget=str),
                )),
        Section("pollingTitle", "pollingDesc",
                fields=(
                    _slider("poll_rate", "pollPeriod",
                            100, 5000, 500, step=100, unit="unitMsSuffix"),
                    _slider("timeout", "respTimeout",
                            100, 5000, 1000, step=100, unit="unitMsSuffix"),
                    _slider("retry_count", "retryCount", 1, 10, 3),
                    _slider("interframe_delay", "interframeDelay",
                            0, 500, 50, step=10, unit="unitMsSuffix"),
                )),
        Section("codecTitle", "codecDesc",
                fields=(
                    _seg("order_short", "orderShort",
                         [("AB", "AB"), ("BA", "BA")], default="AB"),
                    _seg("order_long", "orderLong",
                         [("ABCD", "ABCD"), ("BADC", "BADC"),
                          ("CDAB", "CDAB"), ("DCBA", "DCBA")],
                         default="ABCD"),
                    _seg("order_float", "orderFloat",
                         [("ABCD", "ABCD"), ("BADC", "BADC"),
                          ("CDAB", "CDAB"), ("DCBA", "DCBA")],
                         default="BADC"),
                )),
        Section("connLossTitle", "connLossDesc",
                fields=(
                    _toggle("auto_reconnect", "autoReconnect",
                            hint="autoReconnectHint", default=False),
                    _slider("reconnect_interval", "reconnectInterval",
                            1, 60, 5, unit="unitSec"),
                )),
    )),

    Page("general", "gear", "general", sections=(
        Section("generalTitle", "generalDesc",
                fields=(
                    _seg("lang", "language",
                         [("ru", "Русский"), ("en", "English")], default="ru",
                         hint="langHintInstant"),
                    _toggle("load_last", "startupLoad",
                            hint="loadLastHint", default=True),
                )),
        Section("updSection", "updSectionDesc",
                fields=(
                    _toggle("update_auto", "updAuto",
                            hint="updAutoHint", default=True),
                )),
    )),

    Page("display", "contrast", "appearance", sections=(
        Section("theme", "themeDesc",
                fields=(
                    _seg("theme", "theme",
                         [("Dark", "dark"), ("Light", "light")],
                         default="Dark"),
                    # Whole surface family. The combo is refiltered per theme
                    # in gui/settings.py — a light scheme on a dark base would be
                    # unreadable, so it is never offered.
                    Field("scheme", "combo", "colorScheme", hint="colorSchemeHint",
                          options=tuple(SCHEME_LABELS), width=200,
                          default="graphite"),
                    _seg("contrast", "contrastLbl",
                         [("soft", "contrastSoft"), ("normal", "contrastNormal"),
                          ("high", "contrastHigh")],
                         default="normal", hint="contrastHint"),
                    Field("accent", "swatch", "accentColor",
                          hint="accentHint",
                          swatches=ACCENT_SWATCHES, default="neutral"),
                )),
        Section("typography", fields=(
            # System-font picker with a live preview (kind="font" renders a
            # QFontComboBox + sample text in gui/settings.py).
            Field("font_choice", "font", "uiFont", hint="uiFontHint",
                  width=240, default="inter",
                  to_widget=_font_to_family, from_widget=_font_from_widget,
                  derive=_derive_font_family),
            _slider("font_size", "fontSizeLbl", 8, 16, 9, unit=" pt"),
            _slider("row_height", "rowHeight", 20, 44, 26, unit=" px"),
        )),
    )),

    Page("table", "table", "table", sections=(
        Section("regTableTitle", "regTableDesc",
                fields=(
                    _toggle("show_addr",    "address"),
                    _toggle("show_name",    "name"),
                    _toggle("show_type",    "type"),
                    _toggle("show_access",  "access"),
                    _toggle("show_current", "current"),
                    _toggle("show_new",     "newVal"),
                    _toggle("zebra_rows",   "zebraStriping", hint="zebraHint"),
                    _toggle("mono_values",  "monoValues"),
                    _toggle("highlight_changes", "highlightChanges",
                            hint="highlightChangesHint"),
                )),
    )),

    Page("graphs", "chart", "graphs", sections=(
        Section("graphs", "graphsDesc",
                fields=(
                    _seg("default_window_sec", "defaultWindow",
                         [(10, "10s"), (30, "30s"), (120, "2m"), (600, "10m")],
                         default=30, to_widget=int, from_widget=int),
                    _toggle("graph_autofit_y", "autofitY", hint="autofitYHint"),
                    _seg("graph_anim", "animation",
                         [("off", "offOpt"), ("smooth", "smoothOpt")],
                         default="smooth", hint="animationHint"),
                    _slider("trend_history", "historyLen",
                            60, 2000, 1200, step=20, hint="historyLenHint"),
                    _slider("graph_width", "panelWidth",
                            260, 560, 420, step=10, unit=" px"),
                )),
    )),

    Page("log", "list", "log", sections=(
        Section("txLogTitle", "txLogDesc",
                fields=(
                    _toggle("show_log", "visible"),
                    _slider("log_height", "panelHeight",
                            100, 320, 150, step=10, unit=" px"),
                    _toggle("log_autoscroll", "autoscroll", hint="autoscrollHint"),
                    _seg("log_verbosity", "verbosity",
                         [("min", "minOpt"), ("normal", "normalOpt"), ("debug", "Debug")],
                         default="normal"),
                    _slider("log_max", "maxEntries",
                            50, 2000, 200, step=50, hint="maxEntriesHint"),
                )),
    )),

    Page("shortcuts", "keyboard", "shortcutsTitle", static="_static_shortcuts"),
    Page("about",     "info",     "about",          static="_static_about"),
)


# ── iteration helper ──────────────────────────────────────────────────
def iter_fields(pages=PAGES):
    """Yield every Field across all data pages/sections, in render order."""
    for page in pages:
        for section in page.sections:
            for fld in section.fields:
                yield fld
