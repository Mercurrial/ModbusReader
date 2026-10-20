# core/datatypes.py
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

import math
from dataclasses import dataclass
from typing import Callable, Optional

from core import byteorder


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


# ── v2.1 helpers for the new types ──────────────────────────────────────
def _int_arg(v) -> int:
    """A value the operator typed → an exact integer.

    "0x1F", "17", "-5" parse exactly (int64 must not round-trip through a
    float). A fractional value — typically engineering units converted back
    to raw — is rounded to the nearest integer."""
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, int):
        return v
    s = str(v).strip().replace(",", ".")
    try:
        return int(s, 0)
    except ValueError:
        pass
    f = float(s)
    if not math.isfinite(f):
        raise ValueError(f"{s}: не число")
    return int(round(f))


def _fmt_real(v) -> str:
    """Up to 10 significant digits, no trailing noise ("3.14", "1e+20")."""
    return format(v, ".10g") if math.isfinite(v) else str(v)


def _fmt_bits(v) -> str:
    return str(int(v))          # the table renders BITS16 in its bin view


_TRUE_WORDS = {"1", "true", "on", "yes", "вкл", "да", "истина"}
_FALSE_WORDS = {"0", "false", "off", "no", "выкл", "нет", "ложь"}


def _bool_arg(v) -> int:
    """A coil value the operator typed → 0 / 1 ("ВКЛ", "on", "1", "true"…)."""
    if isinstance(v, bool):
        return int(v)
    s = str(v).strip().lower()
    if s in _TRUE_WORDS:
        return 1
    if s in _FALSE_WORDS:
        return 0
    try:
        return 1 if float(s.replace(",", ".")) else 0
    except ValueError:
        raise ValueError(f"{v}: ожидается 0/1 (ВКЛ/ВЫКЛ)")


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
                   (text types take ``(value, words)`` — the field length)
    fmt            (value) -> str for display (defaults to str())
    text           the value is TEXT, not a number (strings)
    default_view   how the table shows it until the user picks dec/hex/bin
    """
    key: str
    label: str = ""
    hint: str = ""
    fixed_span: Optional[int] = None
    is_area: bool = False
    decode: Optional[Callable] = None
    encode: Optional[Callable] = None
    fmt: Callable = str
    text: bool = False
    default_view: str = "dec"

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
    # One bit: the type of every coil / discrete input (and usable as a
    # "non-zero" flag on a register).
    _dt("BOOL",   fixed_span=1, hint="Бит 0/1 (coil, discrete input или флаг)",
        decode=lambda regs: 1 if int(regs[0]) else 0,
        encode=lambda v: [_bool_arg(v)]),
    _dt("SHORT",  fixed_span=1, hint="2 байта → 1 адрес",
        decode=lambda regs: unpack_short(regs[0]),
        encode=lambda v: [pack_short(int(float(v)))]),
    # Unsigned 16-bit. Without it a counter above 32767 read as negative.
    _dt("UINT16", fixed_span=1, hint="Целое без знака 0…65535 → 1 адрес",
        decode=lambda regs: byteorder.decode_u16(regs[0], _ORDERS["SHORT"]),
        encode=lambda v: [byteorder.encode_u16(_int_arg(v), _ORDERS["SHORT"])]),
    # 16 status flags. Stored as the unsigned word; the table shows it in
    # binary and the dashboard "bits" widget lights one cell per flag.
    _dt("BITS16", fixed_span=1, hint="Битовое поле: 16 флагов → 1 адрес",
        decode=lambda regs: byteorder.decode_u16(regs[0], _ORDERS["SHORT"]),
        encode=lambda v: [byteorder.encode_u16(_int_arg(v), _ORDERS["SHORT"])],
        fmt=_fmt_bits, default_view="bin"),
    _dt("BCD16",  fixed_span=1, hint="BCD: 4 десятичные цифры → 1 адрес",
        decode=lambda regs: byteorder.decode_bcd16(regs[0], _ORDERS["SHORT"]),
        encode=lambda v: [byteorder.encode_bcd16(_int_arg(v), _ORDERS["SHORT"])]),
    _dt("LONG",   fixed_span=2, hint="4 байта → 2 адреса (старшее слово первым)",
        decode=lambda regs: unpack_long(regs),
        encode=lambda v: pack_long(int(float(v)))),
    _dt("UINT32", fixed_span=2, hint="Целое без знака 0…4 294 967 295 → 2 адреса",
        decode=lambda regs: byteorder.decode_u32(regs, _ORDERS["LONG"]),
        encode=lambda v: byteorder.encode_u32(_int_arg(v), _ORDERS["LONG"])),
    _dt("LONG1",  fixed_span=2, hint="4 байта → 2 адреса (младшее слово первым)"),
    _dt("BCD32",  fixed_span=2, hint="BCD: 8 десятичных цифр → 2 адреса",
        decode=lambda regs: byteorder.decode_bcd32(regs, _ORDERS["LONG"]),
        encode=lambda v: byteorder.encode_bcd32(_int_arg(v), _ORDERS["LONG"])),
    _dt("FLOAT",  fixed_span=2, hint="IEEE-754 Single, 4 байта → 2 адреса",
        decode=lambda regs: round(unpack_float(regs), 6),
        encode=lambda v: pack_float(float(v)),
        fmt=lambda v: f"{v:.2f}"),
    _dt("FLOAT1", fixed_span=2, hint="IEEE-754 Single, порядок байт #1"),
    _dt("FLOAT2", fixed_span=2, hint="IEEE-754 Single, порядок байт #2"),
    # 64-bit types follow the 32-bit order settings (LONG for integers,
    # FLOAT for reals) — see byteorder._PERM64 for what each order means.
    _dt("INT64",  fixed_span=4, hint="Целое со знаком, 8 байт → 4 адреса",
        decode=lambda regs: byteorder.decode_i64(regs, _ORDERS["LONG"]),
        encode=lambda v: byteorder.encode_i64(_int_arg(v), _ORDERS["LONG"])),
    _dt("DOUBLE", fixed_span=4, hint="IEEE-754 Double, 8 байт → 4 адреса",
        decode=lambda regs: byteorder.decode_f64(regs, _ORDERS["FLOAT"]),
        encode=lambda v: byteorder.encode_f64(float(v), _ORDERS["FLOAT"]),
        fmt=_fmt_real),
    # ── variable-length / structured ──
    # Text, two characters per register; the field length is the register's
    # "length" (in addresses).
    _dt("STRING", hint="Строка: 2 символа на адрес (длина в адресах)",
        decode=lambda regs: byteorder.decode_str(regs, _ORDERS["SHORT"]),
        encode=lambda v, words=1: byteorder.encode_str(v, words, _ORDERS["SHORT"]),
        text=True),
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


# ══════════════════════════════════════════════════════════════════════
#  AREAS — the four Modbus data tables
# ══════════════════════════════════════════════════════════════════════
# Modbus keeps four separate address spaces: coil 0, discrete input 0, input
# register 0 and holding register 0 are four different things. A register
# dict names its table in the optional "area" key; absent means "holding",
# which is all the app knew before 2.1, so every existing file is unchanged.
#
# Everything that identifies a register (poll results, the table, trends,
# dashboard bindings, the watch list, logger columns) uses ONE integer key:
#     key = area.code << 16 | addr
# Holding has code 0, so for every existing map key == addr and nothing that
# was saved before has to be migrated. The string id is the same key in hex
# (reg_id); key_label() is what a human sees ("IR 0x0010").
@dataclass(frozen=True)
class Area:
    key: str               # stored value of reg["area"]
    code: int              # high bits of the composite key
    prefix: str            # display prefix ("" for holding)
    modicon: int           # first digit in the 0x/1x/3x/4x convention
    fc_read: int
    fc_write: Optional[int]
    bits: bool             # 1-bit table (coils, discrete inputs)
    label_key: str         # i18n

    @property
    def writable(self) -> bool:
        return self.fc_write is not None


AREAS: dict[str, Area] = {a.key: a for a in (
    Area("holding",  0, "",   4, 0x03, 0x06, False, "areaHolding"),
    Area("input",    1, "IR", 3, 0x04, None, False, "areaInput"),
    Area("coil",     2, "CO", 0, 0x01, 0x05, True,  "areaCoil"),
    Area("discrete", 3, "DI", 1, 0x02, None, True,  "areaDiscrete"),
)}
DEFAULT_AREA = "holding"
_AREA_BY_CODE = {a.code: a for a in AREAS.values()}
BIT_TYPE = "BOOL"


def area_of(reg: dict) -> Area:
    return AREAS.get(str(reg.get("area") or DEFAULT_AREA), AREAS[DEFAULT_AREA])


def reg_key(reg: dict) -> int:
    """The register's identity across the app (see AREAS)."""
    raw = reg.get("addr", 0)
    try:
        if isinstance(raw, str):
            addr = int(raw.strip(), 0) if raw.strip() else 0
        else:
            addr = int(raw)
    except (TypeError, ValueError):
        addr = 0
    return (area_of(reg).code << 16) | (addr & 0xFFFF)


