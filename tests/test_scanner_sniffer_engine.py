"""Scanner and sniffer logic, driven by a fake core and a fake serial port.

Both features touch real hardware, which the user cannot exercise while
developing, so everything below the Qt layer is pinned here instead.
"""
import struct

import pytest
from PyQt6.QtWidgets import QApplication

import sniffer_core as sc
from scanner_engine import ScannerWorker


# ═══════════════ sniffer: CRC + framing ═══════════════
def _frame(payload: bytes) -> bytes:
    """Append a correct Modbus CRC (little-endian, as on the wire)."""
    crc = sc.crc16(payload)
    return payload + struct.pack("<H", crc)


def test_crc16_matches_the_known_modbus_vector():
    # The canonical "01 04 02 FF FF" -> B8 80 example from the RTU spec notes.
    assert sc.crc16(b"\x01\x04\x02\xff\xff") == 0x80B8


def test_frame_crc_ok_accepts_good_and_rejects_tampered():
    good = _frame(b"\x01\x03\x00\x10\x00\x02")
    assert sc.frame_crc_ok(good)
    bad = bytearray(good)
    bad[3] ^= 0xFF
    assert not sc.frame_crc_ok(bytes(bad))
    assert not sc.frame_crc_ok(b"\x01\x03")          # too short to hold a CRC


def test_carve_splits_back_to_back_frames():
    """A busy line hands over several frames in one chunk; timing alone cannot
    separate them, so CRC does."""
    a = _frame(b"\x01\x03\x00\x10\x00\x02")
    b = _frame(b"\x01\x03\x04\x00\x0a\x00\x0b")
    c = _frame(b"\x02\x06\x00\x01\x00\xff")
    assert sc.carve_frames(a + b + c) == [a, b, c]


def test_carve_returns_junk_unchanged():
    junk = b"\x11\x22\x33\x44\x55"
    assert sc.carve_frames(junk) == [junk]


def test_carve_keeps_a_trailing_partial_frame():
    a = _frame(b"\x01\x03\x00\x10\x00\x02")
    tail = b"\x01\x03\x00"                    # cut off mid-transmission
    out = sc.carve_frames(a + tail)
    assert out[0] == a and out[-1] == tail    # nothing silently dropped


def test_carve_of_one_clean_frame_is_a_no_op():
    a = _frame(b"\x01\x03\x00\x10\x00\x02")
    assert sc.carve_frames(a) == [a]


# ═══════════════ sniffer: decoding ═══════════════
def test_decode_read_request_and_response():
    req = sc.decode_frame(_frame(b"\x01\x03\x00\x10\x00\x02"))
    assert req["kind"] == "request" and req["slave"] == 1 and req["crc_ok"]
    assert "0x0010" in req["describe"]

    resp = sc.decode_frame(_frame(b"\x01\x03\x04\x00\x0a\x00\x0b"))
    assert resp["kind"] == "response" and resp["crc_ok"]
    assert "000A" in resp["describe"] and "000B" in resp["describe"]


def test_decode_exception_response():
    f = sc.decode_frame(_frame(b"\x01\x83\x02"))
    assert f["kind"] == "exception"
    assert f["describe_key"] == "snifException"
    assert f["describe_args"]["code"] == "0x02"


def test_decode_write_single_register_echo():
    f = sc.decode_frame(_frame(b"\x01\x06\x00\x01\x00\x64"))
    assert f["kind"] == "req/resp" and "100" in f["describe"]


def test_decode_write_multiple_directions():
    """FC 0x10: the 8-byte form is the ECHO (response); the long form with a
    byte count is the request."""
    resp = sc.decode_frame(_frame(b"\x01\x10\x00\x10\x00\x02"))
    assert resp["kind"] == "response"
    req = sc.decode_frame(_frame(b"\x01\x10\x00\x10\x00\x02\x04\x00\x0a\x00\x0b"))
    assert req["kind"] == "request"


def test_decode_short_frame_is_junk_not_a_crash():
    f = sc.decode_frame(b"\x01\x03")
    assert f["kind"] == "junk" and f["describe_key"] == "snifShortFrame"


