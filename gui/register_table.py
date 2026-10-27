# gui/register_table.py
"""Register-table widget — the dashboard grid, extracted from gui/main_window.py as an
MVC-style view.

`RegisterTable` owns everything *about the table itself*: the column schema
(`COLUMNS`), the state column (a status dot + a «log this register» toggle),
the write fields of the New-value column, populating rows from a profile, value
formatting + per-register view modes (dec/hex/bin), stale marking, and the
right-click menu.

The state column used to be ONE dot doing two jobs — green «a value arrived»
and, on a click, «write this register's frames to the log» shown as a ring.
Nobody guessed the click. Now the dot only tells how fresh the value is
(green fresh, amber late, grey no link, hollow nothing yet) and the log has a
button of its own: the console glyph next to the dot, shown on the hovered row
and lit while on — the same switch is in the right-click menu. It references only the `AppContext` (for
settings/theme/translator) and `datatypes`.

It does NOT know about the Modbus core, the trends panel, the status bar or the
memory viewer. Instead it emits *intent* signals that the window routes:
    write_requested(addr, dtype, value)     — cell edit or "Write value…"
    verbose_changed(set[int])               — the log toggle (console glyph)
    value_sampled(reg_id, value)            — a fresh value landed (feed trends)
    inspect_requested(addr, name)           — double-click on a MEMORY_AREA
    trend_add_requested(reg_id, name)       — "Add to Live Chart"
    trend_remove_requested(reg_id)          — "Remove from chart"

The window keeps the coordination glue (it owns those services).
"""
import math
import re
import struct
import time
from dataclasses import dataclass

from PyQt6.QtWidgets import (
    QTableWidget, QTableWidgetItem, QHeaderView, QMenu,
    QApplication, QStyledItemDelegate, QAbstractItemView, QStyleOptionViewItem,
    QStyle, QToolTip,
)
from PyQt6.QtCore import Qt, QSize, QPoint, QRect, QRectF, QTimer, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QPainter, QFont, QPen

from core import datatypes
from gui import icons
from core import scaling
from gui.dialogs import themed_input
from gui.qt_utils import later
from gui.widgets import RowNumberHeader

# ── column indices ────────────────────────────────────────────────
COL_STATE   = 0   # state dot  (custom delegate)
COL_ADDR    = 1   # address hex
COL_NAME    = 2   # register name
COL_TYPE    = 3   # data type
COL_ACCESS  = 4   # RW / RO
COL_CURRENT = 5   # current value (read-only)
COL_NEW     = 6   # new value     (editable for RW)

_INT_LITERAL = re.compile(r"-?\d+")

# Raw numeric value stored in UserRole+1 for view-mode reformatting.
_ROLE_RAW = Qt.ItemDataRole.UserRole + 1
# State-dot item: True while the register's TX/RX frames go to the log.
_ROLE_VERBOSE = Qt.ItemDataRole.UserRole + 2
# Address cell: the register KEY (area << 16 | addr, see datatypes.AREAS).
_ROLE_KEY = Qt.ItemDataRole.UserRole + 3
# Value cell: still showing the "no reading yet" placeholder (drawn muted).
_ROLE_PLACEHOLDER = Qt.ItemDataRole.UserRole + 4
# State item: monotonic time of the last reading, and the gap before it —
# a value is "late" when it has not come for three of its usual gaps.
_ROLE_TS = Qt.ItemDataRole.UserRole + 5
_ROLE_GAP = Qt.ItemDataRole.UserRole + 6

# The state column: the status dot, then the log toggle.
STATE_W = 46
_DOT_X = 13                 # dot centre, from the cell's left edge
_LOG_X0 = 24                # the toggle's zone starts here
LATE_MIN_S = 3.0            # never "late" sooner than this


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
    COL_STATE: STATE_W, COL_ADDR: 64, COL_NAME: 130, COL_TYPE: 72,
    COL_ACCESS: 58, COL_CURRENT: 110, COL_NEW: 132,
}


