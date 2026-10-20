# core/scaling.py
"""Per-register engineering-unit scaling and enum mapping.

A device reports RAW register values; the operator wants engineering units:

    displayed = raw * scale + offset          (e.g. 1234 * 0.01 + 0 = 12.34 V)

and, for status registers, a symbolic label instead of a number:

    enum = {"0": "Стоп", "1": "Работа"}        (raw 1 shown as "Работа")

These live on the register dict (keys ``scale``, ``offset``, ``enum``) with
identity defaults (scale 1.0, offset 0.0, no enum) — a register without them
behaves exactly as before, so old profiles are unaffected.

This module is PURE (no Qt, no I/O): every consumer that has the register dict
(modbus_core poll/write, the table, the dashboard) calls these helpers. Scaling
is a *register* property, so it can't live in datatypes.py (keyed by type only).
"""
import math


def _num(v, default):
    try:
        f = float(v)
        return f if f == f else default          # reject NaN
    except (TypeError, ValueError):
        return default


def get_scale(reg: dict) -> float:
    return _num(reg.get("scale", 1.0), 1.0)


def get_offset(reg: dict) -> float:
    return _num(reg.get("offset", 0.0), 0.0)


def has_scaling(reg: dict) -> bool:
    """True when this register applies a non-identity scale/offset."""
    return get_scale(reg) != 1.0 or get_offset(reg) != 0.0


def get_enum(reg: dict) -> dict:
    """Normalize the enum map to ``{int_key: str_label}`` (keys may arrive as
    strings from JSON). Invalid entries are dropped, not fatal."""
    raw = reg.get("enum")
    if not isinstance(raw, dict):
        return {}
    out = {}
    for k, v in raw.items():
        try:
            out[int(k)] = str(v)
        except (TypeError, ValueError):
            continue
    return out


# ── raw <-> engineering value ────────────────────────────────────────────
def to_engineering(reg: dict, raw):
    """RAW decoded number → engineering value (raw * scale + offset).
    Non-numeric raw passes through untouched."""
    if raw is None:
        return None
    try:
        return float(raw) * get_scale(reg) + get_offset(reg)
    except (TypeError, ValueError):
        return raw


def to_raw(reg: dict, engineering):
    """Engineering value the user typed → RAW number to encode/write, inverting
    ``raw * scale + offset``. With scale 1 / offset 0 this is a no-op."""
    scale = get_scale(reg)
    if scale == 0:
        scale = 1.0                              # guard against /0 in a bad profile
    try:
        return (float(engineering) - get_offset(reg)) / scale
    except (TypeError, ValueError):
        return engineering


# ── display formatting (enum → label; else scaled number, tidy) ───────────
def format_value(reg: dict, raw, unit: bool = False) -> str:
    """Human string for a raw value: enum label if mapped, otherwise the scaled
    number trimmed of trailing zeros, optionally with the register's unit."""
    if raw is None:
        return "—"
    enum = get_enum(reg)
    if enum:
        try:
            key = int(round(float(raw)))
            if key in enum:
                return enum[key]
        except (TypeError, ValueError, OverflowError):
            pass
    eng = to_engineering(reg, raw)
    if isinstance(eng, float):
        # A broken sensor really does report NaN / ±inf over Modbus (FLOAT
        # words 7FC0 0000 / 7F80 0000). int(inf) raises, and an exception here
        # used to escape the table's update path with its signals still
        # blocked — every later cell edit was silently ignored.
        if not math.isfinite(eng):
            text = str(eng)
        elif eng != int(eng):
            text = f"{eng:.6f}".rstrip("0").rstrip(".")
        else:
            text = str(int(eng))
    else:
        text = str(eng)
    u = str(reg.get("unit", "")).strip()
    return f"{text} {u}".strip() if (unit and u) else text
