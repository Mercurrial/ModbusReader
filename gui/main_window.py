# gui/main_window.py

import os

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QFileDialog, QApplication, QLabel, QLineEdit,
    QStackedWidget, QPushButton, QMenu, QMessageBox,
)
from PyQt6.QtCore import Qt, QPropertyAnimation, QTimer
from PyQt6.QtGui import QShortcut, QKeySequence

from gui.toolbar import MainToolBar
from gui.rail import NavRail
from gui.widgets import EmptyState, EmptyOverlay, DropButton
from gui.statusbar import MainStatusBar
from gui.trends import TrendsManager
from gui.settings import SettingsDialog
from gui.log import LogPanel
from gui.memory_viewer import MemoryViewerDialog
from app.settings_manager import load_settings, save_settings
from core.profile_manager import load_profile_data, find_overlaps, find_duplicate_names
from app.app_context import AppContext
from gui.register_table import RegisterTable, COL_ADDR, COL_NAME, mono_font
from gui.views import ConsoleView
from gui.slave import SlaveView
from gui.scanner import ScannerView
from gui.sniffer import SnifferView
from gui.dashboard import DashboardView
from gui.snapshot_view import SnapshotView
from gui.logger import LoggerView
from gui.watch import WatchWindow
from gui.update import UpdateController


def demo_project_path(lang: str = "ru") -> str:
    """The bundled demo project in the UI language — examples/demo.mbproj, or
    demo_en.mbproj for English (its units, enum labels and widget titles are
    English) — next to the sources or inside the build. Falls back to the
    Russian file; "" if this copy was built without any."""
    from app.paths import resource
    names = ("demo_en.mbproj", "demo.mbproj") if lang == "en" else ("demo.mbproj",)
    for name in names:
        path = resource("examples", name)
        if os.path.isfile(path):
            return path
    return ""


def demo_copy_dir() -> str:
    """Where «Демо-проект» puts the user's own copy (Documents/ModbusReader)."""
    from PyQt6.QtCore import QStandardPaths
    docs = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.DocumentsLocation) or os.path.expanduser("~")
    return os.path.join(docs, "ModbusReader")
from gui.dialogs import themed_info, themed_message, themed_input
from gui.qt_utils import later, fit_on_screens
from core import datatypes
from core import formats
from app import commands
from gui import icons


