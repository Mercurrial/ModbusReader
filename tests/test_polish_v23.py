"""2.3 polish: details found by photographing every surface and zooming in.

Row numbers off their zebra stripe, labels shifted by Qt's hidden indent,
settings sections glued together, a clipped placeholder, empty states that
repeated the toolbar's accent button.
"""
import copy

import pytest
from PyQt6.QtWidgets import QApplication, QLabel, QTableWidget

from app.app_context import AppContext
from app.settings_manager import DEFAULT_SETTINGS


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
    from gui.widgets import RowNumberHeader
    from gui.styles import get_stylesheet
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
    from gui.styles import get_stylesheet
    s = DEFAULT_SETTINGS
    lbl = QLabel("Serial / RTU")
    lbl.setObjectName("stSectionTitle")
    lbl.setStyleSheet(get_stylesheet(s["theme"], s["font_family"],
                                     s["font_size"], s["accent"]))
    lbl.ensurePolished()
    assert lbl.indent() == 0


def test_settings_sections_have_air_between_them(tmp_path, monkeypatch):
    from app import settings_manager
    from gui import main_window as gui_main
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
    from app.i18n import STRINGS
    for lang in ("ru", "en"):
        text = STRINGS[lang]["slvLogEmpty"]
        assert "\n" not in text and len(text) <= 36


@pytest.mark.parametrize("modname,cls", [("gui.scanner", "ScannerView"),
                                         ("gui.sniffer", "SnifferView")])
def test_empty_state_does_not_repeat_the_accent_button(modname, cls):
    import importlib
    mod = importlib.import_module(modname)
    view = getattr(mod, cls)(_ctx())
    assert [b.objectName() for b in view.empty.buttons] == ["btnOutline"]
    assert not view.empty.buttons[0].text().startswith(" ")
    view.deleteLater()


def test_editor_hides_zero_counts_on_an_empty_map(tmp_path, monkeypatch):
    from gui.map_editor import ProfileEditorDialog
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


# ── open source: licence, About, demo project ──────────────────────
def test_the_licence_is_the_gpl_v3_text():
    import os
    from app import version
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    text = open(os.path.join(root, "LICENSE"), encoding="utf-8").read()
    assert text.lstrip().startswith("GNU GENERAL PUBLIC LICENSE")
    assert "Version 3, 29 June 2007" in text
    assert version.LICENSE_ID == "GPL-3.0-or-later"
    for spec in ("ModbusReader.spec", "ModbusReader_debug.spec",
                 "ModbusReader_setup.spec"):
        assert "('LICENSE', '.')" in open(os.path.join(root, spec), encoding="utf-8").read()


def test_about_shows_licence_and_source(tmp_path, monkeypatch):
    from app import settings_manager
    from gui import main_window as gui_main
    from gui import settings as gui_settings
    from app.version import SOURCE_URL
    assert gui_settings._license_path().endswith("LICENSE")
    monkeypatch.setattr(settings_manager, "SETTINGS_FILE",
                        str(tmp_path / "settings.json"), raising=False)
    w = gui_main.ModernScadaApp()
    try:
        w.show()
        w._open_settings()
        _pump()
        dlg = w._overlay_page
        dlg.nav.setCurrentRow(dlg._page_keys.index("about"))
        _pump()
        links = [lb.text() for lb in dlg.findChildren(QLabel)
                 if lb.openExternalLinks()]
        assert any("GPL-3.0-or-later" in t for t in links)
        assert any(SOURCE_URL in t for t in links)
        from app.version import DONATE_URL
        assert any(DONATE_URL in t for t in links)
        # the same link drives the GitHub «Sponsor» button
        import os
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        funding = open(os.path.join(root, ".github", "FUNDING.yml"),
                       encoding="utf-8").read()
        assert DONATE_URL in funding
    finally:
        w._close_overlay()
        w._closing_for_update = True
        w.close()
        _pump()


def test_demo_project_opens_clean(tmp_path, monkeypatch):
    import os
    from core import formats
    from app import settings_manager
    from gui import main_window as gui_main
    from core.profile_manager import find_overlaps, find_duplicate_names
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(root, "examples", "demo.mbproj")
    regs = formats.load_project(path)["profile"]["registers"]
    assert len(regs) >= 10 and not find_overlaps(regs) and not find_duplicate_names(regs)
    assert {r.get("area", "holding") for r in regs} == {"holding", "input", "coil", "discrete"}
    monkeypatch.setattr(settings_manager, "SETTINGS_FILE",
                        str(tmp_path / "settings.json"), raising=False)
    w = gui_main.ModernScadaApp()
    try:
        w._open_project(path)
        _pump()
        assert w.register_table.rowCount() == len(regs)
    finally:
        w._closing_for_update = True
        w.close()
        _pump()


