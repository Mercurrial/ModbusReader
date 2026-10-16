"""2.2 polish: the small things that made the app look unfinished.

Each test pins one detail found by reviewing every surface of the running UI
(menus, dialogs, pages, both themes) — and one real bug among them: the
table's «Copy address» copied the word «Двоичное».
"""
import copy

import pytest
from PyQt6.QtWidgets import QApplication, QLineEdit, QMenu

from app import settings_manager
from app.app_context import AppContext
from app.settings_manager import DEFAULT_SETTINGS


def _ctx(**over):
    s = copy.deepcopy(DEFAULT_SETTINGS)
    s.update(over)
    return AppContext(s)


@pytest.fixture()
def win(tmp_path, monkeypatch):
    from gui import main_window as gui_main
    monkeypatch.setattr(settings_manager, "SETTINGS_FILE",
                        str(tmp_path / "settings.json"), raising=False)
    w = gui_main.ModernScadaApp()
    yield w
    w.close()
    QApplication.processEvents()


REGS = [{"addr": 5, "name": "Режим", "type": "SHORT", "rw": "RW"},
        {"addr": 6, "name": "Температура", "type": "FLOAT", "rw": "R"}]


def test_copy_address_copies_the_address(monkeypatch):
    """The dec/hex/bin loop reused the variable that held the address label,
    so «Copy address» put «Двоичное» on the clipboard."""
    from gui.register_table import RegisterTable, COL_NAME
    t = RegisterTable(_ctx())
    t.populate(REGS)
    menus = []
    monkeypatch.setattr(QMenu, "exec", lambda self, *a: menus.append(self))
    rect = t.visualItemRect(t.item(0, COL_NAME))
    t._show_context_menu(rect.center())
    copy_addr = [a for a in menus[0].actions()
                 if a.text().startswith(t.t("ctxCopyAddr"))][0]
    assert copy_addr.text().endswith("\t0x0005")
    copy_addr.trigger()
    assert QApplication.clipboard().text() == "0x0005"
    assert all(not a.icon().isNull() for a in menus[0].actions()
               if a.text() and not a.isSeparator())
    t.deleteLater()


def test_themed_input_returns_text_or_cancel():
    from gui.dialogs import _CardDialog
    from PyQt6.QtWidgets import QMessageBox
    d = _CardDialog(None, "Dark", "question", "T", "Label",
                    [("Cancel", QMessageBox.ButtonRole.RejectRole, False),
                     ("OK", QMessageBox.ButtonRole.AcceptRole, True)], field="abc")
    d.edit.setText("plant")
    d._accept_default()                         # Enter in the field
    assert d.choice == 1 and d.edit.text() == "plant"
    d2 = _CardDialog(None, "Dark", "question", "T", "Label",
                     [("Cancel", QMessageBox.ButtonRole.RejectRole, False),
                      ("OK", QMessageBox.ButtonRole.AcceptRole, True)], field="x")
    d2.reject()
    assert d2.choice == 0


def test_no_native_input_dialogs_left():
    import pathlib
    from _paths import source_files
    for f in map(pathlib.Path, source_files()):
        code = "\n".join(line for line in f.read_text(encoding="utf-8").splitlines()
                         if not line.lstrip().startswith("#"))
        assert "QInputDialog." not in code and "import QInputDialog" not in code, f.name


def test_window_title_names_the_document(win):
    win.profile_data = REGS
    win._set_project("C:/x/plant.mbproj", "plant")
    assert win.windowTitle() == "plant — ModbusReader"
    win._set_project("", "")
    win.profile_path = ""
    win._refresh_window_title()
    assert win.windowTitle() == "ModbusReader"


def test_frame_log_lines_are_localized_and_not_doubled(win):
    lines = []
    core = win.modbus_core
    core.log_msg.connect(lambda lvl, m: lines.append((lvl, m)))
    core._log_tx_read(0x10, 2, 3)
    core._log_rx_read([1, 2], 3)
    core._log_tx_read(0, 8, 1)
    lvl, msg = lines[0]
    assert lvl == "TX" and msg.startswith("→ [")
    assert "TX" not in msg and "Read" not in msg            # RU UI, one tag
    assert "чтение 2 рег. с 0x0010" in msg
    assert "данные: [0001 0002]" in lines[1][1]
    assert "бит" in lines[2][1]


def test_chart_windows_speak_the_ui_language():
    from gui.trends import win_label
    from app.i18n import get_translator
    ru, en = get_translator("ru"), get_translator("en")
    assert [win_label(s, ru) for s in (10, 30, 120, 600)] == \
        ["10 с", "30 с", "2 мин", "10 мин"]
    assert win_label(120, en) == "2 min"


