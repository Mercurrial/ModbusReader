# gui/rail.py
"""The navigation rail — every page of the app, always visible.

Replaces the horizontal tab strip of 1.x/2.0, which held ten pages, five
actions and an overflow "⋯" in one row: half the pages were hidden, and pages
and actions looked exactly alike. The rail separates the three kinds of
things:

* **pages** (``commands.VIEWS``), in two sections — *monitor* (where you watch
  the device) and *tools* (instruments you pick up for a job);
* **housekeeping** (``commands.RAIL_FOOTER``: help) at the bottom — settings
  live in the header's top-right corner, where people look for them;
* **actions** (connect, watch) are NOT here — they live in the header bar.

Built from the command registry like the toolbar was: one entry per
descriptor, its label/icon/shortcut from the descriptor, and one
``command_triggered(cmd_id)`` signal that gui/main_window.py dispatches.

The user shapes it (the rail's right-click menu, or Settings → Appearance):

* **position** (``settings["rail_position"]``): a column on the left or the
  right, or a bar across the top — then the group captions turn into thin
  separators, and when the window is too narrow for every label the bar
  drops to icons, keeping the label of the page on screen;
* **icons only** (``settings["rail_collapsed"]``); the labels move into the
  tooltips;
* **which pages it lists** (``settings["rail_hidden"]``) — a hidden page is
  still one shortcut or palette search away; the register map always stays.

A page whose tool is busy in the background (scanner scanning, logger
recording, emulator serving, macro running…) carries a small dot, so leaving
a page never hides the fact that it is still working.
"""

from PyQt6 import sip
from PyQt6.QtCore import Qt, QSize, pyqtSignal, QRectF
from PyQt6.QtGui import QPainter, QColor, QFont, QFontMetrics, QActionGroup
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QSizePolicy, QFrame, QMenu)

from app import commands
from gui import icons
from app.i18n import get_translator
from gui.theme_manager import get_theme
from app.version import APP_VERSION

EXPANDED_W = 212
COLLAPSED_W = 60
TOP_H = 48
POSITIONS = ("left", "right", "top")
HOME = "view_table"            # the register map: never hidden
_QT_MAX = 16777215


class _RailButton(QPushButton):
    """A rail entry: icon + label, an [active] highlight, and an optional
    activity dot (busy in the background) — at the right edge of a wide
    entry, on the icon's corner of a narrow one."""

    def __init__(self, text: str = ""):
        super().__init__(text)
        self.setObjectName("railBtn")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setIconSize(QSize(16, 16))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.busy_color = None            # QColor while the tool is busy

    def paintEvent(self, e):
        super().paintEvent(e)
        if self.busy_color is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self.busy_color)
        r = 3.5
        if self.property("collapsed") == "true" or self.property("horizontal") == "true":
            cx, cy = self.width() - 6.0, 7.0          # corner of the entry
        else:
            cx, cy = self.width() - 14.0, self.height() / 2
        p.drawEllipse(QRectF(cx - r, cy - r, 2 * r, 2 * r))
        p.end()


