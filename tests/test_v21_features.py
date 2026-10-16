"""v2.1: new data types, line statistics, watch window, app icon, slave mode."""
import copy
import os
import struct
import time

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QMenu

import byteorder
import datatypes as dt
import linestats
import settings_manager
import slave_core as sc
from app_context import AppContext
from settings_manager import DEFAULT_SETTINGS


def _ctx(**over):
    s = copy.deepcopy(DEFAULT_SETTINGS)
    s.update(over)
    return AppContext(s)


@pytest.fixture(autouse=True)
def default_orders():
    """Codec order is module state; every test starts from the defaults."""
    dt.configure_orders({})
    yield
    dt.configure_orders({})


# ═══════════════ data types ═══════════════
def test_uint16_reads_above_32767_as_positive():
    assert dt.decode("UINT16", [0xFFFF]) == 65535
    assert dt.decode("SHORT", [0xFFFF]) == -1            # the signed one is untouched
    assert dt.encode("UINT16", "40000") == [40000]
    with pytest.raises(ValueError):
        dt.encode("UINT16", "70000")
    with pytest.raises(ValueError):
        dt.encode("UINT16", "-1")


@pytest.mark.parametrize("order", byteorder.ORDERS_32)
@pytest.mark.parametrize("key,values", [
    ("UINT32", (0, 1, 65536, 4_000_000_000, 0xFFFFFFFF)),
    ("INT64", (0, -1, 2 ** 53 + 1, -(2 ** 63), 2 ** 63 - 1)),
    ("BCD32", (0, 12345678, 99999999)),
])
def test_32_and_64_bit_integers_round_trip_exactly(order, key, values):
    dt.configure_orders({"order_long": order})
    for v in values:
        assert dt.decode(key, dt.encode(key, str(v))) == v


@pytest.mark.parametrize("order", byteorder.ORDERS_32)
def test_double_round_trips(order):
    dt.configure_orders({"order_float": order})
    for v in (0.0, 3.141592653589793, -1e300, 2.5e-310):
        assert dt.decode("DOUBLE", dt.encode("DOUBLE", v)) == v


def test_64_bit_word_orders():
    one = struct.unpack(">4H", struct.pack(">d", 1.0))       # 3FF0 0 0 0
    assert byteorder.encode_f64(1.0, "ABCD") == list(one)
    assert byteorder.encode_f64(1.0, "CDAB") == list(reversed(one))
    assert byteorder.encode_f64(1.0, "BADC")[0] == 0xF03F


def test_bcd():
    assert dt.decode("BCD16", [0x1234]) == 1234
    assert dt.encode("BCD16", 9876) == [0x9876]
    assert dt.read_to_str("BCD16", [0x12AB]) == "???"        # not BCD: said so
    with pytest.raises(ValueError):
        dt.encode("BCD16", 10000)


def test_string_is_padded_to_its_field_and_decoded():
    words = dt.encode("STRING", "Ток", 4)
    assert len(words) == 4 and words[-1] == 0              # NUL padding
    assert dt.read_to_str("STRING", words) == "Ток"
    with pytest.raises(ValueError):
        dt.encode("STRING", "слишком длинно", 2)
    assert dt.reg_read_count({"type": "STRING", "length": 300}) == 125


def test_bits16_opens_in_binary():
    assert dt.default_view("BITS16") == "bin"
    assert dt.read_to_str("BITS16", [0x0012]) == "18"      # numeric for the pipeline


def test_every_new_type_has_editor_hints():
    import i18n
    for key in ("UINT16", "BITS16", "BCD16", "UINT32", "BCD32", "INT64",
                "DOUBLE", "STRING"):
        assert key in dt.ALL_TYPES
        assert f"hint{key}" in i18n.STRINGS["ru"]


def test_the_table_shows_int64_exactly_and_bits_in_binary():
    from gui_table import RegisterTable, COL_CURRENT
    t = RegisterTable(_ctx())
    t.populate([{"addr": 0, "name": "I", "type": "INT64", "rw": "R"},
                {"addr": 4, "name": "B", "type": "BITS16", "rw": "R"}])
    t.update_value(0, "9007199254740993")
    assert t.item(t.addr_to_row[0], COL_CURRENT).text() == "9007199254740993"
    t.update_value(4, "18")
    cell = t.item(t.addr_to_row[4], COL_CURRENT)
    assert cell.text() == "0b0000 0000 0001 0010"
    assert "1, 4" in cell.toolTip()


class _WriteClient:
    def __init__(self):
        self.words = []

    def write_register(self, address, value, **kw):
        self.words.append((address, value))

        class _Ok:
            def isError(self):
                return False
        return _Ok()


