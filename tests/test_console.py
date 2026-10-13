"""Raw-frame console: hex parsing, CRC, row sync, sending, history, core raw op."""
import pytest

from app_context import AppContext
from settings_manager import DEFAULT_SETTINGS
from gui_console import RawConsole, parse_hex, crc16, fmt_hex
from modbus_core import ModbusCore


# ── pure helpers ──────────────────────────────────────────────────
def test_parse_hex_forms():
    assert parse_hex("0A 03 00 10") == b"\x0a\x03\x00\x10"
    assert parse_hex("0a030010") == b"\x0a\x03\x00\x10"
    assert parse_hex("0x0A, 0x03") == b"\x0a\x03"
    assert parse_hex("  ") is None
    assert parse_hex("0A 3") is None          # odd nibble count
    assert parse_hex("ZZ") is None


def test_crc16_matches_core_implementation():
    """The console CRC must be byte-identical to the core's frame-log CRC."""
    for frame in (b"\x01\x03\x00\x00\x00\x01", b"\x0a\x06\x00\x10\x00\x05", b"\xff"):
        assert crc16(frame) == ModbusCore._crc16(frame)


def test_fmt_hex():
    assert fmt_hex(b"\x0a\x03\xff") == "0A 03 FF"


# ── widget behavior ───────────────────────────────────────────────
@pytest.fixture()
def console():
    ctx = AppContext(dict(DEFAULT_SETTINGS))
    ctx.settings["console_history"] = []
    return RawConsole(ctx)


def test_packet_follows_command(console):
    console.edit_cmd.setText("0A 03 00 10 00 02")
    console._on_cmd_edited()
    crc = crc16(b"\x0a\x03\x00\x10\x00\x02")
    assert console.lbl_crc.text() == f"CRC: {fmt_hex(crc)}"
    assert console.edit_pkt.text() == "0A 03 00 10 00 02 " + fmt_hex(crc)
    assert not console.lbl_edited.isVisibleTo(console)


def test_invalid_command_clears_packet(console):
    console.edit_cmd.setText("garbage!")
    console._on_cmd_edited()
    assert console.lbl_crc.text() == "CRC: —"
    assert console.edit_pkt.text() == ""


def test_manual_packet_edit_marks_and_resyncs(console):
    console.edit_cmd.setText("0A 03")
    console._on_cmd_edited()
    console.edit_pkt.setText("DE AD BE EF")       # user tweaks the wire packet
    console._on_pkt_edited()
    assert console.lbl_edited.isVisibleTo(console)
    console.edit_cmd.setText("0A 04")             # touching the command resyncs
    console._on_cmd_edited()
    assert not console.lbl_edited.isVisibleTo(console)
    assert console.edit_pkt.text().startswith("0A 04")


def test_send_emits_packet_bytes(console):
    sent = []
    console.send_requested.connect(sent.append)
    console.edit_cmd.setText("0A 03 00 10 00 02")
    console._on_cmd_edited()
    console._send()
    expected = b"\x0a\x03\x00\x10\x00\x02" + crc16(b"\x0a\x03\x00\x10\x00\x02")
    assert sent == [expected]
    # manual (garbage) packet is sent verbatim — that's the point
    console.edit_pkt.setText("DE AD")
    console._on_pkt_edited()
    console._send()
    assert sent[-1] == b"\xde\xad"


def test_send_invalid_packet_refused(console):
    sent = []
    console.send_requested.connect(sent.append)
    console.edit_pkt.setText("not hex")
    console._send()
    assert sent == []


def test_history_recall(console):
    for cmd in ("01 03", "02 03"):
        console.edit_cmd.setText(cmd)
        console._on_cmd_edited()
        console._send()
    assert console.ctx.settings["console_history"] == ["01 03", "02 03"]
    console._recall(-1)
    assert console.edit_cmd.text() == "02 03"
    console._recall(-1)
    assert console.edit_cmd.text() == "01 03"
    console._recall(+1); console._recall(+1)
    assert console.edit_cmd.text() == ""          # walked back past the end


# ── core raw execution (fake serial socket) ───────────────────────
class _FakeSock:
    def __init__(self, response=b""):
        self.written = b""
        self._resp = response

    def reset_input_buffer(self):
        pass

    def write(self, data):
        self.written += data

    @property
    def in_waiting(self):
        return len(self._resp)

    def read(self, n):
        out, self._resp = self._resp[:n], self._resp[n:]
        return out


class _FakeClient:
    def __init__(self, sock):
        self.socket = sock


def _collect(core):
    msgs = []
    core.log_msg.connect(lambda lv, m: msgs.append((lv, m)))
    return msgs


def test_execute_raw_logs_tx_rx():
    core = ModbusCore()
    core.timeout = 0.2
    sock = _FakeSock(response=b"\x0a\x03\x04\x00\x01\x00\x02\xaa\xbb")
    core.client = _FakeClient(sock)
    msgs = _collect(core)
    core._execute_raw(b"\x0a\x03\x00\x10\x00\x02\xc5\xc2")
    assert sock.written == b"\x0a\x03\x00\x10\x00\x02\xc5\xc2"
    assert any(lv == "TX" and "0A 03 00 10" in m for lv, m in msgs)
    assert any(lv == "RX" and "AA BB" in m for lv, m in msgs)


def test_execute_raw_no_response_is_err():
    core = ModbusCore()
    core.timeout = 0.1
    core.client = _FakeClient(_FakeSock(response=b""))
    msgs = _collect(core)
    core._execute_raw(b"\xde\xad")
    assert any(lv == "ERR" and "нет ответа" in m for lv, m in msgs)


def test_execute_raw_without_socket_is_err():
    core = ModbusCore()
    core.client = None
    msgs = _collect(core)
    core._execute_raw(b"\x01")
    assert any(lv == "ERR" for lv, m in msgs)
