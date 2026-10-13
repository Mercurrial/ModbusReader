# gui_table.py
"""Register-table widget — the dashboard grid, extracted from gui_main as an
MVC-style view.

`RegisterTable` owns everything *about the table itself*: the column schema
(`COLUMNS`), the state-dot delegate, populating rows from a profile, value
formatting + per-register view modes (dec/hex/bin), stale marking, verbose-dot
toggling, and the right-click menu. It references only the `AppContext` (for
settings/theme/translator) and `datatypes`.

It does NOT know about the Modbus core, the trends panel, the status bar or the
memory viewer. Instead it emits *intent* signals that the window routes:
    write_requested(addr, dtype, value)     — cell edit or "Write value…"
    verbose_changed(set[int])               — state-dot click toggled verbose
    value_sampled(reg_id, value)            — a fresh value landed (feed trends)
    inspect_requested(addr, name)           — double-click on a MEMORY_AREA
    trend_add_requested(reg_id, name)       — "Add to Live Chart"
    trend_remove_requested(reg_id)          — "Remove from chart"

The window keeps the coordination glue (it owns those services).
"""
import math
import struct
from dataclasses import dataclass

from PyQt6.QtWidgets import (
    QTableWidget, QTableWidgetItem, QHeaderView, QMenu, QInputDialog,
    QApplication, QStyledItemDelegate, QAbstractItemView,
)
from PyQt6.QtCore import Qt, QSize, QPoint, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QPainter, QFont, QPen

import datatypes
import scaling
from qt_utils import later
from theme_manager import get_theme

# ── column indices ────────────────────────────────────────────────
COL_STATE   = 0   # state dot  (custom delegate)
COL_ADDR    = 1   # address hex
COL_NAME    = 2   # register name
COL_TYPE    = 3   # data type
COL_ACCESS  = 4   # RW / RO
COL_CURRENT = 5   # current value (read-only)
COL_NEW     = 6   # new value     (editable for RW)

# Raw numeric value stored in UserRole+1 for view-mode reformatting.
_ROLE_RAW = Qt.ItemDataRole.UserRole + 1
# State-dot item: True while the register's TX/RX frames go to the log.
_ROLE_VERBOSE = Qt.ItemDataRole.UserRole + 2


# ── dashboard column registry ─────────────────────────────────────
# Single source for the 7 dashboard columns: header (i18n key), the settings
# key gating visibility, and resize behaviour. Drives header text + show/hide.
# The profile editor uses a different, wider schema — kept separate on purpose.
@dataclass(frozen=True)
class Column:
    index: int
    header_key: str            # i18n key ("" = no header text, e.g. the state dot)
    show_key: str = ""         # settings key toggling visibility ("" = always on)
    resize: str = "interactive"  # "fixed" | "interactive" (user-resizable)


# All data columns are Interactive — ResizeToContents/Stretch would make them
# impossible for the user to resize by hand. Initial widths are auto-fitted
# once per populate() (see _autofit_columns).
COLUMNS = (
    Column(COL_STATE,   "",        resize="fixed"),
    Column(COL_ADDR,    "address", "show_addr"),
    Column(COL_NAME,    "name",    "show_name"),
    Column(COL_TYPE,    "type",    "show_type"),
    Column(COL_ACCESS,  "access",  "show_access"),
    Column(COL_CURRENT, "current", "show_current"),
    Column(COL_NEW,     "newVal",  "show_new"),
)

_RESIZE = {
    "fixed":       QHeaderView.ResizeMode.Fixed,
    "interactive": QHeaderView.ResizeMode.Interactive,
}

# The two value columns share whatever width is left after the content columns —
# they're the "flex" columns that absorb/release space so the grid always spans
# the viewport exactly (no horizontal scrollbar) yet stays user-resizable.
_FLEX_COLS = (COL_CURRENT, COL_NEW)

# Minimum width per column (px). Resizing can never drag a column below this;
# once the flex columns hit their floor the grid stops growing and a scrollbar
# is allowed (window genuinely too narrow for the content).
_MINW = {
    COL_STATE: 24, COL_ADDR: 64, COL_NAME: 130, COL_TYPE: 72,
    COL_ACCESS: 58, COL_CURRENT: 96, COL_NEW: 96,
}