def test_decode_never_omits_the_fields_the_table_reads():
    """The view indexes these for every row; a missing key would be a KeyError
    in the middle of a live capture."""
    for raw in (b"", b"\x01", b"\x01\x03", _frame(b"\x01\x03\x00\x10\x00\x02"),
                _frame(b"\x01\x99\x00"), b"\xff" * 9):
        f = sc.decode_frame(raw)
        for key in ("raw", "hex", "slave", "fc", "crc_ok", "kind"):
            assert key in f, (raw, key)
        assert f.get("describe") or f.get("describe_key") or f.get("hex") == ""


def test_decoder_emits_no_language_specific_prose():
    """The worker must stay language-free: verbal notes travel as i18n keys."""
    import i18n
    for raw in (b"\x01\x03", _frame(b"\x01\x83\x02"), _frame(b"\x01\x99\x00\x01")):
        f = sc.decode_frame(raw)
        key = f.get("describe_key")
        if key:
            assert key in i18n.STRINGS["ru"] and key in i18n.STRINGS["en"]


# ═══════════════ sniffer worker with a fake port ═══════════════
class _FakeSerial:
    def __init__(self, chunks, fail_after=None):
        self._chunks = list(chunks)
        self._fail_after = fail_after
        self._reads = 0
        self.closed = False
        self.written = []
        self.flushed = 0

    def read(self, _n):
        self._reads += 1
        if self._fail_after is not None and self._reads > self._fail_after:
            raise OSError("device disconnected")
        return self._chunks.pop(0) if self._chunks else b""

    def write(self, data):                 # a passive tap must never call this
        self.written.append(data)

    def flush(self):
        self.flushed += 1

    def close(self):
        self.closed = True


def _run_worker(monkeypatch, chunks, fail_after=None, stop_after=40):
    import sys
    import types
    fake = _FakeSerial(chunks, fail_after)
    mod = types.ModuleType("serial")
    mod.Serial = lambda *a, **k: fake
    monkeypatch.setitem(sys.modules, "serial", mod)

    w = sc.SnifferWorker("COM_TEST", 9600)
    frames, errors = [], []
    w.frame_captured.connect(frames.append)
    w.error.connect(errors.append)
    # Drive run() on THIS thread: deterministic, no scheduler in the way.
    reads = {"n": 0}
    real_read = fake.read

    def counting_read(n):
        reads["n"] += 1
        if reads["n"] >= stop_after:
            w.request_stop()
        return real_read(n)
    fake.read = counting_read
    w.run()
    return frames, errors, fake


def test_worker_emits_each_frame_from_a_merged_chunk(monkeypatch):
    a = _frame(b"\x01\x03\x00\x10\x00\x02")
    b = _frame(b"\x01\x03\x04\x00\x0a\x00\x0b")
    frames, errors, fake = _run_worker(monkeypatch, [a + b])
    assert [bytes(f["raw"]) for f in frames] == [a, b]
    assert errors == [] and fake.closed


def test_worker_reports_a_disconnect_instead_of_dying(monkeypatch):
    a = _frame(b"\x01\x03\x00\x10\x00\x02")
    frames, errors, fake = _run_worker(monkeypatch, [a], fail_after=1)
    assert errors and errors[0][0] == "snifReadFail"
    assert fake.closed                        # port still released
    assert [bytes(f["raw"]) for f in frames] == [a]   # buffered data not lost


def test_worker_reports_a_port_that_will_not_open(monkeypatch):
    import sys
    import types
    mod = types.ModuleType("serial")

    def boom(*a, **k):
        raise OSError("access denied")
    mod.Serial = boom
    monkeypatch.setitem(sys.modules, "serial", mod)
    w = sc.SnifferWorker("COM_BUSY", 9600)
    errors, stopped = [], []
    w.error.connect(errors.append)
    w.stopped.connect(lambda: stopped.append(1))
    w.run()
    assert errors[0][0] == "snifPortFail" and stopped == [1]


