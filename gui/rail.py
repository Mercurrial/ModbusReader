# gui/rail.py
"""The left navigation rail — every page of the app, always visible.

Replaces the horizontal tab strip of 1.x/2.0, which held ten pages, five
actions and an overflow "⋯" in one row: half the pages were hidden, and pages
and actions looked exactly alike. The rail separates the three kinds of
things:

* **pages** (``commands.VIEWS``), in two sections — *monitor* (where you watch
  the device) and *tools* (instruments you pick up for a job);
* **housekeeping** (``commands.RAIL_FOOTER``: settings, help) at the bottom;
* **actions** (connect, watch) are NOT here — they live in the header bar.

Built from the command registry like the toolbar was: one entry per
descriptor, its label/icon/shortcut from the descriptor, and one
``command_triggered(cmd_id)`` signal that gui/main_window.py dispatches. The rail can
collapse to icons only (``settings["rail_collapsed"]``); the labels then move
into the tooltips.

A page whose tool is busy in the background (scanner scanning, logger
recording, emulator serving, macro running…) carries a small dot, so leaving
a page never hides the fact that it is still working.
"""

from PyQt6.QtCore import Qt, QSize, pyqtSignal, QRectF
from PyQt6.QtGui import QPainter, QColor
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QSizePolicy)

from app import commands
from gui import icons
from app.i18n import get_translator
from gui.theme_manager import get_theme
from app.version import APP_VERSION

EXPANDED_W = 212
COLLAPSED_W = 60


class _RailButton(QPushButton):
    """A rail entry: icon + label, an [active] highlight, and an optional
    activity dot painted at the right edge (busy in the background)."""

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
        if self.property("collapsed") == "true":
            cx, cy = self.width() - 9.0, 9.0          # corner of the icon tile
        else:
            cx, cy = self.width() - 14.0, self.height() / 2
        p.drawEllipse(QRectF(cx - r, cy - r, 2 * r, 2 * r))
        p.end()


class NavRail(QWidget):
    command_triggered = pyqtSignal(str)
    brand_clicked = pyqtSignal()
    collapsed_changed = pyqtSignal(bool)

    def __init__(self, parent=None, theme: str = "Dark", accent=None,
                 lang: str = "ru", collapsed: bool = False):
        super().__init__(parent)
        self.setObjectName("navRail")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.t = get_translator(lang)
        self._theme, self._accent = theme, accent
        self._c = get_theme(theme, accent)
        self._collapsed = bool(collapsed)
        self._active = "view_table"
        self._busy: set[str] = set()
        self._view_btns: dict[str, _RailButton] = {}
        self._cmd_btns: dict[str, _RailButton] = {}
        self._captions: list[tuple[QLabel, str]] = []
        self._build()
        self.set_collapsed(self._collapsed, emit=False)

    # ── build ─────────────────────────────────────────────────────────
    def _build(self):
        lo = QVBoxLayout(self)
        lo.setContentsMargins(10, 0, 10, 10)
        lo.setSpacing(2)

        # Brand — same mark as the exe; click = home (the register map).
        self.brand = QWidget()
        self.brand.setObjectName("railBrand")
        self.brand.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.brand.setFixedHeight(52)
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
        lo.addWidget(self.brand)
        lo.addSpacing(6)

        for group, caption_key in commands.GROUPS:
            cap = QLabel()
            cap.setObjectName("railCaption")
            self._captions.append((cap, caption_key))
            lo.addWidget(cap)
            for cmd in commands.VIEWS:
                if cmd.group == group:
                    btn = self._make(cmd)
                    self._view_btns[cmd.cmd_id] = btn
                    lo.addWidget(btn)
            lo.addSpacing(10)

        lo.addStretch(1)
        for cmd in commands.RAIL_FOOTER:
            lo.addWidget(self._make(cmd))

        self.btn_collapse = _RailButton()
        self.btn_collapse.setObjectName("railBtn")
        self.btn_collapse.clicked.connect(lambda: self.set_collapsed(not self._collapsed))
        lo.addWidget(self.btn_collapse)
        self.retranslate_ui(self.t)

    def _make(self, cmd) -> _RailButton:
        btn = _RailButton()
        btn.clicked.connect(lambda _=False, cid=cmd.cmd_id: self.command_triggered.emit(cid))
        self._cmd_btns[cmd.cmd_id] = btn
        setattr(self, f"btn_{cmd.cmd_id}", btn)
        return btn

    # ── state ─────────────────────────────────────────────────────────
    def set_active_view(self, cmd_id: str):
        """Highlight the page on screen (or "settings" while its overlay is
        open; the map editor belongs to the map page)."""
        self._active = "view_table" if cmd_id == "view_map" else cmd_id
        for cid, btn in self._cmd_btns.items():
            on = cid == self._active
            btn.setProperty("active", "true" if on else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)
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
        self.setFixedWidth(COLLAPSED_W if self._collapsed else EXPANDED_W)
        flag = "true" if self._collapsed else "false"
        for btn in list(self._cmd_btns.values()) + [self.btn_collapse]:
            btn.setProperty("collapsed", flag)
            btn.style().unpolish(btn)
            btn.style().polish(btn)
        self.lbl_name.setVisible(not self._collapsed)
        self.lbl_ver.setVisible(not self._collapsed)
        for cap, _key in self._captions:
            cap.setProperty("collapsed", flag)
            cap.style().unpolish(cap)
            cap.style().polish(cap)
        self.retranslate_ui(self.t)
        if emit:
            self.collapsed_changed.emit(self._collapsed)

    @property
    def collapsed(self) -> bool:
        return self._collapsed

    # ── text / theme ──────────────────────────────────────────────────
    def retranslate_ui(self, t):
        self.t = t
        for cap, key in self._captions:
            # Collapsed: the caption becomes a hairline gap (see QSS).
            cap.setText("" if self._collapsed else t(key))
        for cid, btn in self._cmd_btns.items():
            cmd = commands.BY_ID[cid]
            btn.setText("" if self._collapsed else "   " + t(cmd.label_key))
        self.btn_collapse.setText(
            "" if self._collapsed else "   " + t("navCollapse"))
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
        col = QColor(self._c["ok"])
        for cid, btn in self._view_btns.items():
            if btn.busy_color is not None:
                btn.busy_color = col
                btn.update()
