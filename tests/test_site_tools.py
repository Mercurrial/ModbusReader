"""The online tools of the project site (docs/javascripts/tools.js) must
compute what the app computes: the CRC of core.sniffer_core and the byte
orders of core.byteorder — a converter that disagreed with the app would
teach people the wrong layout. The JavaScript runs in Node; without Node the
tests are skipped (CI runners have it)."""
import json
import os
import shutil
import subprocess

import pytest

from core import byteorder as b
from core.sniffer_core import crc16

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(ROOT, "docs", "javascripts", "tools.js")
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js is not installed")


def _js(expr_body: str, data) -> object:
    """Run ``expr_body`` with ``T`` = the tools module and ``D`` = *data*;
    it must ``return`` something JSON-serialisable."""
    script = ("const T = require(%s); const D = JSON.parse(process.argv[1]);"
              "const r = (() => { %s })();"
              "process.stdout.write(JSON.stringify(r, (k, v) => typeof v === 'bigint' ? v.toString() : v));"
              % (json.dumps(TOOLS), expr_body))
    out = subprocess.run([NODE, "-e", script, json.dumps(data)], capture_output=True,
                         text=True, timeout=60, check=True)
    return json.loads(out.stdout)


def test_crc_matches_the_app():
    frames = [bytes(range(n)) for n in (1, 2, 6, 11, 40)]
    frames += [bytes([1, 3, 0, 0, 0, 2]), bytes([1, 0x83, 2]), bytes([10, 3, 0, 0x10, 0, 2])]
    got = _js("return D.map(f => T.crc16(f));", [list(f) for f in frames])
    assert got == [crc16(f) for f in frames]
    # the textbook frame, and a frame recognised as carrying a valid CRC
    assert _js("return T.hex(T.withCrc(T.parseHex(D)));", "01 03 00 00 00 02") \
        == "01 03 00 00 00 02 C4 0B"
    assert _js("return [T.crcOk(T.parseHex(D[0])), T.crcOk(T.parseHex(D[1]))];",
               ["01 03 00 00 00 02 C4 0B", "01 03 00 00 00 02 C4 0C"]) == [True, False]


@pytest.mark.parametrize("js_type, values, enc, orders", [
    ("FLOAT", [24.6, -775.25, 0.0, 1e-38, 123456.789], b.encode_f32, b.ORDERS_32),
    ("INT32", [0, 1, -1, 2147483647, -2147483648, 123456789], b.encode_i32, b.ORDERS_32),
    ("UINT32", [0, 4294967295, 3000000000], b.encode_u32, b.ORDERS_32),
    ("DOUBLE", [3.141592653589793, -2.5e100], b.encode_f64, b.ORDERS_32),
    ("INT64", [9007199254740993, -9223372036854775808], b.encode_i64, b.ORDERS_32),
    ("INT16", [-1, -32768, 32767, 1234], lambda v, o: [b.encode_i16(v, o)], b.ORDERS_16),
    ("UINT16", [65535, 4660], lambda v, o: [b.encode_u16(v, o)], b.ORDERS_16),
])
def test_value_to_registers_matches_the_app(js_type, values, enc, orders):
    got = _js("return D.values.map(v => T.encode(D.type, v));",
              {"type": js_type, "values": [str(v) for v in values]})
    want = [{o: list(enc(v, o)) for o in orders} for v in values]
    assert got == want


def test_registers_to_value_round_trip():
    # The reverse direction: the words the app would send, read back in the
    # same order, give the value; FLOAT shows seven significant digits.
    words = b.encode_f32(24.6, "CDAB")
    got = _js("return T.decodeWords('FLOAT', D);", words)
    assert got["CDAB"] == 24.6
    assert got["ABCD"] != 24.6
    words = b.encode_i32(-123456, "BADC")
    assert _js("return T.decodeWords('INT32', D);", words)["BADC"] == -123456
    assert _js("return T.parseWords(D[0], 'hex').concat(T.parseWords(D[1], 'dec'));",
               ["41C4 0xCCCD", "16836 52429"]) == [0x41C4, 0xCCCD, 16836, 52429]


def test_address_conversions():
    got = _js("return D.map(s => T.fromModicon(s));",
              ["40001", "40010", "30001", "10001", "400001", "465536", "00005", "20001"])
    assert got == [{"table": "holding", "offset": 0}, {"table": "holding", "offset": 9},
                   {"table": "input", "offset": 0}, {"table": "discrete", "offset": 0},
                   {"table": "holding", "offset": 0}, {"table": "holding", "offset": 65535},
                   {"table": "coil", "offset": 4}, None]
    assert _js("return [T.toModicon('holding', 0), T.toModicon('input', 15000)];", None) == [
        {"five": "40001", "six": "400001"}, {"five": None, "six": "315001"}]
    assert _js("return D.map(s => T.parseOffset(s));",
               ["0x10", "10h", "16", "$1F", "70000", "zz"]) == [16, 16, 16, 31, None, None]


def test_frame_decoder_names_the_parts():
    fields = dict(_js("return T.decode(T.parseHex(D));", "01 03 04 41 C4 CC CD"))
    assert fields["kind"] == "response" and fields["registers"] == "41C4 CCCD"
    fields = dict(_js("return T.decode(T.parseHex(D));", "01 83 02"))
    assert fields["exception"].startswith("2 ")


def test_frame_decoder_tells_rtu_from_modbus_tcp():
    """The CRC tool recognises a Modbus TCP frame by its MBAP header — and a
    valid trailing CRC still wins: the textbook RTU request also looks like
    an MBAP header."""
    got = _js("return D.map(f => { const r = T.classify(T.parseHex(f));"
              " return [r.kind, Object.fromEntries(r.fields)]; });",
              ["00 01 00 00 00 06 00 03 00 00 00 02", "00 01 00 00 00 07 01 03 04 41 C4 CC CD",
               "01 03 00 00 00 02 C4 0B", "01 03 00 00 00 02"])
    (k1, f1), (k2, f2), (k3, f3), (k4, f4) = got
    assert k1 == "tcp" and f1["unit"] == "0" and f1["count"] == "2" and f1["length"] == "6"
    assert k2 == "tcp" and f2["registers"] == "41C4 CCCD" and f2["kind"] == "response"
    assert k3 == "rtu" and f3["slave"] == "1"
    assert k4 == "raw" and f4["count"] == "2"