def test_core_writes_a_string_over_its_whole_field():
    from modbus_core import ModbusCore
    core = ModbusCore()
    core.client = _WriteClient()
    core.update_profile([{"addr": 0x20, "type": "STRING", "length": 3}])
    assert core._execute_write(0x20, "STRING", "Hi")
    assert [a for a, _ in core.client.words] == [0x20, 0x21, 0x22]
    assert core.client.words[-1][1] == 0                    # old tail cleared


def test_core_writes_int64_without_a_float_round_trip():
    from modbus_core import ModbusCore
    core = ModbusCore()
    core.client = _WriteClient()
    assert core._execute_write(0, "INT64", "9007199254740993")
    words = [w for _, w in core.client.words]
    assert dt.decode("INT64", words) == 9007199254740993


# ═══════════════ line statistics ═══════════════
def test_stats_snapshot_math():
    st = linestats.LineStats()
    st.record("ok", 0.010)
    st.record("ok", 0.030)
    st.record("exception", 0.020)
    st.record("timeout")
    st.record("crc")
    s = st.snapshot()
    assert (s["requests"], s["responses"], s["timeouts"], s["crc"],
            s["exceptions"], s["errors"]) == (5, 3, 1, 1, 1, 3)
    assert s["rt_avg"] == pytest.approx(20.0)
    assert (s["rt_min"], s["rt_max"]) == (pytest.approx(10.0), pytest.approx(30.0))
    assert s["quality"] == pytest.approx(60.0)
    st.reset()
    assert st.snapshot()["requests"] == 0


def test_the_crc_probe_tells_noise_from_silence():
    import sniffer_core
    import transports
    client = transports.get("serial").create({"port": "COM99"}, 0.5)
    st = linestats.LineStats()
    assert linestats.install_crc_probe(client, st)
    body = bytes([10, 3, 2, 0, 7])
    crc = sniffer_core.crc16(body)
    st.begin()
    client.framer.decode(body + bytes([crc & 0xFF, crc >> 8]))
    assert st.crc_flag is False
    st.begin()
    client.framer.decode(body + b"\x00\x00")
    assert st.crc_flag is True
    st.begin()
    client.framer.decode(body[:3])                          # partial: not an error
    assert st.crc_flag is False


def test_the_core_counts_every_outcome():
    from modbus_core import ModbusCore

    class _Res:
        def __init__(self, err=False, fc=3):
            self._err, self.function_code, self.registers = err, fc, [5]

        def isError(self):
            return self._err

    class _Client:
        def __init__(self):
            self.results = [_Res(), _Res(True, 0x83), None]

        def read_holding_registers(self, address, count, **kw):
            return self.results.pop(0)

    core = ModbusCore()
    core.client = _Client()
    core._execute_read(1, "SHORT")
    core._execute_read(1, "SHORT")
    core._execute_read(1, "SHORT")
    s = core.stats.snapshot()
    assert (s["requests"], s["ok"], s["exceptions"], s["timeouts"]) == (3, 1, 1, 1)


def test_status_bar_chip_and_card():
    from gui_statusbar import MainStatusBar
    sb = MainStatusBar()
    st = linestats.LineStats()
    st.record("ok", 0.012)
    st.record("timeout")
    t = _ctx().t
    sb.stats_popup.retranslate(t)
    sb.set_line_stats(st.snapshot(), t)
    assert sb.stats_chip._vals["tx"].text() == "2"
    assert sb.stats_chip._vals["err"].property("state") == "error"
    sb.stats_popup.set_stats(st.snapshot())
    assert sb.stats_popup._vals["timeouts"].text() == "1"
    sb.set_error_count(3)
    assert "3" in sb.btn_log.text()


# ═══════════════ watch window ═══════════════
REGS = [{"addr": 0x10, "name": "Температура", "type": "FLOAT", "rw": "R"},
        {"addr": 0x12, "name": "Уставка", "type": "SHORT", "rw": "RW"}]


@pytest.fixture()
def watch():
    from gui_watch import WatchWindow
    ctx = _ctx()
    w = WatchWindow(ctx, lambda: REGS)
    yield w
    w.deleteLater()


def test_watch_list_is_persisted_in_order(watch):
    watch.add(0x12)
    watch.add(0x10)
    watch.add(0x12)                                         # no duplicates
    assert watch.ctx.settings["watch_list"] == [0x12, 0x10]
    assert watch.toggle(0x12) is False
    assert watch.ctx.settings["watch_list"] == [0x10]


def test_watch_tracks_value_min_max(watch):
    watch.add(0x10)
    for v in (21.5, 19.0, 25.25):
        watch.on_value(0x10, f"{v:.2f}", v)
    row = watch.row_widget(0)
    assert row.lbl_value.text() == "25.25"
    meta = row.lbl_meta.text()
    assert "0x0010" in meta and "19" in meta and "25.25" in meta