def split_key(key: int) -> tuple:
    """key → (Area, 16-bit address)."""
    key = int(key)
    return _AREA_BY_CODE.get(key >> 16, AREAS[DEFAULT_AREA]), key & 0xFFFF


def key_label(key: int) -> str:
    """"0x0010" for holding, "IR 0x0010" / "CO 0x0010" / "DI 0x0010"."""
    area, addr = split_key(key)
    return f"{area.prefix} 0x{addr:04X}" if area.prefix else f"0x{addr:04X}"


def reg_id(key: int) -> str:
    """The string id (trends, dashboard bindings): the key in hex."""
    return f"0x{int(key):04X}"


def parse_key(text):
    """ "IR 0x0010", "co 5", "0x10", "16" → key; None when unparsable.
    The inverse of key_label (macros address coils as reg("CO 0x0005"))."""
    parts = str(text).strip().split()
    if not parts or len(parts) > 2:
        return None
    area = AREAS[DEFAULT_AREA]
    if len(parts) == 2:
        area = next((a for a in AREAS.values()
                     if a.prefix and a.prefix.lower() == parts[0].lower()), None)
        if area is None:
            return None
    try:
        addr = int(parts[-1], 0)
    except ValueError:
        return None
    if not 0 <= addr <= 0xFFFF:
        return None
    return (area.code << 16) | addr