def test_demo_project_button_opens_a_private_copy(tmp_path, monkeypatch):
    """«Демо-проект» on the empty map: one click to a working example, as
    the user's own copy (the bundled file would be wiped by an update)."""
    from app import settings_manager
    from gui import main_window as gui_main
    monkeypatch.setattr(settings_manager, "SETTINGS_FILE",
                        str(tmp_path / "settings.json"), raising=False)
    monkeypatch.setattr("app.projects.projects_dir", lambda: str(tmp_path / "docs"))
    w = gui_main.ModernScadaApp()
    try:
        labels = [b.text() for b in w.map_empty.buttons]
        assert w.t("emptyDemo") in labels
        w._set_profile([], "")
        btn = next(b for b in w.map_empty.buttons if b.text() == w.t("emptyDemo"))
        btn.click()
        _pump()
        copy = tmp_path / "docs" / (w.t("demoFileName") + ".mbproj")
        assert copy.exists()
        assert w.project_path == str(copy)
        assert w.register_table.rowCount() >= 10
        assert len(w.dash_view.cards) >= 10          # it ships with a dashboard
    finally:
        w._closing_for_update = True
        w.close()
        _pump()


def _demo(name):
    import os
    from core import formats
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return formats.load_project(os.path.join(root, "examples", name))


def _cyrillic(text) -> bool:
    import re
    return bool(re.search("[А-Яа-яЁё]", str(text)))


def test_english_demo_is_the_same_device_in_english():
    """demo_en.mbproj: the very registers and panel of demo.mbproj, with
    every one-language word English — the Russian file under English menus
    showed «В», «мА», «Работа» and Russian widget titles."""
    ru, en = _demo("demo.mbproj"), _demo("demo_en.mbproj")
    same = ("addr", "area", "type", "length", "rw", "scale", "offset", "default",
            "name", "name_en")
    assert ([{k: r.get(k) for k in same} for r in en["profile"]["registers"]]
            == [{k: r.get(k) for k in same} for r in ru["profile"]["registers"]])
    layout = ("uid", "kind", "reg_id", "x", "y", "w", "h", "vmin", "vmax")
    ru_cards, en_cards = ru["dashboards"][0]["widgets"], en["dashboards"][0]["widgets"]
    assert ([{k: c.get(k) for k in layout} for c in en_cards]
            == [{k: c.get(k) for k in layout} for c in ru_cards])
    words = [en["name"], en["profile"]["name"], en["dashboards"][0]["name"]]
    for r in en["profile"]["registers"]:
        words += [r.get("unit", ""), r.get("name_en", "")]
        words += list((r.get("enum") or {}).values())
    for c in en_cards:
        words += [c.get("title", ""), c.get("name", ""), c.get("unit", "")]
        words += [label for _v, label in c.get("options", [])]
    assert not [w for w in words if _cyrillic(w)]


def test_demo_button_opens_the_english_demo_in_the_english_ui(tmp_path, monkeypatch):
    from app import settings_manager
    from gui import main_window as gui_main
    monkeypatch.setattr(settings_manager, "SETTINGS_FILE",
                        str(tmp_path / "settings.json"), raising=False)
    monkeypatch.setattr("app.projects.projects_dir", lambda: str(tmp_path / "docs"))
    assert gui_main.demo_project_path("en").endswith("demo_en.mbproj")
    assert gui_main.demo_project_path("ru").endswith("demo.mbproj")
    w = gui_main.ModernScadaApp()
    try:
        w._on_lang_changed("en")
        _pump()
        w._set_profile([], "")
        btn = next(b for b in w.map_empty.buttons if b.text() == w.t("emptyDemo"))
        btn.click()
        _pump()
        copy = tmp_path / "docs" / "Demo temperature controller.mbproj"
        assert copy.exists() and w.project_path == str(copy)
        titles = [c.cfg.get("title", "") for c in w.dash_view.cards.values()]
        assert "Supply voltage" in titles
        assert not [t for t in titles if _cyrillic(t)]
    finally:
        w._closing_for_update = True
        w.close()
        _pump()


def test_every_build_bundles_both_demo_projects():
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for spec in ("ModbusReader.spec", "ModbusReader_debug.spec",
                 "ModbusReader_setup.spec", "ModbusReader_unix.spec"):
        text = open(os.path.join(root, spec), encoding="utf-8").read()
        for demo in ("demo.mbproj", "demo_en.mbproj"):
            assert f"('examples/{demo}', 'examples')" in text, (spec, demo)
