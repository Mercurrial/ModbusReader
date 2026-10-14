# formats.py
"""Versioned file formats + a migration registry — the "lay the foundation
once" module.

Two documents:
  * a **register profile** (the map of registers) and
  * a **project** (.mbproj = connection + embedded profile + layout/dashboard).

Both are JSON with a small envelope carrying a ``version`` integer. Loading
DETECTS the version and runs a chain of migration functions up to the current
version, so a file written by any past build opens forever. Saving always
writes the current version.

Design (mirrors the Descriptor+Registry style used elsewhere): each format has
an ordered ``_MIGRATIONS`` dict ``{from_version: fn(doc) -> doc_at_from+1}``.
To evolve a format you add ONE migration and bump ``*_VERSION`` — you never
edit an old migration (they're the guarantee that old files keep working).

Pure module: json only, no Qt, no app imports beyond ``scaling`` for a couple
of field-normalisation defaults.
"""

import json

PROFILE_KIND = "modbusreader.profile"
PROJECT_KIND = "modbusreader.project"
DASHBOARD_KIND = "modbusreader.dashboard"

PROFILE_VERSION = 2
PROJECT_VERSION = 1
DASHBOARD_VERSION = 1


# ═══════════════════════════════════════════════════════════════════════
#  REGISTER NORMALISATION (schema of ONE register, current version)
# ═══════════════════════════════════════════════════════════════════════
def _clean_enum(raw) -> dict:
    if not isinstance(raw, dict):
        return {}
    out = {}
    for k, v in raw.items():
        try:
            out[str(int(k))] = str(v)          # JSON keys are strings
        except (TypeError, ValueError):
            continue
    return out


def _num(v, default):
    try:
        f = float(v)
        return f if f == f else default
    except (TypeError, ValueError):
        return default


def normalize_register(r: dict) -> dict:
    """One register in canonical v2 shape. Only writes optional keys
    (scale/offset/enum/unit/…) when they carry non-default info, so files stay
    lean and diffs stay small."""
    if not isinstance(r, dict):
        return {}
    try:
        addr = int(str(r.get("addr", 0)), 0) if isinstance(r.get("addr"), str) \
            else int(r.get("addr", 0))
    except (TypeError, ValueError, OverflowError):
        # OverflowError comes from a JSON float like 1e400, which parses as
        # inf. One junk address must not abort the whole file.
        addr = 0
    if not 0 <= addr <= 0xFFFF:          # Modbus addresses are 16-bit
        addr = 0
    reg = {
        "addr": addr,
        "name": str(r.get("name", "")),
        "type": r.get("type", "SHORT"),
        # A negative or absurd length would have the poll loop ask the device
        # for gigabytes; clamp it to the addressable range.
        "length": max(1, min(int(_num(r.get("length", 1), 1)) or 1, 0xFFFF)),
        "rw": r.get("rw", "RW"),
    }
    for k in ("name_en", "unit", "default", "comment"):
        if r.get(k):
            reg[k] = r[k]
    # v2.1: the Modbus table. Written only when not "holding" (the default and
    # all that existed before), so older files are byte-for-byte unchanged.
    import datatypes
    datatypes.apply_area(reg, r.get("area"))
    # v2 additions — engineering scaling + enum map (identity defaults omitted).
    scale = _num(r.get("scale", 1.0), 1.0)
    offset = _num(r.get("offset", 0.0), 0.0)
    if scale != 1.0:
        reg["scale"] = scale
    if offset != 0.0:
        reg["offset"] = offset
    enum = _clean_enum(r.get("enum"))
    if enum:
        reg["enum"] = enum
    return reg


def normalize_registers(rows) -> list:
    return [normalize_register(r) for r in rows if isinstance(r, dict)]


# ═══════════════════════════════════════════════════════════════════════
#  PROFILE FORMAT + MIGRATIONS
# ═══════════════════════════════════════════════════════════════════════
def _profile_v0_to_v1(doc):
    """v0 = a bare JSON array of registers → wrap it."""
    return {"registers": list(doc)}


def _profile_v1_to_v2(doc):
    """v1 = ``{"registers":[...]}`` (or legacy dict) → stamp v2. Registers are
    normalised (scale/offset/enum become first-class but default to identity,
    so nothing changes for existing files)."""
    regs = doc.get("registers") if isinstance(doc, dict) else doc
    return {"registers": normalize_registers(regs or []),
            "name": doc.get("name", "") if isinstance(doc, dict) else ""}


_PROFILE_MIGRATIONS = {
    0: _profile_v0_to_v1,
    1: _profile_v1_to_v2,
}


