# gui_toolbar.py
"""The header bar above every page.

Since 2.2 the pages live in the left rail (gui_rail.py); this bar carries what
is true for the WHOLE window:

    [project ▾]  /  Page title                ● COM3 · 115200 · 8N1 · ID 10  [Подключить]   ⌕ RU|EN ☾ ▤

* left — where you are: the open project (its dropdown is inserted by the
  window, see ``set_project_widget``) and the page on screen;
* right — the device link: what the app will talk to, and the one primary
  button of the whole interface, Connect. Before 2.2 the connection was one
  more grey text button among thirteen, and the port was only in the status
  bar's small print;
* then the small utilities: watch window, language, theme, layout.

Actions are still driven by the command registry: a click emits
``command_triggered(cmd_id)`` and gui_main dispatches it.
"""

from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QPushButton, QMenu, QSizePolicy,
)
from PyQt6.QtCore import Qt, pyqtSignal, QSize

from app.i18n import get_translator
from gui.theme_manager import get_theme
from app import commands
from gui import icons


class MainToolBar(QWidget):
    """Header bar. Kept under its historical name: the window, the guide and
    the tests address it as ``main_toolbar``."""

    command_triggered = pyqtSignal(str)         # command id
    link_clicked      = pyqtSignal()            # the connection chip → settings

    theme_changed   = pyqtSignal(str)   # "Dark" | "Light"
    lang_changed    = pyqtSignal(str)   # "ru"   | "en"
    graphs_toggled  = pyqtSignal(bool)
    log_toggled     = pyqtSignal(bool)

    def __init__(self, parent=None, initial_slave_id: int = 1,
                 initial_theme: str = "Dark", initial_lang: str = "ru",
                 initial_accent: str | None = None):
        super().__init__(parent)
        self.setObjectName("topBar")
        self.setFixedHeight(52)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        self._theme     = initial_theme
        self._accent    = initial_accent
        self._lang      = initial_lang
        self._graphs_on = True
        self._log_on    = True
        self._connected = False
        self._c         = get_theme(initial_theme, initial_accent)
        self.t = get_translator(initial_lang)

        self._icon_btns: list[tuple[QPushButton, str]] = []
        self._cmd_btns: dict[str, QPushButton] = {}
        self._title_key = "registerMap"

        self._build_ui()

    # ──────────────────────────────────────────── helpers
    def _icon_color(self) -> str:
        return self._c["text_2"]

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
        lo.setContentsMargins(14, 0, 12, 0)
        lo.setSpacing(4)

        # Where you are: project ▾ / page.
        self._project_slot = QHBoxLayout()
        self._project_slot.setContentsMargins(0, 0, 0, 0)
        lo.addLayout(self._project_slot)
        self.lbl_sep = QLabel("/")
        self.lbl_sep.setObjectName("hdrSep")
        lo.addWidget(self.lbl_sep)
        self.lbl_title = QLabel()
        self.lbl_title.setObjectName("hdrTitle")
        lo.addWidget(self.lbl_title)
        lo.addStretch(1)

        # The device link: what we talk to + Connect (the primary action).
        self.btn_link = QPushButton()
        self.btn_link.setObjectName("linkChip")
        self.btn_link.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_link.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_link.setIconSize(QSize(10, 10))
        self.btn_link.clicked.connect(self.link_clicked.emit)
        lo.addWidget(self.btn_link)
        lo.addSpacing(6)

        cc = commands.BY_ID["connect"]
        self.btn_connect = QPushButton()
        self.btn_connect.setObjectName("btnConnect")
        self.btn_connect.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_connect.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_connect.setIconSize(QSize(15, 15))
        self.btn_connect.clicked.connect(
            lambda: self.command_triggered.emit(cc.cmd_id))
        self._cmd_btns["connect"] = self.btn_connect
        lo.addWidget(self.btn_connect)
        lo.addSpacing(14)

        # Utilities.
        wc = commands.BY_ID["watch"]
        self.btn_watch = self._icon_btn(
            wc.icon, lambda: self.command_triggered.emit(wc.cmd_id))
        self._cmd_btns["watch"] = self.btn_watch
        lo.addWidget(self.btn_watch)
        lo.addSpacing(4)
        self._build_lang_seg(lo)
        lo.addSpacing(4)
        self.btn_theme = self._icon_btn(self._theme_icon(), self._toggle_theme)
        self._cmd_btns["theme"] = self.btn_theme
        lo.addWidget(self.btn_theme)
        lc = commands.BY_ID["layout"]
        self.btn_layout = self._icon_btn(lc.icon, self._open_layout_menu)
        self._cmd_btns["layout"] = self.btn_layout
        lo.addWidget(self.btn_layout)

        self.set_connect_state(False)
        self.set_link_text("")
        self.retranslate_ui(self.t)

    def set_project_widget(self, w: QWidget):
        """The window owns the project dropdown (its menu needs the window's
        handlers); the bar only gives it its place at the left edge."""
        self._project_slot.addWidget(w)

    # ──────────────────────────────────────────── tooltips
    def _tip(self, cmd_id: str, label: str | None = None) -> str:
        cmd = commands.BY_ID.get(cmd_id)
        text = label if label is not None else (self.t(cmd.label_key) if cmd else cmd_id)
        sc = cmd.shortcut if cmd else ""
        return f"{text}  ({sc})" if sc else text

    def _refresh_tooltips(self):
        for cmd_id, btn in self._cmd_btns.items():
            if cmd_id == "connect":
                btn.setToolTip(self._tip("connect", btn.text().strip()))
            else:
                btn.setToolTip(self._tip(cmd_id))
        self.btn_link.setToolTip(self.t("linkChipTip"))

    def _build_lang_seg(self, parent_lo: QHBoxLayout):
        wrap = QWidget()
        wrap.setObjectName("langSeg")
        wrap.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        wrap.setFixedHeight(26)
        ll = QHBoxLayout(wrap)
        ll.setContentsMargins(2, 2, 2, 2)
        ll.setSpacing(1)
        self._btn_ru = QPushButton("RU")
        self._btn_en = QPushButton("EN")
        for b, code in ((self._btn_ru, "ru"), (self._btn_en, "en")):
            b.setObjectName("segBtn")
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, c=code: self._set_lang(c))
            ll.addWidget(b)
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
        self.set_connect_state(self._connected)

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

    def set_active_view(self, cmd_id: str):
        """Title of the page on screen (pages and the settings / editor
        overlays). The rail carries the highlight."""
        if cmd_id == "view_map":
            self._title_key = "profileEditor"
        else:
            cmd = commands.BY_ID.get(cmd_id)
            self._title_key = cmd.label_key if cmd else "registerMap"
        self.lbl_title.setText(self.t(self._title_key))

    def set_link_text(self, text: str):
        """What the app will talk to: "COM3 · 115200 · 8N1 · ID 10"."""
        self.btn_link.setText(" " + text if text else "")
        self.btn_link.setVisible(bool(text))

    def set_connect_state(self, connected: bool, t_func=None):
        """Connect button + link chip: label, icon colour and QSS state.

        Disconnected, Connect is the accent-filled primary button. Connected,
        it turns into a quiet Disconnect and the chip's dot goes green — the
        state is readable from across the room, not from a status-bar word."""
        tr = t_func if t_func is not None else self.t
        self._connected = connected
        c = self._c
        self.btn_connect.setText("  " + (tr("disconnect") if connected else tr("connect")))
        self.btn_connect.setToolTip(self._tip("connect", self.btn_connect.text().strip()))
        self.btn_connect.setIcon(icons.icon(
            "plug", c["text_1"] if connected else c["accent_fg"], 15))
        for w in (self.btn_connect, self.btn_link):
            w.setProperty("connected", "true" if connected else "false")
            w.style().unpolish(w)
            w.style().polish(w)
        self.btn_link.setIcon(icons.icon(
            "dot", c["ok"] if connected else c["text_4"], 10))

    def retranslate_ui(self, t):
        self.t = t
        self.lbl_title.setText(t(self._title_key))
        self.set_connect_state(self._connected, t)
        self._refresh_tooltips()