class NavRail(QWidget):
    command_triggered = pyqtSignal(str)
    brand_clicked = pyqtSignal()
    collapsed_changed = pyqtSignal(bool)
    update_clicked = pyqtSignal()           # «Обновить до …» (gui/update.py)
    position_changed = pyqtSignal(str)      # the right-click menu: «Расположение»
    hidden_changed = pyqtSignal(list)       # the right-click menu: pages listed

    def __init__(self, parent=None, theme: str = "Dark", accent=None,
                 lang: str = "ru", collapsed: bool = False,
                 position: str = "left", hidden=()):
        super().__init__(parent)
        self.setObjectName("navRail")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.t = get_translator(lang)
        self._theme, self._accent = theme, accent
        self._c = get_theme(theme, accent)
        self._collapsed = bool(collapsed)
        self._position = position if position in POSITIONS else "left"
        self._hidden = self._clean_hidden(hidden)
        self._compact = False             # top bar too narrow for every label
        self._active = HOME
        self._busy: set[str] = set()
        self._view_btns: dict[str, _RailButton] = {}
        self._cmd_btns: dict[str, _RailButton] = {}
        self._captions: list[tuple[QLabel, str]] = []
        self._seps: list[QFrame] = []
        self._build()
        self._relayout()
        self.set_collapsed(self._collapsed, emit=False)
        self._apply_hidden()

    @staticmethod
    def _clean_hidden(hidden) -> set:
        """Known pages only, never the map (a hand-edited settings file)."""
        if not isinstance(hidden, (list, tuple, set)):
            return set()
        views = {c.cmd_id for c in commands.VIEWS}
        return {str(c) for c in hidden if c in views and c != HOME}

    # ── build ─────────────────────────────────────────────────────────
    def _build(self):
        """Every widget once; _relayout() arranges them for the position."""
        # Brand — same mark as the exe; click = home (the register map).
        self.brand = QWidget(self)
        self.brand.setObjectName("railBrand")
        self.brand.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.brand.setCursor(Qt.CursorShape.PointingHandCursor)
        self.brand.mousePressEvent = lambda _e: self.brand_clicked.emit()
        bl = QHBoxLayout(self.brand)
        bl.setContentsMargins(6, 0, 4, 0)
        bl.setSpacing(10)
        self.mark = QLabel()
        self.mark.setObjectName("brandIcon")
        self.mark.setFixedSize(26, 26)
        logo = icons.app_icon()
        if logo.isNull():
            self.mark.setText("M")
            self.mark.setObjectName("brandMark")
        else:
            self.mark.setPixmap(logo.pixmap(QSize(26, 26), self.devicePixelRatioF()))
        names = QVBoxLayout()
        names.setSpacing(0)
        names.setContentsMargins(0, 0, 0, 0)
        self.lbl_name = QLabel("ModbusReader")
        self.lbl_name.setObjectName("brandName")
        self.lbl_ver = QLabel(f"v{APP_VERSION}")
        self.lbl_ver.setObjectName("brandVer")
        names.addWidget(self.lbl_name)
        names.addWidget(self.lbl_ver)
        bl.addWidget(self.mark)
        bl.addLayout(names, 1)

        # Per group: a caption (column) or a separator (bar), then the pages.
        self._groups: list[tuple[QLabel, QFrame, list[str]]] = []
        for group, caption_key in commands.GROUPS:
            cap = QLabel(self)
            cap.setObjectName("railCaption")
            self._captions.append((cap, caption_key))
            ids = []
            for cmd in commands.VIEWS:
                if cmd.group == group:
                    self._view_btns[cmd.cmd_id] = self._make(cmd)
                    ids.append(cmd.cmd_id)
            self._groups.append((cap, self._sep(), ids))

        # A new version installed in the background, waiting for a restart —
        # like Telegram's «Update» at the bottom of its sidebar. Hidden
        # otherwise.
        self.btn_update = _RailButton()
        self.btn_update.setParent(self)
        self.btn_update.setProperty("attention", "true")
        self.btn_update.clicked.connect(self.update_clicked.emit)
        self.btn_update.hide()
        self._update_text, self._update_tip = "", ""
        self._footer = [self._make(cmd) for cmd in commands.RAIL_FOOTER]

        self.btn_collapse = _RailButton()
        self.btn_collapse.setParent(self)
        self.btn_collapse.clicked.connect(lambda: self.set_collapsed(not self._collapsed))

    def _make(self, cmd) -> _RailButton:
        btn = _RailButton()
        btn.setParent(self)
        btn.clicked.connect(lambda _=False, cid=cmd.cmd_id: self.command_triggered.emit(cid))
        self._cmd_btns[cmd.cmd_id] = btn
        setattr(self, f"btn_{cmd.cmd_id}", btn)
        return btn

    def _sep(self) -> QFrame:
        sep = QFrame(self)
        sep.setObjectName("railSep")
        sep.setFixedSize(1, 20)
        return sep

    @property
    def horizontal(self) -> bool:
        return self._position == "top"

    def _relayout(self):
        """(Re)arrange the widgets for the position: a column (left/right)
        or a bar (top). The old layout is deleted, never the widgets."""
        old = self.layout()
        if old is not None:
            sip.delete(old)
        horiz = self.horizontal
        lo = QHBoxLayout(self) if horiz else QVBoxLayout(self)
        lo.setSpacing(2)
        if horiz:
            lo.setContentsMargins(10, 0, 10, 0)
            self.brand.setFixedHeight(40)
            self.brand.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            lo.addWidget(self.brand)
            lo.addSpacing(8)
        else:
            lo.setContentsMargins(10, 0, 10, 10)
            self.brand.setFixedHeight(52)
            self.brand.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
            lo.addWidget(self.brand)
            lo.addSpacing(6)
        for n, (cap, sep, ids) in enumerate(self._groups):
            if horiz:
                if n:
                    lo.addSpacing(6)
                    lo.addWidget(sep, 0, Qt.AlignmentFlag.AlignVCenter)
                    lo.addSpacing(6)
            else:
                lo.addWidget(cap)
            for cid in ids:
                lo.addWidget(self._view_btns[cid])
            if not horiz:
                lo.addSpacing(10)
        lo.addStretch(1)
        lo.addWidget(self.btn_update)
        for btn in self._footer:
            lo.addWidget(btn)
        lo.addWidget(self.btn_collapse)
        # A bar has no room for «Свернуть»: icons only is in its menu.
        self.btn_collapse.setVisible(not horiz)
        policy = QSizePolicy.Policy.Fixed if horiz else QSizePolicy.Policy.Expanding
        for btn in list(self._cmd_btns.values()) + [self.btn_update, self.btn_collapse]:
            btn.setSizePolicy(policy, QSizePolicy.Policy.Fixed)
            btn.setProperty("horizontal", "true" if horiz else "false")
        self.setProperty("pos", self._position)
        self._repolish(self)

    @staticmethod
    def _repolish(w):
        w.style().unpolish(w)
        w.style().polish(w)

    # ── state ─────────────────────────────────────────────────────────
    @property
    def position(self) -> str:
        return self._position

    def set_position(self, position: str):
        position = position if position in POSITIONS else "left"
        if position == self._position:
            return
        self._position = position
        self._compact = False
        self._relayout()
        self._apply_geometry()
        self._apply_hidden()
        self._apply_labels()

    def set_active_view(self, cmd_id: str):
        """Highlight the page on screen (the map editor belongs to the map
        page)."""
        self._active = HOME if cmd_id == "view_map" else cmd_id
        for cid, btn in self._cmd_btns.items():
            on = cid == self._active
            btn.setProperty("active", "true" if on else "false")
            self._repolish(btn)
        if self.horizontal and self._compact:
            self._apply_labels()          # the label follows the page on screen
        self._paint_icons()

    def set_busy(self, busy: dict):
        """``{cmd_id: bool}`` — which tools are working in the background."""
        now = {cid for cid, on in busy.items() if on}
        if now == self._busy:
            return
        self._busy = now
        col = QColor(self._c["ok"])
        for cid, btn in self._view_btns.items():
            btn.busy_color = col if cid in now else None
            btn.update()
        self._refresh_tips()

    def set_collapsed(self, collapsed: bool, emit: bool = True):
        self._collapsed = bool(collapsed)
        self._apply_geometry()
        self._apply_labels()
        if emit:
            self.collapsed_changed.emit(self._collapsed)

    @property
    def collapsed(self) -> bool:
        return self._collapsed

    @property
    def hidden(self) -> set:
        return set(self._hidden)

    def set_hidden(self, hidden, emit: bool = False):
        self._hidden = self._clean_hidden(hidden)
        self._apply_hidden()
        if self.horizontal:
            self._fit_bar()
        if emit:
            self.hidden_changed.emit(sorted(self._hidden))

    def _apply_hidden(self):
        horiz = self.horizontal
        shown_groups = 0
        for cap, sep, ids in self._groups:
            any_shown = False
            for cid in ids:
                on = cid not in self._hidden
                self._view_btns[cid].setVisible(on)
                any_shown = any_shown or on
            cap.setVisible(any_shown and not horiz)
            # A bar's separator sits BEFORE its group: none before the first
            # group on screen.
            sep.setVisible(horiz and any_shown and shown_groups > 0)
            shown_groups += any_shown

    def _apply_geometry(self):
        if self.horizontal:
            self.setMinimumWidth(0)
            self.setMaximumWidth(_QT_MAX)
            self.setFixedHeight(TOP_H)
        else:
            self.setMinimumHeight(0)
            self.setMaximumHeight(_QT_MAX)
            self.setFixedWidth(COLLAPSED_W if self._collapsed else EXPANDED_W)

    def _icons_only(self) -> bool:
        return self._collapsed or (self.horizontal and self._compact)

    def _shows_label(self, cid: str) -> bool:
        if not self._icons_only():
            return True
        # A crowded bar keeps ONE label: the page you are on.
        return self.horizontal and not self._collapsed and cid == self._active

    def _apply_labels(self):
        """Labels on or off per entry — and the flags the QSS keys off."""
        for cid, btn in self._cmd_btns.items():
            btn.setProperty("collapsed", "false" if self._shows_label(cid) else "true")
            self._repolish(btn)
        flag = "true" if self._icons_only() else "false"
        for btn in (self.btn_collapse, self.btn_update):
            btn.setProperty("collapsed", flag)
            self._repolish(btn)
        brand_text = not self._icons_only()
        self.lbl_name.setVisible(brand_text)
        self.lbl_ver.setVisible(brand_text)
        for cap, _key in self._captions:
            cap.setProperty("collapsed", "true" if self._collapsed else "false")
            self._repolish(cap)
        self.retranslate_ui(self.t)

    # ── the bar: drop to icons when the window is too narrow ──────────
    def _full_width(self) -> int:
        """What the bar needs with every label (a little generous: the page
        on screen is set in semibold)."""
        bold = QFont(self.font())
        bold.setWeight(QFont.Weight.DemiBold)
        need = 20 + 8 + 160                       # margins, gap, the brand
        for cid, btn in self._cmd_btns.items():
            if not btn.isVisibleTo(self):
                continue
            btn.ensurePolished()
            f = QFont(btn.font())
            f.setWeight(QFont.Weight.DemiBold)
            text = "   " + self.t(commands.BY_ID[cid].label_key)
            need += QFontMetrics(f).horizontalAdvance(text) + 16 + 20 + 6
        need += 13 * max(0, len(self._groups) - 1)      # separators
        if self.btn_update.isVisibleTo(self):
            need += QFontMetrics(bold).horizontalAdvance("   " + self._update_text) + 42
        return need + 24

    def _fit_bar(self):
        if not self.horizontal or self._collapsed:
            return
        compact = self.width() < self._full_width()
        if compact != self._compact:
            self._compact = compact
            self._apply_labels()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fit_bar()

    # ── the right-click menu ──────────────────────────────────────────
    def build_menu(self, page: str | None = None) -> QMenu:
        """Position, icons only, which pages are listed. *page*: the entry
        under the pointer — offered first as «Убрать из меню»."""
        t = self.t
        m = QMenu(self)
        if page and page in self._view_btns and page != HOME:
            name = t(commands.BY_ID[page].label_key)
            act = m.addAction(t("railHidePage").format(name=name))
            act.triggered.connect(lambda: self.set_hidden(self._hidden | {page}, emit=True))
            m.addSeparator()
        pos_menu = m.addMenu(t("railPosition"))
        group = QActionGroup(pos_menu)
        for pos, key in (("left", "railLeft"), ("top", "railTop"), ("right", "railRight")):
            act = pos_menu.addAction(t(key))
            act.setCheckable(True)
            act.setChecked(pos == self._position)
            group.addAction(act)
            act.triggered.connect(lambda _=False, p=pos: self._request_position(p))
        act_icons = m.addAction(t("railIconsOnly"))
        act_icons.setCheckable(True)
        act_icons.setChecked(self._collapsed)
        act_icons.triggered.connect(lambda on: self.set_collapsed(bool(on)))
        pages = m.addMenu(t("railPages"))
        for n, (_cap, _sep, ids) in enumerate(self._groups):
            if n:
                pages.addSeparator()
            for cid in ids:
                act = pages.addAction(t(commands.BY_ID[cid].label_key))
                act.setCheckable(True)
                act.setChecked(cid not in self._hidden)
                act.setEnabled(cid != HOME)
                act.triggered.connect(lambda on, c=cid: self.set_hidden(
                    (self._hidden - {c}) if on else (self._hidden | {c}), emit=True))
        if self._hidden:
            pages.addSeparator()
            act_all = pages.addAction(t("railShowAll"))
            act_all.triggered.connect(lambda: self.set_hidden((), emit=True))
        return m

    def _request_position(self, position: str):
        self.set_position(position)
        self.position_changed.emit(self._position)

    def _page_at(self, pos) -> str | None:
        w = self.childAt(pos)
        while w is not None and w is not self:
            for cid, btn in self._view_btns.items():
                if btn is w:
                    return cid
            w = w.parentWidget()
        return None

    def contextMenuEvent(self, e):
        self.build_menu(self._page_at(e.pos())).exec(e.globalPos())

    # ── «Обновить до …» ───────────────────────────────────────────────
    def set_update(self, text: str, tip: str = ""):
        """Show «Обновить до …» (text) or hide it (text == "")."""
        self._update_text, self._update_tip = text, tip
        self.btn_update.setVisible(bool(text))
        self._render_update()
        if self.horizontal:
            self._fit_bar()

    def _render_update(self):
        b = self.btn_update
        icons_only = self._icons_only()
        b.setText("" if icons_only else "   " + self._update_text)
        b.setToolTip(self._update_text + ("\n" + self._update_tip if self._update_tip else ""))
        b.busy_color = QColor(self._c["ok"]) if icons_only and self._update_text else None
        b.setIcon(icons.icon("download", self._c["ok"], 16))

    # ── text / theme ──────────────────────────────────────────────────
    def retranslate_ui(self, t):
        self.t = t
        for cap, key in self._captions:
            # Collapsed: the caption becomes a hairline gap (see QSS).
            cap.setText("" if self._collapsed else t(key))
        for cid, btn in self._cmd_btns.items():
            cmd = commands.BY_ID[cid]
            btn.setText("   " + t(cmd.label_key) if self._shows_label(cid) else "")
        self.btn_collapse.setText(
            "" if self._collapsed else "   " + t("navCollapse"))
        self._render_update()
        self.brand.setToolTip(t("backToMap"))
        self._refresh_tips()
        self._paint_icons()

    def _refresh_tips(self):
        t = self.t
        for cid, btn in self._cmd_btns.items():
            cmd = commands.BY_ID[cid]
            tip = t(cmd.label_key)
            if cmd.shortcut:
                tip += f"  ({cmd.shortcut})"
            if cid in self._busy:
                tip += "\n" + t("navBusy")
            btn.setToolTip(tip)
        self.btn_collapse.setToolTip(t("navExpand" if self._collapsed else "navCollapse"))

    def _paint_icons(self):
        c = self._c
        for cid, btn in self._cmd_btns.items():
            col = c["accent"] if cid == self._active else c["text_3"]
            btn.setIcon(icons.icon(commands.BY_ID[cid].icon, col, 16))
        self.btn_collapse.setIcon(icons.icon("sidebar", c["text_4"], 16))

    def apply_theme(self, theme: str, accent=None):
        self._theme, self._accent = theme, accent
        self._c = get_theme(theme, accent)
        self._paint_icons()
        self._render_update()
        col = QColor(self._c["ok"])
        for cid, btn in self._view_btns.items():
            if btn.busy_color is not None:
                btn.busy_color = col
                btn.update()
