# datatypes.py
"""Central registry of Modbus register data types — the single source of truth.

Every part of the app that needs to know "how big is this type", "how do I turn
raw 16-bit register words into a value", "how do I turn a value back into words",
"how do I display it", or "is this a pollable scalar vs. a service area" reads it
from HERE — not from its own private if/elif chain.

Design: the **Descriptor + Registry** style.
    * A `DataType` *descriptor* declares one type as data (span, codecs, flags).
    * The `TYPES` ordered dict is the *registry*.
    * Thin module-level helpers (`decode`, `encode`, `read_count`, `should_poll`,
      `is_area`, ...) are the only API the rest of the app calls.

To add a new register type you add ONE `DataType(...)` entry to `TYPES`.
Nothing else in the codebase needs to change.

The byte-order maths below is the proven device protocol and is preserved
verbatim from the original modbus_core implementation — do not "simplify" it.
"""

from dataclasses import dataclass
from typing import Callable, Optional

import byteorder


# ── low-level codecs (byte order lives in byteorder.py) ─────────────────
# The word/byte order per type is CONFIGURABLE (Settings → Подключение →
# Кодеки). The defaults below are the proven device protocol preserved from
# the original implementation — with them, encode/decode is bit-identical to
# the historical pack/unpack functions (guarded by tests/test_datatypes.py and
# tests/test_byteorder.py golden vectors).
_ORDERS = {
    "SHORT": "AB",      # signed 16-bit, standard byte order
    "LONG":  "ABCD",    # signed int32, big-endian, no swaps
    "FLOAT": "BADC",    # IEEE-754, bytes swapped within each word
}


def configure_orders(settings: dict):
    """Apply the user's byte-order choice from the settings dict (called by
    AppContext on startup and on every settings change)."""
    _ORDERS["SHORT"] = settings.get("order_short", "AB")
    _ORDERS["LONG"] = settings.get("order_long", "ABCD")
    _ORDERS["FLOAT"] = settings.get("order_float", "BADC")


def get_orders() -> dict:
    return dict(_ORDERS)


def pack_float(value) -> list[int]:
    return byteorder.encode_f32(value, _ORDERS["FLOAT"])


def unpack_float(regs) -> float:
    return byteorder.decode_f32(regs, _ORDERS["FLOAT"])


def pack_long(value) -> list[int]:
    return byteorder.encode_i32(value, _ORDERS["LONG"])


def unpack_long(regs) -> int:
    return byteorder.decode_i32(regs, _ORDERS["LONG"])


def pack_short(value) -> int:
    return byteorder.encode_i16(value, _ORDERS["SHORT"])


def unpack_short(reg) -> int:
    return byteorder.decode_i16(reg, _ORDERS["SHORT"])


# ── descriptor ──────────────────────────────────────────────────────────
@dataclass(frozen=True)
class DataType:
    """Declarative description of one register data type.

    key            canonical id stored in profiles, e.g. "FLOAT"
    label          short display label (defaults to key)
    hint           tooltip shown in the profile editor's type dropdown
    fixed_span     Modbus addresses occupied; None => variable (uses reg["length"])
    is_area        service/memory area — excluded from cyclic polling
    decode         (regs: list[int]) -> python value, or None if not decodable
    encode         (value) -> list[int] words to write, or None if not writable
    fmt            (value) -> str for display (defaults to str())
    """
    key: str
    label: str = ""
    hint: str = ""
    fixed_span: Optional[int] = None
    is_area: bool = False
    decode: Optional[Callable] = None
    encode: Optional[Callable] = None
    fmt: Callable = str

    @property
    def variable_length(self) -> bool:
        return self.fixed_span is None

    @property
    def is_scalar(self) -> bool:
        """True for types the app can actually read/write as a number."""
        return self.decode is not None and self.encode is not None


def _dt(key, **kw) -> DataType:
    return DataType(key=key, label=kw.pop("label", "") or key, **kw)