# ═══════════════════════════════════════════════════════════════════
#  MAIN WINDOW
#  The register grid (table widget, columns, state dot, value formatting,
#  interaction) lives in gui.register_table.RegisterTable; the window routes its
#  intent signals to the core / trends / status bar / memory viewer.
# ═══════════════════════════════════════════════════════════════════
class ModernScadaApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ModbusReader")

        # AppContext owns the cross-cutting services (settings, Modbus core,
        # translator, theme). self.settings / modbus_core / lang / t below are
        # read-through properties onto it — see the "SHARED SERVICES" block.
        self.ctx = AppContext(load_settings())
        self._restore_window_geometry()
        self.profile_data: list[dict] = []
        self.profile_path: str        = ""
        # The project is the workspace; the register map is one part of it.
        # Empty path + empty name means "not in a named project yet".
        self.project_path: str        = self.settings.get("last_project_path", "")
        self.project_name: str        = self.settings.get("last_project_name", "")
        self.error_counter: int       = 0

        # Open MemoryViewerDialogs, keyed by address (the table emits
        # inspect_requested; the window owns the dialogs).
        self._memory_viewers: dict[int, MemoryViewerDialog] = {}

        self._connect_modbus_signals()

        self._init_ui()
        self._connect_toolbar_signals()
        self._setup_shortcuts()
        self._retranslate_ui()   # apply saved language on first paint

        # Saved log-panel visibility.
        if not self.settings.get("show_log", True):
            self.main_toolbar.set_layout_state(log=False)
            later(0, self, self._on_log_toggled, False)

        # «Запуск: открывать последний профиль» — уважаем тумблер.
        if self.settings.get("load_last", True):
            self._restore_last_workspace()
        else:
            # Without the restore the head bar must not claim a project that
            # is not loaded.
            self._set_project("", "")

        # Reopen the rest of the session exactly as it was closed: trend
        # cards, log-panel height, the active view.
        self._restore_session_state()

        # Start with nothing "typed into": no caret in the search box.
        later(0, self, self._park_focus)

        # Show the interactive guide once, on the very first launch only.
        # The spotlight rectangles need the window laid out, hence the delay.
        if not self.settings.get("guide_seen_main"):
            later(500, self, self._maybe_show_onboarding)

        # Updates: a quiet check right after start-up, then every few
        # hours; one question when there is something new (gui/update.py).
        self._closing_for_update = False
        self.update_ctl = UpdateController(self)
        self.update_ctl.start()

    # ===========================================================
    #  SHARED SERVICES
    #  Owned by AppContext. These read-through properties keep the window's
    #  long-standing attribute names working everywhere they're already used,
    #  so adopting the context needed no churn at the ~130 call sites.
    # ===========================================================
    @property
    def settings(self) -> dict:
        return self.ctx.settings

    @property
    def modbus_core(self):
        return self.ctx.core

    @property
    def lang(self) -> str:
        return self.ctx.lang

    @property
    def t(self):
        return self.ctx.t

    def _restore_last_workspace(self):
        """Reopen the register map that was on screen at exit.

        ``last_profile_path`` is set only while the map on screen came from a
        .json file; opening a project (or starting a new one) clears it. So:
        a file path means "that file was the map", otherwise the open
        project's own map is reloaded from the project file.

        Before, only the .json path was ever restored — after working in a
        project, the head bar came back showing the project's name over
        whatever bare map had been opened some time before it."""
        proj = self.settings.get("last_project_path", "")
        last_path = self.settings.get("last_profile_path", "")
        if proj and not os.path.exists(proj):
            self._set_project("", "")            # moved/deleted: don't claim it
            proj = ""
        if last_path and os.path.exists(last_path):
            self._load_profile(last_path)
            return
        if proj:
            try:
                doc = formats.load_project(proj)
            except Exception as e:
                self._log("ERR", self.t("logProjectRestoreFail").format(
                    path=proj, err=e))
                return
            # Only the MAP comes from the file. Connection, dashboards and
            # layout are already in the settings exactly as they were at exit
            # — newer than the project file if they changed since the last
            # save, so re-applying the file here would quietly undo them.
            self._set_profile((doc.get("profile") or {}).get("registers") or [], "")
            self._set_project(proj, self.project_name or doc.get("name") or "")

    # ===========================================================
    #  UI CONSTRUCTION
    # ===========================================================

    def _init_ui(self):
        central = QWidget()
        central.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.setCentralWidget(central)

        # The rail (every page) — a column on the left or right, or a bar
        # across the top (_place_rail) — and the work area: header bar over
        # the page stack. The status bar below spans both (QMainWindow).
        self._shell = QVBoxLayout(central)
        self._shell.setContentsMargins(0, 0, 0, 0)
        self._shell.setSpacing(0)
        self._shell_row = QHBoxLayout()
        self._shell_row.setContentsMargins(0, 0, 0, 0)
        self._shell_row.setSpacing(0)
        self._shell.addLayout(self._shell_row, 1)
        self.nav_rail = NavRail(
            self, theme=self.settings.get("theme", "Dark"),
            accent=self.settings.get("accent", "neutral"), lang=self.lang,
            collapsed=bool(self.settings.get("rail_collapsed", False)),
            position=str(self.settings.get("rail_position", "left")),
            hidden=self.settings.get("rail_hidden") or ())
        work = QWidget()
        work.setObjectName("workArea")
        work.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._shell_row.addWidget(work, 1)
        self._place_rail()
        root = QVBoxLayout(work)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header bar
        self.main_toolbar = MainToolBar(
            self,
            initial_slave_id=self.settings.get("slave_id", 10),
            initial_theme=self.settings.get("theme", "Dark"),
            initial_lang=self.lang,
            initial_accent=self.settings.get("accent", "neutral"),
        )
        root.addWidget(self.main_toolbar)

        self.v_splitter = QSplitter(Qt.Orientation.Vertical)
        self.h_splitter = QSplitter(Qt.Orientation.Horizontal)

        # ── Register table (own module; emits intent signals we route) ──
        self.register_table = RegisterTable(self.ctx)
        rt = self.register_table
        rt.write_requested.connect(self._on_write_requested)
        rt.write_blocked.connect(lambda a, v: self._log(
            "ERR", self.t("logWriteOffline").format(addr=f"0x{a:04X}", value=v)))
        rt.verbose_changed.connect(self._on_verbose_changed)
        rt.value_sampled.connect(self._on_value_sampled)
        rt.inspect_requested.connect(self._on_inspect_requested)
        rt.trend_add_requested.connect(self._add_to_trend)
        rt.trend_remove_requested.connect(self._remove_from_trend)

        # ── Register area (head bar + table) ─────────────────────
        self.register_area = QWidget()
        self.register_area.setObjectName("registerArea")
        ra_lo = QVBoxLayout(self.register_area)
        ra_lo.setContentsMargins(0, 0, 0, 0)
        ra_lo.setSpacing(0)
        ra_lo.addWidget(self._build_main_head())
        ra_lo.addWidget(self.register_table, 1)
        # No map yet: say what a map is and offer the three ways to get one.
        t = self.t
        self.map_empty = EmptyState("table", t("emptyMapTitle"), t("emptyMapBody"))
        self.map_empty.add_action(t("emptyOpenProject"), lambda: self._open_project(),
                                  primary=True)
        self.map_empty.add_action(t("emptyOpenMap"), self._open_profile)
        self.map_empty.add_action(t("emptyNewMap"), self._create_config)
        # One click to see what the app does, without a device or a file.
        if demo_project_path():
            self.map_empty.add_action(t("emptyDemo"), self._open_demo)
        self.map_empty.apply_theme(self.ctx.theme_tokens())
        self._map_empty_ov = EmptyOverlay(self.register_table, self.map_empty)

        self.h_splitter.addWidget(self.register_area)

        # ── Trends panel ─────────────────────────────────────────
        self.trends_manager = TrendsManager(self.ctx)
        self.trends_manager.setMinimumWidth(340)
        self.trends_manager.setMaximumWidth(0)
        # Hide/show the panel whenever the card set goes empty/non-empty —
        # this also catches the card's own X button, which removes a trend
        # without going through _remove_from_trend.
        self.trends_manager.state_changed.connect(
            lambda _has: self._update_trends_visibility())
        self.h_splitter.addWidget(self.trends_manager)
        self.h_splitter.setSizes([1, 0])

        # ── Log panel (own module: filter tabs + view + entry buffer) ──
        self.log_panel = LogPanel(self.ctx)
        self.log_panel.console.send_requested.connect(self._on_raw_send)

        self.v_splitter.addWidget(self.h_splitter)
        self.v_splitter.addWidget(self.log_panel)
        self.v_splitter.setSizes([580, 150])
        # The top pane absorbs window resizes; the terminal keeps its PIXEL
        # height (before this, QSplitter rescaled both proportionally and the
        # remembered log height came back wrong).
        self.v_splitter.setStretchFactor(0, 1)
        self.v_splitter.setStretchFactor(1, 0)
        # Dragging the handle to zero collapses the terminal — keep the layout
        # menu + status-bar chip in sync so reopening takes ONE click.
        self.v_splitter.splitterMoved.connect(self._on_log_splitter_moved)

        # ── Content stack ────────────────────────────────────────
        # Page 0 = main register view. Settings / profile-editor are added
        # as additional pages on demand so they appear *inside* this window
        # instead of as separate top-level dialogs.
        self.main_view = QWidget()
        mv_lo = QVBoxLayout(self.main_view)
        mv_lo.setContentsMargins(0, 0, 0, 0)
        mv_lo.setSpacing(0)
        mv_lo.addWidget(self.v_splitter)

        self.content_stack = QStackedWidget()
        self.content_stack.addWidget(self.main_view)

        # Persistent secondary views (nav cluster): full-screen console and the
        # slave-mode placeholder. Settings / editor stay on-demand overlays.
        # The full-screen console shows the SAME log as the bottom panel.
        self.console_view = ConsoleView(self.ctx, store=self.log_panel.store)
        self.console_view.send_requested.connect(self._on_raw_send)
        self.content_stack.addWidget(self.console_view)
        self.scanner_view = ScannerView(self.ctx)
        self.scanner_view.connect_requested.connect(
            lambda link: self.conn_card.open_below(self.main_toolbar.btn_link, link=link))
        self.content_stack.addWidget(self.scanner_view)
        self.sniffer_view = SnifferView(self.ctx)
        self.content_stack.addWidget(self.sniffer_view)
        self.dash_view = DashboardView(self.ctx, lambda: self.profile_data)
        # Dashboard controls (button / input / toggle, and anything a wire
        # activates) write through the SAME path as the register table.
        self.dash_view.write_requested.connect(self._on_write_requested)
        self.content_stack.addWidget(self.dash_view)
        # Snapshot/compare reads the SAME sources as everything else: the
        # loaded profile and the table's current cell values.
        self.snapshot_view = SnapshotView(
            self.ctx, lambda: self.profile_data,
            lambda: self.register_table.current_values())
        self.content_stack.addWidget(self.snapshot_view)
        # The logger samples on its OWN timer: the file is wide, so a row
        # must be a coherent snapshot of every register at one instant.
        # fresh_only: after the link drops the file gets EMPTY cells, never
        # the last value repeated for hours as if the device still said it.
        self.logger_view = LoggerView(
            self.ctx, lambda: self.profile_data,
            lambda: self.register_table.current_values(fresh_only=True))
        self.content_stack.addWidget(self.logger_view)
        self.slave_view = SlaveView(self.ctx, lambda: self.profile_data)
        self.content_stack.addWidget(self.slave_view)
        # Macros are a page like every other tool (a separate window until
        # 2.1 — the one exception to how the app worked). A running macro
        # keeps running when you switch pages; the rail shows it busy.
        from gui.macros import MacroWindow
        self.macro_view = MacroWindow(self.ctx, lambda: self.profile_data,
                                      embedded=True)
        self.macro_window = self.macro_view          # historical name
        self.content_stack.addWidget(self.macro_view)

        # The watch window floats above the main window (built hidden, so
        # the picked registers keep their min/max even while it is closed).
        self.watch_window = WatchWindow(self.ctx, lambda: self.profile_data, self)
        self.watch_window.write_requested.connect(self.register_table.request_write)
        self.watch_window.watch_changed.connect(self.register_table.set_watched)
        self.register_table.set_watched(self.watch_window.watched())
        rt.value_shown.connect(self.watch_window.on_value)
        rt.watch_toggle_requested.connect(self._toggle_watch_register)
        self.dash_view.watch_requested.connect(self._add_watch_register)

        self._overlay_page = None   # currently embedded settings/editor page
        self._current_view = "view_table"   # nav id of the visible base page
        root.addWidget(self.content_stack, 1)

        # ── Status bar ────────────────────────────────────────────
        self.status_bar = MainStatusBar(
            self, initial_slave_id=self.settings.get("slave_id", 10)
        )
        self.setStatusBar(self.status_bar)
        self.status_bar.apply_theme(self.ctx.theme_tokens())
        self._refresh_link_label()
        # Line statistics are counted in the core thread; the status bar
        # samples a snapshot twice a second (cheap: a dict copy under a lock).
        self.status_bar.stats_popup.reset_requested.connect(self._reset_line_stats)
        # The connection card: the link chip in the header opens it.
        from gui.connection import ConnectionCard
        self.conn_card = ConnectionCard(self.ctx, lambda: self.profile_data, self)
        self.conn_card.connect_requested.connect(self._connect_with)
        self.conn_card.disconnect_requested.connect(self._disconnect)
        self.conn_card.committed.connect(self._on_link_committed)
        self.conn_card.settings_requested.connect(self._open_settings)
        self.conn_card.find_requested.connect(self._find_on_network)
        self._stats_timer = QTimer(self)
        self._stats_timer.timeout.connect(self._refresh_line_stats)
        self._stats_timer.start(500)

    # ===========================================================
    #  REGISTER-MAP HEAD BAR
    # ===========================================================

    def _build_main_head(self) -> QWidget:
        """Header bar above the table: title · crumb · count badge · search."""
        t = self.t
        head = QWidget()
        head.setObjectName("mainHead")
        head.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        lo = QHBoxLayout(head)
        lo.setContentsMargins(14, 8, 14, 8)
        lo.setSpacing(10)

        self.mh_title = QLabel(t("registerMap"))
        self.mh_title.setObjectName("mhTitle")

        self.mh_crumb = QLabel(t("crumbDevice"))
        self.mh_crumb.setObjectName("mhCrumb")

        self.mh_badge = QLabel()
        self.mh_badge.setObjectName("mhBadge")
        self.mh_badge.setFont(mono_font())

        # The page title is in the header bar now; these two stay (hidden)
        # because the retranslate path still feeds them.
        self.mh_title.setVisible(False)
        self.mh_crumb.setVisible(False)

        # Project dropdown — the project owns the map, the dashboards and the
        # connection, so it sits at the left of the HEADER bar, on every page
        # ("plant ▾ / Сканер"). Labelled with the OPEN PROJECT: seeing its
        # name is what tells a newcomer that projects are the thing they are
        # working in.
        self.btn_profile = DropButton()
        self.btn_profile.setObjectName("mhProfile")
        self.btn_profile.set_chevron_color(self.ctx.theme_tokens()["text_3"])
        self.btn_profile.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_profile.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_profile.setIcon(
            icons.icon("project", self.ctx.theme_tokens()["text_2"], 15))
        self.btn_profile.clicked.connect(self._open_profile_menu)
        self._refresh_project_button()
        self.main_toolbar.set_project_widget(self.btn_profile)

        # Search box
        search_wrap = QWidget()
        search_wrap.setObjectName("searchBox")
        search_wrap.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        search_wrap.setFixedWidth(300)
        sw_lo = QHBoxLayout(search_wrap)
        sw_lo.setContentsMargins(8, 0, 6, 0)
        sw_lo.setSpacing(6)

        icon = QLabel()
        icon.setObjectName("searchIcon")
        icon.setPixmap(icons.pixmap("search", self.ctx.theme_tokens()["text_4"], 14))
        icon.setFixedSize(16, 16)
        self._search_icon_lbl = icon          # recolored on theme change
        self.search_input = QLineEdit()
        self.search_input.setObjectName("searchInput")
        self.search_input.setPlaceholderText(t("search"))
        self.search_input.setFrame(False)
        self.search_input.textChanged.connect(self._filter_table)

        sw_lo.addWidget(icon)
        sw_lo.addWidget(self.search_input, 1)
        lo.addWidget(search_wrap)
        lo.addWidget(self.mh_badge)
        # A stretch, not a spacer QWidget: a bare QWidget inherits the global
        # `QWidget { background: bg_1 }` rule and paints a slab.
        lo.addStretch(1)

        # The map's own verb, visible where the map is (it used to hide in
        # the project dropdown and behind Ctrl+2).
        self.btn_edit_map = QPushButton()
        self.btn_edit_map.setObjectName("tbBtn")
        self.btn_edit_map.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_edit_map.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_edit_map.setIcon(
            icons.icon("edit", self.ctx.theme_tokens()["text_2"], 15))
        self.btn_edit_map.clicked.connect(self._open_map_editor)
        lo.addWidget(self.btn_edit_map)

        return head

    def _filter_table(self, text: str):
        """Filter table rows by address or name substring."""
        needle = text.strip().lower()
        for row in range(self.register_table.rowCount()):
            if not needle:
                self.register_table.setRowHidden(row, False)
                continue
            addr_item = self.register_table.item(row, COL_ADDR)
            name_item = self.register_table.item(row, COL_NAME)
            hay = " ".join(
                it.text().lower() for it in (addr_item, name_item) if it
            )
            self.register_table.setRowHidden(row, needle not in hay)
        self._update_badge()

    def _update_badge(self):
        """Refresh the '{visible}/{total} reg' count badge."""
        if not hasattr(self, "mh_badge"):
            return
        total = self.register_table.rowCount()
        visible = sum(
            0 if self.register_table.isRowHidden(r) else 1
            for r in range(total)
        )
        self.mh_badge.setText(self.t("regBadge").format(visible=visible,
                                                        total=total))

    # ===========================================================
    #  SIGNAL WIRING
    # ===========================================================

    def _connect_modbus_signals(self):
        self.modbus_core.status_changed.connect(self._on_connection_status)
        self.modbus_core.data_updated.connect(self._on_data_updated)
        self.modbus_core.log_msg.connect(self._on_log_message)
        self.modbus_core.array_read_finished.connect(self._on_array_read_finished)
        self.modbus_core.open_failed.connect(self._on_open_failed)

    def _connect_toolbar_signals(self):
        # Command buttons + their shortcuts all route through one dispatcher
        # (see commands.py + _command_handler_map). Only parameterized /
        # non-command events keep dedicated signals.
        self._command_handlers = self._command_handler_map()
        self.main_toolbar.command_triggered.connect(self._dispatch_command)
        self.nav_rail.command_triggered.connect(self._dispatch_command)
        self.nav_rail.brand_clicked.connect(self._go_to_register_map)
        self.nav_rail.collapsed_changed.connect(self._on_rail_collapsed)
        self.nav_rail.position_changed.connect(self._on_rail_position)
        self.nav_rail.hidden_changed.connect(self._on_rail_hidden)
        self.main_toolbar.link_clicked.connect(self._toggle_conn_card)
        self.main_toolbar.theme_changed.connect(self._on_theme_changed)
        self.main_toolbar.lang_changed.connect(self._on_lang_changed)
        self.main_toolbar.graphs_toggled.connect(self._on_graphs_toggled)
        self.main_toolbar.log_toggled.connect(self._on_log_toggled)

        self.status_bar.slave_id_changed.connect(self._on_slave_id_changed)
        self.status_bar.log_toggle_clicked.connect(self._toggle_log_from_chip)

    def _command_handler_map(self) -> dict:
        """Bind each command id to its handler — the single place command
        behavior is wired (commands.py declares the metadata). Most handlers are
        window methods; ``theme`` is owned by the toolbar."""
        return {
            "new_project":  self._new_project,
            "open_project": lambda: self._open_project(),
            "save_project": self._save_shortcut,
            "new_config":   self._create_config,
            "open_config":  self._open_profile,
            "settings":     self._open_settings,
            "macros":       self._open_macros,
            "view_macros":  self._open_macros,
            "watch":        self._toggle_watch_window,
            "connect":      self._toggle_connection,
            "help":         self._show_help,
            "theme":        self.main_toolbar._toggle_theme,
            "search":       self._focus_search,
            # Nav cluster — main-view switching (Ctrl+1..4).
            "view_table":   lambda: self._switch_view("view_table"),
            "view_map":     self._open_map_editor,
            "view_console": lambda: self._switch_view("view_console"),
            "view_scanner": lambda: self._switch_view("view_scanner"),
            "view_sniffer": lambda: self._switch_view("view_sniffer"),
            "view_dash":    lambda: self._switch_view("view_dash"),
            "view_snapshot": lambda: self._switch_view("view_snapshot"),
            "view_logger":  lambda: self._switch_view("view_logger"),
            "view_slave":   lambda: self._switch_view("view_slave"),
        }

    def _dispatch_command(self, cmd_id: str):
        """Run the handler for a triggered command (button click or shortcut)."""
        handler = self._command_handlers.get(cmd_id)
        if handler is not None:
            handler()

    def _setup_shortcuts(self):
        # Global shortcuts come straight from the command registry: one
        # descriptor declares the key, and it dispatches through the same
        # handler map the toolbar buttons use — no second list to keep in sync.
        for cmd in commands.SHORTCUTS:
            QShortcut(QKeySequence(cmd.shortcut), self).activated.connect(
                lambda cid=cmd.cmd_id: self._dispatch_command(cid))

    # ===========================================================
    #  TOOLBAR / STATUS BAR HANDLERS
    # ===========================================================

    def _toggle_connection(self):
        core = self.modbus_core
        # isRunning() covers the two moments is_running does not: the port is
        # still opening, or the thread is still winding down after a stop.
        # Calling start() on a live QThread silently does nothing, so a quick
        # Disconnect→Connect used to leave the button dead.
        if core.is_running or core.isRunning():
            core.stop()
            core.wait(3000)
            return
        from core import transports
        if transports.is_network(self.settings):
            # Nothing to connect to yet: ask for the address where it is typed.
            if not transports.host_value(self.settings):
                self.conn_card.open_below(self.main_toolbar.btn_link)
                return
        else:
            # One port, one owner: the slave emulator may be serving this port.
            busy = self.slave_view.serving_port()
            if busy and busy.casefold() == str(self.settings.get("port", "")).casefold():
                themed_info(self, self.ctx.theme, "warning", self.t("slvBusyTitle"),
                            self.t("slvMasterBusyText").format(port=busy))
                return
        core.setup_connection(self.settings, self.settings.get("slave_id", 10))
        core.update_profile(self.profile_data)
        core.start()

    # ── the connection card ───────────────────────────────────────────
    def _toggle_conn_card(self):
        card = self.conn_card
        if card.isVisible():
            card.hide()
        else:
            card.open_below(self.main_toolbar.btn_link)

    def _apply_link(self, link: dict):
        """Store a link from the card (persisted) and show it everywhere."""
        self.ctx.update(dict(link))
        try:
            self.status_bar.set_slave_id(int(self.settings.get("slave_id", 10)))
        except (TypeError, ValueError):
            pass
        self._refresh_link_label()
        for console in self._consoles():
            console.sync_transport()

    def _connect_with(self, link: dict):
        """Card → Connect / Reconnect: apply the link, (re)open it."""
        core = self.modbus_core
        self._apply_link(link)
        if core.is_running or core.isRunning():
            core.stop()
            core.wait(3000)
        self._toggle_connection()

    def _disconnect(self):
        core = self.modbus_core
        if core.is_running or core.isRunning():
            self._toggle_connection()

    def _on_link_committed(self, link: dict):
        """The card closed with a changed link: keep it for the next connect."""
        self._apply_link(link)
        if self.modbus_core.is_running:
            self._log("SYS", self.t("logReconnectToApply"))

    def _on_open_failed(self, kind: str, text: str):
        """The link did not open: show the card with the reason in words —
        unless the window is not on screen (then the log line is enough)."""
        if self.isVisible() and not self.isMinimized():
            self.conn_card.open_below(self.main_toolbar.btn_link, failure=(kind, text))

    def _find_on_network(self):
        self._switch_view("view_scanner")
        if self._overlay_page is None:
            self.scanner_view.show_network_mode()

    def _consoles(self) -> list:
        return [c for c in (getattr(self.log_panel, "console", None),
                            getattr(self.console_view, "console", None)) if c is not None]

    def _refresh_link_label(self):
        """The link everywhere it is shown: the header chip ("COM3 · 9600 ·
        8E1 · ID 10", "TCP · 192.168.1.20:502 · ID 1"), the status bar's
        ID field (its range follows the transport)."""
        from core import transports
        s = self.settings
        text = transports.summary(s)
        if transports.is_network(s) and not transports.host_value(s):
            text = f"{transports.active(s).label} · {self.t('connNoHost')}"
        self.status_bar.lbl_params.setText(text)
        self.status_bar.set_id_range(*transports.id_range(s))
        self.main_toolbar.set_link_text(text + f" · ID {s.get('slave_id', 10)}")

    _STYLE_KEYS = ("theme", "font_family", "font_size", "accent", "scheme",
                   "contrast")

    # ── views + embedded-overlay helpers ───────────────────────────

    def _view_pages(self) -> dict:
        return {"view_table": self.main_view,
                "view_console": self.console_view,
                "view_scanner": self.scanner_view,
                "view_sniffer": self.sniffer_view,
                "view_dash": self.dash_view,
                "view_snapshot": self.snapshot_view,
                "view_logger": self.logger_view,
                "view_slave": self.slave_view,
                "view_macros": self.macro_view}

    def _switch_view(self, view_id: str):
        """Show one of the persistent nav pages (table / console / slave).

        An open overlay (settings / editor) is closed through reject() first so
        its unsaved-changes prompt still fires; if the user cancels there, the
        view is NOT switched."""
        if self._overlay_page is not None:
            self._overlay_page.reject()
            if self._overlay_page is not None:
                return                      # user chose to stay in the overlay
        page = self._view_pages().get(view_id, self.main_view)
        self.content_stack.setCurrentWidget(page)
        self._current_view = view_id
        self._set_nav(view_id)
        self._park_focus(page)

    def _park_focus(self, page=None):
        """Give focus to the page itself (the map: its table). Otherwise Qt
        hands it to the first input on the page, and a page opened with a
        caret blinking in its first field — under a highlighted border —
        looks like the app wants something typed there."""
        page = page or self.content_stack.currentWidget()
        target = self.register_table if page is self.main_view else page
        if target.focusPolicy() == Qt.FocusPolicy.NoFocus:
            target.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        target.setFocus(Qt.FocusReason.OtherFocusReason)

    def _set_nav(self, nav_id: str):
        """The rail highlight and the header title follow the page on screen."""
        self.nav_rail.set_active_view(nav_id)
        self.main_toolbar.set_active_view(nav_id)

    def _focus_search(self):
        """Ctrl+F: jump to the register search box (Table view)."""
        self._switch_view("view_table")
        if self._overlay_page is not None:
            return                          # user cancelled leaving the overlay
        self.search_input.setFocus()
        self.search_input.selectAll()

    def _show_overlay(self, widget, nav_id: str | None = None):
        """Embed *widget* (a QDialog) as a page in the content stack and show it.

        Only one overlay may be active at a time. The previous one (if any) is
        discarded first. *nav_id* highlights the matching toolbar button while
        the overlay is open ("view_map" / "settings")."""
        if self._overlay_page is not None:
            self._close_overlay()
        # Treat the dialog as a plain embedded widget, not a top-level window.
        widget.setWindowFlags(Qt.WindowType.Widget)
        self._overlay_page = widget
        self.content_stack.addWidget(widget)
        self.content_stack.setCurrentWidget(widget)
        if nav_id:
            self._set_nav(nav_id)

        # Esc: with focus inside the page, QDialog's own Escape handling calls
        # reject() — AFTER the focused child had its chance (an in-cell editor
        # cancels its edit first). With focus nowhere or outside the page —
        # what Windows hands back after Alt+Tab — keyPressEvent below closes
        # it. The scoped QShortcut used before fired only while a child of
        # the page held focus, so after Alt+Tab Esc did nothing.
        widget.setFocus()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape and self._overlay_page is not None:
            self._overlay_page.reject()
            event.accept()
            return
        super().keyPressEvent(event)

    def changeEvent(self, event):
        super().changeEvent(event)
        # Back from Alt+Tab: put the focus back INTO an open page, so its keys
        # (Esc, Ctrl+Z in the editor…) reach it without a click first.
        if (event.type() == event.Type.ActivationChange and self.isActiveWindow()
                and self._overlay_page is not None):
            fw = QApplication.focusWidget()
            page = self._overlay_page
            if fw is None or (fw is not page and not page.isAncestorOf(fw)):
                page.setFocus()

    def _close_overlay(self):
        """Switch back to the underlying view and drop the overlay page."""
        page = self._overlay_page
        self._overlay_page = None
        base = self._view_pages().get(self._current_view, self.main_view)
        self.content_stack.setCurrentWidget(base)
        self._set_nav(self._current_view)
        if page is not None:
            self.content_stack.removeWidget(page)
            page.deleteLater()

    def _go_to_register_map(self):
        """Brand-logo click: return to the main register-map view.

        If an overlay (settings / profile editor) is open, route through its
        reject() so any unsaved-changes prompt still fires; otherwise just
        make sure the register map is the visible page."""
        if self._overlay_page is not None:
            self._overlay_page.reject()
            if self._overlay_page is not None:
                return
        self._switch_view("view_table")

    def _open_settings(self):
        if isinstance(self._overlay_page, SettingsDialog):
            return  # already open
        dlg = SettingsDialog(self.settings, self)
        dlg.accepted.connect(lambda: self._on_settings_accepted(dlg))
        # Live preview: the appearance is applied to the WHOLE window while
        # the dialog is open, and rolled back if the user cancels. Judging a
        # colour scheme from a swatch in a settings row is impossible.
        dlg.appearance_changed.connect(self._preview_appearance)
        dlg.rejected.connect(self._cancel_appearance_preview)
        self._show_overlay(dlg, nav_id="settings")

    def _preview_appearance(self, values: dict):
        """Restyle from *values* WITHOUT touching saved settings."""
        from gui import theme_manager
        merged = dict(self.settings)
        merged.update(values)
        self._preview_active = True
        theme_manager.set_active(merged.get("scheme"), merged.get("contrast"),
                                 merged.get("accent"))
        from gui.styles import get_stylesheet
        qss = get_stylesheet(
            merged.get("theme", "Dark"),
            merged.get("font_family", "Inter, Segoe UI, system-ui, sans-serif"),
            merged.get("font_size", 9), merged.get("accent"))
        app = QApplication.instance()
        if qss == app.styleSheet():
            # Re-setting an identical sheet still walks and repolishes every
            # widget in the app — hundreds of milliseconds to arrive back at
            # the pixels already on screen. Landing on the appearance you
            # already have is common (click a scheme, click it again, flip
            # theme and flip back), so it is worth one string compare.
            return
        self.setUpdatesEnabled(False)
        try:
            app.setStyleSheet(qss)
            self._repaint_custom_widgets(merged)
        finally:
            self.setUpdatesEnabled(True)

    def _cancel_appearance_preview(self):
        """Cancel/Esc: put the saved appearance back before closing."""
        # Close FIRST. The settings page is several hundred widgets and the
        # restyle below repolishes every one of them — for a page that is
        # about to be destroyed. Same reasoning as _on_settings_accepted.
        self._close_overlay()
        if getattr(self, "_preview_active", False):
            self._preview_active = False
            self.ctx.sync_appearance()
            later(0, self, self._apply_settings, True)

    def _repaint_custom_widgets(self, values: dict):
        """Hand-painted widgets read tokens directly, so a stylesheet swap
        alone leaves them on the old palette."""
        theme, accent = values.get("theme", "Dark"), values.get("accent")
        self.main_toolbar.apply_theme(theme, accent)
        self.nav_rail.apply_theme(theme, accent)
        from gui import theme_manager
        self.status_bar.apply_theme(theme_manager.get_theme(theme, accent))
        self.trends_manager.set_theme(theme)
        self.dash_view.apply_settings()
        self.register_table.apply_settings()
        self.update()

    def _on_settings_accepted(self, dlg):
        prev_lang  = self.lang
        prev_style = {k: self.settings.get(k) for k in self._STYLE_KEYS}
        new_values = dlg.get_new_settings()
        # Close the overlay NOW, apply on the next event-loop pass — after the
        # dialog's deleteLater has actually run. The app-wide setStyleSheet in
        # _apply_settings repolishes every live widget, and repolishing the
        # settings page (300-item font combo, sliders, swatches) made a font
        # change take seconds. Deleting it mid-signal would be a use-after-free
        # (the dialog's accept() is still on the stack), hence the deferral.
        self._close_overlay()
        later(0, self, self._finish_settings_apply, new_values, prev_lang,
              prev_style)

    # Connection parameters are read when the port OPENS (setup_connection).
    _LINK_KEYS = ("transport", "port", "baudrate", "parity", "stopbits",
                  "host", "tcp_port", "timeout", "poll_rate", "interframe_delay", "retry_count",
                  "auto_reconnect", "reconnect_interval")

    def _finish_settings_apply(self, new_values, prev_lang, prev_style):
        prev = {k: self.settings.get(k)
                for k in self._LINK_KEYS + ("show_log", "log_height", "graph_width")}
        # ctx.update merges + persists, and re-derives the translator if the
        # language key changed — so self.lang / self.t already reflect the new
        # language by the time we refresh the UI below.
        self.ctx.update(new_values)
        restyle = any(self.settings.get(k) != prev_style[k] for k in self._STYLE_KEYS)
        self._apply_settings(restyle=restyle)
        self.update_ctl.apply_settings()

        # The Журнал / Графики pages hold layout settings. They used to be
        # read only at startup — and _save_window_geometry overwrote them on
        # exit, so changing them in Settings did nothing at all.
        show_log = bool(self.settings.get("show_log", True))
        if show_log != bool(prev["show_log"]) or (
                show_log and self.settings.get("log_height") != prev["log_height"]):
            self.main_toolbar.set_layout_state(log=show_log)
            self._on_log_toggled(show_log)
        if (self.settings.get("graph_width") != prev["graph_width"]
                and self.trends_manager.active_trends):
            self._update_trends_visibility()

        if self.modbus_core.is_running and any(
                self.settings.get(k) != prev[k] for k in self._LINK_KEYS):
            self._log("SYS", self.t("logReconnectToApply"))

        if self.lang != prev_lang:
            self.main_toolbar._lang = self.lang
            self.main_toolbar._refresh_lang_btns()
            self._retranslate_ui()

        new_theme  = self.settings.get("theme", "Dark")
        new_accent = self.settings.get("accent", "neutral")
        if self.main_toolbar._theme != new_theme or self.main_toolbar._accent != new_accent:
            self.main_toolbar.apply_theme(new_theme, new_accent)
        self.nav_rail.apply_theme(new_theme, new_accent)

    # ── watch window ───────────────────────────────────────────────
    def _toggle_watch_window(self):
        w = self.watch_window
        if w.isVisible():
            w.hide()
        else:
            w.show()
            w.raise_()

    def _toggle_watch_register(self, addr: int):
        if self.watch_window.toggle(addr):
            self._show_watch()

    def _add_watch_register(self, addr: int):
        self.watch_window.add(addr)
        self._show_watch()

    def _show_watch(self):
        """Adding a register is feedback enough to open the window."""
        if not self.watch_window.isVisible():
            self.watch_window.show()
        self.watch_window.raise_()

    def _open_macros(self):
        """Show the macros page (Ctrl+M)."""
        self._switch_view("view_macros")
        if self._current_view != "view_macros":
            return                        # an overlay refused to close
        # First-time visitors get the coach-mark tour automatically (#50).
        if not self.settings.get("guide_seen_macros"):
            self.settings["guide_seen_macros"] = True
            save_settings(self.settings)
            later(450, self.macro_window, self.macro_window._show_guide)

    # ── interactive help / onboarding guide ────────────────────────
    def _show_help(self):
        """Launch the coach-mark guide for whatever context is active.

        There is exactly one Help button (in the top bar). It is context-aware:
        when the profile editor or settings overlay is open, it shows *that*
        page's guide; otherwise it shows the main register-map guide.
        """
        # Only one guide at a time. A finished guide clears _guide (see below),
        # so a stale-but-deleted reference can't block reopening via F1/Help.
        if getattr(self, "_guide", None) is not None:
            return
        # Delegate to the active overlay's own guide when one is open.
        page = self._overlay_page
        if page is not None and hasattr(page, "_show_guide"):
            page._show_guide()
            return
        # …otherwise to the visible base view, so F1 explains the scanner while
        # you are IN the scanner rather than the register map you left behind.
        view = self._view_pages().get(self._current_view)
        if view is not None and hasattr(view, "_show_guide"):
            view._show_guide()
            return
        from gui.onboarding import OnboardingGuide
        tb = self.main_toolbar
        ru = self.lang == "ru"
        L = lambda r, e: r if ru else e
        steps = [
            {"target": None,
             "title": L("Добро пожаловать в ModbusReader",
                        "Welcome to ModbusReader"),
             "body":  L("Краткий тур по основным кнопкам. Листайте «Далее», "
                        "или нажмите «Пропустить» — гайд всегда можно открыть "
                        "кнопкой «Справка» (F1).",
                        "A quick tour of the main controls. Use Next, or hit "
                        "Skip — you can reopen this guide anytime with the "
                        "Help button (F1).")},
            {"target": self.nav_rail,
             "title": {"top": L("Все экраны — сверху", "Every page is at the top"),
                       "right": L("Все экраны — справа", "Every page is on the right"),
                       }.get(self.nav_rail.position,
                             L("Все экраны — слева", "Every page is on the left")),
             "body":  L("Сначала — «Мониторинг»: карта регистров и дашборд. "
                        "Дальше — инструменты: консоль, сканер, сниффер, снимки, "
                        "логгер, макросы, эмулятор. Зелёная точка у пункта — "
                        "инструмент работает в фоне. Правый щелчок по меню — "
                        "поставить его слева, справа или сверху, оставить "
                        "только значки, убрать лишние пункты. Горячие клавиши: "
                        "Ctrl+1…9.",
                        "Monitor first: the register map and the dashboard. "
                        "Then the tools: console, scanner, sniffer, "
                        "snapshots, logger, macros, emulator. A green dot means "
                        "the tool is working in the background. Right-click "
                        "the menu to put it on the left, right or top, keep "
                        "icons only, or drop pages you do not use. Shortcuts: "
                        "Ctrl+1…9.")},
            {"target": [tb.btn_link, tb.btn_connect],
             "title": L("Подключение к устройству", "Connect to the device"),
             "body":  L("Слева — с чем программа будет говорить: порт, скорость, "
                        "формат кадра и адрес прибора (щелчок открывает "
                        "настройки связи). «Подключить» открывает порт и "
                        "запускает опрос. Горячая клавиша: F5.",
                        "On the left, what the app will talk to: port, speed, "
                        "framing and device address (click to open the link "
                        "settings). Connect opens the port and starts polling. "
                        "Shortcut: F5.")},
            {"target": self.btn_profile,
             "title": L("Проект", "Project"),
             "body":  L("Проект хранит карту регистров, дашборды и параметры "
                        "связи вместе. Здесь же — открыть или создать отдельную "
                        "карту (.json). Горячие клавиши: Ctrl+N / Ctrl+O / "
                        "Ctrl+S.",
                        "A project keeps the register map, the dashboards and "
                        "the link settings together. This menu also opens or "
                        "creates a stand-alone map (.json). Shortcuts: "
                        "Ctrl+N / Ctrl+O / Ctrl+S.")},
            {"target": self.main_toolbar.btn_settings,
             "title": L("Настройки", "Settings"),
             "body":  L("Параметры подключения, опроса, внешнего вида и языка. "
                        "Горячая клавиша: Ctrl+,",
                        "Connection, polling, appearance and language options. "
                        "Shortcut: Ctrl+,")},
            {"target": self.nav_rail.btn_view_macros,
             "title": L("Макросы", "Macros"),
             "body":  L("Автоматизация: Python-скрипты, которые читают и пишут "
                        "регистры и собирают таблицу результатов. Запущенный "
                        "макрос продолжает работать, пока вы на других "
                        "экранах. Горячая клавиша: Ctrl+M.",
                        "Automation: Python scripts that read and write "
                        "registers and build a results table. A running macro "
                        "keeps going while you are on other pages. "
                        "Shortcut: Ctrl+M.")},
            {"target": self.nav_rail.btn_help,
             "title": L("Справка", "Help"),
             "body":  L("Эта кнопка открывает гайд снова в любой момент. "
                        "Готово — приятной работы!",
                        "This button reopens the guide anytime. "
                        "That's it — enjoy!")},
        ]
        self._guide = OnboardingGuide(
            self.centralWidget(), steps,
            self.settings.get("theme", "Dark"),
            self.settings.get("accent", "neutral"),
            self.lang)
        # Drop the reference once it closes so F1 / Help can reopen it.
        self._guide.finished.connect(lambda: setattr(self, "_guide", None))
        self._guide.show_guide()

    def _maybe_show_onboarding(self):
        """Auto-open the main guide once, on the very first launch. The
        guide_seen_main flag is persisted so it never reappears unprompted;
        the Help button / F1 still open it on demand."""
        self.settings["guide_seen_main"] = True
        save_settings(self.settings)
        self._show_help()

    def _apply_settings(self, restyle: bool = True):
        # Re-applying the global stylesheet repolishes the whole widget tree —
        # the slow part. Freeze repaints for the whole batch so Qt paints ONCE
        # at the end instead of after each of setStyleSheet / log rebuild /
        # trend re-theme (that stacking was the 1-2 s theme-switch stall).
        self.setUpdatesEnabled(False)
        try:
            if restyle:
                theme = self.settings.get("theme", "Dark")
                qss = self.ctx.stylesheet()
                app = QApplication.instance()
                # Re-setting an identical sheet still repolishes every widget;
                # the live preview has often applied this exact sheet already.
                if qss != app.styleSheet():
                    app.setStyleSheet(qss)
                self.trends_manager.set_theme(theme)
                tok = self.ctx.theme_tokens()
                self._search_icon_lbl.setPixmap(icons.pixmap("search", tok["text_4"], 14))
                self.btn_profile.setIcon(icons.icon("project", tok["text_2"], 15))
                self.btn_profile.set_chevron_color(tok["text_3"])
                self.btn_edit_map.setIcon(icons.icon("edit", tok["text_2"], 15))
                self.map_empty.apply_theme(tok)
            self.trends_manager.default_window_sec = self.settings.get("default_window_sec", 30)
            self.trends_manager.history_len = self.settings.get("trend_history", 1200)

            # Table appearance (row numbers, column visibility, zebra, row height,
            # state-dot theme, mono values, change highlighting) — in the table.
            self.register_table.apply_settings()
            self._apply_rail_settings()
            # Log: buffer cap / verbosity / autoscroll + re-render with the new
            # theme colors (apply_settings() already rebuilds — no double pass).
            self.log_panel.apply_settings()
            self.trends_manager.apply_settings()
            self.console_view.apply_settings()
            self.scanner_view.apply_settings()
            self.sniffer_view.apply_settings()
            self.dash_view.apply_settings()
            self.snapshot_view.apply_settings()
            self.logger_view.apply_settings()
            self.slave_view.apply_settings()
            self.watch_window.apply_settings()
            self.status_bar.apply_theme(self.ctx.theme_tokens())
            self.conn_card.apply_theme()
            for console in self._consoles():
                console.sync_transport()
            win = getattr(self, "macro_window", None)
            if win is not None and hasattr(win, "apply_theme"):
                win.apply_theme()
        finally:
            self.setUpdatesEnabled(True)
        self._refresh_link_label()

    def _open_profile_menu(self):
        """The head-bar dropdown.

        PROJECT FIRST, deliberately. A project is the whole workspace —
        connection, register map, every dashboard — and it is what someone
        should reach for. The bare register map is one part of a project that
        also happens to be openable on its own; useful once you know why you
        want it, confusing as the first thing you meet. So the map actions sit
        below the project ones, under their own heading, and the heading says
        what a project is."""
        t = self.t
        m = QMenu(self)
        c = self.ctx.theme_tokens()

        def section(label):
            """A quiet caption, not a sentence in capitals.

            Section labels in a menu are signposts: two words, muted, no
            punctuation. A full explanatory sentence set in caps reads like a
            warning banner — the explanation belongs in the tooltip, where it
            costs nothing until someone wants it."""
            act = m.addAction(label)
            act.setEnabled(False)
            f = act.font()
            f.setPointSize(max(7, f.pointSize() - 1))
            act.setFont(f)
            return act

        def entry(menu, label, handler, shortcut="", icon="", tip=""):
            # "\t" puts the key in Qt's right-aligned shortcut column, which
            # is what makes a menu read as a real application menu.
            act = menu.addAction(f"{label}\t{shortcut}" if shortcut else label)
            if icon:
                act.setIcon(icons.icon(icon, c["text_2"], 14))
            if tip:
                act.setToolTip(tip)
            act.triggered.connect(handler)
            return act

        section(t("projectSection"))
        entry(m, t("projectNew"), self._new_project, "Ctrl+N", "plus",
              t("projectSectionTip"))
        entry(m, t("projectOpen"), lambda: self._open_project(), "Ctrl+O",
              "folder")
        entry(m, t("projectSave"), self._save_project, "Ctrl+S", "save")
        entry(m, t("projectSaveAs"), self._save_project_as, icon="download")

        projects = [p for p in self.settings.get("recent_projects", [])
                    if p != self.project_path]
        if projects:
            sub = m.addMenu(t("projectRecent"))
            for path in projects:
                entry(sub, os.path.basename(path) or path,
                      lambda _c=False, p=path: self._open_project(p), tip=path)

        m.addSeparator()
        section(t("mapSection"))
        # Never disabled: a disabled item is styled as a section caption here.
        # With no map loaded it simply opens an empty editor.
        entry(m, t("mapEdit"), self._open_map_editor, "Ctrl+2", "edit",
              t("mapEditTip"))
        entry(m, t("createNew"), self._create_config, "Ctrl+Shift+N", "plus",
              t("mapSectionTip"))
        entry(m, t("openExisting"), self._open_profile, "Ctrl+Shift+O", "folder")

        recent = self.settings.get("recent_profiles", [])
        if recent:
            sub = m.addMenu(t("recent"))
            for path in recent:
                entry(sub, os.path.basename(path) or path,
                      lambda _c=False, p=path: self._open_recent_profile(p),
                      tip=path)

        m.exec(self.btn_profile.mapToGlobal(
            self.btn_profile.rect().bottomLeft()))

    # ── project identity ─────────────────────────────────────────────
    def _set_project(self, path: str = "", name: str = ""):
        """Record which project is open and show it in the head bar.

        Naming the open project on screen is most of the fix for "I cannot
        tell what is going on": before this the window looked identical
        whether you were inside a project or not."""
        self.project_path = path or ""
        self.project_name = name or (
            os.path.splitext(os.path.basename(path))[0] if path else "")
        self.settings["last_project_path"] = self.project_path
        self.settings["last_project_name"] = self.project_name
        self._refresh_project_button()

    def _refresh_project_button(self):
        if not hasattr(self, "btn_profile"):
            return
        label = self.project_name or self.t("projectNone")
        self.btn_profile.setText(f"  {label}")
        self.btn_profile.setToolTip(self.project_path or self.t("projectNoneTip"))
        self._refresh_window_title()

    def _refresh_window_title(self):
        """"plant — ModbusReader": the document first, like every desktop
        app (it is what the taskbar and Alt+Tab show)."""
        doc = self.project_name or (
            os.path.splitext(os.path.basename(self.profile_path))[0]
            if getattr(self, "profile_path", "") else "")
        app = self.t("appName")
        self.setWindowTitle(f"{doc} — {app}" if doc else app)

    def _push_recent_project(self, path: str):
        from app.settings_manager import RECENT_MAX
        recent = [p for p in self.settings.get("recent_projects", []) if p != path]
        recent.insert(0, path)
        del recent[RECENT_MAX:]
        self.settings["recent_projects"] = recent

    def _new_project(self):
        """Start an empty workspace: no register map, one blank dashboard.

        Connection settings are KEPT. They describe the bench you are sitting
        at, not the project — wiping the port and baud rate every time someone
        starts a new project would be hostile."""
        if self._overlay_page is not None:
            self._overlay_page.reject()
            if self._overlay_page is not None:
                return
        has_work = bool(self.profile_data) or any(
            b.get("widgets") for b in self.dash_view.all_boards())
        if has_work:
            # There is no dirty flag for a project, so this asks every time
            # rather than pretending to know whether the work was saved.
            choice = themed_message(
                self, self.ctx.theme, "warning",
                self.t("projectNewTitle"), self.t("projectNewBody"),
                [(self.t("projectNewOk"), QMessageBox.ButtonRole.AcceptRole, False),
                 (self.t("cancel"), QMessageBox.ButtonRole.RejectRole, True)])
            if choice != 0:
                return
        self._set_profile([], "")
        self.dash_view.load_boards([])
        self._set_project("", self.t("projectUntitled"))
        self._switch_view("view_table")
        save_settings(self.settings)
        self._log("SYS", self.t("projectNewDone"))

    def _save_shortcut(self):
        """Ctrl+S saves the document in front of you: the map while its editor
        is open, otherwise the project."""
        page = self._overlay_page
        if (page is not None and hasattr(page, "_save")
                and hasattr(page, "get_profile_data")):
            page._save()
            return
        self._save_project()

    # ── project (.mbproj): connection + profile + dashboards + layout ──
    def _save_project(self):
        """Ctrl+S on a project: overwrite the file it came from.

        Only a project that has never been written asks where to go. Making
        every save re-prompt for a name and a folder is what made the project
        feel like an export step rather than the thing you are working in."""
        if self.project_path:
            return self._write_project(self.project_path,
                                       self.project_name
                                       or os.path.splitext(os.path.basename(
                                           self.project_path))[0])
        self._save_project_as()

    def _save_project_as(self):
        default = (self.project_name
                   or (os.path.splitext(os.path.basename(self.profile_path))[0]
                       if self.profile_path else "project"))
        name, ok = themed_input(self, self.ctx.theme,
                                self.t("projectSaveAs").rstrip("…."),
                                self.t("projectName"), default,
                                ok_label=self.t("continueAction"),
                                cancel_label=self.t("cancel"))
        if not ok:
            return
        name = name.strip() or default
        path, _ = QFileDialog.getSaveFileName(
            self, self.t("projectSaveAs"), f"{name}.mbproj",
            "ModbusReader project (*.mbproj)")
        if not path:
            return
        self._write_project(path, name)

    def _write_project(self, path: str, name: str):
        try:
            self._save_window_geometry()          # fresh layout numbers
            formats.dump_project(path, name, self.settings, self.profile_data,
                                 self.dash_view.all_boards())
        except Exception as e:
            themed_info(self, self.ctx.theme, "error", self.t("errTitle"),
                        f"{type(e).__name__}: {e}")
            return
        self._set_project(path, name)
        self._push_recent_project(path)
        save_settings(self.settings)
        self._log("SYS", self.t("projectSaved").format(path=path))

    def _open_project(self, path: str = ""):
        if self._overlay_page is not None:
            self._overlay_page.reject()
            if self._overlay_page is not None:
                return
        if not path:
            path, _ = QFileDialog.getOpenFileName(
                self, self.t("projectOpen"), "",
                self.t("filterProject") + " (*.mbproj);;JSON (*.json)")
        if not path:
            return
        if not os.path.exists(path):
            themed_info(self, self.ctx.theme, "warning",
                        self.t("errNotFoundTitle"),
                        self.t("errNotFoundText").format(path=path))
            self.settings["recent_projects"] = [
                p for p in self.settings.get("recent_projects", []) if p != path]
            save_settings(self.settings)
            return
        try:
            proj = formats.load_project(path)
        except Exception as e:
            # A bare register map picked in the project dialog (it offers
            # *.json) is still something the operator can use — open it as
            # the map instead of refusing it.
            try:
                load_profile_data(path)
            except Exception:
                themed_info(self, self.ctx.theme, "error", self.t("errTitle"),
                            f"{type(e).__name__}: {e}")
                return
            self._log("SYS", self.t("logOpenedAsMap").format(
                name=os.path.basename(path)))
            self._load_profile(path)
            return
        self.apply_project(proj)
        self._set_project(path, proj.get("name") or "")
        self._push_recent_project(path)
        save_settings(self.settings)
        self._log("SYS", self.t("projectLoaded").format(path=path))

    def apply_project(self, proj: dict, persist: bool = True):
        """Restore a whole workspace: connection settings, the register map and
        every dashboard. The port is NOT reopened automatically — the operator
        decides when to connect."""
        conn = proj.get("connection") or {}
        if conn:
            self.ctx.settings.update({k: v for k, v in conn.items() if v is not None})
            self.ctx.update({})          # codecs + appearance re-derived, saved
        try:
            self.status_bar.set_slave_id(int(self.settings.get("slave_id", 10)))
        except (TypeError, ValueError):
            pass
        regs = (proj.get("profile") or {}).get("registers") or []
        self._set_profile(regs, "")
        self.dash_view.load_boards(proj.get("dashboards") or [])
        layout = proj.get("layout") or {}
        if layout.get("pinned_views"):
            # Kept for file compatibility; the rail shows every page.
            self.settings["pinned_views"] = list(layout["pinned_views"])
        self._apply_settings(restyle=False)
        if persist:
            save_settings(self.settings)

    def _open_profile(self):
        # Loading a profile behind an open editor/settings overlay is
        # confusing — close it first (its unsaved-changes prompt may cancel).
        if self._overlay_page is not None:
            self._overlay_page.reject()
            if self._overlay_page is not None:
                return
        try:
            path, _ = QFileDialog.getOpenFileName(
                self, self.t("openProfile"), "", self.t("filterMap") + " (*.json)"
            )
        except Exception as e:
            import traceback
            traceback.print_exc()
            themed_info(self, self.ctx.theme, "error", self.t("errTitle"),
                        self.t("errFileDialog").format(
                            err=f"{type(e).__name__}: {e}"))
            return
        if path:
            self._load_profile(path)

    def _open_recent_profile(self, path: str):
        """Open a profile chosen from the Profile ▸ Recent submenu."""
        if not path:
            return
        if not os.path.exists(path):
            themed_info(self, self.ctx.theme, "warning",
                        self.t("errNotFoundTitle"),
                        self.t("errNotFoundText").format(path=path))
            # Drop the dead entry from the recent list.
            recent = [p for p in self.settings.get("recent_profiles", []) if p != path]
            self.settings["recent_profiles"] = recent
            save_settings(self.settings)
            return
        self._load_profile(path)

    def _push_recent(self, path: str):
        """Move *path* to the front of the recent-profiles list (deduped, capped)."""
        from app.settings_manager import RECENT_MAX
        recent = [p for p in self.settings.get("recent_profiles", []) if p != path]
        recent.insert(0, path)
        del recent[RECENT_MAX:]
        self.settings["recent_profiles"] = recent

    def _on_slave_id_changed(self, val: int):
        self.settings["slave_id"] = val
        save_settings(self.settings)
        if self.modbus_core.is_running:
            self.modbus_core.slave_id = val
        self._refresh_link_label()          # the header chip shows the ID too
        self._log("SYS", self.t("logSlaveId").format(sid=val))

    def _on_theme_changed(self, theme: str):
        self.settings["theme"] = theme
        save_settings(self.settings)
        self._apply_settings()
        self.main_toolbar.apply_theme(theme, self.settings.get("accent", "neutral"))
        self.nav_rail.apply_theme(theme, self.settings.get("accent", "neutral"))

    def _on_lang_changed(self, lang: str):
        self.ctx.set_lang(lang)   # updates lang + translator + settings["lang"]
        self.ctx.save()
        self._retranslate_ui()

    def _retranslate_ui(self):
        t = self.t
        self._refresh_window_title()
        self.main_toolbar.retranslate_ui(t)
        self.main_toolbar.set_connect_state(self.modbus_core.is_running, t)
        self.nav_rail.retranslate_ui(t)
        if hasattr(self, "map_empty"):
            self.map_empty.set_content(t("emptyMapTitle"), t("emptyMapBody"))
            for b, key in zip(self.map_empty.buttons,
                              ("emptyOpenProject", "emptyOpenMap", "emptyNewMap",
                               "emptyDemo")):
                b.setText(t(key))
        if hasattr(self, "btn_edit_map"):
            self.btn_edit_map.setText("  " + t("editMap"))
            self.btn_edit_map.setToolTip(
                f"{t('editMap')}  ({commands.BY_ID['view_map'].shortcut})")

        self.register_table.retranslate()   # headers + register names (ru/en)

        # Register-map head bar
        if hasattr(self, "mh_title"):
            self.mh_title.setText(t("registerMap"))
            self.mh_crumb.setText(t("crumbDevice"))
            # Shows the open project's name, which is not translatable — but
            # the "no project" placeholder is, so re-derive rather than
            # overwrite with a fixed label.
            self._refresh_project_button()
            self.search_input.setPlaceholderText(t("search"))
        # Status bar owns no translator — refresh its texts from here.
        connected = self.modbus_core.is_running
        self.status_bar.set_connection_status(
            connected, t("stConnected" if connected else "stDisconnected"))
        self._refresh_profile_label()
        self._update_badge()
        self._refresh_link_label()
        self.status_bar.set_tooltips(t("statChipTip"), t("sbErrTip"), t("sbLinkTip"))
        self.status_bar.stats_popup.retranslate(t)
        self.conn_card.retranslate(t)
        self._refresh_line_stats()

        # Log tabs
        self.log_panel.retranslate(t)
        self.console_view.retranslate(t)
        self.scanner_view.retranslate(t)
        self.sniffer_view.retranslate(t)
        self.dash_view.retranslate(t)
        self.snapshot_view.retranslate(t)
        self.logger_view.retranslate(t)
        self.slave_view.retranslate(t)
        self.watch_window.retranslate(t)

        if hasattr(self, "trends_manager"):
            self.trends_manager.retranslate(t)
        self._sync_log_chip()

    def _on_graphs_toggled(self, visible: bool):
        width = int(self.settings.get("graph_width", 420))
        target = width if visible else 0
        self.trends_anim = QPropertyAnimation(self.trends_manager, b"maximumWidth")
        self.trends_anim.setDuration(200)
        self.trends_anim.setStartValue(self.trends_manager.width())
        self.trends_anim.setEndValue(target)
        self.trends_anim.start()
        if visible:
            self.h_splitter.setSizes([900, width])
        else:
            self.h_splitter.setSizes([1, 0])

    def _on_log_toggled(self, visible: bool):
        height = int(self.settings.get("log_height", 150))
        target_h = height if visible else 0
        self.log_anim = QPropertyAnimation(self.log_panel, b"maximumHeight")
        self.log_anim.setDuration(180)
        self.log_anim.setStartValue(self.log_panel.height())
        self.log_anim.setEndValue(target_h)
        if visible:
            # The animation pins maximumHeight at `height`. Lift that cap once it
            # finishes so the splitter can freely resize the panel again — without
            # this the log can't be enlarged after a hide→show cycle.
            self.log_anim.finished.connect(
                lambda: self.log_panel.setMaximumHeight(16777215))
        self.log_anim.start()
        if visible:
            self.v_splitter.setSizes([580, height])
        else:
            self.v_splitter.setSizes([1, 0])
        self._sync_log_chip()

    def _on_log_splitter_moved(self, _pos: int = 0, _idx: int = 0):
        """User dragged the terminal edge: remember a real height, and treat a
        drag-to-zero as 'log off' so the toggles stay truthful."""
        h = self.v_splitter.sizes()[1]
        if h > 40:
            self.settings["log_height"] = int(h)
        self.main_toolbar.set_layout_state(log=h > 0)
        self._sync_log_chip()

    def _toggle_log_from_chip(self):
        visible = self.v_splitter.sizes()[1] > 0
        self.main_toolbar.set_layout_state(log=not visible)
        self._on_log_toggled(not visible)

    def _sync_log_chip(self):
        visible = self.v_splitter.sizes()[1] > 0
        self.status_bar.set_log_state(
            visible, self.t("log"), self.ctx.theme_tokens()["text_3"])

    # ===========================================================
    #  PROFILE LOADING → TABLE
    # ===========================================================

    def _load_profile(self, path: str):
        try:
            data = load_profile_data(path)
        except Exception as e:
            self._log("ERR", self.t("logLoadFail").format(path=path, err=e))
            themed_info(self, self.ctx.theme, "error",
                        self.t("errLoadTitle"),
                        self.t("errLoadText").format(
                            path=path, err=f"{type(e).__name__}: {e}"))
            return

        if not data:
            self._log("SYS", self.t("logProfileEmpty").format(path=path))
            themed_info(self, self.ctx.theme, "info",
                        self.t("emptyProfileTitle"),
                        self.t("emptyProfileText"))

        # Hand-edited JSON may store addresses as "0x.." strings; the poll loop
        # and macros expect numeric addresses, so coerce them once here.
        for reg in data:
            if isinstance(reg, dict) and isinstance(reg.get("addr"), str):
                a = reg["addr"].strip()
                try:
                    reg["addr"] = int(a, 0) if a else 0
                except ValueError:
                    reg["addr"] = 0

        try:
            self._set_profile(data, path)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self._log("ERR", self.t("logRenderFail").format(err=e))
            themed_info(self, self.ctx.theme, "error",
                        self.t("errRenderTitle"),
                        self.t("errRenderText").format(
                            err=f"{type(e).__name__}: {e}"))
            return
        self._push_recent(path)
        save_settings(self.settings)

        self._log("SYS", self.t("logProfileLoaded").format(
            name=os.path.basename(path), n=len(data)))
        self._validate_profile(data)

    def _validate_profile(self, data: list):
        """Non-blocking validation: hand-edited JSON can declare overlapping
        address spans or duplicate names — warn in the log, keep loading."""
        for conflict in find_overlaps(data):
            self._log("ERR", f"{self.t('addrOverlaps')}: {conflict}")
        dups = find_duplicate_names(data)
        if dups:
            self._log("ERR", f"{self.t('dupNames')}: {', '.join(dups)}")

    def _set_profile(self, regs: list, path: str = ""):
        """THE one place a register map becomes the current one.

        Everything that shows or uses the map is refreshed from here: the
        table, the poll list, the status bar, the logger's column plan. That
        last one used to be missed — after loading a map the Logger still said
        «open a register map first» until something unrelated refreshed it.

        *path* is the .json the map came from ("" for a project's map or a
        new/edited one). It is also what a restart reopens, so it is cleared
        whenever the map stops being that file."""
        self.profile_data = regs
        self.profile_path = path or ""
        self.settings["last_profile_path"] = self.profile_path
        self.register_table.clear_view_state()
        self.modbus_core.verbose_addrs = set()
        self.register_table.populate(regs)
        self._refresh_table_filter()
        if self.modbus_core.is_running:
            self.modbus_core.update_profile(regs)
        self._refresh_profile_label()
        self.logger_view.refresh_columns()
        self.watch_window.refresh_map()
        self.slave_view.map_changed()

    def _refresh_profile_label(self):
        if self.profile_path:
            text = self.t("stProfile").format(name=os.path.basename(self.profile_path))
        elif self.profile_data:
            text = self.t("stProfileUnsaved").format(n=len(self.profile_data))
        else:
            text = self.t("stNoProfile")
        self.status_bar.lbl_config.setText(text)
        self._refresh_window_title()

    # ===========================================================
    #  MODBUS SIGNAL HANDLERS
    # ===========================================================

    def _on_connection_status(self, connected: bool, message: str):
        self.status_bar.set_connection_status(
            connected, self.t("stConnected" if connected else "stDisconnected"))
        self.main_toolbar.set_connect_state(connected)
        if connected:
            # A link that worked goes to the card's «Недавние».
            import time
            from core import transports
            self.settings["recent_links"] = transports.remember(
                self.settings.get("recent_links"),
                self.modbus_core.settings or self.settings, when=time.time())
        self.conn_card.sync_state()
        self.register_table.set_connected(connected)
        if message:              # a failed open is already logged as ERR
            self._log("SYS", message)
        if not connected:
            self.register_table.mark_all_stale()
            self.watch_window.set_stale_all()

    def _on_data_updated(self, addr: int, val_str: str):
        # The table formats the cell and emits value_sampled for trends.
        self.register_table.update_value(addr, val_str)

    def _refresh_line_stats(self):
        self._refresh_activity()
        self.status_bar.set_line_stats(self.modbus_core.stats.snapshot(), self.t)

    def _reset_line_stats(self):
        self.modbus_core.stats.reset()
        self._refresh_line_stats()

    def _on_log_message(self, level: str, message: str):
        self._log(level, message)

    def _on_array_read_finished(self, addr: int, words: list):
        viewer = self._memory_viewers.get(addr)
        if viewer:
            viewer.set_real_data(words)

    # ===========================================================
    #  TABLE INTENT ROUTING  (signals from gui.register_table.RegisterTable)
    # ===========================================================

    def _on_write_requested(self, addr: int, dtype: str, value: str):
        if not self.modbus_core.is_running:
            self._log("ERR", self.t("logWriteOffline").format(
                addr=f"0x{addr:04X}", value=value))
            return
        self.modbus_core.queue_write(addr, dtype, value)
        self._log("SYS", self.t("logWriteQueued").format(
            addr=f"0x{addr:04X}", type=dtype, value=value))

    def _on_verbose_changed(self, addrs):
        self.modbus_core.verbose_addrs = set(addrs)

    def _on_raw_send(self, frame: bytes):
        """Console frame → the core thread (single owner of the port)."""
        if not self.modbus_core.is_running:
            self._log("ERR", self.t("logRawOffline"))
            return
        self.modbus_core.queue_raw(frame)

    def _on_value_sampled(self, reg_id: str, value: float):
        self.trends_manager.update_trend_data(reg_id, value)
        self.dash_view.update_value(reg_id, value)

    def _on_inspect_requested(self, addr: int, name: str):
        existing = self._memory_viewers.get(addr)
        if existing is not None:
            existing.activateWindow()
            existing.raise_()
            return
        reg_info     = next((r for r in self.profile_data
                             if isinstance(r, dict) and datatypes.reg_key(r) == addr), {})
        length       = reg_info.get("length", 1)
        # The viewer remembers its layout per map; a project's map has no
        # file of its own, so the project name keys it instead.
        profile_name = (os.path.basename(self.profile_path) if self.profile_path
                        else (self.project_name or ""))
        viewer = MemoryViewerDialog(
            addr=addr, length=length, name=name, ctx=self.ctx,
            profile_name=profile_name, parent=None)
        viewer.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        viewer.destroyed.connect(lambda: self._memory_viewers.pop(addr, None))
        self._memory_viewers[addr] = viewer
        viewer.show()

    def _refresh_table_filter(self):
        """Re-apply the active search filter (or refresh the count badge)
        after the table is repopulated."""
        if hasattr(self, "search_input") and self.search_input.text().strip():
            self._filter_table(self.search_input.text())
        else:
            self._update_badge()

    def _reg_by_id(self, reg_id: str) -> dict:
        try:
            key = int(str(reg_id), 16)
        except ValueError:
            return {}
        return next((r for r in self.profile_data
                     if isinstance(r, dict) and datatypes.reg_key(r) == key), {})

    def _add_to_trend(self, reg_id: str, reg_name: str):
        # The card shows the register's unit next to the current value; it
        # used to be dropped here, so a chart of "Temperature" read "21.4".
        unit = str(self._reg_by_id(reg_id).get("unit", "") or "")
        self.trends_manager.add_trend(reg_id, reg_name, unit)
        self._update_trends_visibility()

    def _remove_from_trend(self, reg_id: str):
        self.trends_manager.remove_trend(reg_id)
        self._update_trends_visibility()

    def _update_trends_visibility(self):
        # Keep the table's context-menu state in sync with what's charted.
        self.register_table.set_trended(self.trends_manager.active_trends)
        has_trends = len(self.trends_manager.active_trends) > 0
        try:
            width = max(260, int(self.settings.get("graph_width", 420)))
        except (TypeError, ValueError):
            width = 420
        target = width if has_trends else 0
        self.trends_anim = QPropertyAnimation(self.trends_manager, b"maximumWidth")
        self.trends_anim.setDuration(220)
        self.trends_anim.setStartValue(self.trends_manager.width())
        self.trends_anim.setEndValue(target)
        self.trends_anim.start()
        self.main_toolbar.set_layout_state(graphs=has_trends)
        if has_trends:
            self.h_splitter.setSizes([max(400, self.width() - width), width])
        else:
            self.h_splitter.setSizes([1, 0])

    # ===========================================================
    #  LOG PANEL
    # ===========================================================

    def _log(self, level: str, message: str):
        """Window-side logging entrypoint. One store feeds both the bottom
        panel and the full-screen console view.

        The status-bar error counter counts ERR-level lines. It used to search
        the message for the words "error"/"ошибка", which missed most real
        failures («Соединение потеряно», «Запись не подтверждена») and counted
        harmless lines that merely mentioned an error."""
        self.log_panel.log(level, message)
        if str(level).upper() in ("ERR", "ERROR"):
            self.error_counter += 1
            self.status_bar.set_error_count(self.error_counter)

    # ===========================================================
    #  LIFECYCLE
    # ===========================================================

    def _restore_window_geometry(self):
        """Restore size / position / maximized state saved at last exit."""
        w = int(self.settings.get("win_w") or 1280)
        h = int(self.settings.get("win_h") or 780)
        x, y = self.settings.get("win_x"), self.settings.get("win_y")
        if x is not None and y is not None:
            x, y = int(x), int(y)
        # Only onto a screen that is still there (gui.qt_utils.fit_on_screens).
        app = QApplication.instance()
        primary = app.primaryScreen() if app else None
        screens = ([primary] if primary else []) + [
            s for s in (app.screens() if app else []) if s is not primary]
        x, y, w, h = fit_on_screens(x, y, w, h,
                                    [s.availableGeometry() for s in screens])
        self.resize(w, h)
        if x is not None and y is not None:
            self.move(x, y)
        if self.settings.get("win_maximized"):
            self.setWindowState(self.windowState() | Qt.WindowState.WindowMaximized)

    def _save_window_geometry(self):
        """Persist the full session: geometry, maximized flag, log visibility
        and height, open trend cards, the active view — so the app reopens
        exactly as it was closed."""
        # normalGeometry() is the non-maximized rect — what we want to restore to.
        g = self.normalGeometry()
        self.settings["win_x"] = g.x()
        self.settings["win_y"] = g.y()
        self.settings["win_w"] = g.width()
        self.settings["win_h"] = g.height()
        self.settings["win_maximized"] = self.isMaximized()
        self.settings["show_log"] = self.main_toolbar._log_on
        self.settings["last_view"] = self._current_view
        self.settings["watch_visible"] = self.watch_window.isVisible()
        if self.watch_window.isVisible():
            self.watch_window.save_geometry()
        self.settings["open_trends"] = [
            {"id": c.reg_id, "name": c.reg_name, "unit": c.unit,
             "win": c.window_seconds}
            for c in self.trends_manager.active_trends.values()]
        sizes = self.v_splitter.sizes()
        if len(sizes) == 2 and sizes[1] > 40:
            self.settings["log_height"] = int(sizes[1])

    def _restore_session_state(self):
        """Counterpart of _save_window_geometry for the non-geometry state."""
        # Trend cards — only for registers the restored profile actually has.
        for info in self.settings.get("open_trends", []):
            rid = str(info.get("id", ""))
            try:
                addr = int(rid, 16)
            except ValueError:
                continue
            if addr not in self.register_table.addr_to_row:
                continue
            self.trends_manager.add_trend(rid, str(info.get("name", rid)),
                                          str(info.get("unit", "")))
            card = self.trends_manager.active_trends.get(rid)
            win = info.get("win")
            if card is not None and isinstance(win, int):
                card._set_window(win)
        if self.trends_manager.active_trends:
            self._update_trends_visibility()

        # Log-panel height (the splitter is built with a fixed 150).
        lh = int(self.settings.get("log_height", 150) or 150)
        total = sum(self.v_splitter.sizes()) or 730
        self.v_splitter.setSizes([max(200, total - lh), lh])

        if self.settings.get("watch_visible"):
            later(0, self, self._show_watch)

        # Last active view; the default (map) needs no switch.
        last_view = self.settings.get("last_view", "view_table")
        if last_view != "view_table" and last_view in self._view_pages():
            self._switch_view(last_view)
        self._sync_log_chip()

    def _on_rail_collapsed(self, collapsed: bool):
        self.settings["rail_collapsed"] = bool(collapsed)
        save_settings(self.settings)

    def _on_rail_position(self, position: str):
        self.settings["rail_position"] = position
        save_settings(self.settings)
        self._place_rail()

    def _on_rail_hidden(self, hidden: list):
        self.settings["rail_hidden"] = list(hidden)
        save_settings(self.settings)

    def _place_rail(self):
        """The rail where the user put it: a bar above everything, or a
        column before / after the work area."""
        rail = self.nav_rail
        self._shell.removeWidget(rail)
        self._shell_row.removeWidget(rail)
        if rail.position == "top":
            self._shell.insertWidget(0, rail)
        elif rail.position == "right":
            self._shell_row.addWidget(rail)
        else:
            self._shell_row.insertWidget(0, rail)

    def _apply_rail_settings(self):
        """Settings → Appearance → Menu (position, icons only)."""
        rail = self.nav_rail
        rail.set_position(str(self.settings.get("rail_position", "left")))
        if rail.collapsed != bool(self.settings.get("rail_collapsed", False)):
            rail.set_collapsed(bool(self.settings.get("rail_collapsed")), emit=False)
        self._place_rail()

    def _refresh_activity(self):
        """Busy dots in the rail: a tool working in the background."""
        def alive(w):
            return w is not None and w.isRunning()
        self.nav_rail.set_busy({
            "view_scanner": alive(getattr(self.scanner_view, "_worker", None)),
            "view_sniffer": alive(getattr(self.sniffer_view, "_worker", None)),
            "view_logger": self.logger_view.running,
            "view_slave": self.slave_view.running,
            "view_macros": self.macro_view.running,
        })

    def closeEvent(self, event):
        # The macro window asks before abandoning a running macro or unsaved
        # results; if the operator cancels THERE, the app must stay open too.
        # Before, closing the main window left a running macro thread behind
        # (and the window it belongs to was torn down under it).
        # (quit_for_update has asked this already — the new copy is running
        # by then, so this close must not be cancellable.)
        if not self._closing_for_update and not self.macro_view.confirm_close():
            event.ignore()
            return
        self.update_ctl.shutdown()
        self.macro_view.shutdown()
        self.scanner_view.stop_if_running()
        self.dash_view.stop_if_running()      # kill dashboard automation timers
        self.sniffer_view.stop_if_running()
        self.logger_view.stop_if_running()    # flush + close the CSV
        self.slave_view.stop_if_running()     # release the emulator's port
        if self.modbus_core.is_running or self.modbus_core.isRunning():
            self.modbus_core.stop()
            self.modbus_core.wait(3000)
        for viewer in list(self._memory_viewers.values()):
            viewer.close()
        self._save_window_geometry()
        save_settings(self.settings)
        super().closeEvent(event)

    def quit_for_update(self, args: list) -> bool:
        """Start the downloaded update (*args*, see updater.handover_args) and
        exit so it can replace this copy.

        Everything a normal close would ask is asked FIRST — an open editor's
        unsaved map, a running macro: once the new copy is running, this one
        has to go. If the start itself fails nothing is closed."""
        from core import updater
        if self._overlay_page is not None:
            self._overlay_page.reject()
            if self._overlay_page is not None:
                return False
        if not self.macro_view.confirm_close():
            return False
        try:
            updater.start_detached(args)
        except OSError as e:
            themed_info(self, self.ctx.theme, "error", self.t("updStartFailed"),
                        f"{e}\n{args[0]}")
            return False
        self._closing_for_update = True
        self.close()
        QApplication.quit()
        return True

    def _open_demo(self):
        """«Демо-проект»: the bundled made-up controller (examples/demo.mbproj,
        or demo_en.mbproj in the English UI) with its dashboard — the quickest
        look at the app.

        Opened as the user's OWN copy in Documents/ModbusReader: the bundled
        file sits inside the program folder, where a Save would write and the
        next update would wipe it. An existing copy (maybe edited) is kept.
        The copy is named in the UI language too, so each language has its
        own."""
        import shutil
        src = demo_project_path(self.lang)
        if not src:
            return
        dst = os.path.join(demo_copy_dir(), self.t("demoFileName") + ".mbproj")
        try:
            if not os.path.exists(dst):
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copyfile(src, dst)
        except OSError:
            dst = src                        # read-only Documents: open it as is
        self._open_project(dst)

    def _create_config(self):
        """«Создать карту»: the editor opens EMPTY for a brand-new map."""
        self._open_editor(edit_current=False)

    def _open_map_editor(self):
        """«Редактировать карту» / Ctrl+2: the editor opens on the map that is
        on screen right now.

        It used to open blank no matter what. A map that came from a project
        or a CSV import has no .json to «Open» inside the editor, so it could
        not be edited at all — only replaced."""
        self._open_editor(edit_current=True)

    def _open_editor(self, edit_current: bool):
        from gui.map_editor import ProfileEditorDialog
        if isinstance(self._overlay_page, ProfileEditorDialog):
            return  # already open
        # The editor belongs to the map view — make sure we're on it so the
        # nav highlight stays truthful while the overlay is open.
        self._switch_view("view_table")
        if self._overlay_page is not None:
            return
        data = self.profile_data if edit_current else None
        dlg = ProfileEditorDialog(self, data, self.ctx)
        if edit_current and self.profile_path:
            # Save writes straight back to the file the map came from.
            dlg.set_source_file(self.profile_path)
        elif edit_current and self.project_name:
            # A project's map has no file of its own: name it after the
            # project, not «Безымянная карта».
            dlg.profile_name = self.project_name
            dlg.name_edit.setText(self.project_name)
        dlg.accepted.connect(lambda: self._on_editor_accepted(dlg))
        dlg.rejected.connect(self._close_overlay)
        self._show_overlay(dlg, "view_map")
        # First-time visitors get the coach-mark tour automatically (#50).
        if not self.settings.get("guide_seen_editor"):
            self.settings["guide_seen_editor"] = True
            save_settings(self.settings)
            later(450, dlg, dlg._show_guide)

    def _on_editor_accepted(self, dlg):
        data = dlg.get_profile_data()
        # The map now on screen is the editor's. If it is exactly what is in
        # its file (opened or just saved there), that file IS the map — the
        # status bar, the recent list and the next start all follow it.
        saved_file = dlg.file_path if (dlg.file_path and not dlg.is_modified) else ""
        self._set_profile(data, saved_file)
        if saved_file:
            self._push_recent(saved_file)
        save_settings(self.settings)
        self._log("SYS", self.t("logMapApplied").format(n=len(data)))
        if not saved_file and data:
            self._log("SYS", self.t("logMapNotSaved"))
        self._validate_profile(data)
        self._close_overlay()
