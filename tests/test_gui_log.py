"""LogPanel: HTML escaping, filters, theme rebuild."""
import pytest

from app_context import AppContext
from settings_manager import DEFAULT_SETTINGS
from gui_log import LogPanel


@pytest.fixture()
def panel():
    return LogPanel(AppContext(dict(DEFAULT_SETTINGS)))


def test_message_html_escaped(panel):
    panel.log("TX", "v = <b>5 & 7</b> </span>")
    plain = panel.view.toPlainText()
    assert "<b>" in plain and "& 7" in plain     # literal, not markup


def test_filters(panel):
    for lv in ("TX", "RX", "SYS", "ERR"):
        panel.log(lv, f"m-{lv}")
    panel.set_filter("err")
    text = panel.view.toPlainText()
    assert "m-ERR" in text and "m-TX" not in text
    panel.set_filter("tx")
    text = panel.view.toPlainText()
    assert "m-TX" in text and "m-RX" not in text
    panel.set_filter("all")
    text = panel.view.toPlainText()
    assert all(f"m-{lv}" in text for lv in ("TX", "RX", "SYS", "ERR"))


def test_rebuild_preserves_entries(panel):
    panel.log("SYS", "keep-me")
    panel.rebuild()
    assert "keep-me" in panel.view.toPlainText()


def test_buffer_capped_by_log_max(panel):
    panel.ctx.settings["log_max"] = 50
    for i in range(80):
        panel.log("SYS", f"n{i}")
    assert len(panel._entries) == 50              # oldest rolled out
    assert panel._entries[0][2] == "n30"


def test_apply_settings_trims_buffer(panel):
    panel.ctx.settings["log_max"] = 100
    for i in range(100):
        panel.log("SYS", f"n{i}")
    panel.ctx.settings["log_max"] = 20            # user lowered the limit
    panel.apply_settings()
    assert len(panel._entries) == 20
    assert panel._entries[0][2] == "n80"


def test_verbosity_min_drops_tx_rx(panel):
    panel.ctx.settings["log_verbosity"] = "min"
    panel.log("TX", "frame-out")
    panel.log("RX", "frame-in")
    panel.log("ERR", "kept-err")
    panel.log("SYS", "kept-sys")
    levels = [lv for lv, _, _ in panel._entries]
    assert "TX" not in levels and "RX" not in levels
    assert "ERR" in levels and "SYS" in levels
    panel.ctx.settings["log_verbosity"] = "normal"
    panel.log("TX", "frame-out-2")
    assert panel._entries[-1][0] == "TX"


def test_autoscroll_setting_no_crash(panel):
    for flag in (True, False):
        panel.ctx.settings["log_autoscroll"] = flag
        panel.log("SYS", f"scroll-{flag}")
    assert "scroll-False" in panel.view.toPlainText()
