"""Regression: the deferred FontRole chunks must survive the dialog's death.

The Appearance tab assigns per-item fonts to the 300-family combo in
QTimer.singleShot chunks. Closing the settings overlay deletes the combo while
chunks are still queued; the callback then dereferenced a dead QComboBox
(RuntimeError: wrapped C/C++ object has been deleted — a user-visible crash
in the global excepthook). The callback is now guarded with sip.isdeleted."""
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QEvent

from settings_manager import DEFAULT_SETTINGS
from settings_schema import PAGES


def test_font_chunks_survive_dialog_deletion(monkeypatch):
    # Enough fake families that chunk 2+ is DEFERRED past the deletion.
    import gui_settings
    monkeypatch.setattr(
        gui_settings.QFontDatabase, "families",
        staticmethod(lambda: [f"Fake Font {i}" for i in range(200)]))

    dlg = gui_settings.SettingsDialog(dict(DEFAULT_SETTINGS))
    dlg.nav.setCurrentRow([p.key for p in PAGES].index("display"))
    QApplication.processEvents()              # first chunk runs, next deferred

    dlg.deleteLater()                         # settings overlay closed
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    for _ in range(6):                        # queued chunks fire on a corpse…
        QApplication.processEvents()          # …must be a guarded no-op
    # Reaching here without an unhandled RuntimeError IS the assertion:
    # unguarded, PyQt aborts the interpreter on the dead-object access.