def test_sizes_and_units_speak_the_ui_language():
    from gui.logger import human_size
    from app.i18n import get_translator
    assert human_size(5 << 20, "ru") == "5.0 МБ"
    assert human_size(5 << 20) == "5.0 MB"
    assert get_translator("ru")("unitMsSuffix") == " мс"


def test_switching_pages_does_not_hand_focus_to_a_field(win):
    win.show()
    QApplication.processEvents()
    for page in ("view_scanner", "view_sniffer", "view_slave", "view_logger"):
        win._switch_view(page)
        QApplication.processEvents()
        assert not isinstance(QApplication.focusWidget(), QLineEdit), page


def test_toggles_use_the_accent():
    from gui.widgets import ToggleSwitch
    from gui.theme_manager import get_theme
    c = get_theme("Dark", "rose")
    assert ToggleSwitch(True, theme=c)._c_on.name() == c["accent"].lower()


def test_status_bar_does_not_repeat_the_link(win):
    assert not win.status_bar.lbl_params.isVisibleTo(win.status_bar)
    assert win.main_toolbar.btn_link.text().strip()


def test_version_resource_follows_version_py():
    import sys
    import pathlib
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
    from tools import version_resource
    from app.version import APP_VERSION
    assert version_resource._quad(APP_VERSION)[:3] == tuple(
        int(p) for p in APP_VERSION.split("."))
    pytest.importorskip("PyInstaller")
    info = version_resource.version_info("ModbusReader.exe")
    assert APP_VERSION in str(info)


# ═══════════════ the live-chart card ═══════════════
@pytest.mark.parametrize("values,decimals", [
    ([380, 501, 466], 0),                    # integers stay integers
    ([19.29, 22.734, 21.3], 2),              # ~1 % of a 3.4 span
    ([0.0012, 0.0019], 4),                   # capped at 4
    ([7.5, 7.5], 2),                         # flat line: from the magnitude
])
def test_one_precision_per_card(values, decimals):
    from gui.trends import decimals_for
    assert decimals_for(values) == decimals


def test_value_formatting():
    from gui.trends import fmt_value
    assert fmt_value(22.309, 2) == "22.31"
    assert fmt_value(4000000, 0) == "4 000 000"   # thin-space groups
    assert fmt_value(-0.0001, 2) == "0"                       # no "-0.00"
    assert fmt_value(float("nan"), 2) == "—"
    assert "e" in fmt_value(3e10, 0)


@pytest.fixture()
def card():
    from gui.trends import TrendCard
    from app.i18n import get_translator
    from gui.theme_manager import get_theme
    c = TrendCard("0x0014", "Температура", get_theme("Dark"), "#12cbf5",
                  t=get_translator("ru"), unit="°C")
    yield c
    c.deleteLater()


def test_card_states_waiting_live_stale_paused(card, monkeypatch):
    from gui import trends as gui_trends
    assert card._state == "waiting" and not card.lbl_wait.isHidden()
    card.add_value(21.5)
    assert card._state == "live" and card.lbl_wait.isHidden()
    # The link drops: no sample for longer than STALE_AFTER.
    card._last_rx -= gui_trends.STALE_AFTER + 2
    card._refresh_state()
    assert card._state == "stale"
    assert "нет данных" in card.lbl_delta.text()
    assert card.curve.opacity() < 1.0                # an old line looks old
    card.add_value(21.6)                             # data again
    assert card._state == "live" and card.curve.opacity() == 1.0
    card._toggle_pause()
    assert card._state == "paused" and card.lbl_delta.text() == card.t("trendPaused")
    card._toggle_pause()
    assert card._state == "live"


def test_card_numbers_share_a_precision_and_ticks_stay_inside(card):
    import time
    now = time.time()
    for i, v in enumerate((19.29, 20.5, 22.734, 21.3)):
        card._ts.append(now - 4 + i)
        card._vs.append(v)
    card._last_rx = time.monotonic()
    card._apply_state("live")
    card._dirty = True
    card._render_if_dirty()
    assert card.lbl_value.text() == "21.30"
    assert (card._stat_labels["min"].text(), card._stat_labels["max"].text()) == \
        ("19.29", "22.73")
    assert card.lbl_delta.text() == "↑ 2.01"
    lo, hi = card.plot.getViewBox().viewRange()[1]
    assert lo < 19.29 and hi > 22.734                # min/max ticks not on the edge
