"""The TCP surfaces of the window: the connection card, the header chip,
the settings page, the console, the network scanner, the TCP emulator —
and the whole path an operator can try with no hardware at all: the
emulator serves Modbus TCP on 127.0.0.1, the master connects to it.

Servers listen on 127.0.0.1 only (a LAN listener would raise Windows'
firewall prompt in the middle of a test run)."""
import copy
import socket
import time

import pytest
from PyQt6.QtWidgets import QApplication

from app import settings_manager
from app.app_context import AppContext
from app.settings_manager import DEFAULT_SETTINGS
from core import linktest
from core import slave_core as sc

HOST = "127.0.0.1"
REGS = [{"addr": 0x10, "name": "Setpoint", "type": "SHORT", "rw": "RW", "default": "1234"},
        {"addr": 0x11, "name": "Mode", "type": "SHORT", "rw": "RW", "default": "7"}]


def _ctx(**over):
    s = copy.deepcopy(DEFAULT_SETTINGS)
    s.update(over)
    return AppContext(s)


def _pump(seconds=0.0):
    end = time.monotonic() + seconds
    while True:
        QApplication.processEvents()
        if time.monotonic() >= end:
            break
        time.sleep(0.01)


def _wait(cond, timeout=8.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        QApplication.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return cond()


def _free_port() -> int:
    s = socket.socket()
    s.bind((HOST, 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
def server():
    srv = sc.SlaveTcpServer(HOST, 0, sc.SlaveStore.from_registers(REGS), 1)
    srv.start()
    assert srv.listening.wait(5)
    yield srv
    srv.request_stop()
    assert srv.wait(5000)


@pytest.fixture
def card():
    from gui.connection import ConnectionCard
    from PyQt6.QtWidgets import QWidget
    host = QWidget()
    host.resize(900, 600)
    ctx = _ctx()
    c = ConnectionCard(ctx, lambda: REGS, host)
    yield c
    c.hide()
    host.deleteLater()


@pytest.fixture
def win(tmp_path, monkeypatch):
    from gui import main_window as gui_main
    monkeypatch.setattr(settings_manager, "SETTINGS_FILE",
                        str(tmp_path / "settings.json"), raising=False)
    w = gui_main.ModernScadaApp()
    w.profile_data = [dict(r) for r in REGS]
    w.register_table.populate(w.profile_data)
    yield w
    w.conn_card.hide()
    core = w.modbus_core
    if core.isRunning():
        core.stop()
        core.wait(5000)
    w.slave_view.stop_if_running()
    w.scanner_view.stop_if_running()
    w.watch_window.hide()
    w.deleteLater()


# ── the card ──────────────────────────────────────────────────────────
def test_the_card_shows_the_fields_of_the_chosen_transport(card):
    card.load(dict(card.ctx.settings, transport="serial", port="COM7", slave_id=10))
    card.show()
    _pump()
    assert card.box_serial.isVisible() and not card.box_net.isVisible()
    assert (card.sp_id.minimum(), card.sp_id.maximum()) == (1, 247)
    card.seg.setValue("tcp")
    _pump()
    assert card.box_net.isVisible() and not card.box_serial.isVisible()
    assert (card.sp_id.minimum(), card.sp_id.maximum()) == (0, 255)
    assert card.btn_find.isVisible() and card.lbl_id.text() == card.ctx.t("connUnitId")
    card.seg.setValue("rtu_tcp")
    _pump()
    assert card.box_net.isVisible() and not card.btn_find.isVisible()
    assert card.lbl_net_hint.text() == card.ctx.t("connRtuTcpHint")


def test_the_draft_keeps_the_other_transports_fields(card):
    card.ctx.settings.update({"port": "COM4", "baudrate": "19200", "host": "", "tcp_port": 502})
    card.load(card.ctx.settings)
    card.seg.setValue("tcp")
    card.ed_host.setText(" 10.1.1.5 ")
    card.sp_tcp_port.setValue(1502)
    d = card.draft()
    assert (d["transport"], d["host"], d["tcp_port"]) == ("tcp", "10.1.1.5", 1502)
    assert (d["port"], d["baudrate"]) == ("COM4", "19200")       # untouched
    assert card.changed()


def test_an_empty_host_is_asked_for_not_tried(card):
    card.load(dict(card.ctx.settings, transport="tcp", host=""))
    card.show()
    got = []
    card.connect_requested.connect(got.append)
    card._primary()
    assert not got and card.box_result.isVisible()
    assert card.ed_host.property("state") == "error"
    assert card.lbl_result.text() == card.ctx.t("connNeedHost")


def test_closing_the_card_keeps_the_edited_link(card):
    card.load(card.ctx.settings)
    card.show()
    got = []
    card.committed.connect(got.append)
    card.seg.setValue("tcp")
    card.ed_host.setText("192.168.0.50")
    card.hide()
    assert got and got[0]["host"] == "192.168.0.50" and got[0]["transport"] == "tcp"
    got.clear()
    card.show()
    card.hide()                                     # nothing changed this time
    assert not got


def test_recent_links_fill_the_draft(card):
    card.ctx.settings["recent_links"] = [
        {"transport": "tcp", "host": "10.0.0.9", "tcp_port": 502, "slave_id": 255}]
    card.load(card.ctx.settings)
    btn = card._recent_btns[0]
    assert not btn.isHidden() and "10.0.0.9" in btn.text()
    btn.click()
    d = card.draft()
    assert (d["transport"], d["host"], d["slave_id"]) == ("tcp", "10.0.0.9", 255)


def test_the_test_button_reports_a_live_device(card, server):
    card.load(dict(card.ctx.settings, transport="tcp", host=HOST,
                   tcp_port=server.port, slave_id=1))
    card.show()
    card.run_test()
    assert card._testing and card.btn_test.text() == card.ctx.t("connTesting")
    assert _wait(lambda: not card._testing)
    assert card.box_result.property("state") == "ok"
    assert card.lbl_result.text().startswith(card.ctx.t("connTestOk").split("·")[0])


def test_a_suggested_unit_id_is_one_click_away(card, server):
    card.load(dict(card.ctx.settings, transport="tcp", host=HOST,
                   tcp_port=server.port, slave_id=7, timeout=300))
    card.show()
    card.run_test()
    assert _wait(lambda: not card._testing)
    assert card._suggestion and card._suggestion[0] == "unit"
    unit = card._suggestion[1]
    assert card.btn_suggest.isVisible() and str(unit) in card.btn_suggest.text()
    card.btn_suggest.click()                         # takes it and tests again
    assert card.sp_id.value() == unit
    assert _wait(lambda: not card._testing)
    assert card.box_result.property("state") == "ok"


def test_a_refused_port_is_explained(card):
    card.load(dict(card.ctx.settings, transport="tcp", host=HOST, tcp_port=_free_port()))
    card.show()
    card.run_test()
    assert _wait(lambda: not card._testing, 10)
    assert card.box_result.property("state") == "error"
    why = linktest.why("refused", card.draft(), "", card.ctx.t)
    assert why in card.lbl_result.text()


def test_a_stale_test_result_is_dropped(card):
    card._test_seq = 5
    card._on_test_done((4, linktest.LinkReport("ok", ms=1.0), card.draft(), "holding", 0))
    assert not card.box_result.isVisible()


def test_the_card_height_follows_its_content(card):
    """Wrapped rows are never squeezed: every label gets at least the
    height its text needs at its width."""
    card.load(dict(card.ctx.settings, transport="tcp", host="10.0.0.1"))
    card.show()
    d = card.draft()
    card._test_seq = 1
    card._on_test_done((1, linktest.LinkReport("silent", unit=1, suggest_transport="rtu_tcp"),
                        d, "holding", 0))
    _pump()
    for lb in (card.lbl_net_hint, card.lbl_result, card.lbl_result_more):
        assert lb.height() >= lb.heightForWidth(lb.width()) - 1, lb.objectName()
    tall = card.height()
    card._clear_result()
    assert card.height() < tall


# ── the window ────────────────────────────────────────────────────────
def test_the_chip_opens_the_card_and_shows_the_link(win):
    win.settings.update({"transport": "tcp", "host": "192.168.1.20", "tcp_port": 502,
                         "slave_id": 1})
    win._refresh_link_label()
    assert win.main_toolbar.btn_link.text().strip() == "TCP · 192.168.1.20:502 · ID 1"
    win.settings["host"] = ""
    win._refresh_link_label()
    assert win.t("connNoHost") in win.main_toolbar.btn_link.text()
    win.main_toolbar.link_clicked.emit()
    assert win.conn_card.isVisible()
    win.main_toolbar.link_clicked.emit()
    assert not win.conn_card.isVisible()


def test_connect_without_a_host_opens_the_card(win):
    win.settings.update({"transport": "tcp", "host": ""})
    win.show()
    win._toggle_connection()
    assert win.conn_card.isVisible() and not win.modbus_core.isRunning()


def test_the_status_bar_id_range_follows_the_transport(win):
    win.settings["transport"] = "tcp"
    win._refresh_link_label()
    assert (win.status_bar._slave_ed._lo, win.status_bar._slave_ed._hi) == (0, 255)
    win.settings["transport"] = "serial"
    win._refresh_link_label()
    assert (win.status_bar._slave_ed._lo, win.status_bar._slave_ed._hi) == (1, 247)


def test_a_failed_connect_opens_the_card_with_the_reason(win):
    win.show()
    win.settings.update({"transport": "tcp", "host": HOST, "tcp_port": _free_port()})
    win._toggle_connection()
    assert _wait(lambda: win.conn_card.isVisible(), 12)
    assert win.conn_card.box_result.property("state") == "error"
    assert linktest.why("refused", win.settings, "", win.t) in win.conn_card.lbl_result.text()


def test_the_emulator_and_the_master_in_one_window(win):
    """What the operator can do without any hardware: serve the map over
    Modbus TCP on this PC and connect the master to it."""
    port = _free_port()
    sv = win.slave_view
    sv.reload_map()
    sv.seg_mode.setValue("tcp")
    sv.combo_access.setCurrentIndex(1)               # this PC only
    sv.spin_tcp_port.setValue(port)
    sv.spin_sid.setValue(3)
    sv.toggle()
    assert _wait(lambda: sv._server.listening.is_set(), 5)
    assert sv.serving_port() == ""                   # no COM port is held
    assert f"127.0.0.1:{port}" in sv.lbl_info.text()

    win._connect_with({"transport": "tcp", "host": HOST, "tcp_port": port, "slave_id": 3})
    core = win.modbus_core
    assert _wait(lambda: core.is_running, 8)
    assert core.request_op("read", 0x10, "SHORT", timeout=5) == 1234
    core.request_op("write", 0x11, "SHORT", value="42", timeout=5)
    assert sv.store.read(0x11, 1) == [42]
    assert _wait(lambda: "TCP" in win.main_toolbar.btn_link.text())
    recent = win.settings["recent_links"]
    assert recent[0]["host"] == HOST and recent[0]["tcp_port"] == port
    assert _wait(lambda: len(sv._clients) == 1)
    # the card tests the OPEN link through the core, not a second socket
    card = win.conn_card
    card.open_below(win.main_toolbar.btn_link)
    assert card.btn_primary.text().strip() == win.t("disconnect")
    card.run_test()
    assert _wait(lambda: not card._testing)
    assert card.box_result.property("state") == "ok"
    card.hide()
    core.stop()
    assert core.wait(5000)
    sv.stop_if_running()
    assert not sv.running


def test_the_settings_page_shows_the_fields_of_the_transport():
    from gui.settings import SettingsDialog
    dlg = SettingsDialog(dict(DEFAULT_SETTINGS, transport="tcp", host="10.0.0.2"))
    dlg.show()
    _pump()
    seg = dlg._controls["transport"]
    host = dlg._controls["host"]
    port = dlg._controls["port"]
    assert host.isVisible() and not port.isVisible()
    seg.setValue("serial")
    _pump()
    assert port.isVisible() and not host.isVisible()
    seg.setValue("rtu_tcp")
    dlg._controls["tcp_port"].setText("junk")
    new = dlg.get_new_settings()
    assert new["transport"] == "rtu_tcp" and new["host"] == "10.0.0.2"
    assert new["tcp_port"] == 502                    # garbage falls back
    dlg.deleteLater()


def test_the_console_builds_mbap_over_tcp():
    from gui.console import RawConsole
    ctx = _ctx(transport="tcp")
    c = RawConsole(ctx)
    c.edit_cmd.setText("01 03 00 00 00 02")
    c._on_cmd_edited()
    assert c.edit_pkt.text() == "00 01 00 00 00 06 01 03 00 00 00 02"
    assert c.lbl_crc.text() == "MBAP: 00 01 00 00 00 06"
    sent = []
    c.send_requested.connect(sent.append)
    c._send()
    assert sent == [bytes.fromhex("000100000006010300000002")]
    assert c.edit_pkt.text().startswith("00 02 ")     # the next transaction
    ctx.settings["transport"] = "serial"
    c.sync_transport()
    assert c.lbl_crc.text().startswith("CRC: ") and c.edit_pkt.text().endswith("C4 0B")
    c.deleteLater()


def test_the_core_logs_and_sends_raw_frames_over_tcp(server):
    from core.modbus_core import ModbusCore
    from PyQt6.QtCore import Qt
    core = ModbusCore()
    core.setup_connection({"transport": "tcp", "host": HOST, "tcp_port": server.port,
                           "timeout": 500}, 1)
    lines = []
    core.log_msg.connect(lambda lvl, text: lines.append((lvl, text)),
                         Qt.ConnectionType.DirectConnection)
    core.verbose_addrs = {0x10}
    core.update_profile([dict(REGS[0])])
    core.start()
    try:
        assert _wait(lambda: core.is_running, 8)
        assert _wait(lambda: any(l == "RX" and "04 D2" in t for l, t in lines), 5)
        tx = next(t for l, t in lines if l == "TX")
        assert "00 00 00 06 01 03 00 10 00 01" in tx      # MBAP + PDU, no CRC
        core.queue_raw(bytes.fromhex("0077 0000 0006 01 03 0011 0001"))
        assert _wait(lambda: any("00 77 00 00 00 05 01 03 02 00 07" in t
                                 for l, t in lines if l == "RX"), 5)
    finally:
        core.stop()
        assert core.wait(5000)


def test_the_scanner_network_mode(win):
    sv = win.scanner_view
    sv.show_network_mode()
    _pump()
    assert sv.cb_subnet.isVisibleTo(sv) and sv.spin_net_port.isVisibleTo(sv)
    assert not sv.spin_from.isVisibleTo(sv) and not sv.spin_sid.isVisibleTo(sv)
    custom = sv.cb_subnet.count() - 1
    sv.cb_subnet.setCurrentIndex(custom)
    sv._on_subnet(custom)
    assert sv.ed_ip_from.isVisibleTo(sv) and sv.ed_ip_to.isVisibleTo(sv)
    sv.ed_ip_from.setText("10.0.0.1")
    sv.ed_ip_to.setText("10.0.9.9")                  # too many addresses
    sv._toggle_scan()
    assert sv.lbl_status.property("state") == "error" and sv._worker is None
    sv._on_found({"ip": "192.168.1.20", "port": 502, "state": "modbus", "unit": 255,
                  "exception": 0, "ms": 9.0})
    sv._on_found({"ip": "192.168.1.3", "port": 502, "state": "open", "unit": None,
                  "exception": 0, "ms": 9.0})
    assert [sv.table.item(r, 0).text() for r in range(2)] == ["192.168.1.3", "192.168.1.20"]
    sv._on_row_activated(1, 0)                       # opens the card with that device
    assert win.conn_card.isVisible()
    d = win.conn_card.draft()
    assert (d["transport"], d["host"], d["slave_id"]) == ("tcp", "192.168.1.20", 255)


def test_the_scanner_finds_the_emulator(win, server):
    sv = win.scanner_view
    sv.show_network_mode()
    custom = sv.cb_subnet.count() - 1
    sv.cb_subnet.setCurrentIndex(custom)
    sv._on_subnet(custom)
    sv.ed_ip_from.setText(HOST)
    sv.ed_ip_to.setText(HOST)
    sv.spin_net_port.setValue(server.port)
    sv._toggle_scan()
    assert _wait(lambda: sv._worker is not None and not sv._worker.isRunning()
                 and sv.table.rowCount() == 1, 10)
    assert sv.table.item(0, 0).text() == f"{HOST}:{server.port}"
    assert win.t("scanNetHint") in sv.lbl_status.text()


def test_the_device_sweep_covers_unit_ids_over_tcp(win):
    sv = win.scanner_view
    win.settings["transport"] = "tcp"
    sv.seg_mode.setValue("devices")
    sv._on_mode_changed("devices")
    assert (sv.spin_from.minimum(), sv.spin_to.maximum()) == (0, 255)
    win.settings["transport"] = "serial"
    sv._on_mode_changed("devices")
    assert (sv.spin_from.minimum(), sv.spin_to.maximum()) == (1, 247)


def test_a_busy_tcp_port_is_shown_in_the_emulator(win, server):
    sv = win.slave_view
    sv.reload_map()
    sv.seg_mode.setValue("tcp")
    sv.combo_access.setCurrentIndex(1)
    sv.spin_tcp_port.setValue(server.port)          # taken by the fixture's server
    sv.toggle()
    assert _wait(lambda: not sv.running
                 and sv.lbl_status.property("state") == "error", 5)
    assert str(server.port) in sv.lbl_status.text()
    assert sv.seg_mode.isEnabled()                  # the controls are back
