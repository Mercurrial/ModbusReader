# gui_watch.py
"""Watch window — the handful of registers you care about, in one place.

A register map can run to hundreds of rows, and the ones that matter during
commissioning are spread across it; on top of that the operator is usually
looking at something else — the dashboard, the console, the map editor. The
watch window is a small floating window (it stays above the main window, and
can be pinned above every window) that shows just the picked registers, live,
whatever the main window is showing.

Registers are added from the register table's context menu or from a
dashboard widget's menu. Each row shows the current value (the SAME text as
the table: scaling, enum labels and view mode applied), the min / max seen
since it was added, and how long ago the value last changed. Writable
registers can be written straight from the «Новое» cell.

The list is persisted in ``settings["watch_list"]`` (addresses, in order);
names, units and types are looked up in the current map at display time, so a
watched address that is not in the map says so instead of vanishing.
"""

import time

from PyQt6.QtCore import Qt, QTimer, QSize, pyqtSignal
from PyQt6.QtGui import QColor, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTableWidget,
    QTableWidgetItem, QHeaderView, QAbstractItemView, QMenu,
)

import datatypes
import icons
from gui_table import StateDotDelegate, mono_font

STALE_AFTER = 5.0           # s without a fresh value -> the dot goes grey

COL_DOT, COL_ADDR, COL_NAME, COL_VALUE, COL_MIN, COL_MAX, COL_AGE, COL_NEW = range(8)
# Short headers on purpose: this is a small floating window, and the long
# table captions («ТЕКУЩЕЕ ЗНАЧЕНИЕ») were clipped and starved the names.
_HEADERS = ("", "address", "name", "watchValue", "watchMin", "watchMax",
            "watchChanged", "watchNew")


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


