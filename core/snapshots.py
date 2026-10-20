# core/snapshots.py
"""Freeze the current register values, then see what changed.

The most common commissioning question is "what did that parameter change?".
Answering it by eye across a hundred rows does not work, so: take a snapshot,
turn the knob, compare.

PURE module (no Qt, no I/O beyond JSON) — the comparison is where the subtlety
lives and it is fully testable:

* A register that was **absent** from one side is not "changed", it is added or
  removed. Reporting it as a change would be a lie.
* Values are compared **numerically when both sides are numbers**, so "5" and
  "5.0" are equal, but as text otherwise (strings, enum labels, "—").
* Float noise: an absolute + relative epsilon, because a 0.0001 wobble on an
  analogue input is not an engineering change and would bury the real diffs.
"""

import json
import time

from core import datatypes

FORMAT = "modbus-snapshot"
VERSION = 1

# Below this, two floats are "the same reading". The tolerance exists ONLY to
# absorb float round-trip noise ("0.30000000000000004" vs "0.3"), which is
# ~1e-16 relative — so it is kept far tighter than it first looks. At 1e-9 the
# relative term made 1e9 and 1e9+1 compare equal, i.e. it hid a whole unit of
# change on a large register.
EPS_ABS = 1e-12
EPS_REL = 1e-12

# What a compared row can be.
SAME, CHANGED, ADDED, REMOVED = "same", "changed", "added", "removed"


def _num(value):
    """The value as a float, or None when it is not numeric."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", ".")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def values_equal(a, b) -> bool:
    """True when two readings mean the same thing.

    Numeric when both sides parse as numbers ("5" == "5.0" == 5), textual
    otherwise. Float comparison is tolerant, or sensor noise in the last
    decimal would flood the diff and hide the real changes."""
    if a is None or b is None:
        return a is b
    fa, fb = _num(a), _num(b)
    if fa is not None and fb is not None:
        return abs(fa - fb) <= max(EPS_ABS, EPS_REL * max(abs(fa), abs(fb)))
    return str(a).strip() == str(b).strip()


def make(registers, values: dict, name: str = "") -> dict:
    """Build a snapshot document.

    *values* maps ``key -> displayed value`` (key = datatypes.reg_key). Registers with no reading are
    stored with ``None`` rather than skipped, so a later comparison can tell
    "was never read" apart from "is gone from the map"."""
    rows = []
    for reg in registers or []:
        if not isinstance(reg, dict) or "addr" not in reg:
            # No address at all is junk, not "register 0" — defaulting here
            # invented a phantom row at address 0 for every malformed entry.
            continue
        try:
            addr = int(reg["addr"])
        except (TypeError, ValueError):
            continue
        entry = {"addr": addr, "name": str(reg.get("name", "")),
                 "type": reg.get("type", "SHORT")}
        area = datatypes.area_of(reg).key
        if area != datatypes.DEFAULT_AREA:
            entry["area"] = area             # coils etc.: only when not holding
        key = datatypes.reg_key(entry)
        raw = values.get(key, values.get(str(key)))
        entry["value"] = None if raw is None else str(raw)
        if reg.get("unit"):
            entry["unit"] = reg["unit"]
        rows.append(entry)
    return {"format": FORMAT, "version": VERSION, "name": name,
            "taken_at": time.time(), "registers": rows}


def load(doc) -> dict:
    """Validate a parsed snapshot. Raises ValueError with a readable message —
    the UI shows it verbatim."""
    if not isinstance(doc, dict):
        raise ValueError("Снимок: ожидался JSON-объект.")
    if doc.get("format") != FORMAT:
        raise ValueError("Это не файл снимка значений.")
    version = doc.get("version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise ValueError("Снимок: некорректная версия. Файл повреждён.")
    if version > VERSION:
        raise ValueError(
            f"Снимок версии {version} новее, чем поддерживает программа "
            f"(до {VERSION}). Обновите ModbusReader.")
    rows = doc.get("registers")
    if not isinstance(rows, list):
        raise ValueError("Снимок: нет списка регистров.")
    out = dict(doc)
    clean = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        try:
            addr = int(r.get("addr"))
        except (TypeError, ValueError):
            continue
        area = datatypes.area_of(r).key
        clean.append({"addr": addr, "name": str(r.get("name", "")),
                      "type": r.get("type", "SHORT"),
                      "value": r.get("value"),
                      **({"area": area} if area != datatypes.DEFAULT_AREA else {}),
                      **({"unit": r["unit"]} if r.get("unit") else {})})
    out["registers"] = clean
    return out


def dumps(snapshot: dict) -> str:
    return json.dumps(snapshot, indent=2, ensure_ascii=False)


def compare(before: dict, after: dict) -> list:
    """Two snapshots → one row per register, newest map order first.

    Each row: ``{addr, name, type, unit, before, after, state}`` where state is
    same / changed / added / removed. A register present on only one side is
    reported as added/removed — calling that a "change" would be wrong, and
    those are exactly the rows an operator needs to notice after editing a map.
    """
    # Keyed by (table, address): coil 5 and holding 5 are different registers.
    a_rows = {datatypes.reg_key(r): r for r in (before or {}).get("registers", [])}
    b_rows = {datatypes.reg_key(r): r for r in (after or {}).get("registers", [])}

    out = []
    for key, row in b_rows.items():
        addr = key
        old = a_rows.get(addr)
        if old is None:
            state = ADDED
            before_value = None
        else:
            before_value = old.get("value")
            state = SAME if values_equal(before_value, row.get("value")) \
                else CHANGED
        out.append({
            "addr": addr & 0xFFFF,
            "key": addr,
            "name": row.get("name") or (old or {}).get("name", ""),
            "type": row.get("type", "SHORT"),
            "unit": row.get("unit", "") or (old or {}).get("unit", ""),
            "before": before_value,
            "after": row.get("value"),
            "state": state,
        })
    for addr, old in a_rows.items():
        if addr in b_rows:
            continue
        out.append({"addr": addr & 0xFFFF, "key": addr, "name": old.get("name", ""),
                    "type": old.get("type", "SHORT"),
                    "unit": old.get("unit", ""),
                    "before": old.get("value"), "after": None,
                    "state": REMOVED})
    out.sort(key=lambda r: r["key"])
    return out


def summarize(rows: list) -> dict:
    """Counts per state — drives the one-line summary above the table."""
    counts = {SAME: 0, CHANGED: 0, ADDED: 0, REMOVED: 0}
    for r in rows:
        counts[r["state"]] = counts.get(r["state"], 0) + 1
    return counts


def delta(row: dict):
    """Numeric difference for a changed row, or None when it is not numeric.
    Shown as a separate column so a drift of +0.3 reads at a glance."""
    a, b = _num(row.get("before")), _num(row.get("after"))
    if a is None or b is None:
        return None
    return b - a
