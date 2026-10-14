# gui_toolbar.py

from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QLabel,
    QPushButton, QMenu, QSizePolicy,
)
from PyQt6.QtCore import Qt, pyqtSignal, QSize

from i18n import get_translator
from theme_manager import get_theme
import commands
import icons
from version import APP_VERSION


class MainToolBar(QWidget):
    """Application top bar — brand, file actions, lang/theme/layout controls.

    The action buttons, their shortcuts and tooltips are driven by the command
    registry (commands.py): clicking one emits ``command_triggered(cmd_id)`` and
    gui_main dispatches it. Only the parameterized / non-command events below
    keep their own dedicated signals."""

    # One generic dispatch for every top-bar action command (see commands.py).
    command_triggered = pyqtSignal(str)         # command id

    brand_clicked      = pyqtSignal()           # click logo → back to register map
    pins_changed       = pyqtSignal(list)       # user re-configured the tab set

    theme_changed   = pyqtSignal(str)   # "Dark" | "Light"
    lang_changed    = pyqtSignal(str)   # "ru"   | "en"
    graphs_toggled  = pyqtSignal(bool)
    log_toggled     = pyqtSignal(bool)

    def __init__(self, parent=None, initial_slave_id: int = 1,
                 initial_theme: str = "Dark", initial_lang: str = "ru",
                 initial_accent: str | None = None):
        super().__init__(parent)
        self.setObjectName("topBar")
        self.setFixedHeight(48)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        self._theme     = initial_theme   # "Dark" or "Light"
        self._accent    = initial_accent
        self._lang      = initial_lang    # "ru"   or "en"
        self._graphs_on = True
        self._log_on    = True
        self._c         = get_theme(initial_theme, initial_accent)

        # Translator — updated by retranslate_ui; used in dynamic menus
        self.t = get_translator(initial_lang)

        # (button, icon_name) registry so we can recolor on theme change
        self._icon_btns: list[tuple[QPushButton, str]] = []
        # command id -> its button, for registry-driven tooltips/retranslation
        self._cmd_btns: dict[str, QPushButton] = {}

        self._build_ui()

    # ──────────────────────────────────────────── helpers

    def _icon_color(self) -> str:
        return self._c["text_2"]

    def _tb_btn(self, icon_name: str, text: str, callback=None) -> QPushButton:
        b = QPushButton(f"  {text}")
        b.setObjectName("tbBtn")
        b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setIcon(icons.icon(icon_name, self._icon_color(), 16))
        b.setIconSize(QSize(16, 16))
        self._icon_btns.append((b, icon_name))
        if callback:
            b.clicked.connect(callback)
        return b

    def _icon_btn(self, icon_name: str, callback=None, tooltip: str = "") -> QPushButton:
        b = QPushButton()
        b.setObjectName("iconBtn")
        b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setFixedSize(32, 32)
        b.setIcon(icons.icon(icon_name, self._icon_color(), 16))
        b.setIconSize(QSize(16, 16))
        self._icon_btns.append((b, icon_name))
        if tooltip:
            b.setToolTip(tooltip)
        if callback:
            b.clicked.connect(callback)
        return b

    # ──────────────────────────────────────────── build

    def _build_ui(self):
        lo = QHBoxLayout(self)
        lo.setContentsMargins(10, 0, 8, 0)
        lo.setSpacing(2)

        # Brand — clickable: returns to the main register-map view.
        brand = QWidget()
        brand.setObjectName("brandPanel")
        brand.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        brand.setCursor(Qt.CursorShape.PointingHandCursor)
        brand.setToolTip(self.t("backToMap"))
        # Forward a left-click on the panel (or any of its labels) to the signal.
        brand.mousePressEvent = lambda _e: self.brand_clicked.emit()
        brand_lo = QHBoxLayout(brand)
        brand_lo.setContentsMargins(4, 2, 6, 2)
        brand_lo.setSpacing(0)

        # The same mark as the exe / taskbar icon (assets/app.png).
        mark = QLabel()
        mark.setObjectName("brandIcon")
        mark.setFixedSize(24, 24)
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo = icons.app_icon()
        if logo.isNull():
            mark.setText("M")
            mark.setObjectName("brandMark")
        else:
            mark.setPixmap(logo.pixmap(QSize(24, 24), self.devicePixelRatioF()))

        name_row = QHBoxLayout()
        name_row.setSpacing(3)
        name_row.setContentsMargins(0, 0, 0, 0)
        lbl_name = QLabel("ModbusReader")
        lbl_name.setObjectName("brandName")
        lbl_ver  = QLabel(f"v{APP_VERSION}")
        lbl_ver.setObjectName("brandVer")
        name_row.addWidget(lbl_name)
        name_row.addWidget(lbl_ver, 0, Qt.AlignmentFlag.AlignBottom)

        brand_lo.addWidget(mark)
        brand_lo.addSpacing(8)
        brand_lo.addLayout(name_row)

        lo.addWidget(brand)
        # No rule between the brand and the nav: whitespace already separates
        # them, and a vertical hairline next to a logo reads as a defect.
        # Grouping in a top bar is done with space, not with lines.
        lo.addSpacing(18)

        # Main-view nav cluster — one button per registry "view" command. Which
        # buttons are visible is the user's pin list (settings["pinned_views"]);
        # everything else lives in the ⋯ overflow menu (professional adaptive
        # toolbar). The active view carries [active="true"] either way.
        self._view_btns: dict[str, QPushButton] = {}
        for cmd in commands.VIEWS:
            btn = self._tb_btn(
                cmd.icon, self.t(cmd.label_key),
                (lambda _checked=False, cid=cmd.cmd_id:
                 self.command_triggered.emit(cid)))
            self._cmd_btns[cmd.cmd_id] = btn
            self._view_btns[cmd.cmd_id] = btn
            setattr(self, f"btn_{cmd.cmd_id}", btn)
            lo.addWidget(btn)
        # ⋯ — unpinned views + tab configuration.
        self.btn_more = self._icon_btn("dots", self._open_more_menu,
                                       self.t("navMore"))
        lo.addWidget(self.btn_more)
        self._pinned: list[str] = []
        self.set_pinned(None)                # visibility from settings default
        # Settings overlay highlights its own button, same mechanism.
        self._active_view = "view_table"

        lo.addSpacing(14)

        # System actions — built from the command registry (commands.py). Each
        # click dispatches via command_triggered(cmd_id); the matching handler
        # lives in gui_main. Order follows the registry's declaration order.
        for cmd in commands.BUTTONS:
            btn = self._tb_btn(
                cmd.icon, self.t(cmd.label_key),
                (lambda _checked=False, cid=cmd.cmd_id:
                 self.command_triggered.emit(cid)))
            self._cmd_btns[cmd.cmd_id] = btn
            setattr(self, f"btn_{cmd.cmd_id}", btn)   # btn_settings, btn_connect…
            lo.addWidget(btn)
        self.set_active_view("view_table")

        # Spacer
        sp = QWidget()
        sp.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        lo.addWidget(sp)

        # Right cluster. Also unruled — the RU/EN pill is already a shape, and
        # a divider beside it just added a third grey edge to the same corner.
        lo.addSpacing(10)

        self._build_lang_seg(lo)
        lo.addSpacing(4)

        # Theme toggle (icon button) — dynamic moon/sun glyph, toolbar-internal.
        tc = commands.BY_ID["theme"]
        self.btn_theme = self._icon_btn(self._theme_icon(), self._toggle_theme,
                                        self.t(tc.label_key))
        self._cmd_btns["theme"] = self.btn_theme
        lo.addWidget(self.btn_theme)

        # Layout toggle (icon button + dropdown) — toolbar-internal.
        lc = commands.BY_ID["layout"]
        self.btn_layout = self._icon_btn(lc.icon, self._open_layout_menu,
                                         self.t(lc.label_key))
        self._cmd_btns["layout"] = self.btn_layout
        lo.addWidget(self.btn_layout)

        self._refresh_tooltips()

    # ──────────────────────────────────────────── tooltips

    def _tip(self, cmd_id: str, label: str | None = None) -> str:
        """Tooltip text = localized label + shortcut hint, e.g. 'Settings (Ctrl+,)'.
        Both the label key and the shortcut come from the command registry."""
        cmd = commands.BY_ID.get(cmd_id)
        text = label if label is not None else (self.t(cmd.label_key) if cmd else cmd_id)
        sc = cmd.shortcut if cmd else ""
        return f"{text}  ({sc})" if sc else text

    def _refresh_tooltips(self):
        for cmd_id, btn in self._cmd_btns.items():
            if cmd_id == "connect":
                # Connect label flips with state, so derive from current text.
                btn.setToolTip(self._tip("connect", btn.text().strip()))
            else:
                btn.setToolTip(self._tip(cmd_id))

    def _build_lang_seg(self, parent_lo: QHBoxLayout):
        wrap = QWidget()
        wrap.setObjectName("langSeg")
        wrap.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        # Fixed height: without it the HBox stretches the pill to the full
        # 48px toolbar height and it reads as a plain gray rectangle.
        wrap.setFixedHeight(26)
        ll = QHBoxLayout(wrap)
        ll.setContentsMargins(2, 2, 2, 2)
        ll.setSpacing(1)

        self._btn_ru = QPushButton("RU")
        self._btn_ru.setObjectName("segBtn")
        self._btn_ru.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._btn_ru.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_ru.clicked.connect(lambda: self._set_lang("ru"))

        self._btn_en = QPushButton("EN")
        self._btn_en.setObjectName("segBtn")
        self._btn_en.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._btn_en.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_en.clicked.connect(lambda: self._set_lang("en"))

        ll.addWidget(self._btn_ru)
        ll.addWidget(self._btn_en)
        parent_lo.addWidget(wrap)
        self._refresh_lang_btns()

    # ──────────────────────────────────────────── slots

    def _theme_icon(self) -> str:
        return "moon" if self._theme == "Dark" else "sun"

    def _set_lang(self, lang: str):
        self._lang = lang
        self._refresh_lang_btns()
        self.lang_changed.emit(lang)

    def _refresh_lang_btns(self):
        for btn, key in [(self._btn_ru, "ru"), (self._btn_en, "en")]:
            btn.setProperty("active", "true" if self._lang == key else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def _toggle_theme(self):
        self._theme = "Light" if self._theme == "Dark" else "Dark"
        self.theme_changed.emit(self._theme)

    def apply_theme(self, theme_name: str, accent: str | None = None):
        """Recompute palette and recolor all SVG icons + theme glyph."""
        self._theme = theme_name
        self._accent = accent
        self._c = get_theme(theme_name, accent)
        col = self._icon_color()
        for btn, name in self._icon_btns:
            icon_name = self._theme_icon() if btn is self.btn_theme else name
            btn.setIcon(icons.icon(icon_name, col, 16))
        # The connect button keeps its green while connected.
        if getattr(self, "_connected", False):
            self.btn_connect.setIcon(icons.icon("plug", self._c["ok"], 16))

    def _open_layout_menu(self):
        m = QMenu(self)

        act_g = m.addAction(self.t("showGraphs"))
        act_g.setCheckable(True)
        act_g.setChecked(self._graphs_on)
        act_g.triggered.connect(lambda checked: self._toggle_graphs())

        act_l = m.addAction(self.t("showLog"))
        act_l.setCheckable(True)
        act_l.setChecked(self._log_on)
        act_l.triggered.connect(lambda checked: self._toggle_log())

        m.exec(self.btn_layout.mapToGlobal(self.btn_layout.rect().bottomLeft()))

    def _toggle_graphs(self):
        self._graphs_on = not self._graphs_on
        self.graphs_toggled.emit(self._graphs_on)

    def _toggle_log(self):
        self._log_on = not self._log_on
        self.log_toggled.emit(self._log_on)

    # ──────────────────────────────────────────── public API

    def set_layout_state(self, graphs: bool = None, log: bool = None):
        """Sync the layout-menu checkbox state without emitting toggle signals."""
        if graphs is not None:
            self._graphs_on = graphs
        if log is not None:
            self._log_on = log

    # ── smart nav: pinned tabs + overflow ─────────────────────────────
    _DEFAULT_PINNED = ["view_table", "view_console",
                       "view_scanner", "view_sniffer"]

    def set_pinned(self, pinned: list | None):
        """Show only the pinned views as labelled tabs (view_table is always
        pinned — the home tab can't disappear); the rest go to the ⋯ menu."""
        pinned = list(pinned) if pinned else list(self._DEFAULT_PINNED)
        if "view_table" not in pinned:
            pinned.insert(0, "view_table")
        self._pinned = [cid for cid in pinned if cid in self._view_btns]
        for cid, btn in self._view_btns.items():
            btn.setVisible(cid in self._pinned)
        self.btn_more.setVisible(len(self._pinned) < len(self._view_btns))

    def _open_more_menu(self):
        m = QMenu(self)
        for cmd in commands.VIEWS:
            if cmd.cmd_id in self._pinned:
                continue
            act = m.addAction(icons.icon(cmd.icon, self._icon_color(), 14),
                              self.t(cmd.label_key))
            act.triggered.connect(lambda _checked=False, cid=cmd.cmd_id:
                                  self.command_triggered.emit(cid))
        m.addSeparator()
        cfg = m.addMenu(self.t("navConfigure"))
        for cmd in commands.VIEWS:
            act = cfg.addAction(self.t(cmd.label_key))
            act.setCheckable(True)
            act.setChecked(cmd.cmd_id in self._pinned)
            if cmd.cmd_id == "view_table":
                act.setEnabled(False)          # home tab is always pinned
            act.toggled.connect(lambda on, cid=cmd.cmd_id:
                                self._toggle_pin(cid, on))
        m.exec(self.btn_more.mapToGlobal(self.btn_more.rect().bottomLeft()))

    def _toggle_pin(self, cmd_id: str, on: bool):
        pinned = [c for c in self._pinned if c != cmd_id]
        if on:
            # keep registry order stable regardless of toggle order
            order = [c.cmd_id for c in commands.VIEWS]
            pinned = [cid for cid in order if cid in pinned + [cmd_id]]
        self.set_pinned(pinned)
        self.set_active_view(self._active_view)   # refresh ⋯ highlight
        self.pins_changed.emit(list(self._pinned))

    def set_active_view(self, cmd_id: str):
        """Highlight the nav button for the current view/overlay.

        Accepts a "view_*" command id or "settings" (the settings overlay
        highlights its own button while open). If the active view is unpinned,
        the ⋯ overflow button carries the highlight instead."""
        self._active_view = cmd_id
        targets = dict(self._view_btns)
        if "settings" in self._cmd_btns:
            targets["settings"] = self._cmd_btns["settings"]
        for cid, btn in targets.items():
            on = cid == cmd_id
            btn.setProperty("active", "true" if on else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)
        more_on = (cmd_id in self._view_btns and cmd_id not in self._pinned)
        self.btn_more.setProperty("active", "true" if more_on else "false")
        self.btn_more.style().unpolish(self.btn_more)
        self.btn_more.style().polish(self.btn_more)

    def set_connect_state(self, connected: bool, t_func=None):
        """Update the Connect button: label, icon colour and QSS state.

        Connected: green plug + [connected="true"] styling, so the connection
        state is readable at a glance without parsing the label."""
        tr = t_func if t_func is not None else self.t
        self.btn_connect.setText("  " + (tr("disconnect") if connected else tr("connect")))
        self.btn_connect.setToolTip(self._tip("connect", self.btn_connect.text().strip()))
        col = self._c["ok"] if connected else self._icon_color()
        self.btn_connect.setIcon(icons.icon("plug", col, 16))
        self.btn_connect.setProperty("connected", "true" if connected else "false")
        self.btn_connect.style().unpolish(self.btn_connect)
        self.btn_connect.style().polish(self.btn_connect)
        self._connected = connected

    def retranslate_ui(self, t):
        """Re-apply all static labels using translator *t*.

        Labelled command buttons get their text from the registry; icon-only
        buttons (theme/layout) have none. The Connect label is reset here and
        re-synced to the live connection state by set_connect_state()."""
        self.t = t   # store for dynamic menus
        for cmd_id, btn in self._cmd_btns.items():
            cmd = commands.BY_ID.get(cmd_id)
            if cmd is None or cmd.place == "icon":
                continue   # icon-only buttons carry no text
            btn.setText("  " + t(cmd.label_key))
        self._refresh_tooltips()