def detect_profile_version(doc) -> int:
    """Infer the on-disk version of a parsed profile document. A dict that is
    neither versioned nor a ``{"registers":[...]}`` wrapper is rejected (a
    malformed file shouldn't silently load as an empty profile)."""
    if isinstance(doc, list):
        return 0                                # bare array (oldest)
    if isinstance(doc, dict):
        v = doc.get("version")
        if isinstance(v, bool):
            raise ValueError("Профиль: поле 'version' должно быть числом.")
        if isinstance(v, int):
            if v < 0:
                # A negative version has no migration to run from, and the
                # chain used to fail with a bare KeyError(-1).
                raise ValueError(
                    f"Профиль: некорректная версия {v}. Файл повреждён.")
            return v
        if isinstance(doc.get("registers"), list):
            return 1                            # {"registers":[...]} без версии
        raise ValueError(
            "Профиль: объект без ключа 'registers' и без версии.")
    raise ValueError("Профиль: ожидался JSON-массив или объект.")


def migrate_profile(doc) -> dict:
    """Run the migration chain until the doc reaches PROFILE_VERSION.
    Returns a dict ``{"version", "registers", "name"}``."""
    version = detect_profile_version(doc)
    if version > PROFILE_VERSION:
        raise ValueError(
            f"Профиль версии {version} новее, чем поддерживает программа "
            f"(до {PROFILE_VERSION}). Обновите ModbusReader.")
    while version < PROFILE_VERSION:
        step = _PROFILE_MIGRATIONS.get(version)
        if step is None:
            # No path from this version — say so instead of KeyError.
            raise ValueError(
                f"Профиль: нет способа обновить версию {version} "
                f"до {PROFILE_VERSION}. Файл повреждён.")
        doc = step(doc)
        version += 1
    doc = dict(doc)
    doc["version"] = PROFILE_VERSION
    doc.setdefault("registers", [])
    doc.setdefault("name", "")
    return doc


def make_profile(registers, name: str = "") -> dict:
    """Build the current-version profile envelope from a register list."""
    return {"format": PROFILE_KIND, "version": PROFILE_VERSION,
            "name": name or "", "registers": normalize_registers(registers)}


def loads_profile(text: str) -> dict:
    return migrate_profile(json.loads(text))


