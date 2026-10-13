# gui_views.py
"""Full-screen secondary views for the nav switcher (gui_main content stack).

ConsoleView   — the exchange terminal: the SAME log store as the bottom panel
                (gui_log.LogStore), shown full screen with its own filter tabs,
                plus the raw packet console strip at the bottom. Its
                RawConsole re-emits send_requested so gui_main routes frames to
                the core exactly like the bottom-strip console.
SlaveStubView — placeholder for the future device-simulation (slave) mode.
"""

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PyQt6.QtCore import Qt, pyqtSignal

import icons
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
        self.log_view.rebuild()

    def showEvent(self, e):
        # Another view may have recalled history meanwhile — it is shared.
        self.console.reload_history()
        super().showEvent(e)

    def retranslate(self, t):
        self.log_view.retranslate(t)
        self.console.retranslate(t)


class SlaveStubView(QWidget):
    """Placeholder page for the planned slave / device-simulation mode."""

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.setObjectName("slaveStub")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        lo = QVBoxLayout(self)
        lo.addStretch(3)

        self._ico = QLabel()
        self._ico.setPixmap(icons.pixmap("cpu", ctx.theme_tokens()["text_4"], 52))
        self._ico.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._ico.setStyleSheet("background: transparent;")

        self.lbl_title = QLabel(ctx.t("slaveStubTitle"))
        self.lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_title.setObjectName("mhTitle")

        self.lbl_text = QLabel(ctx.t("slaveStubText"))
        self.lbl_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_text.setWordWrap(True)
        self.lbl_text.setObjectName("mhCrumb")
        self.lbl_text.setMaximumWidth(520)

        lo.addWidget(self._ico)
        lo.addSpacing(10)
        lo.addWidget(self.lbl_title)
        lo.addSpacing(6)
        lo.addWidget(self.lbl_text, 0, Qt.AlignmentFlag.AlignHCenter)
        lo.addStretch(5)

    def apply_settings(self):
        self._ico.setPixmap(icons.pixmap(
            "cpu", self.ctx.theme_tokens()["text_4"], 52))

    def retranslate(self, t):
        self.lbl_title.setText(t("slaveStubTitle"))
        self.lbl_text.setText(t("slaveStubText"))
