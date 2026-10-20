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
