# core/byteorder.py
"""Byte/word-order codecs for multi-register Modbus values.

Vendors pack 32-bit values into two 16-bit registers in four common ways.
The industry labels ("ABCD", "BADC", ...) describe where the value's bytes
(A = most significant … D = least significant) sit in the transmitted words:

    ABCD  reg0 = A<<8|B, reg1 = C<<8|D   big-endian (Modbus standard)
    BADC  reg0 = B<<8|A, reg1 = D<<8|C   byte swap inside each word
    CDAB  reg0 = C<<8|D, reg1 = A<<8|B   word swap
    DCBA  reg0 = D<<8|C, reg1 = B<<8|A   full reverse (little-endian)

For 16-bit values there are two: "AB" (standard) and "BA" (byte-swapped).

Every permutation here is an involution (applying it twice = identity), so the
same permutation is used for encode and decode — no separate inverse tables.

The app's device defaults (the proven protocol preserved from the original
implementation) are: SHORT="AB", LONG="ABCD", FLOAT="BADC". They are the
settings defaults in settings_manager — an existing installation keeps decoding
exactly as before.
"""

import struct

# UI-facing option tuples (declaration order == dropdown order).
ORDERS_16 = ("AB", "BA")
ORDERS_32 = ("ABCD", "BADC", "CDAB", "DCBA")

# value-byte index for each wire-byte position (involutions — see docstring).
_PERM32 = {
    "ABCD": (0, 1, 2, 3),
    "BADC": (1, 0, 3, 2),
    "CDAB": (2, 3, 0, 1),
    "DCBA": (3, 2, 1, 0),
}


def _permute32(raw: bytes, order: str) -> bytes:
    p = _PERM32.get(order, _PERM32["ABCD"])
    return bytes(raw[i] for i in p)


def _words_to_bytes(regs) -> bytes:
    return struct.pack(">HH", regs[0] & 0xFFFF, regs[1] & 0xFFFF)


def _bytes_to_words(b: bytes) -> list[int]:
    return list(struct.unpack(">HH", b))


# ── 32-bit signed int ────────────────────────────────────────────────────
def decode_i32(regs, order: str = "ABCD") -> int:
    if len(regs) < 2:
        return 0
    return struct.unpack(">i", _permute32(_words_to_bytes(regs), order))[0]


def encode_i32(value, order: str = "ABCD") -> list[int]:
    return _bytes_to_words(_permute32(struct.pack(">i", int(value)), order))


# ── 32-bit IEEE-754 float ────────────────────────────────────────────────
def decode_f32(regs, order: str = "ABCD") -> float:
    if len(regs) < 2:
        return 0.0
    return struct.unpack(">f", _permute32(_words_to_bytes(regs), order))[0]


def encode_f32(value, order: str = "ABCD") -> list[int]:
    return _bytes_to_words(_permute32(struct.pack(">f", float(value)), order))


# ── 16-bit signed int ────────────────────────────────────────────────────
def _swap16(word: int) -> int:
    return ((word & 0xFF) << 8) | ((word >> 8) & 0xFF)


def decode_i16(reg: int, order: str = "AB") -> int:
    w = _swap16(reg) if order == "BA" else (reg & 0xFFFF)
    return struct.unpack(">h", struct.pack(">H", w))[0]


def encode_i16(value, order: str = "AB") -> int:
    w = struct.unpack(">H", struct.pack(">h", int(value)))[0]
    return _swap16(w) if order == "BA" else w


# ══════════════════════════════════════════════════════════════════════
#  v2.1 — unsigned, 64-bit, BCD and string codecs
#  (the functions above are the guarded historical codecs — untouched)
# ══════════════════════════════════════════════════════════════════════
# A 64-bit value spans four registers. The configured 32-bit order name is
# applied the way vendors mean it for 64 bits: "ABCD" big-endian, "BADC" bytes
# swapped inside every word, "CDAB" the four WORDS reversed, "DCBA" fully
# reversed (little-endian). Each is again an involution.
_PERM64 = {
    "ABCD": (0, 1, 2, 3, 4, 5, 6, 7),
    "BADC": (1, 0, 3, 2, 5, 4, 7, 6),
    "CDAB": (6, 7, 4, 5, 2, 3, 0, 1),
    "DCBA": (7, 6, 5, 4, 3, 2, 1, 0),
}


def _permute64(raw: bytes, order: str) -> bytes:
    p = _PERM64.get(order, _PERM64["ABCD"])
    return bytes(raw[i] for i in p)


def _words_to_bytes_n(regs, n: int) -> bytes:
    return b"".join(struct.pack(">H", int(r) & 0xFFFF) for r in list(regs)[:n])