_MONO_FAMILY = None


def mono_font(size: int | None = None) -> QFont:
    """Monospace face for addresses/values. Sized like the UI font (Settings →
    Внешний вид → размер) — it used to be pinned at 9 pt, so at a 13 pt UI the
    numbers were the smallest text on screen."""
    global _MONO_FAMILY
    if _MONO_FAMILY is None:
        probe = QFont("JetBrains Mono")
        _MONO_FAMILY = "JetBrains Mono" if probe.exactMatch() else "Consolas"
    f = QFont(_MONO_FAMILY)
    f.setPointSize(int(size) if size else 9)
    return f


def format_value(raw: float, mode: str, bits: int = 16, is_float: bool = False) -> str:
    """Display text for a raw reading in dec / hex / bin.

    *bits* is the register width: a 32-bit LONG shown in hex used to be cut to
    its low 16 bits. A FLOAT in hex/bin shows its IEEE-754 bit pattern — the
    integer part of 21.5 in hex says nothing to anyone."""
    try:
        if mode in ("hex", "bin") and is_float:
            word = struct.unpack(">I", struct.pack(">f", float(raw)))[0]
            return f"0x{word:08X}" if mode == "hex" else f"0b{word:032b}"
        iv = int(raw)
        mask = (1 << bits) - 1
        if mode == "hex":
            return f"0x{iv & mask:0{bits // 4}X}"
        if mode == "bin":
            return f"0b{iv & mask:0{bits}b}"
        # dec — smart
        if raw == iv:
            return str(iv)
        return f"{raw:.4f}".rstrip("0").rstrip(".")
    except (ValueError, OverflowError, struct.error):
        return str(raw)


# ═══════════════════════════════════════════════════════════════════
#  STATE DOT DELEGATE
# ═══════════════════════════════════════════════════════════════════
class StateDotDelegate(QStyledItemDelegate):
    """Paints a 6 × 6 colored circle in the state column. Colors come from the
    active theme's semantic tokens, so the dots track Light/Dark."""

    # state value -> theme token (stale uses a muted text gray).
    _TOKENS = {"ok": "ok", "warn": "warn", "err": "error", "stale": "text_4"}

    def __init__(self, theme: dict, parent=None):
        super().__init__(parent)
        self.set_theme(theme)

    def set_theme(self, theme: dict):
        self._colors = {state: QColor(theme[tok])
                        for state, tok in self._TOKENS.items()}
        self._ring = QColor(theme.get("accent", "#d8dfe6"))

    def paint(self, painter: QPainter, option, index):
        """Dot = data state (grey: nothing fresh, green: reading received
        since connecting). A ring around it = this register's frames are
        being written to the log (click the dot to toggle)."""
        state = index.data(Qt.ItemDataRole.UserRole) or "stale"
        color = self._colors.get(state, self._colors["stale"])
        r  = option.rect
        cx = r.center().x()
        cy = r.center().y()
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if index.data(_ROLE_VERBOSE):
            pen = QPen(self._ring)
            pen.setWidthF(1.5)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(cx - 6, cy - 6, 12, 12)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawEllipse(cx - 3, cy - 3, 6, 6)
        painter.restore()

    def sizeHint(self, option, index):
        return QSize(24, option.rect.height())


