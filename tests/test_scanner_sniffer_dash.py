"""Scanner engine, sniffer decoding and dashboard persistence."""
import pytest
from PyQt6.QtWidgets import QApplication

from app_context import AppContext
from settings_manager import DEFAULT_SETTINGS


def _pump():
    for _ in range(4):
        QApplication.processEvents()


# ── sniffer: CRC + frame decode (pure) ──────────────────────────────────
def test_crc16_known_vector():
    from sniffer_core import crc16
    # The classic textbook frame: 01 03 00 00 00 02 -> CRC C4 0B on the wire.
    assert crc16(bytes([0x01, 0x03, 0x00, 0x00, 0x00, 0x02])) == 0x0BC4


def test_decode_request_and_response():
    from sniffer_core import crc16, decode_frame
    req = bytes([0x01, 0x03, 0x00, 0x10, 0x00, 0x02])
    c = crc16(req)
    d = decode_frame(req + bytes([c & 0xFF, c >> 8]))
    assert d["crc_ok"] and d["kind"] == "request"
    assert "0x0010" in d["describe"] and d["slave"] == 1

    resp = bytes([0x01, 0x03, 0x04, 0x12, 0x34, 0x56, 0x78])
    c = crc16(resp)
    d = decode_frame(resp + bytes([c & 0xFF, c >> 8]))
    assert d["crc_ok"] and d["kind"] == "response"
    assert "1234" in d["describe"] and "5678" in d["describe"]


def test_decode_exception_and_bad_crc():
    from sniffer_core import crc16, decode_frame
    exc = bytes([0x01, 0x83, 0x02])
    c = crc16(exc)
    d = decode_frame(exc + bytes([c & 0xFF, c >> 8]))
    assert d["kind"] == "exception" and d["crc_ok"]

    bad = bytes([0x01, 0x03, 0x00, 0x00, 0x00, 0x02, 0xDE, 0xAD])
    assert decode_frame(bad)["crc_ok"] is False


def test_write_single_is_ambiguous_echo():
    from sniffer_core import crc16, decode_frame
    frm = bytes([0x0A, 0x06, 0x00, 0x10, 0x00, 0x2A])
    c = crc16(frm)
    d = decode_frame(frm + bytes([c & 0xFF, c >> 8]))
    assert d["kind"] == "req/resp" and "42" in d["describe"]


# ── scanner: classification through a fake core ─────────────────────────
class _FakeCore:
    """request_op stub: slave 5 answers, slave 7 answers with an exception,
    the rest are silent. Register mode: addr 3 alive with value 123."""
    is_running = True

    def request_op(self, kind, addr, dtype, value=None, timeout=5.0, slave=None):
        if kind == "probe":
            if slave == 5:
                return "alive"
            if slave == 7:
                return "exception"
            if addr == 3:
                return "alive"
            return "silent"
        if kind == "read":
            return 123
        raise RuntimeError("unexpected")


def test_scanner_finds_devices():
    from scanner_engine import ScannerWorker
    w = ScannerWorker(_FakeCore(), "devices", 1, 10)
    hits = []
    w.found.connect(hits.append)
    done = []
    w.finished_scan.connect(lambda h, t, s: done.append((h, t)))
    w.run()                                   # synchronously, no thread needed
    assert [h["id"] for h in hits] == [5, 7]
    assert hits[0]["state"] == "alive" and hits[1]["state"] == "exception"
    assert done == [(2, 10)]


def test_scanner_finds_registers_with_value():
    from scanner_engine import ScannerWorker
    w = ScannerWorker(_FakeCore(), "registers", 0, 5, slave_id=9)
    hits = []
    w.found.connect(hits.append)
    w.run()
    assert len(hits) == 1
    assert hits[0]["addr"] == 3 and hits[0]["value"] == 123


def test_scanner_stop_breaks_loop():
    from scanner_engine import ScannerWorker
    w = ScannerWorker(_FakeCore(), "devices", 1, 247)
    w.request_stop()
    done = []
    w.finished_scan.connect(lambda h, t, s: done.append(t))
    w.run()
    assert done == [247]                      # finished immediately, 0 probed


# ── dashboard: config, persistence, value routing ───────────────────────
@pytest.fixture()
def dash():
    from gui_dash import DashboardView
    ctx = AppContext(dict(DEFAULT_SETTINGS))
    regs = [{"addr": 1, "name": "Ток", "type": "SHORT", "unit": "А"}]
    view = DashboardView(ctx, lambda: regs)
    yield view
    view.deleteLater()


def test_dash_add_persist_remove(dash):
    dash._make_card({"reg_id": "0x0001", "name": "Ток", "unit": "А",
                     "kind": "bar", "vmin": 0, "vmax": 50, "thr": 0.5})
    dash._persist()
    saved = dash.ctx.settings["dash_widgets"]
    assert len(saved) == 1 and saved[0]["kind"] == "bar"
    uid = saved[0]["uid"]
    dash._remove_card(uid)
    assert dash.ctx.settings["dash_widgets"] == []


