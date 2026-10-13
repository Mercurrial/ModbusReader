"""Coverage for the widget/view layer that had none.

These modules are small but sit under everything: a broken Segmented control
means an unusable settings page, a missing icon name is a silent blank button,
and a guide step pointing at a widget that no longer exists raises mid-tour.
"""
import pytest
from PyQt6.QtWidgets import QApplication, QMessageBox, QWidget

import icons
from app_context import AppContext
from settings_manager import DEFAULT_SETTINGS
from theme_manager import get_theme


@pytest.fixture()
def ctx():
    return AppContext(dict(DEFAULT_SETTINGS))


# ═══════════════════ icons ═══════════════════
def test_every_icon_name_renders_something():
    """A name that is not in _PATHS would silently produce a blank button."""
    blank = []
    for name in icons._PATHS:
        pm = icons.pixmap(name, "#ffffff", 16)
        assert not pm.isNull(), name
        img = pm.toImage()
        if not any(img.pixelColor(x, y).alpha()
                   for y in range(0, img.height(), 2)
                   for x in range(0, img.width(), 2)):
            blank.append(name)
    assert not blank, f"icons that draw nothing: {blank}"


def test_icon_names_used_in_code_all_exist():
    """icons.icon("typo") returns an empty icon with no error at all — the
    button just loses its glyph, which is easy to miss in review."""
    import glob
    import os
    import re
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    pat = re.compile(r'icons\.(?:icon|pixmap|icon_url)\(\s*"([a-z_]+)"')
    missing = {}
    for path in glob.glob(os.path.join(root, "*.py")):
        for lineno, line in enumerate(open(path, encoding="utf-8"), 1):
            for name in pat.findall(line):
                if name not in icons._PATHS:
                    missing.setdefault(os.path.basename(path), []).append(
                        (lineno, name))
    assert not missing, f"unknown icon names: {missing}"


def test_icon_url_is_a_usable_stylesheet_url():
    """Qt QSS cannot draw a CSS triangle, so arrows come from a cached PNG.
    The value must be a ready-to-paste url(...) with forward slashes."""
    import os
    url = icons.icon_url("chevron", "#ffffff", 12)
    assert url.startswith("url(") and url.endswith(".png)")
    path = url[4:-1]
    assert "\\" not in path, "QSS needs forward slashes"
    assert os.path.exists(path)


def test_icon_url_reuses_the_cached_png():
    """Re-rendering on every restyle was a measurable theme-switch cost."""
    import os
    first = icons.icon_url("chevron", "#abcdef", 12)
    stamp = os.path.getmtime(first[4:-1])
    assert icons.icon_url("chevron", "#abcdef", 12) == first
    assert os.path.getmtime(first[4:-1]) == stamp


def test_pixmap_honours_size_and_device_ratio():
    """Icons are rendered at 2x and tagged, or they look soft on HiDPI."""
    pm = icons.pixmap("check", "#ff0000", 16)
    assert pm.devicePixelRatio() == 2.0
    assert pm.width() == 32 and pm.height() == 32


# ═══════════════════ gui_widgets ═══════════════════
def test_segmented_selects_and_reports():
    from gui_widgets import Segmented
    seg = Segmented([("a", "First"), ("b", "Second")], "a")
    seen = []
    seg.valueChanged.connect(seen.append)
    assert seg.value() == "a"
    seg.setValue("b")
    assert seg.value() == "b" and seen == ["b"]


def test_segmented_ignores_an_unknown_value():
    """Settings can hold a value from a newer build; the control must not end
    up with nothing selected."""
    from gui_widgets import Segmented
    seg = Segmented([("a", "First"), ("b", "Second")], "a")
    seg.setValue("nonsense")
    assert seg.value() in ("a", "b")


def test_segmented_does_not_re_emit_the_same_value():
    from gui_widgets import Segmented
    seg = Segmented([("a", "A"), ("b", "B")], "a")
    seen = []
    seg.valueChanged.connect(seen.append)
    seg.setValue("a")
    assert seen == []