# ═══════════════════════════════════════════════════════════════════
#  REGISTER TABLE  (MVC view; emits intent signals)
# ═══════════════════════════════════════════════════════════════════
class RegisterTable(QTableWidget):
    """Dashboard register grid. Owns rendering + interaction; emits intents."""

    write_requested        = pyqtSignal(int, str, str)   # addr, dtype, value
    verbose_changed        = pyqtSignal(object)           # set[int]
    value_sampled          = pyqtSignal(str, float)       # reg_id, value
    inspect_requested      = pyqtSignal(int, str)         # addr, name
    trend_add_requested    = pyqtSignal(str, str)         # reg_id, reg_name
    trend_remove_requested = pyqtSignal(str)              # reg_id
    # A value typed while disconnected: not sent, but the operator is told.
    write_blocked          = pyqtSignal(int, str)         # addr, value

    # Guard against re-entrant column sizing (our setColumnWidth re-emits
    # sectionResized). Class-level default covers any resizeEvent that fires
    # before __init__ finishes.
    _adjusting = False

    def __init__(self, ctx, parent=None):
        super().__init__(0, len(COLUMNS), parent)
        self.ctx = ctx
        self.addr_to_row: dict[int, int] = {}
        # addr -> register dict, for per-register scaling / enum / unit at
        # display time (scaling is a register property, not a type property).
        self._regs_by_addr: dict[int, dict] = {}
        # reg dict per visual row (ALL rows incl. service), for retranslating
        # the NAME column when the UI language flips (name / name_en).
        self._row_regs: list[dict] = []
        self._view_modes: dict[str, str] = {}
        self._verbose_addrs: set[int] = set()
        self._trended: set[str] = set()
        self._connected = False
        # Registers that delivered a reading since the link came up. Data
        # consumers that must not record a frozen value (the logger) read
        # only these; a disconnect clears the set.
        self._fresh: set[int] = set()
        # Settings-driven display flags (refreshed in apply_settings()).
        self._mono_values = bool(ctx.settings.get("mono_values", True))
        self._highlight = bool(ctx.settings.get("highlight_changes", True))
        self._flash_brush = QBrush(QColor(ctx.theme_tokens()["accent_soft"]))

        s = ctx.settings
        self.apply_headers()
        self.verticalHeader().setVisible(s.get("show_row_nums", True))
        self.setAlternatingRowColors(s.get("zebra_rows", True))
        self._state_delegate = StateDotDelegate(ctx.theme_tokens(), self)
        self.setItemDelegateForColumn(COL_STATE, self._state_delegate)

        hdr = self.horizontalHeader()
        hdr.setDefaultAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
        hdr.setStretchLastSection(False)
        for c in COLUMNS:
            hdr.setSectionResizeMode(c.index, _RESIZE[c.resize])
        self.setColumnWidth(COL_STATE, 24)
        # Width-stealing fill: reentrancy guard so our own setColumnWidth() calls
        # (which re-emit sectionResized) don't recurse. See _reflow_columns().
        self._adjusting = False
        hdr.sectionResized.connect(self._on_section_resized)
        self.apply_visibility()
        self.verticalHeader().setDefaultSectionSize(int(s.get("row_height", 26)))

        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)
        self.cellChanged.connect(self._on_cell_changed)
        self.cellClicked.connect(self._on_cell_clicked)
        self.doubleClicked.connect(self._on_double_click)

    # ── column-wise Tab navigation ─────────────────────────────────
    # Tab / Shift+Tab move DOWN / UP the current column (wrapping) so the
    # operator can pour values into "New value" row-after-row.
    def moveCursor(self, action, modifiers):
        cur = self.currentIndex()
        if action == QAbstractItemView.CursorAction.MoveNext:
            return self._step_row(cur, +1)
        if action == QAbstractItemView.CursorAction.MovePrevious:
            return self._step_row(cur, -1)
        return super().moveCursor(action, modifiers)

    def _step_row(self, cur, delta: int):
        rows = self.rowCount()
        if rows <= 0:
            return cur
        col = cur.column() if cur.isValid() else 0
        row = (cur.row() if cur.isValid() else 0) + delta
        row %= rows
        return self.model().index(row, col)

    # ── column / appearance helpers (driven by COLUMNS + settings) ──
    def apply_headers(self):
        self.setHorizontalHeaderLabels(
            [self.ctx.t(c.header_key) if c.header_key else "" for c in COLUMNS])

    def _display_name(self, reg: dict) -> str:
        """Register name for the current UI language: the English name when the
        UI is in English and the register carries a ``name_en``, else the
        primary (Russian) name."""
        if self.ctx.lang == "en" and reg.get("name_en"):
            return str(reg["name_en"])
        return str(reg.get("name", "???"))

    @property
    def t(self):
        """The active translator. The context menu called ``self.t(...)``
        while no such attribute existed, so EVERY right-click raised — and
        with it the only way to put a register on a live chart was gone."""
        return self.ctx.t

    def retranslate(self):
        """Re-apply headers AND the NAME column for the new UI language — the
        register names flip between name / name_en without a full repopulate
        (which would drop live values and view state)."""
        self.apply_headers()
        dot_tip = self.ctx.t("stateDotTip")
        self.blockSignals(True)
        try:
            for row, reg in enumerate(self._row_regs):
                it = self.item(row, COL_NAME)
                if it is not None:
                    name = self._display_name(reg)
                    it.setText(name)
                    it.setToolTip(name)
                dtype = reg.get("type", "SHORT")
                if datatypes.is_area(dtype):
                    cur = self.item(row, COL_CURRENT)
                    if cur is not None:
                        cur.setText(self._placeholder(dtype))
                else:
                    dot = self.item(row, COL_STATE)
                    if dot is not None:
                        dot.setToolTip(dot_tip)
        finally:
            self.blockSignals(False)

    def apply_visibility(self):
        for c in COLUMNS:
            if c.show_key:
                self.setColumnHidden(
                    c.index, not self.ctx.settings.get(c.show_key, True))

    def _font_size(self) -> int:
        try:
            return max(7, min(24, int(self.ctx.settings.get("font_size", 9))))
        except (TypeError, ValueError):
            return 9

    def apply_settings(self):
        """Re-apply settings-driven appearance (called on a settings change)."""
        s = self.ctx.settings
        self.verticalHeader().setVisible(s.get("show_row_nums", True))
        self.apply_visibility()
        self.setAlternatingRowColors(s.get("zebra_rows", True))
        self.verticalHeader().setDefaultSectionSize(int(s.get("row_height", 26)))
        tokens = self.ctx.theme_tokens()
        self._state_delegate.set_theme(tokens)
        self._highlight = bool(s.get("highlight_changes", True))
        self._flash_brush = QBrush(QColor(tokens["accent_soft"]))
        # mono_values / font size may have changed — re-apply fonts in place.
        mono = bool(s.get("mono_values", True))
        size = self._font_size()
        if mono != self._mono_values or size != getattr(self, "_font_pt", size):
            self._mono_values = mono
            self._font_pt = size
            self._apply_cell_fonts()
        self._font_pt = size
        # Column visibility may have changed — re-fill so the value columns
        # reclaim/yield the freed space and the grid still spans the viewport.
        self._fit_to_viewport()
        self.viewport().update()

    def _apply_cell_fonts(self):
        ident = mono_font(self._font_size())
        value = ident if self._mono_values else self.font()
        self.blockSignals(True)
        try:
            for r in range(self.rowCount()):
                for col, font in ((COL_ADDR, ident), (COL_ACCESS, ident),
                                  (COL_CURRENT, value), (COL_NEW, value)):
                    it = self.item(r, col)
                    if it is not None:
                        it.setFont(font)
        finally:
            self.blockSignals(False)

    # ── window-facing state hooks ──────────────────────────────────
    def set_connected(self, connected: bool):
        self._connected = connected

    def set_trended(self, reg_ids):
        self._trended = set(reg_ids)

    def clear_view_state(self):
        """Forget per-register view modes + verbose flags (on a fresh profile)."""
        self._view_modes.clear()
        self._verbose_addrs.clear()
        self._fresh.clear()

    # ── register helpers ───────────────────────────────────────────
    @staticmethod
    def _writable(rw) -> bool:
        """'W' anywhere in the access code: RW and write-only W both write.
        Comparing to "RW" exactly locked write-only registers (imported
        vendor maps use them) out of the New-value column."""
        return "W" in str(rw or "").upper()

    def _placeholder(self, dtype: str) -> str:
        if dtype == "MEMORY_AREA":
            return self.ctx.t("cellMemoryArea")
        if dtype == "UNUSED_AREA":
            return self.ctx.t("cellReserved")
        return "—"

    def _type_shape(self, addr: int) -> tuple:
        """(bit width, is IEEE float) of the register at *addr*."""
        dtype = self._regs_by_addr.get(addr, {}).get("type", "SHORT")
        span = datatypes.FIXED_TYPE_LEN.get(dtype, 1)
        return (32 if span >= 2 else 16), dtype == "FLOAT"

    # ── data ───────────────────────────────────────────────────────
    def populate(self, profile: list[dict]):
        c = get_theme(self.ctx.settings.get("theme", "Dark"))
        muted = QColor(c["text_4"])
        t = self.ctx.t
        size = self._font_size()
        self._font_pt = size
        ident_font = mono_font(size)
        value_font = ident_font if self._mono_values else self.font()
        dot_tip = t("stateDotTip")

        self.blockSignals(True)
        try:
            self.addr_to_row.clear()
            self._regs_by_addr.clear()
            self._fresh.clear()
            self._row_regs = list(profile)
            self.setRowCount(len(profile))

            for row, reg in enumerate(profile):
                addr = reg.get("addr", 0)
                if isinstance(addr, str):
                    try:
                        addr = int(addr, 0) if addr.strip() else 0
                    except ValueError:
                        addr = 0
                name       = self._display_name(reg)
                dtype      = reg.get("type", "SHORT")
                rw         = reg.get("rw", "R")
                is_service = datatypes.is_area(dtype)
                writable   = self._writable(rw) and not is_service

                state_item = QTableWidgetItem()
                state_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                state_item.setData(Qt.ItemDataRole.UserRole, "stale")
                if not is_service:
                    state_item.setToolTip(dot_tip)

                addr_item = QTableWidgetItem(f"0x{addr:04X}")
                addr_item.setFlags(addr_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                addr_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                addr_item.setFont(ident_font)

                name_item = QTableWidgetItem(name)
                name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                name_item.setToolTip(name)

                type_item = QTableWidgetItem(dtype)
                type_item.setFlags(type_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                type_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

                access_item = QTableWidgetItem(rw)
                access_item.setFlags(access_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                access_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                access_item.setFont(ident_font)
                if not writable:
                    access_item.setForeground(muted)

                # Values honor the mono_values setting; addr/access stay
                # monospace (they're identifiers, not data).
                val_item = QTableWidgetItem(self._placeholder(dtype))
                val_item.setFlags(val_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                val_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                val_item.setFont(value_font)

                new_val_item = QTableWidgetItem("")
                new_val_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                new_val_item.setFont(value_font)
                if not writable:
                    new_val_item.setFlags(new_val_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    new_val_item.setForeground(muted)
                    new_val_item.setText("—")

                if is_service:
                    for item in (addr_item, name_item, type_item, access_item,
                                 val_item, new_val_item):
                        item.setForeground(muted)

                self.setItem(row, COL_STATE,   state_item)
                self.setItem(row, COL_ADDR,    addr_item)
                self.setItem(row, COL_NAME,    name_item)
                self.setItem(row, COL_TYPE,    type_item)
                self.setItem(row, COL_ACCESS,  access_item)
                self.setItem(row, COL_CURRENT, val_item)
                self.setItem(row, COL_NEW,     new_val_item)

                if not is_service:
                    self.addr_to_row[addr] = row
                    self._regs_by_addr[addr] = reg
        finally:
            self.blockSignals(False)
        self._fit_to_viewport()

    # ── full-width layout with width-stealing resize ───────────────────
    def _visible_cols(self) -> list[int]:
        return [c.index for c in COLUMNS if not self.isColumnHidden(c.index)]

    def _fit_to_viewport(self):
        """Initial fit after (re)populate: content-size the fixed columns, then
        let the value columns fill the rest so the grid spans the whole viewport.
        The user can still drag any border afterwards (see _on_section_resized)."""
        self._adjusting = True
        try:
            for idx in self._visible_cols():
                if idx == COL_STATE or idx in _FLEX_COLS:
                    continue
                self.resizeColumnToContents(idx)
                self.setColumnWidth(
                    idx, max(_MINW.get(idx, 60), self.columnWidth(idx) + 16))
            self.setColumnWidth(COL_NAME, max(200, self.columnWidth(COL_NAME)))
        finally:
            self._adjusting = False
        self._reflow_columns()
        # Run once more after layout settles: at populate time the viewport may
        # not have its final width yet (e.g. before the vertical scrollbar
        # appears), which would leave the flex columns slightly off.
        later(0, self, self._reflow_columns)

    def _reflow_columns(self, exclude: int | None = None):
        """Keep total column width == viewport width.

        The flex value columns (CURRENT/NEW) share the leftover space equally; if
        they bottom out at their minimum and the grid would still overflow, the
        overflow is stolen back from `exclude` (the column the user is dragging)
        so widening one column visibly narrows another instead of spilling past
        the edge into a horizontal scrollbar."""
        if self._adjusting:
            return
        vp = self.viewport().width()
        if vp <= 0:
            return
        self._adjusting = True
        try:
            vis = self._visible_cols()
            flex = [c for c in _FLEX_COLS if c in vis and c != exclude]
            if flex:
                fixed_sum = sum(self.columnWidth(c) for c in vis if c not in flex)
                leftover = vp - fixed_sum
                base = leftover // len(flex)
                for i, c in enumerate(flex):
                    share = base + (leftover - base * len(flex) if i == 0 else 0)
                    self.setColumnWidth(c, max(_MINW.get(c, 96), share))
            # If the flex columns hit their floor (or none were available), take
            # the remaining overflow out of the dragged column.
            over = sum(self.columnWidth(c) for c in vis) - vp
            if over > 0 and exclude is not None and exclude in vis:
                self.setColumnWidth(
                    exclude, max(_MINW.get(exclude, 60),
                                 self.columnWidth(exclude) - over))
        finally:
            self._adjusting = False

    def _on_section_resized(self, idx: int, _old: int, _new: int):
        # User (or code) dragged a border: re-fill so the value columns absorb
        # the change and the grid keeps exactly spanning the viewport.
        self._reflow_columns(exclude=idx)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reflow_columns()

    def current_values(self, fresh_only: bool = False) -> dict:
        """``{addr: value text}`` for every register that has a reading.

        The text is the ENGINEERING value (scaling applied, enum label if any)
        but WITHOUT the unit and always in decimal. It used to be the cell
        text verbatim, so a scaled register reached the snapshot as "12.5 V"
        (rendered "12.5 V V" and never compared numerically) and the CSV
        logger wrote "12,5 V" — text, not a number, in the one file meant for
        charting; a register viewed in hex logged "0x002A".

        *fresh_only* keeps just registers read since the link came up: a
        logger must write an empty cell, not repeat a frozen last value for
        hours after the device went silent."""
        out = {}
        for addr, row in self.addr_to_row.items():
            if fresh_only and addr not in self._fresh:
                continue
            item = self.item(row, COL_CURRENT)
            if item is None:
                continue
            raw = item.data(_ROLE_RAW)
            if raw is None:
                text = item.text().strip()
                if text and text != "—":
                    out[addr] = text          # non-numeric reading, as shown
                continue
            reg = self._regs_by_addr.get(addr, {})
            if scaling.has_scaling(reg) or scaling.get_enum(reg):
                out[addr] = scaling.format_value(reg, raw, unit=False)
            else:
                out[addr] = format_value(float(raw), "dec")
        return out

    def update_value(self, addr: int, val_str: str):
        """Update one register's current-value cell; emit value_sampled when a
        numeric value lands (the window feeds it to trends and the dashboard)."""
        row = self.addr_to_row.get(addr)
        if row is None:
            return
        sampled = None
        reg = self._regs_by_addr.get(addr, {})
        scaled = scaling.has_scaling(reg) or bool(scaling.get_enum(reg))
        # try/finally: an exception between blockSignals(True) and (False)
        # used to leave the table deaf for good — every later cell edit (i.e.
        # every write the operator typed) was silently ignored.
        self.blockSignals(True)
        try:
            self._fresh.add(addr)
            state = self.item(row, COL_STATE)
            if state is not None and state.data(Qt.ItemDataRole.UserRole) != "ok":
                state.setData(Qt.ItemDataRole.UserRole, "ok")
            ci = self.item(row, COL_CURRENT)
            if ci:
                try:
                    raw = float(val_str)
                except (ValueError, TypeError):
                    ci.setData(_ROLE_RAW, None)
                    ci.setText(val_str)
                else:
                    prev = ci.data(_ROLE_RAW)
                    ci.setData(_ROLE_RAW, raw)
                    if scaled:
                        # Engineering units / enum label. dec/hex/bin view
                        # modes don't apply to a scaled or symbolic value.
                        ci.setText(scaling.format_value(reg, raw, unit=True))
                        sampled = scaling.to_engineering(reg, raw)
                    else:
                        mode = self._view_modes.get(f"0x{addr:04X}", "dec")
                        bits, is_float = self._type_shape(addr)
                        ci.setText(format_value(raw, mode, bits, is_float))
                        sampled = raw
                    # highlight_changes: flash the cell when the value changed.
                    if self._highlight and prev is not None and prev != raw:
                        self._flash(ci)
        finally:
            self.blockSignals(False)
        # NaN / ±inf (a broken sensor) are shown, but never fed to charts:
        # one non-finite sample wrecks a plot's auto-range.
        if isinstance(sampled, float) and math.isfinite(sampled):
            self.value_sampled.emit(f"0x{addr:04X}", sampled)

    def _flash(self, item):
        """Short background pulse on a changed cell (highlight_changes)."""
        item.setBackground(self._flash_brush)
        row, col = item.row(), item.column()

        def _restore():
            it = self.item(row, col)
            if it is not None:
                self.blockSignals(True)
                try:
                    it.setBackground(QBrush())
                finally:
                    self.blockSignals(False)
        later(280, self, _restore)

    def mark_all_stale(self):
        """Reset every state dot to stale (on disconnect). The verbose rings
        stay: logging for those registers resumes with the next connection."""
        self._fresh.clear()
        self.blockSignals(True)
        try:
            for row in range(self.rowCount()):
                item = self.item(row, COL_STATE)
                if item:
                    item.setData(Qt.ItemDataRole.UserRole, "stale")
        finally:
            self.blockSignals(False)
        self.viewport().update()

    def set_view_mode(self, reg_id: str, row: int, mode: str):
        self._view_modes[reg_id] = mode
        ci = self.item(row, COL_CURRENT)
        if ci:
            raw = ci.data(_ROLE_RAW)
            if raw is not None:
                try:
                    addr = int(reg_id, 16)
                except ValueError:
                    addr = -1
                bits, is_float = self._type_shape(addr)
                ci.setText(format_value(float(raw), mode, bits, is_float))

    # ── writes (convert engineering → raw for scaled registers) ────
    def _emit_write(self, addr: int, dtype: str, text: str):
        """Emit a write intent. For a scaled register the user typed an
        engineering value (e.g. 12.34 V); convert it back to the RAW register
        value (1234) the device expects. An enum register also accepts its
        LABEL ("Работа") and writes the matching number."""
        reg = self._regs_by_addr.get(addr, {})
        enum = scaling.get_enum(reg)
        if enum:
            wanted = str(text).strip().lower()
            for key, label in enum.items():
                if label.strip().lower() == wanted:
                    text = str(key)
                    break
        if scaling.has_scaling(reg):
            try:
                raw = scaling.to_raw(reg, float(str(text).replace(",", ".")))
                text = repr(round(raw, 6))       # kill float dust before encode
            except (ValueError, TypeError):
                pass
        self.write_requested.emit(addr, dtype, str(text).strip())

    # ── interaction (emits intents) ────────────────────────────────
    def _on_cell_changed(self, row: int, col: int):
        if col != COL_NEW:
            return
        item = self.item(row, COL_NEW)
        if not item or not item.text().strip() or item.text() == "—":
            return
        addr_item = self.item(row, COL_ADDR)
        type_item = self.item(row, COL_TYPE)
        if not addr_item or not type_item:
            return
        try:
            addr = int(addr_item.text(), 16)
        except ValueError:
            return
        value = item.text().strip()
        if self._connected:
            self._emit_write(addr, type_item.text(), value)
        else:
            # Not sent — but never silently: the value used to just sit in the
            # cell with nothing saying it went nowhere.
            self.write_blocked.emit(addr, value)
        self.blockSignals(True)
        try:
            item.setText("")
        finally:
            self.blockSignals(False)

    def _on_cell_clicked(self, row: int, col: int):
        # New-value column: jump straight into edit mode on a single click.
        if col == COL_NEW:
            item = self.item(row, COL_NEW)
            if item and (item.flags() & Qt.ItemFlag.ItemIsEditable):
                self.editItem(item)
            return
        if col != COL_STATE:
            return
        addr_item = self.item(row, COL_ADDR)
        type_item = self.item(row, COL_TYPE)
        if not addr_item or not type_item or datatypes.is_area(type_item.text()):
            return
        try:
            addr = int(addr_item.text(), 16)
        except ValueError:
            return
        state_item = self.item(row, COL_STATE)
        if not state_item:
            return
        on = addr not in self._verbose_addrs
        if on:
            self._verbose_addrs.add(addr)
        else:
            self._verbose_addrs.discard(addr)
        state_item.setData(_ROLE_VERBOSE, on)
        self.verbose_changed.emit(self._verbose_addrs.copy())

    def _on_double_click(self, index):
        row = index.row()
        type_item = self.item(row, COL_TYPE)
        if not type_item or type_item.text() != "MEMORY_AREA":
            return
        addr_item = self.item(row, COL_ADDR)
        if not addr_item:
            return
        try:
            addr = int(addr_item.text(), 16)
        except ValueError:
            return
        name_item = self.item(row, COL_NAME)
        self.inspect_requested.emit(addr, name_item.text() if name_item else "Memory")

    def _show_context_menu(self, pos: QPoint):
        item = self.itemAt(pos)
        if item is None:
            return
        row       = item.row()
        addr_item = self.item(row, COL_ADDR)
        name_item = self.item(row, COL_NAME)
        type_item = self.item(row, COL_TYPE)
        cur_item  = self.item(row, COL_CURRENT)
        acc_item  = self.item(row, COL_ACCESS)
        if not addr_item:
            return
        if type_item and datatypes.is_area(type_item.text()):
            return

        reg_id   = addr_item.text()
        reg_name = name_item.text() if name_item else f"Reg_{row}"
        cur_val  = cur_item.text() if cur_item else "—"
        rw       = acc_item.text() if acc_item else "R"
        try:
            reg = self._regs_by_addr.get(int(reg_id, 16), {})
        except ValueError:
            reg = {}
        symbolic = scaling.has_scaling(reg) or bool(scaling.get_enum(reg))

        menu = QMenu(self)

        if reg_id in self._trended:
            act = menu.addAction(self.t("ctxTrendRemove"))
            act.triggered.connect(lambda: self.trend_remove_requested.emit(reg_id))
        else:
            act = menu.addAction(self.t("ctxTrendAdd"))
            act.triggered.connect(lambda: self.trend_add_requested.emit(reg_id, reg_name))

        # dec/hex/bin is about a raw number; an engineering value or an enum
        # label has no meaningful hex form, so the submenu is not offered.
        if not symbolic:
            menu.addSeparator()
            view_menu = menu.addMenu(self.t("ctxViewAs"))
            mode = self._view_modes.get(reg_id, "dec")
            for label, key in [(self.t("ctxDec"), "dec"), (self.t("ctxHex"), "hex"),
                               (self.t("ctxBin"), "bin")]:
                a = view_menu.addAction(label)
                a.setCheckable(True)
                a.setChecked(mode == key)
                a.triggered.connect(lambda _, k=key: self.set_view_mode(reg_id, row, k))

        menu.addSeparator()
        act_cv = menu.addAction(f'{self.t("ctxCopyValue")}   [{cur_val}]')
        act_cv.triggered.connect(lambda: QApplication.clipboard().setText(cur_val))
        act_ca = menu.addAction(f'{self.t("ctxCopyAddr")}   [{reg_id}]')
        act_ca.triggered.connect(lambda: QApplication.clipboard().setText(reg_id))

        if self._writable(rw):
            menu.addSeparator()
            act_w = menu.addAction(self.t("ctxWrite"))
            act_w.triggered.connect(lambda: self._prompt_write(row))

        menu.exec(self.viewport().mapToGlobal(pos))

    def _prompt_write(self, row: int):
        addr_item = self.item(row, COL_ADDR)
        type_item = self.item(row, COL_TYPE)
        if not addr_item or not type_item:
            return
        dtype = type_item.text()
        val, ok = QInputDialog.getText(
            self, self.t("ctxWrite"),
            self.t("writePrompt").format(addr=addr_item.text(), type=dtype))
        if not ok or not val.strip():
            return
        try:
            addr = int(addr_item.text(), 16)
        except ValueError:
            return
        if not self._connected:
            self.write_blocked.emit(addr, val.strip())
            return
        self._emit_write(addr, dtype, val.strip())