def test_dash_value_routing(dash):
    dash._make_card({"reg_id": "0x0001", "name": "Ток", "unit": "А",
                     "kind": "value", "vmin": 0, "vmax": 50, "thr": 0.5})
    dash.update_value("0x0001", 42.5)
    dash.update_value("0x0099", 7)            # unrelated register — ignored
    card = list(dash.cards.values())[0]
    assert card.value == 42.5


def test_dash_restores_from_settings():
    from gui_dash import DashboardView
    s = dict(DEFAULT_SETTINGS)
    s["dash_widgets"] = [{"uid": "aa", "reg_id": "0x0002", "name": "T",
                          "unit": "", "kind": "gauge", "vmin": 0,
                          "vmax": 10, "thr": 0.5}]
    ctx = AppContext(s)
    view = DashboardView(ctx, lambda: [])
    assert set(view.cards) == {"aa"}
    view.deleteLater()


# ── dashboard v2: alarms, LED semantics, order, duplicate, stale ────────
def test_alarm_state_thresholds():
    from gui_dash import alarm_state
    cfg = {"alo": 10, "ahi": 90}
    assert alarm_state(cfg, 5) and alarm_state(cfg, 95)
    assert not alarm_state(cfg, 50)
    assert not alarm_state({"alo": None, "ahi": None}, 1e9)   # alarms off
    assert not alarm_state({}, None)                          # no value yet


def test_led_on_with_invert():
    from gui_dash import led_on
    assert led_on({"thr": 0.5}, 1) and not led_on({"thr": 0.5}, 0)
    assert led_on({"thr": 0.5, "invert": True}, 0)
    assert not led_on({"thr": 0.5, "invert": True}, 1)


def test_dash_positions_persist(dash):
    # v4: cfg holds LOGICAL geometry (card.x() is zoom-scaled), so moves go
    # through the real path and persistence reads the cfg.
    dash._make_card({"uid": "a", "reg_id": "0x0001", "name": "A", "unit": "",
                     "kind": "value", "x": 40, "y": 60})
    dash.sel_uid = "a"
    dash._nudge("a", 100, 160)
    saved = dash.ctx.settings["dash_widgets"][0]
    assert (saved["x"], saved["y"]) == (140, 220)
    assert saved["w"] > 0 and saved["h"] > 0


def test_dash_duplicate_offsets_copy(dash):
    dash._make_card({"reg_id": "0x0001", "name": "X", "unit": "",
                     "kind": "led", "x": 10, "y": 10})
    uid = next(iter(dash.cards))
    dash._duplicate_widget(uid)
    assert len(dash.cards) == 2
    copies = [c for u, c in dash.cards.items() if u != uid]
    assert copies[0].cfg["name"] == "X"
    assert (copies[0].x(), copies[0].y()) == (30, 30)          # offset by 20
    assert copies[0].cfg["uid"] != uid                         # fresh uid


def test_dash_legacy_cards_get_positions():
    """Pre-v3 saved cards had no x/y — they must be laid out, not stacked."""
    from gui_dash import DashboardView
    s = dict(DEFAULT_SETTINGS)
    s["dash_widgets"] = [
        {"uid": "a", "reg_id": "0x0001", "kind": "value", "name": "A"},
        {"uid": "b", "reg_id": "0x0002", "kind": "value", "name": "B"},
    ]
    ctx = AppContext(s)
    view = DashboardView(ctx, lambda: [])
    a, b = view.cards["a"], view.cards["b"]
    assert (a.x(), a.y()) != (b.x(), b.y())
    assert all(c.cfg.get("x") is not None for c in view.cards.values())
    view.deleteLater()


def test_dash_stale_marking(dash):
    import gui_dash
    dash._make_card({"reg_id": "0x0001", "name": "S", "unit": "",
                     "kind": "value", "vmin": 0, "vmax": 1, "thr": 0.5})
    card = list(dash.cards.values())[0]
    dash.update_value("0x0001", 7)
    assert card.stale is False
    card.last_sample -= gui_dash.STALE_AFTER + 1              # age the sample
    dash._check_stale()
    assert card.stale is True
    dash.update_value("0x0001", 8)                            # fresh sample
    assert card.stale is False


# ── header bar ──────────────────────────────────────────────────────────
def test_header_bar_title_and_connect():
    """The 2.2 header: the page title follows the page; Connect is the
    primary button and flips with the link."""
    from gui_toolbar import MainToolBar
    tb = MainToolBar(None)
    tb.set_active_view("view_scanner")
    assert tb.lbl_title.text() == tb.t("viewScanner")
    tb.set_connect_state(True)
    assert tb.btn_connect.property("connected") == "true"
    assert tb.btn_link.property("connected") == "true"
    tb.set_connect_state(False)
    assert tb.btn_connect.property("connected") == "false"
    tb.deleteLater()