def _bytes_to_words_n(b: bytes) -> list[int]:
    return [int.from_bytes(b[i:i + 2], "big") for i in range(0, len(b), 2)]


# ── 16-bit unsigned ──────────────────────────────────────────────────────
def decode_u16(reg: int, order: str = "AB") -> int:
    return _swap16(reg) if order == "BA" else (int(reg) & 0xFFFF)


def encode_u16(value: int, order: str = "AB") -> int:
    w = int(value)
    if not 0 <= w <= 0xFFFF:
        raise ValueError(f"{w}: вне диапазона 0…65535")
    return _swap16(w) if order == "BA" else w


# ── 32-bit unsigned ──────────────────────────────────────────────────────
def decode_u32(regs, order: str = "ABCD") -> int:
    if len(regs) < 2:
        return 0
    return struct.unpack(">I", _permute32(_words_to_bytes(regs), order))[0]


def encode_u32(value, order: str = "ABCD") -> list[int]:
    v = int(value)
    if not 0 <= v <= 0xFFFFFFFF:
        raise ValueError(f"{v}: вне диапазона 0…4294967295")
    return _bytes_to_words(_permute32(struct.pack(">I", v), order))


# ── 64-bit signed int / IEEE-754 double ──────────────────────────────────
def decode_i64(regs, order: str = "ABCD") -> int:
    if len(regs) < 4:
        return 0
    return struct.unpack(">q", _permute64(_words_to_bytes_n(regs, 4), order))[0]


def encode_i64(value, order: str = "ABCD") -> list[int]:
    v = int(value)
    if not -(1 << 63) <= v < (1 << 63):
        raise ValueError(f"{v}: вне диапазона int64")
    return _bytes_to_words_n(_permute64(struct.pack(">q", v), order))


def decode_f64(regs, order: str = "ABCD") -> float:
    if len(regs) < 4:
        return 0.0
    return struct.unpack(">d", _permute64(_words_to_bytes_n(regs, 4), order))[0]


def encode_f64(value, order: str = "ABCD") -> list[int]:
    return _bytes_to_words_n(_permute64(struct.pack(">d", float(value)), order))


# ── BCD (one decimal digit per nibble) ───────────────────────────────────
def bcd_to_int(raw: int, digits: int) -> int:
    """0x1234 → 1234. A nibble above 9 is not BCD: ValueError (shown "???")."""
    out = 0
    for shift in range((digits - 1) * 4, -1, -4):
        d = (raw >> shift) & 0xF
        if d > 9:
            raise ValueError(f"не BCD: 0x{raw:0{digits}X}")
        out = out * 10 + d
    return out


def int_to_bcd(value: int, digits: int) -> int:
    v = int(value)
    if not 0 <= v < 10 ** digits:
        raise ValueError(f"{v}: BCD вмещает 0…{10 ** digits - 1}")
    out = 0
    for i, ch in enumerate(reversed(str(v))):
        out |= int(ch) << (4 * i)
    return out


def decode_bcd16(reg: int, order: str = "AB") -> int:
    return bcd_to_int(decode_u16(reg, order), 4)


def encode_bcd16(value, order: str = "AB") -> int:
    return encode_u16(int_to_bcd(value, 4), order)


def decode_bcd32(regs, order: str = "ABCD") -> int:
    return bcd_to_int(decode_u32(regs, order), 8)


def encode_bcd32(value, order: str = "ABCD") -> list[int]:
    return encode_u32(int_to_bcd(value, 8), order)


# ── strings: two characters per register ─────────────────────────────────
# cp1251 is a superset of ASCII and is what a Russian device puts in a text
# register when it uses anything beyond ASCII. The 16-bit order setting also
# governs strings: a device that swaps bytes in a number swaps them in text.
STRING_ENCODING = "cp1251"


def decode_str(regs, order: str = "AB") -> str:
    raw = b"".join(struct.pack(">H", decode_u16(r, order)) for r in regs)
    raw = raw.split(b"\x00", 1)[0]                 # C-string: stop at NUL
    return raw.decode(STRING_ENCODING, errors="replace").rstrip()


def encode_str(text, words: int, order: str = "AB") -> list[int]:
    """Text → exactly *words* registers, NUL-padded (an old, longer value
    must not survive past the new end). Too long for the field: ValueError."""
    raw = str(text).encode(STRING_ENCODING, errors="replace")
    if len(raw) > words * 2:
        raise ValueError(f"строка длиннее поля ({len(raw)} > {words * 2} байт)")
    raw = raw.ljust(words * 2, b"\x00")
    return [encode_u16(int.from_bytes(raw[i:i + 2], "big"), order)
            for i in range(0, len(raw), 2)]