# ── the registry (declaration order == profile-editor dropdown order) ─────
# Fixed-width types first, then variable / area types, matching the original
# `ALL_TYPES = list(FIXED_TYPE_LEN) + VARIABLE_TYPES` ordering exactly.
TYPES: dict[str, DataType] = {dt.key: dt for dt in [
    # ── fixed-width scalars ──
    _dt("BYTE",   fixed_span=1, hint="Байт (1 байт → 1 адрес)"),
    _dt("SHORT",  fixed_span=1, hint="2 байта → 1 адрес",
        decode=lambda regs: unpack_short(regs[0]),
        encode=lambda v: [pack_short(int(float(v)))]),
    _dt("LONG",   fixed_span=2, hint="4 байта → 2 адреса (старшее слово первым)",
        decode=lambda regs: unpack_long(regs),
        encode=lambda v: pack_long(int(float(v)))),
    _dt("LONG1",  fixed_span=2, hint="4 байта → 2 адреса (младшее слово первым)"),
    _dt("FLOAT",  fixed_span=2, hint="IEEE-754 Single, 4 байта → 2 адреса",
        decode=lambda regs: round(unpack_float(regs), 6),
        encode=lambda v: pack_float(float(v)),
        fmt=lambda v: f"{v:.2f}"),
    _dt("FLOAT1", fixed_span=2, hint="IEEE-754 Single, порядок байт #1"),
    _dt("FLOAT2", fixed_span=2, hint="IEEE-754 Single, порядок байт #2"),
    # ── variable-length / structured ──
    _dt("ARR",       hint="Массив байт (длина в адресах)"),
    _dt("STR_LEN",   hint="Строка с длиной"),
    _dt("STR_PNTR",  hint="Указатель на строку с длиной"),
    _dt("MANY_STR",  hint="Несколько строк с длиной"),
    _dt("DIBUS_ADR", hint="DiBUS адрес"),
    _dt("DATE_TIME", hint="Дата/время"),
    # ── service areas (not polled) ──
    _dt("UNUSED_AREA", is_area=True,
        hint="Неиспользуемая область (читаем 0, писать нельзя)"),
    _dt("MEMORY_AREA", is_area=True,
        hint="Область RAM, отображаемая на регистры MODBUS"),
]}

# Legacy alias kept for back-compat with old profiles / call sites.
_LEGACY_AREA_KEYS = {"AREA"}


# ── derived views (built once, mirror the old module constants) ──────────
ALL_TYPES: list[str] = list(TYPES.keys())
FIXED_TYPE_LEN: dict[str, int] = {
    k: dt.fixed_span for k, dt in TYPES.items() if dt.fixed_span is not None}
VARIABLE_TYPES: list[str] = [k for k, dt in TYPES.items() if dt.fixed_span is None]
TYPE_HINTS: dict[str, str] = {k: dt.hint for k, dt in TYPES.items()}
SCALAR_KEYS: tuple[str, ...] = tuple(k for k, dt in TYPES.items() if dt.is_scalar)
_AREA_KEYS = {k for k, dt in TYPES.items() if dt.is_area} | _LEGACY_AREA_KEYS

DEFAULT_TYPE = "SHORT"


# ── public API ───────────────────────────────────────────────────────────
def get(key: str) -> Optional[DataType]:
    return TYPES.get(key)


def is_area(key: str) -> bool:
    """Service/memory area — excluded from cyclic polling."""
    return key in _AREA_KEYS


def should_poll(key: str) -> bool:
    """Whether a register of this type participates in cyclic polling."""
    return not is_area(key)


def is_scalar(key: str) -> bool:
    dt = TYPES.get(key)
    return bool(dt and dt.is_scalar)


def read_count(key: str) -> int:
    """Number of Modbus registers to request when reading this type."""
    dt = TYPES.get(key)
    if dt and dt.fixed_span:
        return dt.fixed_span
    return 2  # legacy default for non-fixed / unknown scalar reads


def addr_span(reg: dict) -> int:
    """Number of Modbus addresses a *register dict* occupies.

    Fixed types use their declared span; variable types use reg["length"]."""
    dt = TYPES.get(reg.get("type", DEFAULT_TYPE))
    if dt and dt.fixed_span:
        return dt.fixed_span
    try:
        return max(1, int(reg.get("length", 1)))
    except (TypeError, ValueError):
        return 1


def decode(key: str, regs):
    """Raw register words → python value. None if the type has no decoder."""
    dt = TYPES.get(key)
    return dt.decode(regs) if (dt and dt.decode) else None


def encode(key: str, value) -> list[int]:
    """Python value → register words to write. [] if the type has no encoder."""
    dt = TYPES.get(key)
    return dt.encode(value) if (dt and dt.encode) else []


def read_to_str(key: str, regs) -> str:
    """Decode + format for table display. '???' for non-decodable types,
    matching the original modbus_core behavior."""
    dt = TYPES.get(key)
    if not dt or dt.decode is None:
        return "???"
    return dt.fmt(dt.decode(regs))
