"""Byte-order codecs (byteorder.py) — the sacred-protocol guard.

The historical device codecs were extracted into byteorder.py with a
configurable order per type. THE defaults (SHORT=AB, LONG=ABCD, FLOAT=BADC)
must stay bit-identical to the original pack/unpack implementation — the
LEGACY vectors below are that original code inlined verbatim. If these fail,
the user's devices read garbage.
"""
import struct

import pytest

from core import byteorder as bo
from core import datatypes as dt


# ── the ORIGINAL implementation, inlined as the golden reference ────────
def _legacy_pack_float(value):
    packed = struct.pack('>f', float(value))
    reg1, reg2 = struct.unpack('>HH', packed)
    return [((reg1 & 0xFF) << 8) | ((reg1 >> 8) & 0xFF),
            ((reg2 & 0xFF) << 8) | ((reg2 >> 8) & 0xFF)]


def _legacy_unpack_float(regs):
    r1 = ((regs[0] & 0xFF) << 8) | ((regs[0] >> 8) & 0xFF)
    r2 = ((regs[1] & 0xFF) << 8) | ((regs[1] >> 8) & 0xFF)
    return struct.unpack('>f', struct.pack('>HH', r1, r2))[0]


def _legacy_pack_long(value):
    return list(struct.unpack('>HH', struct.pack('>i', int(value))))


def _legacy_unpack_long(regs):
    return struct.unpack('>i', struct.pack('>HH', regs[0], regs[1]))[0]


def _legacy_pack_short(value):
    return struct.unpack('>H', struct.pack('>h', int(value)))[0]


def _legacy_unpack_short(reg):
    return struct.unpack('>h', struct.pack('>H', reg))[0]


FLOATS = (0.0, 1.0, -1.5, 3.14159, 1e6, -1e-3, 12.34)
INTS32 = (-2147483648, -65536, -1, 0, 1, 65535, 65536, 0x12345678, 2147483647)
INTS16 = (-32768, -1, 0, 1, 255, 256, 32767)


@pytest.fixture(autouse=True)
def _default_orders():
    """Every test starts and ends with the device-default orders."""
    dt.configure_orders({})
    yield
    dt.configure_orders({})


# ── parity with the original code (the whole point of this file) ────────
def test_float_default_matches_legacy_bit_for_bit():
    for v in FLOATS:
        assert dt.pack_float(v) == _legacy_pack_float(v)
    for regs in ([0x803F, 0x0000], [0x0000, 0x0000], [0xC940, 0x0000],
                 [0x1234, 0x5678]):
        assert dt.unpack_float(regs) == _legacy_unpack_float(regs)


def test_long_default_matches_legacy_bit_for_bit():
    for v in INTS32:
        assert dt.pack_long(v) == _legacy_pack_long(v)
    for regs in ([0, 0], [0xFFFF, 0xFFFF], [0x1234, 0x5678], [0x8000, 0x0000]):
        assert dt.unpack_long(regs) == _legacy_unpack_long(regs)


def test_short_default_matches_legacy_bit_for_bit():
    for v in INTS16:
        assert dt.pack_short(v) == _legacy_pack_short(v)
    for reg in (0, 1, 0x7FFF, 0x8000, 0xFFFF):
        assert dt.unpack_short(reg) == _legacy_unpack_short(reg)


def test_registry_decode_encode_still_legacy():
    # Through the public registry API too (what modbus_core actually calls).
    assert dt.decode("FLOAT", _legacy_pack_float(12.34)) == pytest.approx(12.34)
    assert dt.encode("LONG", 0x12345678) == _legacy_pack_long(0x12345678)
    assert dt.decode("SHORT", [0xFFFF]) == -1


# ── known wire vectors (hand-checked, catch silent permutation bugs) ────
def test_known_vectors():
    # 1.0f = 3F 80 00 00
    assert bo.encode_f32(1.0, "ABCD") == [0x3F80, 0x0000]
    assert bo.encode_f32(1.0, "BADC") == [0x803F, 0x0000]
    assert bo.encode_f32(1.0, "CDAB") == [0x0000, 0x3F80]
    assert bo.encode_f32(1.0, "DCBA") == [0x0000, 0x803F]
    # 0x12345678
    assert bo.encode_i32(0x12345678, "ABCD") == [0x1234, 0x5678]
    assert bo.encode_i32(0x12345678, "BADC") == [0x3412, 0x7856]
    assert bo.encode_i32(0x12345678, "CDAB") == [0x5678, 0x1234]
    assert bo.encode_i32(0x12345678, "DCBA") == [0x7856, 0x3412]
    # 16-bit
    assert bo.encode_i16(0x1234, "AB") == 0x1234
    assert bo.encode_i16(0x1234, "BA") == 0x3412


def test_roundtrip_every_order():
    for order in bo.ORDERS_32:
        for v in INTS32:
            assert bo.decode_i32(bo.encode_i32(v, order), order) == v
        for v in FLOATS:
            assert bo.decode_f32(bo.encode_f32(v, order), order) == pytest.approx(v)
    for order in bo.ORDERS_16:
        for v in INTS16:
            assert bo.decode_i16(bo.encode_i16(v, order), order) == v


def test_configure_orders_switches_live():
    dt.configure_orders({"order_long": "CDAB"})
    assert dt.encode("LONG", 0x12345678) == [0x5678, 0x1234]   # word-swapped
    dt.configure_orders({})                                     # back to default
    assert dt.encode("LONG", 0x12345678) == [0x1234, 0x5678]


def test_short_regs_when_missing_words():
    assert bo.decode_i32([], "ABCD") == 0
    assert bo.decode_f32([0x1234], "BADC") == 0.0


def test_settings_defaults_equal_device_protocol():
    from app.settings_manager import DEFAULT_SETTINGS
    assert DEFAULT_SETTINGS["order_short"] == "AB"
    assert DEFAULT_SETTINGS["order_long"] == "ABCD"
    assert DEFAULT_SETTINGS["order_float"] == "BADC"
