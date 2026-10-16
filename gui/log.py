# gui_log.py
"""Transaction log — ONE buffer, shown in two places.

``LogStore`` holds the entries (level, time, message) and applies the two
settings that decide what is kept: ``log_max`` (buffer cap) and
``log_verbosity`` («min» drops the per-frame TX/RX traffic). ``LogView`` renders
a store: the filter tab bar (All / TX / RX / Errors) plus a themed read-only
text view. Every view keeps its own filter but reads the SAME entries.

Before this split the bottom panel and the full-screen Консоль each kept a
private buffer, fed line-by-line by the window. They drifted: the console
ignored the verbosity setting and clamped the cap differently, so the "same"
log showed different lines in the two places.

``LogPanel`` is the bottom strip: a LogView + the raw-frame console with its
show/hide toggle. ``gui_views.ConsoleView`` is the same LogView full screen.

Object names (``logPanel`` / ``logTabBar`` / ``logTab`` / ``txLog``) are what
styles.py targets, so both surfaces share one look.
"""
import html

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QTextEdit, QLineEdit,
    QFileDialog,
)
from PyQt6.QtCore import Qt, QDateTime, QSize, QObject, pyqtSignal

from gui.theme_manager import get_theme
from gui.console import RawConsole
from gui import icons

# (filter key, initial label, i18n key)
_TABS = (("all", "All", "all"), ("tx", "TX", "tx"),
         ("rx", "RX", "rx"), ("err", "ERR", "errors"))
_MAX_ENTRIES = 2000   # hard ceiling; the effective cap is the log_max setting


class LogStore(QObject):
    """The log entries, shared by every view that shows the log."""

    appended = pyqtSignal(str, str, str)      # level, time, message
    reset = pyqtSignal()                      # trimmed / cleared — re-render

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        # Stored raw (level, ts, message) — NOT pre-formatted HTML — so colors
        # re-bind on a theme change.
        self.entries: list[tuple[str, str, str]] = []

    def cap(self) -> int:
        try:
            return max(10, min(_MAX_ENTRIES,
                               int(self.ctx.settings.get("log_max", 200))))
        except (TypeError, ValueError):
            return 200

    def records(self, lv: str) -> bool:
        """Verbosity gate: «min» records only system/error lines, dropping the
        per-frame TX/RX traffic. «normal»/«debug» record everything."""
        if self.ctx.settings.get("log_verbosity", "normal") == "min":
            return lv not in ("TX", "RX")
        return True

    def add(self, level: str, message: str):
        lv = str(level).upper()
        if not self.records(lv):
            return
        ts = QDateTime.currentDateTime().toString("HH:mm:ss.zzz")
        self.entries.append((lv, ts, str(message)))
        cap = self.cap()
        if len(self.entries) > cap:
            del self.entries[:len(self.entries) - cap]
        self.appended.emit(lv, ts, str(message))

    def apply_settings(self):
        """Re-apply log_max after the settings dialog: trim and re-render."""
        cap = self.cap()
        if len(self.entries) > cap:
            del self.entries[:len(self.entries) - cap]
        self.reset.emit()

    def clear(self):
        self.entries.clear()
        self.reset.emit()


def render_entry(theme_name: str, lv: str, ts: str, message: str) -> str:
    """Themed HTML for one entry; colors read live from the active theme."""
    c = get_theme(theme_name)
    color = {
        "TX":  c.get("accent", "#dee2ee"),
        "RX":  c.get("info", "#5dadec"),
        "SYS": c.get("text_3", "#8b92a5"),
        "ERR": c.get("error", "#e04848"),
    }.get(lv, c.get("text_1", "#ffffff"))
    # Escape the message — it carries user content (typed values, register
    # names, device errors) and is rendered as rich text by QTextEdit.
    return (
        f'<span style="color:{c.get("text_4", "#656c81")}">[{ts}]</span>&nbsp;'
        f'<span style="color:{color};font-weight:bold">[{lv}]</span>&nbsp;'
        f'<span style="color:{c.get("text_2", "#bcc1cc")}">{html.escape(message)}</span>'
    )