def test_toggle_switch_reports_its_state():
    from gui_widgets import ToggleSwitch
    t = ToggleSwitch(False, theme=get_theme("Dark"))
    assert t.isChecked() is False
    t.setChecked(True)
    assert t.isChecked() is True


def test_labeled_slider_clamps_to_its_range():
    from gui_widgets import LabeledSlider
    sl = LabeledSlider(8, 16, 9, unit=" pt")
    assert sl.value() == 9
    sl.slider.setValue(999)
    assert sl.value() == 16
    sl.slider.setValue(-5)
    assert sl.value() == 8


def test_swatch_picker_round_trips_every_accent():
    from gui_widgets import SwatchPicker
    from settings_schema import ACCENT_SWATCHES
    p = SwatchPicker(list(ACCENT_SWATCHES), "neutral")
    for key, _hex in ACCENT_SWATCHES:
        p.setValue(key)
        assert p.value() == key


def test_swatch_picker_marks_exactly_one_selected():
    from gui_widgets import SwatchPicker
    from settings_schema import ACCENT_SWATCHES
    p = SwatchPicker(list(ACCENT_SWATCHES), "blue")
    selected = [k for k, b in p._buttons.items() if b._selected]
    assert selected == ["blue"]


# ═══════════════════ dialogs ═══════════════════
def test_themed_message_returns_the_clicked_index(monkeypatch):
    """Every confirmation in the app depends on this index mapping; an off-by-
    one here silently turns Cancel into Discard."""
    import dialogs
    captured = {}

    def fake_exec(self):
        captured["dlg"] = self
        self._pick(1)                      # click the middle button
        return 1
    monkeypatch.setattr(dialogs._CardDialog, "exec", fake_exec)
    choice = dialogs.themed_message(
        None, "Dark", "warning", "T", "B",
        [("Cancel", QMessageBox.ButtonRole.RejectRole, False),
         ("Discard", QMessageBox.ButtonRole.DestructiveRole, False),
         ("Save", QMessageBox.ButtonRole.AcceptRole, True)])
    assert choice == 1


def test_esc_maps_to_the_reject_button(monkeypatch):
    """Dismissing with Esc must mean Cancel, not the destructive option."""
    import dialogs
    dlg = dialogs._CardDialog(
        None, "Dark", "warning", "T", "B",
        [("Save", QMessageBox.ButtonRole.AcceptRole, True),
         ("Cancel", QMessageBox.ButtonRole.RejectRole, False)])
    dlg.reject()
    assert dlg.choice == 1                 # the RejectRole button's index


def test_dialog_with_no_reject_button_reports_minus_one(monkeypatch):
    import dialogs
    dlg = dialogs._CardDialog(
        None, "Dark", "info", "T", "B",
        [("OK", QMessageBox.ButtonRole.AcceptRole, True)])
    dlg.reject()
    assert dlg.choice == -1


def test_no_button_label_is_ever_clipped():
    """Three buttons did not fit the old fixed 400 px card and the middle label
    came out cut mid-word."""
    import dialogs
    from PyQt6.QtWidgets import QPushButton
    dlg = dialogs._CardDialog(
        None, "Dark", "warning", "Заголовок", "Тело сообщения",
        [("Отмена", QMessageBox.ButtonRole.RejectRole, False),
         ("Выйти без сохранения", QMessageBox.ButtonRole.DestructiveRole, False),
         ("Сохранить и закрыть", QMessageBox.ButtonRole.AcceptRole, True)])
    dlg.show()
    QApplication.processEvents()
    for b in dlg.findChildren(QPushButton):
        need = b.fontMetrics().horizontalAdvance(b.text())
        assert b.width() >= need, f"{b.text()!r} clipped ({b.width()} < {need})"
    dlg.close()


@pytest.mark.parametrize("kind", ["warning", "error", "question", "info",
                                  "success", "nonsense"])