def mono_font(size: int | None = None) -> QFont:
    """Monospace face for addresses/values. Sized like the UI font (Settings →
    Внешний вид → размер) — it used to be pinned at 9 pt, so at a 13 pt UI the
    numbers were the smallest text on screen."""
    from app.fonts import mono_family
    f = QFont(mono_family())
    f.setPointSize(int(size) if size else 9)
    return f


def format_value(raw: float, mode: str, bits: int = 16, is_float: bool = False) -> str:
    """Display text for a raw reading in dec / hex / bin.

    *bits* is the register width: a 32-bit LONG shown in hex used to be cut to
    its low 16 bits. A FLOAT in hex/bin shows its IEEE-754 bit pattern — the
    integer part of 21.5 in hex says nothing to anyone."""
    try:
        if mode in ("hex", "bin") and is_float:
            if bits >= 64:
                word = struct.unpack(">Q", struct.pack(">d", float(raw)))[0]
                bits = 64
            else:
                word = struct.unpack(">I", struct.pack(">f", float(raw)))[0]
                bits = 32
        else:
            word = int(raw) & ((1 << bits) - 1)
        if mode == "hex":
            return f"0x{word:0{bits // 4}X}"
        if mode == "bin":
            # Nibble groups: 16 bare binary digits cannot be read at a glance,
            # and binary is how a BITS16 status word is shown by default.
            digits = f"{word:0{bits}b}"
            return "0b" + " ".join(digits[i:i + 4] for i in range(0, bits, 4))
        iv = int(raw)
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
    """The state column: a status dot and the «log this register» toggle.

    Dot: green — a fresh value; amber — connected, but no value for three
    of this register's usual gaps (the device stopped answering it); grey —
    no link (the last value is still shown); a hollow ring — no value since
    the map was opened. Toggle: the console glyph, on the hovered row
    (faint) or lit while the register's frames go to the log."""

    def __init__(self, theme: dict, parent=None):
        super().__init__(parent)
        self.set_theme(theme)

    def set_theme(self, theme: dict):
        grey = QColor(theme["text_4"])
        self._colors = {"fresh": QColor(theme["ok"]), "late": QColor(theme["warn"]),
                        "waiting": grey, "offline": grey, "none": grey}
        # The toggle: on — a filled accent chip (a pressed button); the
        # pointer on it — a soft chip; elsewhere on the row — a faint glyph.
        self._chip = {"on": QColor(theme["accent"]), "hover": QColor(theme["bg_3"])}
        self._tok = {"on": theme["accent_fg"], "hover": theme["text_1"],
                     "idle": theme["text_4"]}

    @staticmethod
    def has_state(index) -> bool:
        """A register row (a service row — memory area, reserve — has none)."""
        return index.data(_ROLE_VERBOSE) is not None

    @staticmethod
    def freshness(index, connected: bool, now: float | None = None) -> str:
        """"fresh" | "late" | "waiting" | "offline" | "none" for *index*'s row.
        "waiting": reconnected, the last value is from the link before."""
        ts = index.data(_ROLE_TS)
        if ts is None:
            return "none"
        if not connected:
            return "offline"
        if index.data(Qt.ItemDataRole.UserRole) != "ok":
            return "waiting"
        gap = index.data(_ROLE_GAP) or 0.0
        age = (time.monotonic() if now is None else now) - ts
        return "fresh" if age <= max(LATE_MIN_S, 3.0 * gap) else "late"

    def paint(self, painter: QPainter, option, index):
        # The cell's own background first (zebra stripe, selection, the row
        # line): painting only the dot left this column a dark square in
        # every other row — a checkerboard down the left edge.
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.text = ""
        widget = option.widget
        style = widget.style() if widget is not None else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, widget)
        if not self.has_state(index):
            return                                  # a service row: no state
        table = widget if isinstance(widget, RegisterTable) else None
        kind = self.freshness(index, bool(table and table._connected))
        r = option.rect
        cx, cy = r.left() + _DOT_X, r.center().y()
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = self._colors[kind]
        if kind == "none":
            pen = QPen(color)
            pen.setWidthF(1.2)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QRectF(cx - 3, cy - 3, 6, 6))
        else:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            painter.drawEllipse(QRectF(cx - 3.5, cy - 3.5, 7, 7))
        on = bool(index.data(_ROLE_VERBOSE))
        hovered = table is not None and table._hover_row == index.row()
        if on or hovered:
            tone = ("on" if on else
                    "hover" if (hovered and table._hover_log) else "idle")
            x = r.left() + _LOG_X0 + max(0, (r.width() - _LOG_X0 - 14) // 2)
            if tone in self._chip:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(self._chip[tone])
                painter.drawRoundedRect(QRectF(x - 3, cy - 9, 20, 18), 4, 4)
            painter.drawPixmap(x, cy - 7, icons.pixmap("terminal", self._tok[tone], 14))
        painter.restore()

    def sizeHint(self, option, index):
        return QSize(STATE_W, option.rect.height())


class NewValueDelegate(QStyledItemDelegate):
    """The New-value column: a register you can write gets a real input
    field — a rounded box with a pencil — and one you cannot gets nothing.
    Before, both were the same blank cell and only a click told them apart."""

    def __init__(self, theme: dict, parent=None):
        super().__init__(parent)
        self.set_theme(theme)

    def set_theme(self, theme: dict):
        self._fill = QColor(theme["bg_2"])
        self._line = QColor(theme["line"])
        self._line_hover = QColor(theme["line_strong"])
        self._text = QColor(theme["text_1"])
        self._pencil = {"idle": theme["text_4"], "hover": theme["text_2"]}

    @staticmethod
    def field_rect(rect: QRect) -> QRect:
        return rect.adjusted(4, 3, -6, -3)

    def paint(self, painter: QPainter, option, index):
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        text = opt.text
        opt.text = ""
        widget = option.widget
        style = widget.style() if widget is not None else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, widget)
        if not index.flags() & Qt.ItemFlag.ItemIsEditable:
            return                                  # read-only: an empty cell
        table = widget if isinstance(widget, RegisterTable) else None
        hovered = table is not None and table._hover_row == index.row()
        r = self.field_rect(option.rect)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(self._line_hover if hovered else self._line, 1))
        painter.setBrush(self._fill)
        painter.drawRoundedRect(QRectF(r).adjusted(0.5, 0.5, -0.5, -0.5), 4, 4)
        if text:
            painter.setPen(self._text)
            painter.setFont(opt.font)
            area = r.adjusted(8, 0, -24, 0)
            painter.drawText(area, int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                             opt.fontMetrics.elidedText(text, Qt.TextElideMode.ElideRight,
                                                        area.width()))
        pm = icons.pixmap("edit", self._pencil["hover" if hovered else "idle"], 12)
        painter.drawPixmap(r.right() - 18, r.center().y() - 6, pm)
        painter.restore()

    def createEditor(self, parent, option, index):
        editor = super().createEditor(parent, option, index)
        editor.setObjectName("newValEditor")
        return editor

    def updateEditorGeometry(self, editor, option, index):
        editor.setGeometry(self.field_rect(option.rect))


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
    # Every reading as SHOWN (scaling/enum/view mode applied) + the
    # engineering number (None for text) — feeds the watch window.
    value_shown            = pyqtSignal(int, str, object)
    watch_toggle_requested = pyqtSignal(int)              # addr

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
        self._watched: set[int] = set()
        # Settings-driven display flags (refreshed in apply_settings()).
        self._mono_values = bool(ctx.settings.get("mono_values", True))
        self._highlight = bool(ctx.settings.get("highlight_changes", True))
        self._flash_brush = QBrush(QColor(ctx.theme_tokens()["accent_soft"]))

        s = ctx.settings
        self.setVerticalHeader(RowNumberHeader(self))
        self.apply_headers()
        self.verticalHeader().setVisible(s.get("show_row_nums", True))
        self.verticalHeader().setDefaultAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._set_zebra(s.get("zebra_rows", True))
        self._state_delegate = StateDotDelegate(ctx.theme_tokens(), self)
        self.setItemDelegateForColumn(COL_STATE, self._state_delegate)
        self._new_delegate = NewValueDelegate(ctx.theme_tokens(), self)
        self.setItemDelegateForColumn(COL_NEW, self._new_delegate)
        # The hovered row shows its log toggle and lifts its write field.
        self._hover_row = -1
        self._hover_log = False
        self.setMouseTracking(True)
        # The dots age without new data: a slow tick repaints the column.
        self._age_timer = QTimer(self)
        self._age_timer.setInterval(1000)
        self._age_timer.timeout.connect(self._repaint_states)
        self._age_timer.start()

        hdr = self.horizontalHeader()
        # Left-aligned, like the cells under them: a header centred over a
        # left-aligned column points at nothing.
        hdr.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        hdr.setStretchLastSection(False)
        for c in COLUMNS:
            hdr.setSectionResizeMode(c.index, _RESIZE[c.resize])
        self.setColumnWidth(COL_STATE, STATE_W)
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
        acc = self.horizontalHeaderItem(COL_ACCESS)
        if acc is not None:                  # a two-letter code: centred
            acc.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

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
                    new = self.item(row, COL_NEW)
                    if new is not None:
                        new.setToolTip(self.ctx.t("newValTip" if datatypes.is_writable(reg)
                                                  else "newValReadOnly"))
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
        self._set_zebra(s.get("zebra_rows", True))
        self.verticalHeader().setDefaultSectionSize(int(s.get("row_height", 26)))
        tokens = self.ctx.theme_tokens()
        self._state_delegate.set_theme(tokens)
        self._new_delegate.set_theme(tokens)
        self._highlight = bool(s.get("highlight_changes", True))
        self._flash_brush = QBrush(QColor(tokens["accent_soft"]))
        self._recolor()
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

    def _set_zebra(self, on: bool):
        """Stripes OR row lines, never both: two structures on one grid read
        as noise (QSS keys the row line off the [zebra] property)."""
        self.setAlternatingRowColors(bool(on))
        self.setProperty("zebra", "true" if on else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    # ── window-facing state hooks ──────────────────────────────────
    def set_connected(self, connected: bool):
        self._connected = connected
        self.viewport().update()                    # the dots follow the link

    def set_trended(self, reg_ids):
        self._trended = set(reg_ids)

    def set_watched(self, addrs):
        self._watched = set(addrs)

    def request_write(self, addr: int, text: str):
        """Write from outside the grid (the watch window): same scaling/enum
        conversion and the same not-connected handling as a typed cell."""
        reg = self._regs_by_addr.get(int(addr))
        if reg is None:
            return
        if not self._connected:
            self.write_blocked.emit(int(addr), str(text))
            return
        self._emit_write(int(addr), reg.get("type", "SHORT"), str(text))

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

    def _row_key(self, row: int):
        """The register key of *row* (None for a missing row)."""
        item = self.item(row, COL_ADDR)
        if item is None:
            return None
        key = item.data(_ROLE_KEY)
        return int(key) if key is not None else None

    def _type_shape(self, addr: int) -> tuple:
        """(bit width, is IEEE float) of the register at *addr*."""
        dtype = self._regs_by_addr.get(addr, {}).get("type", "SHORT")
        span = datatypes.FIXED_TYPE_LEN.get(dtype, 1)
        return min(64, 16 * max(1, span)), dtype in ("FLOAT", "DOUBLE")

    def _view_mode(self, addr: int) -> str:
        """The user's dec/hex/bin choice, else the type's default (a BITS16
        status word opens in binary)."""
        reg_id = f"0x{addr:04X}"
        if reg_id in self._view_modes:
            return self._view_modes[reg_id]
        return datatypes.default_view(
            self._regs_by_addr.get(addr, {}).get("type", "SHORT"))

    # ── data ───────────────────────────────────────────────────────
    def populate(self, profile: list[dict]):
        t = self.ctx.t
        size = self._font_size()
        self._font_pt = size
        ident_font = mono_font(size)
        value_font = ident_font if self._mono_values else self.font()

        self.blockSignals(True)
        try:
            self.addr_to_row.clear()
            self._regs_by_addr.clear()
            self._fresh.clear()
            self._row_regs = list(profile)
            self.setRowCount(len(profile))

            for row, reg in enumerate(profile):
                addr       = datatypes.reg_key(reg)        # area-aware identity
                name       = self._display_name(reg)
                dtype      = reg.get("type", "SHORT")
                rw         = reg.get("rw", "R")
                is_service = datatypes.is_area(dtype)
                writable   = datatypes.is_writable(reg)

                state_item = QTableWidgetItem()
                state_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                state_item.setData(Qt.ItemDataRole.UserRole, "stale")
                if not is_service:                   # a service row has no state
                    state_item.setData(_ROLE_VERBOSE, addr in self._verbose_addrs)

                addr_item = QTableWidgetItem(datatypes.key_label(addr))
                addr_item.setData(_ROLE_KEY, addr)
                area = datatypes.area_of(reg)
                if area.key != datatypes.DEFAULT_AREA:
                    addr_item.setToolTip(t(area.label_key + "Hint"))
                addr_item.setFlags(addr_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                addr_item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                addr_item.setFont(ident_font)

                name_item = QTableWidgetItem(name)
                name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                name_item.setToolTip(name)

                type_item = QTableWidgetItem(dtype)
                type_item.setFlags(type_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                type_item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

                access_item = QTableWidgetItem(rw)
                access_item.setFlags(access_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                access_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                access_item.setFont(ident_font)

                # Values honor the mono_values setting; addr/access stay
                # monospace (they're identifiers, not data).
                val_item = QTableWidgetItem(self._placeholder(dtype))
                val_item.setData(_ROLE_PLACEHOLDER, True)
                val_item.setFlags(val_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                val_item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                val_item.setFont(value_font)

                # Read-only rows leave the cell EMPTY: a dash in every other
                # row was the loudest thing in the column.
                new_val_item = QTableWidgetItem("")
                new_val_item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                new_val_item.setFont(value_font)
                if not writable:
                    new_val_item.setFlags(new_val_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    if not is_service:
                        new_val_item.setToolTip(t("newValReadOnly"))
                else:
                    new_val_item.setToolTip(t("newValTip"))

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
            self._recolor()
        finally:
            self.blockSignals(False)
        self._fit_to_viewport()

    def _recolor(self):
        """Text hierarchy of the grid: name and value are what you read
        (text_1); address and type are reference (text_3); the access code of
        a row you cannot write, and every cell of a service area, recede
        (text_4). Re-run on a theme change — colours are baked into items."""
        tok = self.ctx.theme_tokens()
        primary, ref, muted = (QColor(tok["text_1"]), QColor(tok["text_3"]),
                               QColor(tok["text_4"]))
        was = self.signalsBlocked()
        self.blockSignals(True)
        try:
            for row, reg in enumerate(self._row_regs):
                service = datatypes.is_area(reg.get("type", "SHORT"))
                writable = datatypes.is_writable(reg)
                colors = {COL_ADDR: ref, COL_NAME: primary, COL_TYPE: ref,
                          COL_ACCESS: ref if writable else muted,
                          COL_CURRENT: primary, COL_NEW: primary}
                for col, color in colors.items():
                    it = self.item(row, col)
                    if it is not None:
                        if col == COL_CURRENT and it.data(_ROLE_PLACEHOLDER):
                            color = muted            # "—": no reading yet
                        it.setForeground(muted if service else color)
            self._value_brush = QBrush(primary)
        finally:
            self.blockSignals(was)

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
            # A long name may not push the values off-screen: past ~40 % of
            # the width it elides (the full name is in the tooltip).
            vp = self.viewport().width()
            cap = max(220, int(vp * 0.40)) if vp > 0 else 10 ** 6
            self.setColumnWidth(COL_NAME, min(cap, max(200, self.columnWidth(COL_NAME))))
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
            # Overflow comes out of the column being dragged — or, when the
            # viewport itself shrank (the trends panel opened, the window got
            # narrower), out of the NAME column, which elides gracefully. A
            # horizontal scrollbar under a register list is never the answer.
            victim = exclude if exclude in vis else (
                COL_NAME if COL_NAME in vis else None)
            if over > 0 and victim is not None:
                self.setColumnWidth(
                    victim, max(_MINW.get(victim, 60),
                                self.columnWidth(victim) - over))
        finally:
            self._adjusting = False

    def _on_section_resized(self, idx: int, _old: int, _new: int):
        # User (or code) dragged a border: re-fill so the value columns absorb
        # the change and the grid keeps exactly spanning the viewport.
        self._reflow_columns(exclude=idx)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reflow_columns()

    def viewportEvent(self, event):
        # The viewport also narrows WITHOUT the table resizing — when the
        # vertical scrollbar appears as rows arrive. Re-fit then too, or the
        # columns overshoot by the scrollbar's width and a horizontal
        # scrollbar shows up under the map.
        if event.type() == event.Type.Resize:
            later(0, self, self._reflow_columns)
        if event.type() == event.Type.ToolTip:
            pos = event.pos()
            idx = self.indexAt(pos)
            if idx.isValid() and idx.column() == COL_STATE:
                tip = self._state_tip(pos)
                if tip:
                    QToolTip.showText(event.globalPos(), tip, self.viewport())
                else:
                    QToolTip.hideText()
                return True
        return super().viewportEvent(event)

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
            if state is not None:
                now = time.monotonic()
                prev = state.data(_ROLE_TS)
                if prev is not None and state.data(Qt.ItemDataRole.UserRole) == "ok":
                    state.setData(_ROLE_GAP, now - prev)
                state.setData(_ROLE_TS, now)
                if state.data(Qt.ItemDataRole.UserRole) != "ok":
                    state.setData(Qt.ItemDataRole.UserRole, "ok")
            ci = self.item(row, COL_CURRENT)
            if ci:
                if ci.data(_ROLE_PLACEHOLDER):       # first reading: full colour
                    ci.setData(_ROLE_PLACEHOLDER, False)
                    ci.setForeground(getattr(self, "_value_brush", QBrush(
                        QColor(self.ctx.theme_tokens()["text_1"]))))
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
                        mode = self._view_mode(addr)
                        bits, is_float = self._type_shape(addr)
                        if mode == "dec" and _INT_LITERAL.fullmatch(val_str):
                            # Exact: an INT64 above 2**53 does not survive
                            # the trip through a float.
                            ci.setText(val_str)
                        else:
                            ci.setText(format_value(raw, mode, bits, is_float))
                        if reg.get("type") == "BITS16":
                            ci.setToolTip(self._bits_tip(raw))
                        sampled = raw
                    # highlight_changes: flash the cell when the value changed.
                    if self._highlight and prev is not None and prev != raw:
                        self._flash(ci)
        finally:
            self.blockSignals(False)
        # NaN / ±inf (a broken sensor) are shown, but never fed to charts:
        # one non-finite sample wrecks a plot's auto-range.
        finite = isinstance(sampled, float) and math.isfinite(sampled)
        if finite:
            self.value_sampled.emit(f"0x{addr:04X}", sampled)
        if addr in self._watched and ci is not None:
            self.value_shown.emit(addr, ci.text(), sampled if finite else None)

    def _bits_tip(self, raw) -> str:
        try:
            word = int(raw) & 0xFFFF
        except (ValueError, OverflowError):
            return ""
        bits = [str(i) for i in range(16) if word >> i & 1]
        return (self.ctx.t("bitsSet").format(bits=", ".join(bits)) if bits
                else self.ctx.t("bitsNone"))

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
        """Every state dot to "no link" (on disconnect); the last values stay
        on screen, grey. The log toggles stay: logging for those registers
        resumes with the next connection."""
        self._fresh.clear()
        self.blockSignals(True)
        try:
            for row in range(self.rowCount()):
                item = self.item(row, COL_STATE)
                if item:
                    item.setData(Qt.ItemDataRole.UserRole, "stale")
                    item.setData(_ROLE_GAP, None)
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
        addr = self._row_key(row)
        type_item = self.item(row, COL_TYPE)
        if addr is None or not type_item:
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

    # ── the log toggle (console glyph in the state column) ─────────
    def toggle_verbose(self, row: int):
        """Write this register's TX/RX frames to the log — or stop."""
        addr = self._row_key(row)
        state_item = self.item(row, COL_STATE)
        if (addr is None or state_item is None
                or state_item.data(_ROLE_VERBOSE) is None):
            return                                  # a service row
        on = addr not in self._verbose_addrs
        if on:
            self._verbose_addrs.add(addr)
        else:
            self._verbose_addrs.discard(addr)
        state_item.setData(_ROLE_VERBOSE, on)
        self.verbose_changed.emit(self._verbose_addrs.copy())

    def _in_log_zone(self, pos: QPoint) -> bool:
        idx = self.indexAt(pos)
        if not idx.isValid() or idx.column() != COL_STATE:
            return False
        if not StateDotDelegate.has_state(idx):
            return False
        return pos.x() >= self.visualRect(idx).left() + _LOG_X0

    def _update_row(self, row: int, cols=(COL_STATE, COL_NEW)):
        if row < 0:
            return
        for col in cols:
            idx = self.model().index(row, col)
            if idx.isValid():
                self.viewport().update(self.visualRect(idx))

    def _repaint_states(self):
        if not self._connected or not self.rowCount() or self.isColumnHidden(COL_STATE):
            return
        x = self.columnViewportPosition(COL_STATE)
        self.viewport().update(QRect(x, 0, self.columnWidth(COL_STATE),
                                     self.viewport().height()))

    def mouseMoveEvent(self, event):
        pos = event.position().toPoint()
        row = self.rowAt(pos.y())
        on_log = self._in_log_zone(pos)
        if row != self._hover_row or on_log != self._hover_log:
            old = self._hover_row
            self._hover_row, self._hover_log = row, on_log
            self._update_row(old)
            self._update_row(row)
            if on_log:
                self.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
            else:
                self.viewport().unsetCursor()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        old, self._hover_row, self._hover_log = self._hover_row, -1, False
        self._update_row(old)
        self.viewport().unsetCursor()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        pos = event.position().toPoint()
        if event.button() == Qt.MouseButton.LeftButton and self._in_log_zone(pos):
            self.toggle_verbose(self.rowAt(pos.y()))
            event.accept()
            return
        super().mousePressEvent(event)

    def _state_tip(self, pos: QPoint) -> str:
        """What the state column says at *pos* (dot or log toggle)."""
        idx = self.indexAt(pos)
        if not StateDotDelegate.has_state(idx):
            return ""
        t = self.ctx.t
        if self._in_log_zone(pos):
            return t("logToggleOn" if idx.data(_ROLE_VERBOSE) else "logToggleOff")
        kind = StateDotDelegate.freshness(idx, self._connected)
        if kind == "none":
            return t("stateNone")
        if kind in ("offline", "waiting"):
            return t("stateOffline" if kind == "offline" else "stateWaiting")
        age = time.monotonic() - float(idx.data(_ROLE_TS))
        return t("stateFresh" if kind == "fresh" else "stateLate").format(
            age=self._age_text(age))

    def _age_text(self, seconds: float) -> str:
        t = self.ctx.t
        if seconds < 1.0:
            return t("ageUnderSec")
        if seconds < 60:
            return t("ageSec").format(n=int(seconds))
        return t("ageMin").format(n=int(seconds // 60))

    def _on_double_click(self, index):
        row = index.row()
        type_item = self.item(row, COL_TYPE)
        if not type_item or type_item.text() != "MEMORY_AREA":
            return
        addr = self._row_key(row)
        if addr is None:
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
        if not addr_item:
            return
        if type_item and datatypes.is_area(type_item.text()):
            return

        addr_int = self._row_key(row)
        if addr_int is None:
            return
        reg_id   = datatypes.reg_id(addr_int)
        # NOT "label": the dec/hex/bin loop below reuses that name, and the
        # copy-address action used to copy the word «Двоичное».
        addr_label = addr_item.text()
        reg_name = name_item.text() if name_item else f"Reg_{row}"
        cur_val  = cur_item.text() if cur_item else "—"
        reg = self._regs_by_addr.get(addr_int, {})
        symbolic = (scaling.has_scaling(reg) or bool(scaling.get_enum(reg))
                    or datatypes.is_text(reg.get("type", "")))

        menu = QMenu(self)
        ic = self.ctx.theme_tokens()["text_2"]

        if reg_id in self._trended:
            act = menu.addAction(icons.icon("chart", ic, 14), self.t("ctxTrendRemove"))
            act.triggered.connect(lambda: self.trend_remove_requested.emit(reg_id))
        else:
            act = menu.addAction(icons.icon("chart", ic, 14), self.t("ctxTrendAdd"))
            act.triggered.connect(lambda: self.trend_add_requested.emit(reg_id, reg_name))

        watched = addr_int in self._watched
        act_watch = menu.addAction(icons.icon("watch", ic, 14),
            self.t("watchRemoveFrom" if watched else "watchAddTo"))
        act_watch.triggered.connect(
            lambda: self.watch_toggle_requested.emit(addr_int))
        act_log = menu.addAction(icons.icon("terminal", ic, 14), self.t("ctxLogFrames"))
        act_log.setCheckable(True)
        act_log.setChecked(addr_int in self._verbose_addrs)
        act_log.triggered.connect(lambda: self.toggle_verbose(row))

        # dec/hex/bin is about a raw number; an engineering value or an enum
        # label has no meaningful hex form, so the submenu is not offered.
        if not symbolic:
            menu.addSeparator()
            view_menu = menu.addMenu(icons.icon("bits", ic, 14), self.t("ctxViewAs"))
            mode = self._view_mode(addr_int)
            for label, key in [(self.t("ctxDec"), "dec"), (self.t("ctxHex"), "hex"),
                               (self.t("ctxBin"), "bin")]:
                a = view_menu.addAction(label)
                a.setCheckable(True)
                a.setChecked(mode == key)
                a.triggered.connect(lambda _, k=key: self.set_view_mode(reg_id, row, k))

        menu.addSeparator()
        # "label\thint": Qt right-aligns the hint like a shortcut — the text
        # that will be copied, shown quietly instead of in [brackets].
        act_cv = menu.addAction(icons.icon("copy", ic, 14),
                                f'{self.t("ctxCopyValue")}\t{cur_val}')
        act_cv.triggered.connect(lambda: QApplication.clipboard().setText(cur_val))
        act_ca = menu.addAction(icons.icon("copy", ic, 14),
                                f'{self.t("ctxCopyAddr")}\t{addr_label}')
        act_ca.triggered.connect(lambda: QApplication.clipboard().setText(addr_label))

        if datatypes.is_writable(reg):
            menu.addSeparator()
            act_w = menu.addAction(icons.icon("edit", ic, 14), self.t("ctxWrite"))
            act_w.triggered.connect(lambda: self._prompt_write(row))

        menu.exec(self.viewport().mapToGlobal(pos))

    def _prompt_write(self, row: int):
        addr_item = self.item(row, COL_ADDR)
        type_item = self.item(row, COL_TYPE)
        if not addr_item or not type_item:
            return
        dtype = type_item.text()
        addr = self._row_key(row)
        if addr is None:
            return
        val, ok = themed_input(
            self, self.ctx.theme, self.t("ctxWrite").rstrip("…."),
            self.t("writePrompt").format(addr=addr_item.text(), type=dtype),
            ok_label=self.t("writeAction"), cancel_label=self.t("cancel"))
        if not ok or not val.strip():
            return
        if not self._connected:
            self.write_blocked.emit(addr, val.strip())
            return
        self._emit_write(addr, dtype, val.strip())
