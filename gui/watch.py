# gui/watch.py
"""Watch window — the handful of registers you care about, in one place.

A register map can run to hundreds of rows, and the ones that matter during
commissioning are spread across it; on top of that the operator is usually
looking at something else — the dashboard, the console, the map editor. The
watch window is a small floating panel (above the main window; the pin keeps
it above every window) that shows just the picked registers, live, whatever
the main window is showing.

2.2 rebuilt it as a panel, not a spreadsheet: its own dark chrome (the native
title bar was a white strip across a dark app), one row per register —

    ● Температура датчик 1                           21.5 °C
      0x0014 · мин 19 · макс 25.3 · 3 с назад     [записать…]

— the value large, everything else one quiet line, the write field only on
registers that can be written. Drag the title to move it, the corner to size
it; right-click a row to reorder / reset min-max / remove.

Registers are added from the register table's context menu or from a
dashboard widget's menu. The value is the SAME text as the table (scaling,
enum labels, view mode). The list is persisted in ``settings["watch_list"]``
(register keys, in order); names, units and writability come from the current
map at display time, so a watched register that is not in the map says so.
"""

import time

from PyQt6.QtCore import Qt, QTimer, QSize, pyqtSignal
from PyQt6.QtGui import QColor, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame, QMenu,
    QScrollArea, QLineEdit, QSizeGrip, QGraphicsDropShadowEffect, QSizePolicy,
)

from core import datatypes
from gui import icons
from gui.widgets import EmptyState

STALE_AFTER = 5.0           # s without a fresh value -> the dot goes grey
_SHADOW = 12                # px around the card for its drop shadow