def id_label(rid) -> str:
    """A reg_id as people read it: "0x20010" → "CO 0x0010". Anything that is
    not a hex id is returned unchanged."""
    try:
        return key_label(int(str(rid), 16))
    except (TypeError, ValueError):
        return str(rid)


def apply_area(reg: dict, area) -> None:
    """Put *reg* into a Modbus table, in place. Holding (the default) is
    stored as NO key, so maps without coils stay byte-identical; a bit table
    forces BOOL x1, a read-only table forces access R. Unknown → holding."""
    a = AREAS.get(str(area or "").strip().lower()) or AREAS[DEFAULT_AREA]
    if a.key == DEFAULT_AREA:
        reg.pop("area", None)
        return
    reg["area"] = a.key
    if a.bits:
        reg["type"], reg["length"] = BIT_TYPE, 1
    if not a.writable:
        reg["rw"] = "R"


# Free-text names of the four tables (import from vendor sheets).
_AREA_ALIASES = {
    "holding": ("holding", "hr", "4x", "fc3", "fc03", "03", "хранения",
                "holding register", "holding registers", "регистр хранения"),
    "input": ("input", "ir", "3x", "fc4", "fc04", "04", "input register",
              "input registers", "входной регистр", "входные регистры"),
    "coil": ("coil", "coils", "co", "0x", "fc1", "fc01", "01", "катушка",
             "катушки", "дискретный выход", "выход"),
    "discrete": ("discrete", "discrete input", "discrete inputs", "di", "1x",
                 "fc2", "fc02", "02", "дискретный вход", "дискретные входы",
                 "вход"),
}


def parse_area(text):
    """A table name as vendors write it → AREAS key, or None."""
    t = " ".join(str(text or "").strip().lower().split())
    if not t:
        return None
    if t in AREAS:
        return t
    for key, names in _AREA_ALIASES.items():
        if t in names:
            return key
    return None


def is_writable(reg: dict) -> bool:
    """The register can be written: its table allows writes AND its access
    code contains W. (Input registers and discrete inputs never can.)"""
    return (area_of(reg).writable and "W" in str(reg.get("rw", "")).upper()
            and not is_area(reg.get("type", "")))


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


MAX_READ = 125          # Modbus RTU limit for one FC03/FC04 request


def reg_read_count(reg: dict) -> int:
    """Registers to request for THIS register dict: the fixed span, or — for
    a text field — its own length (capped at one request)."""
    key = reg.get("type", DEFAULT_TYPE)
    dt = TYPES.get(key)
    if dt and dt.text:
        return max(1, min(addr_span(reg), MAX_READ))
    return read_count(key)


def is_text(key: str) -> bool:
    dt = TYPES.get(key)
    return bool(dt and dt.text)


def default_view(key: str) -> str:
    dt = TYPES.get(key)
    return dt.default_view if dt else "dec"


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


def encode(key: str, value, words: int | None = None) -> list[int]:
    """Python value → register words to write. [] if the type has no encoder.
    Text types need *words*, the field length (shorter text is NUL-padded)."""
    dt = TYPES.get(key)
    if not (dt and dt.encode):
        return []
    if dt.text:
        return dt.encode(value, max(1, int(words or 1)))
    return dt.encode(value)


def read_to_str(key: str, regs) -> str:
    """Decode + format for table display. '???' for non-decodable types and
    for words that are not a valid value of the type (e.g. a BCD nibble > 9)."""
    dt = TYPES.get(key)
    if not dt or dt.decode is None:
        return "???"
    try:
        return dt.fmt(dt.decode(regs))
    except (ValueError, OverflowError, TypeError):
        return "???"