class LogView(QWidget):
    """Filter tab bar + text view over a LogStore. The tab bar has a slot on
    its right end (``tab_bar_layout``) for extra controls."""

    def __init__(self, ctx, store: LogStore, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.store = store
        self._filter = "all"
        self._needle = ""
        lo = QVBoxLayout(self)
        lo.setContentsMargins(0, 0, 0, 0)
        lo.setSpacing(0)

        tab_bar = QWidget()
        tab_bar.setObjectName("logTabBar")
        self.tab_bar_layout = QHBoxLayout(tab_bar)
        self.tab_bar_layout.setContentsMargins(6, 0, 6, 0)
        self.tab_bar_layout.setSpacing(0)
        self._tabs: dict[str, QPushButton] = {}
        for key, label, _ in _TABS:
            btn = QPushButton(label)
            btn.setObjectName("logTab")
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _checked=False, k=key: self.set_filter(k))
            self._tabs[key] = btn
            self.tab_bar_layout.addWidget(btn)
        self.tab_bar_layout.addStretch()
        # The tools every log viewer has: find a line, keep the log, start
        # clean. (The full-screen console had none of them.)
        self.ed_search = QLineEdit()
        self.ed_search.setObjectName("logSearch")
        self.ed_search.setFixedWidth(200)
        self.ed_search.setClearButtonEnabled(True)
        self.ed_search.textChanged.connect(self._on_search)
        self.tab_bar_layout.addWidget(self.ed_search)
        self.tab_bar_layout.addSpacing(4)
        self.btn_save = self._tool("download", self.save_to_file)
        self.btn_clear = self._tool("trash", self.store.clear)
        lo.addWidget(tab_bar)

        self.view = QTextEdit()
        self.view.setObjectName("txLog")
        self.view.setReadOnly(True)
        self.view.setPlaceholderText(ctx.t("logPlaceholder"))
        lo.addWidget(self.view, 1)

        store.appended.connect(self._on_appended)
        store.reset.connect(self.rebuild)
        self.set_filter("all")

    def _tool(self, icon_name: str, slot) -> QPushButton:
        b = QPushButton()
        b.setObjectName("logTab")
        b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setIconSize(QSize(14, 14))
        b.setProperty("icon_name", icon_name)
        b.clicked.connect(slot)
        self.tab_bar_layout.addWidget(b)
        self.paint_tool(b)
        return b

    def paint_tool(self, b: QPushButton):
        b.setIcon(icons.icon(b.property("icon_name"),
                             get_theme(self.ctx.theme)["text_3"], 14))

    def apply_theme(self):
        for b in (self.btn_save, self.btn_clear):
            self.paint_tool(b)

    def _on_search(self, text: str):
        self._needle = text.strip().lower()
        self.rebuild()

    def save_to_file(self):
        """The log as plain text («time [LEVEL] message» per line)."""
        from gui.dialogs import themed_info
        t = self.ctx.t
        stamp = QDateTime.currentDateTime().toString("yyyyMMdd_HHmmss")
        path, _ = QFileDialog.getSaveFileName(
            self, t("logSave"), f"modbusreader_log_{stamp}.txt",
            t("logSaveFilter"))
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                for lv, ts, msg in self.store.entries:
                    f.write(f"{ts} [{lv}] {msg}\n")
        except OSError as e:
            themed_info(self, self.ctx.theme, "error", t("logSave"), str(e))

    # ── filtering ─────────────────────────────────────────────────
    def _should_show(self, level: str, message: str = "") -> bool:
        if self._needle and self._needle not in f"{level} {message}".lower():
            return False
        f = self._filter
        if f == "tx":
            return level == "TX"
        if f == "rx":
            return level == "RX"
        if f == "err":
            return level in ("ERR", "ERROR")
        return True

    def set_filter(self, key: str):
        self._filter = key
        for k, btn in self._tabs.items():
            btn.setProperty("active", "true" if k == key else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)
        self.rebuild()

    # ── rendering ─────────────────────────────────────────────────
    def _autoscroll(self) -> bool:
        return bool(self.ctx.settings.get("log_autoscroll", True))

    def _on_appended(self, lv: str, ts: str, message: str):
        if not self._should_show(lv, message):
            return
        sb = self.view.verticalScrollBar()
        keep = sb.value()
        self.view.append(render_entry(self.ctx.theme, lv, ts, message))
        sb.setValue(sb.maximum() if self._autoscroll() else keep)

    def rebuild(self):
        """Re-render every stored entry with current theme colors + filter.

        Builds ONE HTML block and sets it in a single pass — appending
        line-by-line here caused a layout reflow per entry (noticeable on a
        theme switch with a full log)."""
        theme = self.ctx.theme
        lines = [render_entry(theme, lv, ts, m) for lv, ts, m in self.store.entries
                 if self._should_show(lv, m)]
        self.view.setHtml("<br>".join(lines))
        sb = self.view.verticalScrollBar()
        sb.setValue(sb.maximum() if self._autoscroll() else 0)

    def retranslate(self, t):
        for key, _, i18n_key in _TABS:
            if key in self._tabs:
                self._tabs[key].setText(t(i18n_key))
        self.view.setPlaceholderText(t("logPlaceholder"))
        self.ed_search.setPlaceholderText(t("logSearch"))
        self.btn_save.setToolTip(t("logSave"))
        self.btn_clear.setToolTip(t("logClear"))