class WatchWindow(QWidget):
    """Floating watch list. Emits ``write_requested(addr, text)`` and
    ``watch_changed(set_of_addrs)``."""

    write_requested = pyqtSignal(int, str)
    watch_changed = pyqtSignal(object)

    def __init__(self, ctx, get_registers, parent=None):
        super().__init__(parent, Qt.WindowType.Tool)
        self.ctx = ctx
        self.get_registers = get_registers
        self.setObjectName("watchWin")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMinimumSize(420, 220)
        self._rows: list[_Row] = []
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
                self.resize(720, 320)
        else:
            self.resize(720, 320)
        self.retranslate(ctx.t)
        self._rebuild()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(1000)

    # ── UI ────────────────────────────────────────────────────────────
    def _build_ui(self):
        c = self.ctx.theme_tokens()
        lo = QVBoxLayout(self)
        lo.setContentsMargins(0, 0, 0, 0)
        lo.setSpacing(0)

        bar = QWidget()
        bar.setObjectName("watchBar")
        bar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(12, 6, 8, 6)
        bl.setSpacing(6)
        self._ico = QLabel()
        self._ico.setPixmap(icons.pixmap("watch", c["text_2"], 16))
        bl.addWidget(self._ico)
        self.lbl_title = QLabel()
        self.lbl_title.setObjectName("mhTitle")
        bl.addWidget(self.lbl_title)
        self.lbl_count = QLabel()
        self.lbl_count.setObjectName("mhBadge")
        bl.addWidget(self.lbl_count)
        bl.addStretch(1)
        self.btn_pin = QPushButton()
        self.btn_pin.setObjectName("iconBtn")
        self.btn_pin.setCheckable(True)
        self.btn_pin.setFixedSize(30, 30)
        self.btn_pin.setIconSize(QSize(16, 16))
        self.btn_pin.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_pin.toggled.connect(lambda on: self._apply_on_top(on))
        bl.addWidget(self.btn_pin)
        self.btn_clear = QPushButton()
        self.btn_clear.setObjectName("iconBtn")
        self.btn_clear.setFixedSize(30, 30)
        self.btn_clear.setIconSize(QSize(16, 16))
        self.btn_clear.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_clear.clicked.connect(self.clear)
        bl.addWidget(self.btn_clear)
        lo.addWidget(bar)

        self.table = QTableWidget(0, len(_HEADERS))
        self.table.setObjectName("watchTable")
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked
                                   | QAbstractItemView.EditTrigger.EditKeyPressed
                                   | QAbstractItemView.EditTrigger.AnyKeyPressed)
        self._dots = StateDotDelegate(self.ctx.theme_tokens(), self.table)
        self.table.setItemDelegateForColumn(COL_DOT, self._dots)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(COL_NAME, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(COL_VALUE, QHeaderView.ResizeMode.Interactive)
        hh.setSectionResizeMode(COL_NEW, QHeaderView.ResizeMode.Interactive)
        self.table.setColumnWidth(COL_VALUE, 110)
        self.table.setColumnWidth(COL_NEW, 80)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._menu)
        self.table.cellChanged.connect(self._on_cell_changed)
        lo.addWidget(self.table, 1)

        self.lbl_empty = QLabel()
        self.lbl_empty.setObjectName("emptyState")
        self.lbl_empty.setWordWrap(True)
        self.lbl_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lo.addWidget(self.lbl_empty, 1)

        sc = QShortcut(QKeySequence(Qt.Key.Key_Delete), self.table)
        sc.activated.connect(self._remove_selected)
        self._paint_icons()

    def _paint_icons(self):
        c = self.ctx.theme_tokens()
        on = self.btn_pin.isChecked()
        self.btn_pin.setIcon(icons.icon("pin", c["accent"] if on else c["text_3"], 16))
        self.btn_clear.setIcon(icons.icon("trash", c["text_3"], 16))
        self._ico.setPixmap(icons.pixmap("watch", c["text_2"], 16))

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
            self._list_changed()

    def _move(self, addr: int, step: int):
        i = next((k for k, r in enumerate(self._rows) if r.addr == addr), None)
        j = None if i is None else i + step
        if i is None or not 0 <= j < len(self._rows):
            return
        self._rows[i], self._rows[j] = self._rows[j], self._rows[i]
        self._list_changed()
        self.table.selectRow(j)

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
    def _item(self, text="", align=Qt.AlignmentFlag.AlignCenter, editable=False):
        it = QTableWidgetItem(text)
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if editable:
            flags |= Qt.ItemFlag.ItemIsEditable
        it.setFlags(flags)
        it.setTextAlignment(align | Qt.AlignmentFlag.AlignVCenter)
        return it

    def _rebuild(self):
        """Full re-render (list changed, map changed, language/theme)."""
        t = self.ctx.t
        regs = self._regs()
        try:
            size = int(self.ctx.settings.get("font_size", 9))
        except (TypeError, ValueError):
            size = 9
        mono = mono_font(size)
        big = mono_font(size + 2)
        big.setBold(True)
        muted = QColor(self.ctx.theme_tokens()["text_4"])
        self.table.blockSignals(True)
        try:
            self.table.setRowCount(len(self._rows))
            for i, row in enumerate(self._rows):
                reg = regs.get(row.addr)
                dot = self._item()
                dot.setData(Qt.ItemDataRole.UserRole, self._state(row))
                self.table.setItem(i, COL_DOT, dot)
                a = self._item(datatypes.key_label(row.addr), Qt.AlignmentFlag.AlignLeft)
                a.setFont(mono)
                self.table.setItem(i, COL_ADDR, a)
                if reg is None:
                    name = self._item(t("watchNotInMap"), Qt.AlignmentFlag.AlignLeft)
                    name.setForeground(muted)
                else:
                    label = (reg.get("name_en") if self.ctx.lang == "en"
                             and reg.get("name_en") else reg.get("name", ""))
                    name = self._item(str(label), Qt.AlignmentFlag.AlignLeft)
                    name.setToolTip(f"{label}\n{reg.get('type', '')} · {reg.get('rw', '')}")
                self.table.setItem(i, COL_NAME, name)
                v = self._item(row.text if row.text is not None else "—")
                v.setFont(big)
                self.table.setItem(i, COL_VALUE, v)
                for col, val in ((COL_MIN, row.vmin), (COL_MAX, row.vmax)):
                    it = self._item("—" if val is None else _num_text(val))
                    it.setFont(mono)
                    self.table.setItem(i, col, it)
                self.table.setItem(i, COL_AGE, self._item(self._age_text(row)))
                writable = reg is not None and datatypes.is_writable(reg)
                # Read-only: an empty cell, not a dash (same rule as the map).
                new = self._item("", Qt.AlignmentFlag.AlignLeft, editable=writable)
                if writable:
                    new.setToolTip(t("watchNewTip"))
                new.setFont(mono)
                self.table.setItem(i, COL_NEW, new)
        finally:
            self.table.blockSignals(False)
        empty = not self._rows
        self.table.setVisible(not empty)
        self.lbl_empty.setVisible(empty)
        self.lbl_count.setText(str(len(self._rows)))

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
        self.table.blockSignals(True)
        try:
            for col, txt in ((COL_VALUE, text),
                             (COL_MIN, "—" if row.vmin is None else _num_text(row.vmin)),
                             (COL_MAX, "—" if row.vmax is None else _num_text(row.vmax)),
                             (COL_AGE, self._age_text(row))):
                it = self.table.item(i, col)
                if it is not None and it.text() != txt:
                    it.setText(txt)
            dot = self.table.item(i, COL_DOT)
            if dot is not None and dot.data(Qt.ItemDataRole.UserRole) != "ok":
                dot.setData(Qt.ItemDataRole.UserRole, "ok")
        finally:
            self.table.blockSignals(False)

    def set_stale_all(self):
        for r in self._rows:
            r.seen_at = None
        self._tick()

    def _tick(self):
        """Once a second: age labels and stale dots."""
        if not self.isVisible():
            return
        self.table.blockSignals(True)
        try:
            for i, row in enumerate(self._rows):
                age = self.table.item(i, COL_AGE)
                if age is not None:
                    age.setText(self._age_text(row))
                dot = self.table.item(i, COL_DOT)
                if dot is not None:
                    dot.setData(Qt.ItemDataRole.UserRole, self._state(row))
        finally:
            self.table.blockSignals(False)
        self.table.viewport().update()

    def reset_minmax(self, addr: int | None = None):
        for r in self._rows:
            if addr is None or r.addr == addr:
                r.vmin = r.vmax = r.num
        self._rebuild()

    # ── interaction ───────────────────────────────────────────────────
    def _selected_addr(self):
        row = self.table.currentRow()
        return self._rows[row].addr if 0 <= row < len(self._rows) else None

    def _remove_selected(self):
        addr = self._selected_addr()
        if addr is not None:
            self.remove(addr)

    def _menu(self, pos):
        it = self.table.itemAt(pos)
        if it is None:
            return
        addr = self._rows[it.row()].addr
        t = self.ctx.t
        m = QMenu(self)
        a_up = m.addAction(t("watchUp"))
        a_down = m.addAction(t("watchDown"))
        m.addSeparator()
        a_reset = m.addAction(t("watchResetMinMax"))
        m.addSeparator()
        a_del = m.addAction(t("watchRemove"))
        chosen = m.exec(self.table.viewport().mapToGlobal(pos))
        if chosen is a_up:
            self._move(addr, -1)
        elif chosen is a_down:
            self._move(addr, +1)
        elif chosen is a_reset:
            self.reset_minmax(addr)
        elif chosen is a_del:
            self.remove(addr)

    def _on_cell_changed(self, row: int, col: int):
        if col != COL_NEW or not 0 <= row < len(self._rows):
            return
        it = self.table.item(row, COL_NEW)
        text = it.text().strip() if it else ""
        if not text or text == "—":
            return
        self.write_requested.emit(self._rows[row].addr, text)
        self.table.blockSignals(True)
        it.setText("")
        self.table.blockSignals(False)

    # ── app plumbing ──────────────────────────────────────────────────
    def refresh_map(self):
        """The register map changed: names, units and writability follow."""
        self._rebuild()

    def apply_settings(self):
        self._dots.set_theme(self.ctx.theme_tokens())
        self._paint_icons()
        self._rebuild()

    def retranslate(self, t):
        self.setWindowTitle(t("watchTitle"))
        self.lbl_title.setText(t("watchTitle"))
        self.lbl_empty.setText(t("watchEmpty"))
        self.btn_pin.setToolTip(t("watchPinTip"))
        self.btn_clear.setToolTip(t("watchClearTip"))
        self.table.setHorizontalHeaderLabels(
            [t(k) if k else "" for k in _HEADERS])
        hdr = self.table.horizontalHeaderItem(COL_NEW)
        if hdr is not None:
            hdr.setToolTip(t("watchNewTip"))
        # Headers sit over their cells: text columns left, readouts centred.
        for col in (COL_ADDR, COL_NAME, COL_NEW):
            h = self.table.horizontalHeaderItem(col)
            if h is not None:
                h.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._rebuild()

    def save_geometry(self):
        g = self.geometry()
        self.ctx.settings["watch_geom"] = [g.x(), g.y(), g.width(), g.height()]

    def hideEvent(self, e):
        self.save_geometry()
        super().hideEvent(e)
