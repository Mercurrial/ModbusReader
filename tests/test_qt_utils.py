"""qt_utils.later — the guarded deferred call.

An unguarded QTimer.singleShot whose callback touches a destroyed widget is an
access violation (process abort), not an exception. This project hit that class
of bug five times, so the guard is centralised and pinned by these tests."""
from PyQt6.QtCore import QEvent
from PyQt6.QtWidgets import QApplication, QLabel, QWidget

from gui.qt_utils import alive, later


def _pump(n=10):
    for _ in range(n):
        QApplication.processEvents()


def test_alive_reports_deleted_widgets():
    w = QLabel()
    assert alive(w)
    w.deleteLater()
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert not alive(w)
    assert not alive(None)


def test_later_runs_when_owner_lives():
    w = QWidget()
    calls = []
    later(0, w, calls.append, "ran")
    _pump()
    assert calls == ["ran"]


def test_later_skips_when_owner_is_gone():
    w = QWidget()
    calls = []
    later(0, w, lambda: calls.append(w.objectName()))   # touches the widget
    w.deleteLater()
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    _pump()
    assert calls == []            # skipped instead of crashing the process


def test_later_swallows_runtime_error_from_a_dying_widget():
    w = QWidget()

    def boom():
        raise RuntimeError("wrapped C/C++ object has been deleted")
    later(0, w, boom)
    _pump()                       # must not propagate


def test_editor_guide_popup_survives_immediate_close():
    """Real scenario: the profile editor auto-opens its guide after 450 ms.
    Closing it sooner used to call _show_guide on a dead dialog."""
    from app.app_context import AppContext
    from app.settings_manager import DEFAULT_SETTINGS
    from gui.map_editor import ProfileEditorDialog

    ctx = AppContext(dict(DEFAULT_SETTINGS))
    dlg = ProfileEditorDialog(None, [], ctx)
    later(0, dlg, dlg._show_guide)
    dlg.close()
    dlg.deleteLater()
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    _pump()                       # reaching here without an abort is the test
