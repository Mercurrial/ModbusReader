"""Sacred codecs: byte order must never drift (FLOAT swaps bytes within each
word, LONG does not, SHORT is signed 16-bit)."""
import struct

import pytest

from core import datatypes as dt


def test_short_roundtrip_signed():
    for v in (-32768, -1, 0, 1, 100, 32767):
        assert dt.decode("SHORT", dt.encode("SHORT", v)) == v
    assert dt.decode("SHORT", [0xFFFF]) == -1
    assert dt.decode("SHORT", [0x8000]) == -32768


def test_long_signed_int32_no_swap():
    for v in (-2147483648, -1, 0, 1, 65535, 65536, 2_000_000, 2147483647):
        regs = dt.encode("LONG", v)
        assert len(regs) == 2
        assert dt.decode("LONG", regs) == v
    # reference: big-endian '>i' split into two big-endian words, no swap
    assert dt.encode("LONG", 0x12345678) == list(
        struct.unpack(">HH", struct.pack(">i", 0x12345678)))


def test_long_out_of_range_raises():
    with pytest.raises((struct.error, OverflowError, ValueError)):
        dt.encode("LONG", 5_000_000_000)


def test_float_roundtrip():
    for v in (0.0, 1.5, -3.25, 3.14159, 1e6, -1e-3):
        regs = dt.encode("FLOAT", v)
        assert len(regs) == 2
        assert abs(dt.decode("FLOAT", regs) - v) < abs(v) * 1e-6 + 1e-6


def test_read_count():
    assert dt.read_count("SHORT") == 1
    assert dt.read_count("LONG") == 2
    assert dt.read_count("FLOAT") == 2


def test_area_flags():
    for area in ("MEMORY_AREA", "UNUSED_AREA"):
        assert dt.is_area(area)
        assert not dt.should_poll(area)
        assert not dt.is_scalar(area)
    for scalar in ("SHORT", "LONG", "FLOAT"):
        assert not dt.is_area(scalar)
        assert dt.should_poll(scalar)
        assert dt.is_scalar(scalar)


def test_read_to_str():
    assert dt.read_to_str("SHORT", [0xFFFF]) == "-1"
    assert "?" in dt.read_to_str("MEMORY_AREA", [1, 2])


def test_addr_span():
    assert dt.addr_span({"type": "SHORT"}) == 1
    assert dt.addr_span({"type": "FLOAT"}) == 2
    assert dt.addr_span({"type": "MEMORY_AREA", "length": 16}) == 16
    assert dt.addr_span({"type": "MEMORY_AREA", "length": "junk"}) == 1
