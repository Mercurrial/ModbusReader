# byteorder.py
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