def test_worker_never_transmits(monkeypatch):
    """A passive tap that writes would corrupt the very line it observes. The
    fake port records writes, so this fails loudly if that ever changes."""
    a = _frame(b"\x01\x03\x00\x10\x00\x02")
    b = _frame(b"\x01\x06\x00\x01\x00\x64")
    _, _, fake = _run_worker(monkeypatch, [a, b])
    assert fake.written == [] and fake.flushed == 0


# ═══════════════ scanner ═══════════════
class _FakeCore:
    """Answers request_op the way ModbusCore does, from a scripted map."""

    def __init__(self, alive=(), exceptions=(), values=None, raises=False):
        self.alive = set(alive)
        self.exceptions = set(exceptions)
        self.values = values or {}
        self.raises = raises
        self.calls = []
        self.is_running = True

    def request_op(self, kind, addr, dtype, value=None, timeout=5.0, slave=None):
        self.calls.append((kind, addr, slave))
        if self.raises:
            raise RuntimeError("Modbus не подключён")
        key = slave if kind == "probe" and slave is not None and addr == 0 else addr
        if kind == "probe":
            target = slave if addr == 0 else addr
            if target in self.alive:
                return "alive"
            if target in self.exceptions:
                return "exception"
            return "silent"
        if kind == "read":
            if addr in self.values:
                return self.values[addr]
            raise RuntimeError("no answer")
        return None


def _drain(worker):
    hits, done = [], []
    worker.found.connect(hits.append)
    worker.finished_scan.connect(lambda *a: done.append(a))
    worker.run()
    return hits, done[0]


def test_device_scan_reports_alive_and_exception_as_found():
    """An exception response proves someone decoded the request — the device
    IS there, it just refuses that address."""
    core = _FakeCore(alive={3}, exceptions={7})
    hits, (found, total, _s) = _drain(ScannerWorker(core, "devices", 1, 10))
    assert total == 10 and found == 2
    assert {h["id"]: h["state"] for h in hits} == {3: "alive", 7: "exception"}


def test_device_scan_probes_every_id_in_the_range():
    core = _FakeCore()
    _drain(ScannerWorker(core, "devices", 5, 9))
    assert [c[2] for c in core.calls] == [5, 6, 7, 8, 9]


def test_register_scan_reports_values():
    core = _FakeCore(alive={0x10, 0x12}, values={0x10: 111, 0x12: 222})
    hits, (found, total, _s) = _drain(
        ScannerWorker(core, "registers", 0x10, 0x13, slave_id=4))
    assert found == 2 and total == 4
    assert {h["addr"]: h["value"] for h in hits} == {0x10: 111, 0x12: 222}
    assert all(c[2] == 4 for c in core.calls)      # scanned the chosen slave


def test_register_scan_survives_a_read_that_fails_after_a_good_probe():
    core = _FakeCore(alive={0x20})                 # probe says alive, read raises
    hits, (found, _t, _s) = _drain(ScannerWorker(core, "registers", 0x20, 0x20))
    assert found == 1 and hits[0]["value"] is None


def test_stop_request_ends_the_scan_early():
    core = _FakeCore()
    w = ScannerWorker(core, "devices", 1, 247)
    seen = []

    def on_progress(done, _total):
        seen.append(done)
        if done == 3:
            w.request_stop()
    w.progress.connect(on_progress)
    w.run()
    assert max(seen) <= 4                          # stopped, did not run to 247


def test_disconnect_mid_scan_is_reported_not_raised():
    core = _FakeCore(raises=True)
    w = ScannerWorker(core, "devices", 1, 5)
    errors, done = [], []
    w.error.connect(errors.append)
    w.finished_scan.connect(lambda *a: done.append(a))
    w.run()
    assert errors and done, "must still report completion so the UI unlocks"


def test_progress_reaches_the_total():
    core = _FakeCore()
    w = ScannerWorker(core, "devices", 1, 6)
    seen = []
    w.progress.connect(lambda d, t: seen.append((d, t)))
    w.run()
    assert seen[-1] == (6, 6)