def test_a_watched_address_missing_from_the_map_says_so(watch):
    watch.add(0x99)
    assert watch.row_widget(0).lbl_name.text() == watch.ctx.t("watchNotInMap")


def test_writing_from_the_watch_window(watch):
    watch.add(0x12)
    sent = []
    watch.write_requested.connect(lambda a, v: sent.append((a, v)))
    row = watch.row_widget(0)
    row.ed_write.setText("42")
    row.ed_write.returnPressed.emit()
    assert sent == [(0x12, "42")] and row.ed_write.text() == ""
    watch.add(0x10)                                         # read-only: no field
    assert watch.row_widget(1).ed_write.isHidden()


def test_watch_window_has_its_own_chrome(watch):
    """The native title bar was a white strip over a dark app."""
    from PyQt6.QtCore import Qt as _Qt
    assert watch.windowFlags() & _Qt.WindowType.FramelessWindowHint
    assert watch.btn_close is not None and watch.grip is not None


@pytest.fixture()
def win(tmp_path, monkeypatch):
    import gui_main
    monkeypatch.setattr(settings_manager, "SETTINGS_FILE",
                        str(tmp_path / "settings.json"), raising=False)
    w = gui_main.ModernScadaApp()
    w.profile_data = [dict(r) for r in REGS]
    w.register_table.populate(w.profile_data)
    yield w
    w.slave_view.stop_if_running()
    w.watch_window.hide()
    w.deleteLater()


def test_table_menu_adds_to_watch_and_values_flow(win, monkeypatch):
    from gui_table import COL_NAME
    labels = []
    monkeypatch.setattr(QMenu, "exec", lambda self, *a: labels.append(
        [x.text() for x in self.actions()]))
    rt = win.register_table
    rect = rt.visualItemRect(rt.item(rt.addr_to_row[0x10], COL_NAME))
    rt._show_context_menu(rect.center())
    assert win.t("watchAddTo") in labels[0]
    rt.watch_toggle_requested.emit(0x10)
    assert 0x10 in win.watch_window.watched()
    assert win.watch_window.isVisible()
    rt.update_value(0x10, "21.50")
    from gui_table import COL_CURRENT
    shown = rt.item(rt.addr_to_row[0x10], COL_CURRENT).text()
    # The watch window shows exactly what the table shows.
    assert win.watch_window.row_widget(0).lbl_value.text() == shown == "21.5"


def test_dashboard_widget_can_be_watched(win):
    win.dash_view.watch_requested.emit(0x12)
    assert 0x12 in win.watch_window.watched()


# ═══════════════ app icon ═══════════════
def test_the_app_icon_exists_and_loads():
    import icons
    for name in ("app.png", "app.ico"):
        assert os.path.exists(icons.asset_path(name)), name
    data = open(icons.asset_path("app.ico"), "rb").read()
    assert struct.unpack("<HHH", data[:6])[:2] == (0, 1)     # an ICO header
    assert not icons.app_icon().isNull()


# ═══════════════ slave mode ═══════════════
SLAVE_REGS = [
    {"addr": 0, "name": "S", "type": "SHORT", "default": "-5"},
    {"addr": 1, "name": "F", "type": "FLOAT"},
    {"addr": 3, "name": "U", "type": "UINT32"},
    {"addr": 5, "name": "T", "type": "STRING", "length": 2},
    {"addr": 7, "name": "D", "type": "DOUBLE"},
]


def _store():
    return sc.SlaveStore.from_registers(SLAVE_REGS)


def _req(*b):
    return sc.with_crc(bytes(b))


def test_fc03_read_returns_the_stored_words():
    st = _store()
    r = sc.build_response(_req(10, 3, 0, 0, 0, 1), st, 10)
    assert r["kind"] == "read"
    assert r["response"] == sc.with_crc(bytes([10, 3, 2, 0xFF, 0xFB]))   # -5


@pytest.mark.parametrize("req,code", [
    ((10, 3, 0x01, 0x00, 0, 1), sc.ILLEGAL_ADDRESS),        # outside the map
    ((10, 3, 0, 0, 0, 0), sc.ILLEGAL_VALUE),                # count 0
    ((10, 3, 0, 0, 0, 126), sc.ILLEGAL_VALUE),              # count > 125
    ((10, 5, 0, 0, 0xFF, 0), sc.ILLEGAL_ADDRESS),           # no coils in this map
    ((10, 0x08, 0, 0, 0, 0), sc.ILLEGAL_FUNCTION),          # diagnostics: not served
])
def test_exceptions(req, code):
    r = sc.build_response(_req(*req), _store(), 10)
    assert r["exception"] == code
    assert r["response"] == sc.with_crc(bytes([10, req[1] | 0x80, code]))