def _age(sec: float | None, t) -> str:
    if sec is None:
        return "—"
    if sec < 1:
        return t("agoNow")
    if sec < 60:
        return t("agoSec").format(n=int(sec))
    if sec < 3600:
        return t("agoMin").format(n=int(sec // 60))
    return f"{int(sec // 3600)}h"


def _num_text(v: float) -> str:
    if v == int(v) and abs(v) < 1e15:
        return str(int(v))
    return f"{v:.6g}"


class _Row:
    """Runtime state of one watched register."""

    __slots__ = ("addr", "text", "num", "vmin", "vmax", "changed_at", "seen_at")

    def __init__(self, addr: int):
        self.addr = addr
        self.text = None
        self.num = None
        self.vmin = None
        self.vmax = None
        self.changed_at = None
        self.seen_at = None


class _Dot(QLabel):
    """The live/stale dot of a row."""

    def __init__(self):
        super().__init__()
        self.setFixedSize(10, 10)
        self.state = "stale"


class WatchRowWidget(QFrame):
    """One register: name + big value on top, the details line below."""

    write_requested = pyqtSignal(int, str)
    menu_requested = pyqtSignal(int, object)      # addr, global pos
    clicked = pyqtSignal(int)

    def __init__(self, addr: int, ctx):
        super().__init__()
        self.addr = addr
        self.ctx = ctx
        self.setObjectName("watchRow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(
            lambda pos: self.menu_requested.emit(self.addr, self.mapToGlobal(pos)))
        lo = QVBoxLayout(self)
        lo.setContentsMargins(12, 8, 12, 8)
        lo.setSpacing(2)

        top = QHBoxLayout()
        top.setSpacing(8)
        self.dot = _Dot()
        self.lbl_name = QLabel()
        self.lbl_name.setObjectName("wName")
        self.lbl_name.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.lbl_value = QLabel("—")
        self.lbl_value.setObjectName("wValue")
        self.lbl_value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.lbl_unit = QLabel()
        self.lbl_unit.setObjectName("wUnit")
        top.addWidget(self.dot, 0, Qt.AlignmentFlag.AlignVCenter)
        top.addWidget(self.lbl_name, 1)
        top.addWidget(self.lbl_value)
        top.addWidget(self.lbl_unit)

        bottom = QHBoxLayout()
        bottom.setSpacing(8)
        bottom.setContentsMargins(18, 0, 0, 0)       # under the name, past the dot
        self.lbl_meta = QLabel()
        self.lbl_meta.setObjectName("wMeta")
        self.lbl_meta.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.ed_write = QLineEdit()
        self.ed_write.setObjectName("wWrite")
        self.ed_write.setFixedWidth(120)
        # Rows without a write field keep its HEIGHT (every row the same) but
        # not its width: retaining the whole hidden field cut a read-only
        # row's details mid-word («изменено сей…»).
        self.ed_write.ensurePolished()
        self.lbl_meta.setMinimumHeight(self.ed_write.sizeHint().height())
        self.ed_write.returnPressed.connect(self._write)
        bottom.addWidget(self.lbl_meta, 1)
        bottom.addWidget(self.ed_write)
        lo.addLayout(top)
        lo.addLayout(bottom)

    def _write(self):
        text = self.ed_write.text().strip()
        if text:
            self.write_requested.emit(self.addr, text)
            self.ed_write.clear()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.addr)
        super().mousePressEvent(e)

    def set_selected(self, on: bool):
        self.setProperty("selected", "true" if on else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def set_dot(self, state: str, tokens: dict):
        if state == self.dot.state and self.dot.pixmap() is not None \
                and not self.dot.pixmap().isNull():
            return
        self.dot.state = state
        self.dot.setPixmap(icons.pixmap(
            "dot", tokens["ok"] if state == "ok" else tokens["text_4"], 10))


class WatchWindow(QWidget):
    """Floating watch panel. Emits ``write_requested(addr, text)`` and
    ``watch_changed(set_of_addrs)``."""

    write_requested = pyqtSignal(int, str)
    watch_changed = pyqtSignal(object)

    def __init__(self, ctx, get_registers, parent=None):
        super().__init__(parent, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
        self.ctx = ctx
        self.get_registers = get_registers
        self.setObjectName("watchWin")
        # Rounded card + soft shadow: the window itself is transparent.
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMinimumSize(340 + 2 * _SHADOW, 180 + 2 * _SHADOW)
        self._rows: list[_Row] = []
        self._widgets: list[WatchRowWidget] = []
        self._selected = None
        for a in ctx.settings.get("watch_list") or []:
            try:
                addr = int(a)
            except (TypeError, ValueError):
                continue
            # A key: area << 16 | address (holding keys are plain addresses).
            if 0 <= addr <= 0x3FFFF and all(r.addr != addr for r in self._rows):
                self._rows.append(_Row(addr))
        self._build_ui()
        self._apply_on_top(bool(ctx.settings.get("watch_on_top", False)), show=False)
        geo = ctx.settings.get("watch_geom")
        if isinstance(geo, list) and len(geo) == 4:
            try:
                self.setGeometry(*[int(v) for v in geo])
            except (TypeError, ValueError):
                self.resize(460, 360)
        else:
            self.resize(460, 360)
        self.retranslate(ctx.t)
        self._rebuild()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(1000)

    # ── UI ────────────────────────────────────────────────────────────
    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(_SHADOW, _SHADOW, _SHADOW, _SHADOW)
        self.card = QFrame()
        self.card.setObjectName("watchCard")
        self.card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        shadow = QGraphicsDropShadowEffect(self.card)
        shadow.setBlurRadius(28)
        shadow.setOffset(0, 6)
        shadow.setColor(QColor(0, 0, 0, 130))
        self.card.setGraphicsEffect(shadow)
        outer.addWidget(self.card)
        lo = QVBoxLayout(self.card)
        lo.setContentsMargins(1, 1, 1, 1)
        lo.setSpacing(0)

        # Title bar — drag it to move the panel (native move: snapping works).
        self.bar = QWidget()
        self.bar.setObjectName("watchBar")
        self.bar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.bar.setFixedHeight(40)
        self.bar.mousePressEvent = self._bar_press
        self.bar.mouseDoubleClickEvent = lambda _e: None
        bl = QHBoxLayout(self.bar)
        bl.setContentsMargins(12, 0, 6, 0)
        bl.setSpacing(6)
        self._ico = QLabel()
        bl.addWidget(self._ico)
        self.lbl_title = QLabel()
        self.lbl_title.setObjectName("wTitle")
        bl.addWidget(self.lbl_title)
        self.lbl_count = QLabel()
        self.lbl_count.setObjectName("wCount")
        bl.addWidget(self.lbl_count)
        bl.addStretch(1)

        def _btn(slot, checkable=False):
            b = QPushButton()
            b.setObjectName("iconBtn")
            b.setCheckable(checkable)
            b.setFixedSize(28, 28)
            b.setIconSize(QSize(15, 15))
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            (b.toggled if checkable else b.clicked).connect(slot)
            bl.addWidget(b)
            return b
        self.btn_pin = _btn(lambda on: self._apply_on_top(on), checkable=True)
        self.btn_clear = _btn(self.clear)
        self.btn_close = _btn(self.hide)
        lo.addWidget(self.bar)

        self.scroll = QScrollArea()
        self.scroll.setObjectName("watchScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list_host = QWidget()
        self.list_host.setObjectName("watchList")
        self.list_lo = QVBoxLayout(self.list_host)
        self.list_lo.setContentsMargins(6, 6, 6, 6)
        self.list_lo.setSpacing(2)
        self.list_lo.addStretch(1)
        self.scroll.setWidget(self.list_host)
        lo.addWidget(self.scroll, 1)

        self.empty = EmptyState("watch", "", "")
        lo.addWidget(self.empty, 1)

        grip_row = QHBoxLayout()
        grip_row.setContentsMargins(0, 0, 2, 2)
        grip_row.addStretch(1)
        self.grip = QSizeGrip(self.card)
        self.grip.setObjectName("watchGrip")
        self.grip.setFixedSize(14, 14)
        grip_row.addWidget(self.grip)
        lo.addLayout(grip_row)

        sc = QShortcut(QKeySequence(Qt.Key.Key_Delete), self)
        sc.activated.connect(self._remove_selected)
        self._paint_icons()

    def _bar_press(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            handle = self.windowHandle()
            if handle is not None:
                handle.startSystemMove()

    def _paint_icons(self):
        c = self.ctx.theme_tokens()
        on = self.btn_pin.isChecked()
        self.btn_pin.setIcon(icons.icon("pin", c["accent"] if on else c["text_3"], 15))
        self.btn_clear.setIcon(icons.icon("trash", c["text_3"], 15))
        self.btn_close.setIcon(icons.icon("x", c["text_3"], 15))
        self._ico.setPixmap(icons.pixmap("watch", c["text_2"], 16))
        self.empty.apply_theme(c)

    def _apply_on_top(self, on: bool, show: bool = True):
        """«Поверх всех окон»: by default the window floats above the main
        window only (a tool window); pinned, it stays above every app — for
        watching a value while working in another program."""
        if self.btn_pin.isChecked() != on:
            self.btn_pin.blockSignals(True)
            self.btn_pin.setChecked(on)
            self.btn_pin.blockSignals(False)
        visible = self.isVisible()
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, on)
        self.ctx.settings["watch_on_top"] = bool(on)
        self._paint_icons()
        if show and visible:
            self.show()                  # re-applying flags hides the window

    # ── the list ──────────────────────────────────────────────────────
    def watched(self) -> set:
        return {r.addr for r in self._rows}

    def add(self, addr: int):
        addr = int(addr)
        if addr in self.watched():
            return
        self._rows.append(_Row(addr))
        self._list_changed()

    def remove(self, addr: int):
        self._rows = [r for r in self._rows if r.addr != int(addr)]
        if self._selected == int(addr):
            self._selected = None
        self._list_changed()

    def toggle(self, addr: int) -> bool:
        """Add or remove; True when the register is now watched."""
        if int(addr) in self.watched():
            self.remove(addr)
            return False
        self.add(addr)
        return True

    def clear(self):
        if self._rows:
            self._rows = []
            self._selected = None
            self._list_changed()

    def _move(self, addr: int, step: int):
        i = next((k for k, r in enumerate(self._rows) if r.addr == addr), None)
        j = None if i is None else i + step
        if i is None or not 0 <= j < len(self._rows):
            return
        self._rows[i], self._rows[j] = self._rows[j], self._rows[i]
        self._list_changed()

    def _list_changed(self):
        self.ctx.settings["watch_list"] = [r.addr for r in self._rows]
        self._rebuild()
        self.watch_changed.emit(self.watched())

    # ── register lookup ───────────────────────────────────────────────
    def _regs(self) -> dict:
        out = {}
        for reg in self.get_registers() or []:
            if isinstance(reg, dict):
                out[datatypes.reg_key(reg)] = reg
        return out

    # ── rendering ─────────────────────────────────────────────────────
    def row_widget(self, i: int) -> WatchRowWidget:
        return self._widgets[i]

    def _rebuild(self):
        """Full re-render (list changed, map changed, language/theme)."""
        t = self.ctx.t
        regs = self._regs()
        tok = self.ctx.theme_tokens()
        for wdg in self._widgets:
            self.list_lo.removeWidget(wdg)
            # Out of the window NOW: a removed-but-not-yet-deleted row was
            # still painted, a ghost line on top of the new list.
            wdg.hide()
            wdg.setParent(None)
            wdg.deleteLater()
        self._widgets = []
        for i, row in enumerate(self._rows):
            reg = regs.get(row.addr)
            wdg = WatchRowWidget(row.addr, self.ctx)
            wdg.write_requested.connect(self.write_requested.emit)
            wdg.menu_requested.connect(self._menu)
            wdg.clicked.connect(self._select)
            if reg is None:
                wdg.lbl_name.setText(t("watchNotInMap"))
                wdg.lbl_name.setProperty("missing", "true")
                unit = ""
                writable = False
            else:
                label = (reg.get("name_en") if self.ctx.lang == "en"
                         and reg.get("name_en") else reg.get("name", ""))
                wdg.lbl_name.setText(str(label))
                wdg.lbl_name.setToolTip(
                    f"{label}\n{reg.get('type', '')} · {reg.get('rw', '')}")
                unit = str(reg.get("unit", "") or "")
                writable = datatypes.is_writable(reg)
            wdg.unit = unit
            wdg.ed_write.setVisible(writable)
            wdg.ed_write.setPlaceholderText(t("watchWritePh"))
            wdg.ed_write.setToolTip(t("watchNewTip"))
            wdg.set_dot(self._state(row), tok)
            wdg.set_selected(row.addr == self._selected)
            self._fill(wdg, row)
            self.list_lo.insertWidget(i, wdg)
            self._widgets.append(wdg)
        empty = not self._rows
        self.scroll.setVisible(not empty)
        self.empty.setVisible(empty)
        self.lbl_count.setText(str(len(self._rows)) if self._rows else "")

    def _fill(self, wdg: WatchRowWidget, row: _Row):
        """Value + details line of one row."""
        t = self.ctx.t
        text = row.text if row.text is not None else "—"
        # The table text of a scaled register already carries its unit
        # («55.3 %»): take it off the number so every row shows the unit the
        # same way — small, beside the value, not in the big digits.
        unit = getattr(wdg, "unit", "")
        if unit and row.text and text.endswith(unit):
            text = text[: -len(unit)].rstrip()
        wdg.lbl_value.setText(text)
        wdg.lbl_value.setProperty("state", "live" if row.text is not None else "none")
        wdg.lbl_value.style().unpolish(wdg.lbl_value)
        wdg.lbl_value.style().polish(wdg.lbl_value)
        wdg.lbl_unit.setText(unit if unit and row.text else "")
        wdg.lbl_unit.setVisible(bool(wdg.lbl_unit.text()))
        parts = [datatypes.key_label(row.addr)]
        if row.vmin is not None:
            parts.append(f"{t('trendMin')} {_num_text(row.vmin)}")
            parts.append(f"{t('trendMax')} {_num_text(row.vmax)}")
        if row.changed_at is not None:
            parts.append(t("watchChangedAgo").format(age=self._age_text(row)))
        wdg.lbl_meta.setText("  ·  ".join(parts))

    def _state(self, row: _Row) -> str:
        if row.seen_at is None:
            return "stale"
        return "ok" if time.monotonic() - row.seen_at <= STALE_AFTER else "stale"

    def _age_text(self, row: _Row) -> str:
        if row.changed_at is None:
            return "—"
        return _age(time.monotonic() - row.changed_at, self.ctx.t)

    def _row_index(self, addr: int):
        return next((i for i, r in enumerate(self._rows) if r.addr == addr), None)

    # ── live data ─────────────────────────────────────────────────────
    def on_value(self, addr: int, text: str, num=None):
        """A fresh reading for *addr*: *text* exactly as the table shows it,
        *num* the engineering number (None for text/enum values)."""
        i = self._row_index(addr)
        if i is None:
            return
        row = self._rows[i]
        now = time.monotonic()
        if text != row.text:
            row.changed_at = now if row.text is not None else (row.changed_at or now)
        row.text = text
        row.seen_at = now
        if isinstance(num, (int, float)) and num == num:
            row.num = float(num)
            row.vmin = row.num if row.vmin is None else min(row.vmin, row.num)
            row.vmax = row.num if row.vmax is None else max(row.vmax, row.num)
        if i < len(self._widgets):
            wdg = self._widgets[i]
            self._fill(wdg, row)
            wdg.set_dot("ok", self.ctx.theme_tokens())

    def set_stale_all(self):
        for r in self._rows:
            r.seen_at = None
        self._tick(force=True)

    def _tick(self, force: bool = False):
        """Once a second: age text and stale dots."""
        if not self.isVisible() and not force:
            return
        tok = self.ctx.theme_tokens()
        for row, wdg in zip(self._rows, self._widgets):
            wdg.set_dot(self._state(row), tok)
            self._fill(wdg, row)

    def reset_minmax(self, addr: int | None = None):
        for r in self._rows:
            if addr is None or r.addr == addr:
                r.vmin = r.vmax = r.num
        self._rebuild()

    # ── interaction ───────────────────────────────────────────────────
    def _select(self, addr: int):
        self._selected = addr
        for wdg in self._widgets:
            wdg.set_selected(wdg.addr == addr)

    def _remove_selected(self):
        if self._selected is not None:
            self.remove(self._selected)

    def _menu(self, addr: int, gpos):
        self._select(addr)
        t = self.ctx.t
        c = self.ctx.theme_tokens()["text_2"]
        m = QMenu(self)
        a_up = m.addAction(icons.icon("chevron_up", c, 14), t("watchUp"))
        a_down = m.addAction(icons.icon("chevron", c, 14), t("watchDown"))
        m.addSeparator()
        a_reset = m.addAction(icons.icon("focus", c, 14), t("watchResetMinMax"))
        m.addSeparator()
        a_del = m.addAction(icons.icon("x", c, 14), t("watchRemove"))
        chosen = m.exec(gpos)
        if chosen is a_up:
            self._move(addr, -1)
        elif chosen is a_down:
            self._move(addr, +1)
        elif chosen is a_reset:
            self.reset_minmax(addr)
        elif chosen is a_del:
            self.remove(addr)

    # ── app plumbing ──────────────────────────────────────────────────
    def refresh_map(self):
        """The register map changed: names, units and writability follow."""
        self._rebuild()

    def apply_settings(self):
        self._paint_icons()
        self._rebuild()

    def retranslate(self, t):
        self.setWindowTitle(t("watchTitle"))
        self.lbl_title.setText(t("watchTitle"))
        self.empty.set_content(t("watchEmptyTitle"), t("watchEmpty"))
        self.btn_pin.setToolTip(t("watchPinTip"))
        self.btn_clear.setToolTip(t("watchClearTip"))
        self.btn_close.setToolTip(t("close"))
        self._rebuild()

    def save_geometry(self):
        g = self.geometry()
        self.ctx.settings["watch_geom"] = [g.x(), g.y(), g.width(), g.height()]

    def hideEvent(self, e):
        self.save_geometry()
        super().hideEvent(e)