def load_profile(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return migrate_profile(json.load(f))


def dump_profile(path: str, registers, name: str = ""):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(make_profile(registers, name), f, indent=2, ensure_ascii=False)


# ═══════════════════════════════════════════════════════════════════════
#  DASHBOARD FORMAT (.mbdash) + MIGRATIONS
# ═══════════════════════════════════════════════════════════════════════
# One dashboard = a name + its widgets + the automation wires between them.
# A project embeds a LIST of these; a .mbdash file carries exactly one, so a
# screen can be shared between projects.
_DASHBOARD_MIGRATIONS: dict = {}


def normalize_dashboard(doc, default_name: str = "") -> dict:
    """Coerce anything dashboard-shaped into ``{name, widgets, links}``.

    Accepts the current dict, a bare list of widgets (the pre-multi-dashboard
    shape) and junk (→ empty), so old settings and old files both survive."""
    if isinstance(doc, list):
        return {"name": default_name, "widgets": [dict(w) for w in doc
                                                  if isinstance(w, dict)],
                "links": []}
    if not isinstance(doc, dict):
        return {"name": default_name, "widgets": [], "links": []}
    widgets = [dict(w) for w in (doc.get("widgets") or []) if isinstance(w, dict)]
    links = [{"from": l.get("from"), "to": l.get("to")}
             for l in (doc.get("links") or [])
             if isinstance(l, dict) and l.get("from") and l.get("to")]
    return {"name": str(doc.get("name", default_name) or default_name),
            "widgets": widgets, "links": links}


def detect_dashboard_version(doc) -> int:
    if (isinstance(doc, dict) and isinstance(doc.get("version"), int)
            and not isinstance(doc.get("version"), bool)):
        return doc["version"]
    return DASHBOARD_VERSION           # bare/legacy shapes are normalized


def migrate_dashboard(doc) -> dict:
    version = detect_dashboard_version(doc)
    if version > DASHBOARD_VERSION:
        raise ValueError(
            f"Дашборд версии {version} новее, чем поддерживает программа "
            f"(до {DASHBOARD_VERSION}). Обновите ModbusReader.")
    while version < DASHBOARD_VERSION:
        step = _DASHBOARD_MIGRATIONS.get(version)
        if step is None:
            # Version 0 or a negative number has no migration to run; this
            # used to surface as a bare KeyError("0").
            raise ValueError(
                f"Дашборд: некорректная версия {version}. Файл повреждён.")
        doc = step(doc)
        version += 1
    out = normalize_dashboard(doc)
    out["version"] = DASHBOARD_VERSION
    return out


def make_dashboard(name, widgets, links) -> dict:
    return {"format": DASHBOARD_KIND, "version": DASHBOARD_VERSION,
            "name": name or "", "widgets": [dict(w) for w in (widgets or [])],
            "links": [dict(l) for l in (links or [])]}


def load_dashboard(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return migrate_dashboard(json.load(f))


def dump_dashboard(path: str, name, widgets, links):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(make_dashboard(name, widgets, links), f, indent=2,
                  ensure_ascii=False)


# ═══════════════════════════════════════════════════════════════════════
#  PROJECT FORMAT (.mbproj) + MIGRATIONS
# ═══════════════════════════════════════════════════════════════════════
# The connection keys a project captures (the device identity + link + codecs).
PROJECT_CONNECTION_KEYS = (
    "transport", "port", "baudrate", "parity", "stopbits", "slave_id",
    "timeout", "poll_rate", "interframe_delay", "retry_count",
    "order_short", "order_long", "order_float",
)
# The layout keys a project captures.
PROJECT_LAYOUT_KEYS = ("pinned_views", "last_view", "log_height",
                       "show_log", "graph_width")


_PROJECT_MIGRATIONS: dict = {
    # (none yet — v1 is the first version; future: {1: _v1_to_v2, ...})
}


_PROJECT_KEYS = ("profile", "dashboards", "dashboard", "connection",
                 "layout", "registers", "format")


def detect_project_version(doc) -> int:
    if not isinstance(doc, dict):
        raise ValueError("Проект: ожидался JSON-объект.")
    # An object with none of a project's keys is not a project. Accepting it
    # produced a silently EMPTY project — which to the operator looks exactly
    # like the file's contents were thrown away.
    if not any(k in doc for k in _PROJECT_KEYS):
        raise ValueError(
            "Проект: файл не похож на проект ModbusReader "
            "(нет ни профиля, ни дашбордов, ни настроек подключения).")
    v = doc.get("version")
    if isinstance(v, bool) or (isinstance(v, int) and v < 0):
        raise ValueError("Проект: некорректная версия. Файл повреждён.")
    return v if isinstance(v, int) else 1


def migrate_project(doc) -> dict:
    version = detect_project_version(doc)
    if version > PROJECT_VERSION:
        raise ValueError(
            f"Проект версии {version} новее, чем поддерживает программа "
            f"(до {PROJECT_VERSION}). Обновите ModbusReader.")
    while version < PROJECT_VERSION:
        step = _PROJECT_MIGRATIONS.get(version)
        if step is None:
            raise ValueError(
                f"Проект: некорректная версия {version}. Файл повреждён.")
        doc = step(doc)
        version += 1
    doc = dict(doc)
    doc["version"] = PROJECT_VERSION
    # The embedded profile and each dashboard are migrated on their own tracks.
    raw_profile = doc.get("profile")
    if raw_profile is None and isinstance(doc.get("registers"), list):
        # A bare register map ({"registers": [...]}) opened as a project. Its
        # registers sit at the TOP level; reading only doc["profile"] used to
        # turn such a file into an empty map without a word — which on screen
        # is indistinguishable from the file having been wiped.
        raw_profile = {"registers": doc["registers"], "name": doc.get("name", "")}
    doc["profile"] = migrate_profile(raw_profile or {"registers": []})
    doc["dashboards"] = _project_dashboards(doc)
    doc.pop("dashboard", None)              # legacy single-dashboard key
    doc.setdefault("connection", {})
    doc.setdefault("layout", {})
    doc.setdefault("name", "")
    return doc


def _project_dashboards(doc: dict) -> list:
    """Dashboards of a project, accepting every shape ever written:
    ``dashboards: [{name,widgets,links}]`` (current), or the legacy
    ``dashboard: [widget, ...]`` single flat list."""
    raw = doc.get("dashboards")
    if raw is None:
        legacy = doc.get("dashboard")
        raw = [legacy] if legacy else []
    out = [migrate_dashboard(d) for d in raw if d is not None]
    return out or [make_dashboard("", [], [])]


def make_project(name, settings: dict, registers, dashboards=None,
                 layout=None) -> dict:
    """Build a current-version project from live app state.

    *dashboards* is a list of ``{name, widgets, links}`` dicts; a bare widget
    list is accepted too and becomes a single unnamed dashboard."""
    conn = {k: settings.get(k) for k in PROJECT_CONNECTION_KEYS
            if k in settings}
    lay = layout if layout is not None else {
        k: settings.get(k) for k in PROJECT_LAYOUT_KEYS if k in settings}
    if dashboards and isinstance(dashboards[0], dict) \
            and "widgets" not in dashboards[0]:
        dashboards = [{"name": "", "widgets": dashboards, "links": []}]
    boards = [make_dashboard(d.get("name", ""), d.get("widgets"),
                             d.get("links")) for d in (dashboards or [])]
    return {
        "format": PROJECT_KIND,
        "version": PROJECT_VERSION,
        "name": name or "",
        "connection": conn,
        "profile": make_profile(registers, name),
        "dashboards": boards or [make_dashboard("", [], [])],
        "layout": lay,
    }


def load_project(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return migrate_project(json.load(f))


def dump_project(path: str, name, settings, registers, dashboards=None,
                 layout=None):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(make_project(name, settings, registers, dashboards, layout),
                  f, indent=2, ensure_ascii=False)


def looks_like_project(doc) -> bool:
    return isinstance(doc, dict) and doc.get("format") == PROJECT_KIND