def test_fc06_echoes_and_fc16_acknowledges():
    st = _store()
    req = _req(10, 6, 0, 0, 0, 42)
    r = sc.build_response(req, st, 10)
    assert r["response"] == req and st.read(0, 1) == [42]
    r = sc.build_response(_req(10, 0x10, 0, 3, 0, 2, 4, 0, 1, 0, 2), st, 10)
    assert r["response"] == sc.with_crc(bytes([10, 0x10, 0, 3, 0, 2]))
    assert st.read(3, 2) == [1, 2]


def test_silence_where_a_real_device_stays_silent():
    st = _store()
    assert sc.build_response(_req(11, 3, 0, 0, 0, 1), st, 10)["response"] is None
    bad = bytearray(_req(10, 3, 0, 0, 0, 1))
    bad[-1] ^= 0xFF
    assert sc.build_response(bytes(bad), st, 10)["reason"] == "crc"
    r = sc.build_response(_req(0, 6, 0, 0, 0, 9), st, 10)   # broadcast write
    assert r["response"] is None and st.read(0, 1) == [9]


@pytest.mark.parametrize("order_float", byteorder.ORDERS_32)
def test_master_reads_exactly_what_the_slave_serves(order_float):
    """End to end without a port: ModbusCore polls through a client that
    hands its requests to build_response(). Same codecs on both sides."""
    from modbus_core import ModbusCore
    dt.configure_orders({"order_float": order_float})
    st = _store()
    values = {"S": "-5", "F": "21.5", "U": "4000000000", "T": "OK",
              "D": "-123.456"}
    for reg in SLAVE_REGS:
        st.set_value(reg, values[reg["name"]])

    class _Loop:
        def read_holding_registers(self, address, count, **kw):
            resp = sc.build_response(_req(10, 3, address >> 8, address & 0xFF,
                                          count >> 8, count & 0xFF), st, 10)["response"]
            words = [int.from_bytes(resp[3 + 2 * i:5 + 2 * i], "big")
                     for i in range(count)]

            class _R:
                registers = words

                def isError(self):
                    return False
            return _R()

    core = ModbusCore()
    core.client = _Loop()
    core.update_profile(SLAVE_REGS)
    got = {}
    core.data_updated.connect(lambda a, v: got.__setitem__(a, v))
    for reg in SLAVE_REGS:
        core._execute_read(reg["addr"], reg["type"], dt.reg_read_count(reg))
    assert got == {0: "-5", 1: "21.50", 3: "4000000000", 5: "OK",
                   7: "-123.456"}


class _FakePort:
    def __init__(self, chunks):
        self.chunks = list(chunks)
        self.written = []

    def read(self, _n):
        return self.chunks.pop(0) if self.chunks else b""

    def write(self, data):
        self.written.append(bytes(data))

    def close(self):
        pass


def test_the_server_answers_over_a_fake_port(monkeypatch):
    import sys
    import types
    port = _FakePort([_req(10, 3, 0, 0, 0, 1), b"", b"", _req(11, 3, 0, 0, 0, 1)])
    mod = types.ModuleType("serial")
    mod.Serial = lambda *a, **k: port
    monkeypatch.setitem(sys.modules, "serial", mod)
    srv = sc.SlaveServer("COM_T", 115200, _store(), 10)    # t3.5 = 1.75 ms
    seen = []
    srv.exchange.connect(seen.append)
    reads = {"n": 0}
    real = port.read

    def read(n):
        reads["n"] += 1
        if reads["n"] > 40:
            srv.request_stop()
        time.sleep(0.003)            # real line time, so the silence gap passes
        return real(n)
    port.read = read
    srv.run()
    assert port.written == [sc.with_crc(bytes([10, 3, 2, 0xFF, 0xFB]))]
    assert [i["kind"] for i in seen] == ["read", "ignored"]


def test_master_refuses_the_port_the_emulator_serves(win, monkeypatch):
    import gui_main
    told = []
    monkeypatch.setattr(gui_main, "themed_info", lambda *a, **k: told.append(a[3]))
    monkeypatch.setattr(win.slave_view, "serving_port",
                        lambda: str(win.settings.get("port", "")).lower())
    win._toggle_connection()
    assert told == [win.t("slvBusyTitle")]
    assert not win.modbus_core.isRunning()


def test_the_slave_view_serves_the_open_map(win):
    win._set_profile([dict(r) for r in SLAVE_REGS], "")
    sv = win.slave_view
    assert sv.table.rowCount() == len(SLAVE_REGS)
    from gui_slave import COL_VALUE
    assert sv.table.item(0, COL_VALUE).text() == "-5"       # the map's default
    sv.table.item(1, COL_VALUE).setText("12.5")             # typed by the user
    assert sv.store.get_value(SLAVE_REGS[1]) == "12.50"
    sv.table.item(1, COL_VALUE).setText("nonsense")
    assert sv.lbl_status.property("state") == "error"
