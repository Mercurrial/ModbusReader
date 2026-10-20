"""Start-up: what the user sees between the double-click and the window."""
from PyQt6.QtCore import QEvent, QObject
from PyQt6.QtWidgets import QApplication, QWidget


class _ShownWindows(QObject):
    """Records every widget that is shown as a window of its own."""

    def __init__(self):
        super().__init__()
        self.shown = []

    def eventFilter(self, obj, ev):
        if (ev.type() == QEvent.Type.Show and isinstance(obj, QWidget)
                and obj.isWindow()):
            self.shown.append(f"{type(obj).__name__} {obj.objectName()!r}")
        return False


def test_building_the_window_shows_no_stray_windows(tmp_path, monkeypatch):
    """A widget shown before it has a parent becomes a window of its own.
    The empty-state labels did that: five of them flashed at start-up, each
    took the foreground and handed it back to the previous program — which
    kept it, so the main window opened behind it, «minimized»."""
    from app import settings_manager
    from gui import main_window as gui_main
    monkeypatch.setattr(settings_manager, "SETTINGS_FILE",
                        str(tmp_path / "settings.json"), raising=False)
    spy = _ShownWindows()
    app = QApplication.instance()
    app.installEventFilter(spy)
    try:
        w = gui_main.ModernScadaApp()
    finally:
        app.removeEventFilter(spy)
    try:
        assert spy.shown == []
    finally:
        w.update_ctl.shutdown()
        w.deleteLater()


def test_an_empty_state_is_never_a_window_of_its_own():
    from gui.widgets import EmptyState
    spy = _ShownWindows()
    app = QApplication.instance()
    app.installEventFilter(spy)
    try:
        e = EmptyState("table", "Title", "Body text that wraps")
        e.set_content(body="Another body")
    finally:
        app.removeEventFilter(spy)
    assert spy.shown == []
    assert e.lbl_body.parent() is e and e.lbl_body.isVisibleTo(e)
    e.deleteLater()


def test_a_saved_position_on_a_vanished_monitor_is_brought_back():
    from PyQt6.QtCore import QRect
    from gui.qt_utils import fit_on_screens
    primary = QRect(0, 0, 1845, 1080)          # taskbar on the right
    second = QRect(1920, 0, 2560, 1400)
    # On a screen: kept as it is.
    assert fit_on_screens(254, 207, 1119, 680, [primary]) == (254, 207, 1119, 680)
    assert fit_on_screens(2100, 100, 1400, 900, [primary, second]) == (2100, 100, 1400, 900)
    # The second monitor is gone: centred on the primary one, size clamped.
    assert fit_on_screens(2100, 100, 2400, 900, [primary]) == (0, 90, 1845, 900)
    # Title bar above the top edge / only a sliver left on screen.
    assert fit_on_screens(100, -200, 800, 600, [primary]) == (522, 240, 800, 600)
    assert fit_on_screens(1800, 100, 800, 600, [primary]) == (522, 240, 800, 600)
    # Nothing saved yet: centred.
    assert fit_on_screens(None, None, 1280, 780, [primary]) == (282, 150, 1280, 780)
    # No screens reported (headless corner cases): untouched.
    assert fit_on_screens(5, 6, 7, 8, []) == (5, 6, 7, 8)


def test_the_window_restores_onto_a_visible_screen(tmp_path, monkeypatch):
    import json
    from app import settings_manager
    from gui import main_window as gui_main
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"win_x": -30000, "win_y": -30000,
                                "win_w": 900, "win_h": 600}), encoding="utf-8")
    monkeypatch.setattr(settings_manager, "SETTINGS_FILE", str(path), raising=False)
    w = gui_main.ModernScadaApp()
    try:
        area = QApplication.primaryScreen().availableGeometry()
        assert area.intersects(w.frameGeometry()) or area.contains(w.pos())
        assert w.width() <= area.width() and w.height() <= area.height()
    finally:
        w.update_ctl.shutdown()
        w.deleteLater()