def test_every_dialog_kind_builds(kind):
    """An unknown kind must fall back, not raise — callers pass strings."""
    import dialogs
    dlg = dialogs._CardDialog(None, "Dark", kind, "T", "B",
                              [("OK", QMessageBox.ButtonRole.AcceptRole, True)])
    assert dlg is not None


# ═══════════════════ view guides ═══════════════════
@pytest.mark.parametrize("lang", ["ru", "en"])
def test_every_view_guide_builds_with_live_targets(lang, monkeypatch):
    """A guide step pointing at a widget that was renamed raises in the middle
    of the tour. Build each one for real and check the steps survive."""
    import gui_onboarding
    from gui_scanner import ScannerView
    from gui_sniffer import SnifferView
    from gui_dash import DashboardView

    built = []
    monkeypatch.setattr(gui_onboarding.OnboardingGuide, "show_guide",
                        lambda self: built.append(list(self._steps)))
    c = AppContext(dict(DEFAULT_SETTINGS, lang=lang, dash_widgets=[],
                        dash_links=[]))
    host = QWidget()
    host.resize(1200, 800)
    for factory in (lambda: ScannerView(c), lambda: SnifferView(c),
                    lambda: DashboardView(c, lambda: [])):
        view = factory()
        view.setParent(host)
        host.show()
        QApplication.processEvents()
        built.clear()
        view._show_guide()
        assert built and built[0], f"{type(view).__name__}: no steps survived"
        for step in built[0]:
            assert step.get("title") and step.get("body")
        if hasattr(view, "stop_if_running"):
            view.stop_if_running()
    host.close()


def test_guide_drops_steps_whose_target_is_hidden():
    """Steps are filtered rather than crashing when a panel is toggled off."""
    from gui_onboarding import OnboardingGuide
    host = QWidget()
    visible, hidden = QWidget(host), QWidget(host)
    hidden.hide()
    g = OnboardingGuide(host, [
        {"target": None, "title": "intro", "body": "b"},
        {"target": visible, "title": "shown", "body": "b"},
        {"target": hidden, "title": "gone", "body": "b"},
    ])
    titles = [s["title"] for s in g._steps]
    assert titles == ["intro", "shown"]


# ═══════════════════ trends data ═══════════════════
def test_trend_history_is_bounded(ctx):
    """An always-on session must not grow memory without limit."""
    from gui_trends import TrendCard
    card = TrendCard(reg_id="0x0001", reg_name="T", theme=get_theme("Dark"),
                     color="#12cbf5", default_window_sec=30, history_len=50,
                     t=ctx.t, unit="")
    for i in range(500):
        card.add_value(float(i))
    assert len(card._vs) == 50
    assert card._vs[-1] == 499.0            # newest kept, oldest dropped
    assert len(card._ts) == len(card._vs)


def test_trends_manager_routes_a_sample_to_the_right_card(ctx):
    from gui_trends import TrendsManager
    m = TrendsManager(ctx)
    m.add_trend("0x0001", "A")
    m.add_trend("0x0002", "B")
    m.update_trend_data("0x0002", 42.0)
    assert list(m.active_trends["0x0002"]._vs) == [42.0]
    assert list(m.active_trends["0x0001"]._vs) == []
    m.deleteLater()


def test_a_sample_for_an_unknown_register_is_ignored(ctx):
    from gui_trends import TrendsManager
    m = TrendsManager(ctx)
    m.update_trend_data("0xBEEF", 1.0)      # must not raise
    assert m.active_trends == {}
    m.deleteLater()


def test_removing_a_trend_frees_its_card(ctx):
    from gui_trends import TrendsManager
    m = TrendsManager(ctx)
    m.add_trend("0x0001", "A")
    m.remove_trend("0x0001")
    assert "0x0001" not in m.active_trends
    m.update_trend_data("0x0001", 5.0)      # late sample after removal
    m.deleteLater()
