# gui_views.py
"""Full-screen secondary views for the nav switcher (gui_main content stack).

ConsoleView   — the exchange terminal: the SAME log store as the bottom panel
                (gui_log.LogStore), shown full screen with its own filter tabs,
                plus the raw packet console strip at the bottom. Its
                RawConsole re-emits send_requested so gui_main routes frames to
                the core exactly like the bottom-strip console.
(The slave / device-emulator view lives in gui_slave.py.)
"""

from PyQt6.QtWidgets import QWidget, QVBoxLayout
from PyQt6.QtCore import Qt, pyqtSignal

from gui_console import RawConsole
from gui_log import LogStore, LogView


class ConsoleView(QWidget):
    """Full-screen exchange terminal + raw packet sender."""

    send_requested = pyqtSignal(bytes)

    def __init__(self, ctx, parent=None, store: LogStore | None = None):
        super().__init__(parent)
        self.ctx = ctx
        # Normally the window hands in the bottom panel's store, so both
        # surfaces show one log. Standalone (tests) it owns a private one.
        self.store = store or LogStore(ctx, self)
        self.setObjectName("consoleView")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        lo = QVBoxLayout(self)
        lo.setContentsMargins(0, 0, 0, 0)
        lo.setSpacing(0)

        self.log_view = LogView(ctx, self.store)
        self.view = self.log_view.view
        self._tabs = self.log_view._tabs
        lo.addWidget(self.log_view, 1)

        self.console = RawConsole(ctx)
        self.console.send_requested.connect(self.send_requested)
        lo.addWidget(self.console)

    @property
    def _entries(self):
        return self.store.entries

    def set_filter(self, key: str):
        self.log_view.set_filter(key)

    def log(self, level: str, message: str):
        """Append to the shared store (every view of it updates)."""
        self.store.add(level, message)

    def rebuild(self):
        self.log_view.rebuild()

    def apply_settings(self):
        self.log_view.apply_theme()
        self.log_view.rebuild()

    def showEvent(self, e):
        # Another view may have recalled history meanwhile — it is shared.
        self.console.reload_history()
        super().showEvent(e)

    def retranslate(self, t):
        self.log_view.retranslate(t)
        self.console.retranslate(t)
