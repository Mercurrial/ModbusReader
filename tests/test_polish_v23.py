"""2.3 polish: details found by photographing every surface and zooming in.

Row numbers off their zebra stripe, labels shifted by Qt's hidden indent,
settings sections glued together, a clipped placeholder, empty states that
repeated the toolbar's accent button.
"""
import copy

import pytest
from PyQt6.QtWidgets import QApplication, QLabel, QTableWidget

from app_context import AppContext
from settings_manager import DEFAULT_SETTINGS


def _ctx(**over):
    s = copy.deepcopy(DEFAULT_SETTINGS)
    s.update(over)
    return AppContext(s)


def _pump():
    for _ in range(5):
        QApplication.processEvents()


@pytest.mark.parametrize("hidden", [[], [1], [1, 2, 5]])
def test_row_numbers_share_their_rows_stripe(hidden):
    """The number column painted every row on one colour, so each zebra
    stripe started a number's width in from the edge."""
    from gui_widgets import RowNumberHeader
    from styles import get_stylesheet
    s = DEFAULT_SETTINGS
    t = QTableWidget(10, 1)
    t.setStyleSheet(get_stylesheet(s["theme"], s["font_family"],
                                   s["font_size"], s["accent"]))
    t.setVerticalHeader(RowNumberHeader(t))
    t.setAlternatingRowColors(True)
    t.setProperty("zebra", "true")
    t.resize(240, 420)
    for r in hidden:
        t.setRowHidden(r, True)
    t.show()
    _pump()
    shot = t.grab().toImage()
    vh = t.verticalHeader()
    colours = []
    for r in range(10):
        if r in hidden:
            continue
        y = vh.y() + t.rowViewportPosition(r) + 3
        cell = shot.pixelColor(vh.width() + 30, y).name()
        number = shot.pixelColor(vh.x() + 1, y).name()
        assert cell == number, f"row {r}: stripe stops at the number"
        colours.append(cell)
    assert colours[0] != colours[1]          # it IS striped
    t.close()


def test_padded_labels_start_at_their_padding_edge():
    """Any QSS padding switched on Qt's automatic label indent (half an "x"),
    so section titles and hints sat ~5 px in from the fields under them."""
    from styles import get_stylesheet
    s = DEFAULT_SETTINGS
    lbl = QLabel("Serial / RTU")
    lbl.setObjectName("stSectionTitle")
    lbl.setStyleSheet(get_stylesheet(s["theme"], s["font_family"],
                                     s["font_size"], s["accent"]))
    lbl.ensurePolished()
    assert lbl.indent() == 0


def test_settings_sections_have_air_between_them(tmp_path, monkeypatch):
    import settings_manager
    import gui_main
    monkeypatch.setattr(settings_manager, "SETTINGS_FILE",
                        str(tmp_path / "settings.json"), raising=False)
    w = gui_main.ModernScadaApp()
    try:
        w.resize(1400, 900)
        w.show()
        w._open_settings()
        _pump()
        dlg = w._overlay_page
        titles = [lb for lb in dlg.findChildren(QLabel)
                  if lb.objectName() == "stSectionTitle" and lb.isVisible()]
        assert len(titles) >= 2
        a, b = titles[0], titles[1]
        # the row right above the second title ends well before it
        fields = [f for f in dlg.findChildren(type(a.parentWidget()))
                  if f.objectName() == "stField" and f.isVisible()
                  and f.mapTo(dlg, f.rect().topLeft()).y()
                  < b.mapTo(dlg, b.rect().topLeft()).y()]
        last_bottom = max(f.mapTo(dlg, f.rect().bottomLeft()).y() for f in fields)
        assert b.mapTo(dlg, b.rect().topLeft()).y() - last_bottom >= 24
    finally:
        w._close_overlay()
        w.close()
        _pump()


def test_slave_log_placeholder_is_one_short_line():
    """Qt clips a QTextEdit placeholder to the empty document's height: the
    wrapped second half of the old sentence was never visible."""
    from i18n import STRINGS
    for lang in ("ru", "en"):
        text = STRINGS[lang]["slvLogEmpty"]
        assert "\n" not in text and len(text) <= 36


@pytest.mark.parametrize("modname,cls", [("gui_scanner", "ScannerView"),
                                         ("gui_sniffer", "SnifferView")])
def test_empty_state_does_not_repeat_the_accent_button(modname, cls):
    import importlib
    mod = importlib.import_module(modname)
    view = getattr(mod, cls)(_ctx())
    assert [b.objectName() for b in view.empty.buttons] == ["btnOutline"]
    assert not view.empty.buttons[0].text().startswith(" ")
    view.deleteLater()


def test_editor_hides_zero_counts_on_an_empty_map(tmp_path, monkeypatch):
    from profile_editor import ProfileEditorDialog
    ed = ProfileEditorDialog(profile_data=[], ctx=_ctx())
    ed.show()
    _pump()
    try:
        assert not ed.lbl_stats_total.isVisibleTo(ed)
        ed._add_row()
        _pump()
        assert ed.lbl_stats_total.isVisibleTo(ed)
    finally:
        ed.is_modified = False
        ed.close()