class LogPanel(QWidget):
    """The bottom strip: log view + raw-frame console (toggle in the tab bar).

    Public API: ``log()``, ``rebuild()``, ``set_filter()``, ``retranslate()``,
    ``apply_settings()``; ``store`` is the shared buffer other views attach
    to."""

    def __init__(self, ctx, parent=None, store: LogStore | None = None):
        super().__init__(parent)
        self.ctx = ctx
        self.store = store or LogStore(ctx, self)
        self.setObjectName("logPanel")
        self._build_ui()

    def _build_ui(self):
        lo = QVBoxLayout(self)
        lo.setContentsMargins(0, 0, 0, 0)
        lo.setSpacing(0)

        self.log_view = LogView(self.ctx, self.store)
        self.view = self.log_view.view
        self._tabs = self.log_view._tabs
        # Console visibility toggle (terminal icon, right side of the tab bar).
        self.btn_console = QPushButton()
        self.btn_console.setObjectName("logTab")
        self.btn_console.setCheckable(True)
        self.btn_console.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_console.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_console.setIconSize(QSize(14, 14))
        self._paint_console_icon()
        self.btn_console.toggled.connect(self._toggle_console)
        self.log_view.tab_bar_layout.addWidget(self.btn_console)
        lo.addWidget(self.log_view, 1)

        # Raw-frame console strip (command + resulting packet).
        self.console = RawConsole(self.ctx)
        lo.addWidget(self.console)
        visible = bool(self.ctx.settings.get("console_visible", True))
        self.console.setVisible(visible)
        self.btn_console.setChecked(visible)
        self.btn_console.setToolTip(self.ctx.t("consoleToggleTip"))

    def _paint_console_icon(self):
        self.btn_console.setIcon(icons.icon(
            "terminal", get_theme(self.ctx.theme)["text_3"], 14))

    def _toggle_console(self, on: bool):
        self.console.setVisible(on)
        self.ctx.settings["console_visible"] = bool(on)

    # ── the shared buffer, as the window and tests know it ────────
    @property
    def _entries(self):
        return self.store.entries

    def log(self, level: str, message: str):
        self.store.add(level, message)

    def rebuild(self):
        self.log_view.rebuild()

    def set_filter(self, key: str):
        self.log_view.set_filter(key)

    def apply_settings(self):
        """Re-apply log_max / verbosity / theme after the settings dialog."""
        self._paint_console_icon()
        self.log_view.apply_theme()
        self.store.apply_settings()          # trims + every view re-renders

    def retranslate(self, t):
        self.log_view.retranslate(t)
        self.btn_console.setToolTip(t("consoleToggleTip"))
        self.console.retranslate(t)
