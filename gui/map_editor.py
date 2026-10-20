# gui/map_editor.py

import json
import copy
import os
from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QTableWidget, QTableWidgetItem, QHeaderView,
    QTextEdit, QSplitter, QAbstractItemView, QComboBox, QLineEdit,
    QFileDialog, QMessageBox, QStackedWidget, QMenu, QSpinBox, QFrame
)
from PyQt6.QtCore import (
    Qt, QRect, pyqtSignal, QVariantAnimation, QEasingCurve,
)
from PyQt6.QtGui import QFont, QColor, QKeySequence, QShortcut, QPixmap, QPainter
from PyQt6 import sip
from gui.theme_manager import get_theme
from core.profile_manager import (find_overlaps, find_duplicate_names,
                             chained_flags, rechain, is_contiguous)
from gui import icons
from app.fonts import MONO_CSS
from core import formats
from gui.dialogs import themed_message, themed_info
from gui.qt_utils import later

# ── Device data types ────────────────────────────────────────────────
# All knowledge of register data types now lives in the central registry
# (datatypes.py). The names below are imported aliases so the editor's many
# call sites keep working unchanged. To add/modify a type, edit datatypes.py.
from core import datatypes
from core.datatypes import FIXED_TYPE_LEN, ALL_TYPES

# Number of Modbus addresses a register occupies (alias to the registry).
type_size = datatypes.addr_span


def _coerce_name(reg: dict):
    """Return (name_ru, name_en) from either string or legacy {ru,en} dict."""
    n = reg.get("name", "")
    if isinstance(n, dict):
        return n.get("ru", "") or n.get("en", ""), n.get("en", "")
    return str(n), str(reg.get("name_en", "") or "")


def _to_int(value, default: int) -> int:
    """Best-effort int coercion for hand-edited JSON fields: accepts ints,
    floats, "0x.."/"0b.."/decimal strings; null/empty/garbage -> *default*
    (the row stays visible in the editor instead of crashing the open)."""
    try:
        if isinstance(value, str):
            return int(value.strip(), 0) if value.strip() else default
        return int(value)
    except (TypeError, ValueError):
        return default


def normalize_registers(raw_list: list) -> list:
    """Coerce any incoming register list into the canonical flat schema:
    {addr:int, name:str, name_en:str, type:str, length:int, rw:str,
     unit:str, default:str, comment:str}."""
    out = []
    for r in raw_list:
        if not isinstance(r, dict):
            continue
        name_ru, name_en = _coerce_name(r)
        reg = {
            "addr":    _to_int(r.get("addr", 0), 0),
            "name":    name_ru,
            "type":    r.get("type", "SHORT"),
            "length":  _to_int(r.get("length", 1), 1) or 1,
            "rw":      r.get("rw", "RW"),
            "unit":    r.get("unit", ""),
            "default": r.get("default", ""),
            "comment": r.get("comment", ""),
        }
        if name_en:
            reg["name_en"] = name_en
        _apply_area(reg, r.get("area"))
        # Engineering scaling / enum (v2) — carried through edits untouched so
        # opening and re-saving a profile never drops them.
        for k in ("scale", "offset", "enum"):
            if r.get(k) not in (None, "", {}):
                reg[k] = r[k]
        # Fixed types: length is implied by type.
        if reg["type"] in FIXED_TYPE_LEN:
            reg["length"] = FIXED_TYPE_LEN[reg["type"]]
        out.append(reg)
    return out


_apply_area = datatypes.apply_area


# Column indices.
COL_GRIP, COL_ADDR, COL_AREA, COL_RU, COL_EN, COL_TYPE, COL_LEN, COL_ACC, \
    COL_UNIT, COL_DEF, COL_COMMENT = range(11)


class ReorderableTable(QTableWidget):
    """Live WYSIWYG row reordering — grab a row anywhere and drag it.

    Any *item* cell starts a drag once the cursor moves past the threshold
    (widget cells — the type/access combos and the LEN spin — keep their own
    mouse handling, so drags start everywhere else, grip included). While
    dragging:
      * the row VISUALLY moves under the cursor via
        ``verticalHeader().moveSection()`` — a pure view-level operation, so no
        cell widget is destroyed/recreated per crossing (this was the lag);
      * a translucent snapshot of the row ("ghost") rides with the cursor and
        the cursor switches to a closed hand, so it's obvious what is moving;
      * the view auto-scrolls near the top/bottom edge.
    The DATA is reordered exactly once, on release: the dialog reads
    ``visual_order()`` in its ``reorderCommitted`` handler and applies the
    permutation (one repopulate, one undo step). Esc during the drag just
    restores the visual order — the model was never touched.
    """
    reorderCommitted = pyqtSignal()

    _DRAG_THRESHOLD = 6      # px before a press becomes a drag
    _EDGE_SCROLL = 28        # px from the edge where auto-scroll kicks in

    def __init__(self, rows, cols):
        super().__init__(rows, cols)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.setWordWrap(False)
        self._drag_logical = -1   # logical row being dragged (stable id)
        self._press_y = 0
        self._armed = False       # pressed on a row, waiting for the threshold
        self._dragging = False
        self._grabbed = False     # explicit viewport mouse-grab is active
        self._ghost = None        # floating translucent row snapshot
        self._slot = None         # dashed "landing slot" over the dragged row
        # live displaced-row slide animations -> their snapshot labels
        self._anims: dict = {}

    # ── visual-order helpers ─────────────────────────────────────────
    def visual_order(self) -> list[int]:
        """Logical row indices in their current visual order."""
        vh = self.verticalHeader()
        return [vh.logicalIndex(v) for v in range(self.rowCount())]

    def reset_visual_order(self):
        """Undo all visual section moves (visual index == logical index)."""
        vh = self.verticalHeader()
        for logical in range(self.rowCount()):
            v = vh.visualIndex(logical)
            if v != logical:
                vh.moveSection(v, logical)

    def _visual_from_y(self, y: float) -> int:
        """Clamp cursor Y to a valid visual row index (0 .. rowCount-1)."""
        n = self.rowCount()
        if n == 0:
            return -1
        r = self.rowAt(int(y))                    # logical row under cursor
        if r >= 0:
            return self.verticalHeader().visualIndex(r)
        first_logical = self.verticalHeader().logicalIndex(0)
        return 0 if y < self.rowViewportPosition(first_logical) else n - 1

    # ── ghost (floating row snapshot) ────────────────────────────────
    def _make_ghost(self):
        row_y = self.rowViewportPosition(self._drag_logical)
        h = self.rowHeight(self._drag_logical)
        w = self.viewport().width()
        src = self.viewport().grab(QRect(0, row_y, w, h))
        pm = QPixmap(src.size())
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setOpacity(0.85)
        p.drawPixmap(0, 0, src)
        p.setOpacity(1.0)
        accent = get_theme(getattr(self.window(), "_theme_name", "Dark"))["accent"]
        p.setPen(QColor(accent))
        p.drawRect(0, 0, pm.width() - 1, pm.height() - 1)
        p.end()
        self._ghost = QLabel(self.viewport())
        self._ghost.setPixmap(pm)
        self._ghost.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._ghost.show()
        self._ghost.raise_()

    def _move_ghost(self, y: float):
        if self._ghost is None:
            return
        h = self._ghost.height()
        top = int(y - h / 2)
        top = max(0, min(top, self.viewport().height() - h))
        self._ghost.move(0, top)

    def _drop_ghost(self):
        if self._ghost is not None:
            self._ghost.deleteLater()
            self._ghost = None

    # ── landing slot + displaced-row slide animation ─────────────────
    def _make_slot(self):
        """Dashed placeholder drawn where the dragged row currently sits — the
        row's own cells are covered, so the grid clearly shows an empty slot
        (its content travels in the ghost)."""
        c = get_theme(getattr(self.window(), "_theme_name", "Dark"))
        self._slot = QLabel(self.viewport())
        self._slot.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._slot.setStyleSheet(
            f"background: {c['bg_1']};"
            f"border: 1px dashed {c['accent_soft']}; border-radius: 6px;")
        self._update_slot()
        self._slot.show()

    def _update_slot(self):
        if self._slot is None:
            return
        y = self.rowViewportPosition(self._drag_logical)
        h = self.rowHeight(self._drag_logical)
        self._slot.setGeometry(2, y + 1, self.viewport().width() - 4, h - 2)
        self._slot.raise_()
        if self._ghost is not None:
            self._ghost.raise_()             # ghost always on top

    def _animate_displaced(self, logical: int, y_from: int):
        """Slide the row that just got pushed out of the way from its old
        position to its new one (a snapshot label glides over the grid). Pure
        eye-candy on top of the instant section move — capped so a fast flick
        can't pile up animations."""
        y_to = self.rowViewportPosition(logical)
        if abs(y_to - y_from) < 2 or len(self._anims) >= 8:
            return
        h = self.rowHeight(logical)
        w = self.viewport().width()
        # Hide the overlays while grabbing so they don't bleed into the shot.
        if self._ghost is not None:
            self._ghost.hide()
        if self._slot is not None:
            self._slot.hide()
        pm = self.viewport().grab(QRect(0, y_to, w, h))
        if self._slot is not None:
            self._slot.show()
        if self._ghost is not None:
            self._ghost.show()

        lbl = QLabel(self.viewport())
        lbl.setPixmap(pm)
        lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        lbl.setGeometry(0, y_from, w, h)
        lbl.show()
        self._update_slot()                  # keep slot+ghost above the flyer

        anim = QVariantAnimation(self)
        anim.setStartValue(float(y_from))
        anim.setEndValue(float(y_to))
        anim.setDuration(140)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        # Guard every deferred callback: the flying label (and the table) can
        # be deleted mid-animation, and touching a dead C++ object is an
        # access violation rather than a catchable error.
        def _step(v, l=lbl):
            if not sip.isdeleted(l):
                l.move(0, int(v))
        anim.valueChanged.connect(_step)

        def _done(l=lbl, a=anim):
            if not sip.isdeleted(l):
                l.deleteLater()
            self._anims.pop(a, None)
        anim.finished.connect(_done)
        self._anims[anim] = lbl
        anim.start()

    # ── drag lifecycle ───────────────────────────────────────────────
    def _end_drag(self):
        """Release the grab, drop the overlays, restore the cursor."""
        if self._grabbed:
            self.viewport().releaseMouse()
            self._grabbed = False
        self._dragging = self._armed = False
        self._drag_logical = -1
        # stop() does NOT emit finished(): delete the snapshots here, or a
        # release mid-glide leaves stale pictures of rows over the table.
        for a, lbl in list(self._anims.items()):
            a.stop()
            if not sip.isdeleted(lbl):
                lbl.hide()
                lbl.deleteLater()
        self._anims.clear()
        if self._slot is not None:
            self._slot.deleteLater()
            self._slot = None
        self._drop_ghost()
        self.viewport().unsetCursor()

    def mousePressEvent(self, event):
        row = self.rowAt(int(event.position().y()))
        if event.button() == Qt.MouseButton.LeftButton and row >= 0:
            # Arm a potential drag from ANY item cell; selection/editing keep
            # working because the event still goes to the base class.
            self._armed = True
            self._drag_logical = row
            self._press_y = int(event.position().y())
        else:
            self._armed = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        y = event.position().y()
        if self._armed and not self._dragging:
            if abs(int(y) - self._press_y) >= self._DRAG_THRESHOLD:
                self._dragging = True
                # Explicit grab: survives any child-widget churn in the row.
                self.viewport().grabMouse()
                self._grabbed = True
                self.selectRow(self._drag_logical)
                self._make_ghost()
                self._make_slot()
                self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
        if self._dragging:
            vh = self.verticalHeader()
            target_v = self._visual_from_y(y)
            cur_v = vh.visualIndex(self._drag_logical)
            if target_v >= 0 and target_v != cur_v:
                # Rows between the old and new position shift one slot — note
                # where they were so they can glide there instead of jumping.
                step = 1 if target_v > cur_v else -1
                displaced = [vh.logicalIndex(v)
                             for v in range(cur_v + step, target_v + step, step)]
                before = {lg: self.rowViewportPosition(lg) for lg in displaced}
                vh.moveSection(cur_v, target_v)   # visual move only — instant
                self._update_slot()
                for lg in displaced:
                    self._animate_displaced(lg, before[lg])
            self._move_ghost(y)
            self._edge_autoscroll(y)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def _edge_autoscroll(self, y: float):
        sb = self.verticalScrollBar()
        if y < self._EDGE_SCROLL:
            sb.setValue(sb.value() - sb.singleStep())
        elif y > self.viewport().height() - self._EDGE_SCROLL:
            sb.setValue(sb.value() + sb.singleStep())

    def mouseReleaseEvent(self, event):
        if self._dragging:
            self._end_drag()
            self.reorderCommitted.emit()
            event.accept()
            return
        self._armed = False
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if self._dragging and event.key() == Qt.Key.Key_Escape:
            self._end_drag()
            self.reset_visual_order()      # data was never touched — just undo
            event.accept()
            return
        super().keyPressEvent(event)


class ProfileEditorDialog(QDialog):
    """Fullscreen Profile Editor as shown in the design."""

    def __init__(self, parent=None, profile_data=None, ctx=None):
        super().__init__(parent)
        self.profile_data = normalize_registers(profile_data) if profile_data else []
        # The import dialog needs the whole context (translator + theme),
        # not just the three values unpacked below.
        self.ctx = ctx
        self.lang = ctx.lang
        self.t = ctx.t
        self._theme_name = ctx.theme
        self.file_path = ""
        self.profile_name = ""

        self.history = []
        self.history_index = -1
        self.is_modified = False

        self.setWindowTitle(self.t("profileEditor"))
        self.setMinimumSize(1000, 600)
        self.setWindowState(Qt.WindowState.WindowMaximized)

        self._build_ui()
        self._push_state(init=True)
        self._refresh_ui()

    def _build_ui(self):
        c = get_theme(self._theme_name)
        try:
            fs = max(7, min(20, int(self.ctx.settings.get("font_size", 9))))
        except (TypeError, ValueError):
            fs = 9
        self._fs = fs

        self.setStyleSheet(f"""
            QDialog {{ background: {c["bg_0"]}; }}
            QTableWidget {{
                background: {c["bg_0"]};
                gridline-color: transparent;
                border: none;
                color: {c["text_1"]};
                font-size: {fs + 1}pt;
                outline: none;
            }}
            QTableWidget::item {{
                border-bottom: 1px solid {c["line"]};
                padding: 4px 8px;
            }}
            QHeaderView::section {{
                background: {c["bg_0"]};
                color: {c["text_4"]};
                border: none;
                border-bottom: 1px solid {c["line"]};
                padding: 6px 8px;
                font-size: 8pt;
                text-transform: uppercase;
                font-weight: 600;
            }}
            QTextEdit {{
                background: {c["bg_1"]};
                color: {c["text_2"]};
                border: none;
                font-family: {MONO_CSS};
                font-size: {fs}pt;
                padding: 12px;
            }}
            QWidget#peToolbar {{
                background: {c["bg_1"]};
                border-bottom: 1px solid {c["line_soft"]};
            }}
            QLabel#peTitle {{
                color: {c["text_1"]};
                font-size: {fs + 2}pt;
                font-weight: 600;
            }}
            QLabel#peSep {{ color: {c["text_4"]}; }}
            QLabel#peDirty {{ color: {c["warn"]}; font-size: {fs}pt; }}
            QLineEdit#peName {{
                background: transparent;
                color: {c["text_1"]};
                border: none;
                border-bottom: 1px solid transparent;
                font-size: {fs + 1}pt;
                padding: 2px 2px;
            }}
            QLineEdit#peName:hover {{ border-bottom: 1px solid {c["line"]}; }}
            QLineEdit#peName:focus {{ border-bottom: 1px solid {c["text_4"]}; }}
            QFrame#peVSep {{ background: {c["line"]}; border: none; }}
            /* Same button language as every other page (2.2): one filled
               accent action, the rest quiet ghost buttons. */
            QPushButton#btnPrimary {{
                background: {c["accent"]};
                color: {c["accent_fg"]};
                border: none;
                border-radius: 6px;
                padding: 6px 14px;
                font-weight: 600;
            }}
            QPushButton#btnPrimary:hover {{
                background: {c["accent_soft"]};
                color: {c["text_1"]};
            }}
            QPushButton#btnSecondary {{
                background: transparent;
                color: {c["text_2"]};
                border: none;
                border-radius: 6px;
                padding: 6px 10px;
                font-weight: 500;
            }}
            QPushButton#btnSecondary:hover {{
                background: {c["bg_3"]};
                color: {c["text_1"]};
            }}
            QPushButton#btnGhost {{
                background: transparent;
                color: {c["text_3"]};
                border: none;
                padding: 6px;
                font-size: 11pt;
            }}
            QPushButton#btnGhost:hover {{
                color: {c["text_1"]};
            }}
            QLabel#statBadge {{
                background: transparent;
                color: {c["text_4"]};
                padding: 0 2px;
                font-size: {max(7, fs - 1)}pt;
            }}
            QWidget#peFooter {{
                background: {c["bg_1"]};
                border-top: 1px solid {c["line_soft"]};
            }}
            QPushButton#peToggle {{
                background: transparent;
                color: {c["text_2"]};
                border: none;
                border-radius: 6px;
                padding: 6px 10px;
            }}
            QPushButton#peToggle:hover {{ background: {c["bg_3"]}; color: {c["text_1"]}; }}
            QPushButton#peToggle:checked {{ background: {c["bg_3"]}; color: {c["text_1"]}; }}
            QSpinBox {{
                background: transparent;
                border: 1px solid transparent;
                border-radius: 4px;
                color: {c["text_1"]};
                padding: 2px 6px;
            }}
            QSpinBox:hover {{
                border: 1px solid {c["line"]};
                background: {c["bg_2"]};
            }}
            QComboBox {{
                background: transparent;
                border: 1px solid transparent;
                color: {c["text_1"]};
                padding: 2px 6px;
            }}
            QComboBox:hover {{
                border: 1px solid {c["line"]};
                background: {c["bg_2"]};
            }}
            QComboBox QAbstractItemView {{
                background: {c["bg_2"]};
                color: {c["text_1"]};
                selection-background-color: {c["bg_4"]};
                border: 1px solid {c["line"]};
                outline: none;
            }}
            QComboBox QAbstractItemView::item {{
                padding: 4px 12px;
                min-height: 22px;
            }}
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Toolbar: identity row + action row ─────────────────────
        # Everything used to sit on ONE line. At 1440 px that line was wider
        # than the window, so Qt squeezed every button below its text and the
        # labels came out as "Открыть JS(", "Сохранит", "Применит". Two rows:
        # what you are editing (+ its stats) on top, what you can do below.
        # The style is scoped to #peToolbar — the old bare
        # "background:…; border-bottom:…" cascaded into every child and drew
        # a stray rule under each label.
        tb = QWidget()
        tb.setObjectName("peToolbar")
        tb.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        tb_lo = QVBoxLayout(tb)
        tb_lo.setContentsMargins(16, 10, 16, 10)
        tb_lo.setSpacing(8)
        row_top = QHBoxLayout()
        row_top.setSpacing(8)
        row_act = QHBoxLayout()
        row_act.setSpacing(6)
        tb_lo.addLayout(row_top)
        tb_lo.addLayout(row_act)

        icon_col = c["text_2"]
        lbl_title_ico = QLabel()
        lbl_title_ico.setPixmap(icons.pixmap("edit", c["text_1"], 16))
        lbl_title = QLabel(self.t('profileEditor'))
        lbl_title.setObjectName("peTitle")

        sep_dot = QLabel("·")
        sep_dot.setObjectName("peSep")

        # Editable map name — used as the suggested filename when saving.
        self.name_edit = QLineEdit()
        self.name_edit.setObjectName("peName")
        self.name_edit.setText(self.profile_name)
        self.name_edit.setPlaceholderText(self.t("untitledProfile"))
        self.name_edit.setMinimumWidth(220)
        self.name_edit.setMaximumWidth(360)
        self.name_edit.setToolTip(self.t("profileNameHint"))

        # Unsaved-changes dot.
        self.lbl_dirty = QLabel("●")
        self.lbl_dirty.setObjectName("peDirty")
        self.lbl_dirty.setToolTip(self.t("unsavedDot"))
        self.lbl_dirty.setVisible(False)

        # Data / file action buttons — all the same btnSecondary style, all
        # with SVG icons from the shared set (one consistent stroke style).
        def _btn(icon_name, text, slot, tip=""):
            b = QPushButton("  " + text)
            b.setObjectName("btnSecondary")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setIcon(icons.icon(icon_name, icon_col, 15))
            if tip:
                b.setToolTip(tip)
            b.clicked.connect(slot)
            return b

        self.btn_add = _btn("plus", self.t("addRegister"), self._add_row)
        btn_add = self.btn_add
        btn_del = _btn("x", self.t("deleteRow"), self._delete_selected)
        self.btn_clear = _btn("trash", self.t("clearAll"), self._clear_all,
                              self.t("clearAllHint"))
        self.btn_open_json = _btn("folder", self.t("openJson"), self._open_file)
        # Vendors ship register maps as spreadsheets, not JSON — importing
        # one is the normal way a map enters the app for the first time.
        self.btn_import = _btn("table", self.t("impOpen"), self._import_table)
        self.btn_save = _btn("save", self.t("save"), self._save, self.t("saveHint"))
        # No setShortcut("Ctrl+S") here: the main window owns Ctrl+S (save
        # project) and two window-level shortcuts on one key are AMBIGUOUS to
        # Qt — neither fires. The window routes Ctrl+S to this editor while
        # it is open (gui.main_window._save_shortcut).
        # "Save" replaces the file in place once it has a path, so saving a
        # COPY needed its own button (Ctrl+Shift+S), not a hidden mode.
        self.btn_save_as = _btn("download", self.t("saveAs"), self._save_as_file,
                                self.t("saveAsHint"))
        self.btn_save_as.setShortcut(QKeySequence("Ctrl+Shift+S"))
        self.btn_apply = _btn("check", self.t("apply"), self.accept,
                              self.t("applyHint"))
        self.btn_apply.setObjectName("btnPrimary")
        self.btn_apply.setIcon(icons.icon("check", c["accent_fg"], 15))
        btn_close = _btn("x", self.t("close"), self.reject, "Esc")

        # Stats badges.
        self.lbl_stats_total = QLabel("0 " + self.t("registers"))
        self.lbl_stats_total.setObjectName("statBadge")
        self.lbl_stats_rw = QLabel("0 RW")
        self.lbl_stats_rw.setObjectName("statBadge")
        self.lbl_stats_ro = QLabel("0 RO")
        self.lbl_stats_ro.setObjectName("statBadge")
        # Validation badge: warning icon + address-overlap / duplicate-name
        # counts (details in the tooltip). Hidden while the profile is clean.
        self.ico_warn = QLabel()
        self.ico_warn.setPixmap(icons.pixmap("warning", c["error"], 14))
        self.ico_warn.setVisible(False)
        self.lbl_stats_warn = QLabel("")
        self.lbl_stats_warn.setObjectName("statBadge")
        self.lbl_stats_warn.setStyleSheet(
            f"color: {c['error']}; font-weight: 600;")
        self.lbl_stats_warn.setToolTip("")
        self.lbl_stats_warn.setVisible(False)

        # Thin vertical separators between logical button groups.
        def _vsep():
            f = QFrame()
            f.setObjectName("peVSep")
            f.setFixedSize(1, 20)
            return f

        # Row 1 — identity block: name · dirty-dot … stats. The page title
        # itself is in the window's header bar since 2.2 ("project / Редактор
        # карты регистров"); a second copy here was the same words twice.
        for w in (lbl_title_ico, lbl_title, sep_dot):
            w.setVisible(False)
        row_top.addWidget(lbl_title_ico)
        row_top.addWidget(lbl_title)
        row_top.addWidget(sep_dot)
        # Row 1 — what you are editing: the name, the unsaved dot, the counts
        # (quiet text, not three bordered pills crowding the corner).
        self.name_edit.setMaximumWidth(320)
        row_top.addWidget(self.name_edit)
        row_top.addWidget(self.lbl_dirty)
        row_top.addSpacing(10)
        row_top.addWidget(self.lbl_stats_total)
        row_top.addWidget(self.lbl_stats_rw)
        row_top.addWidget(self.lbl_stats_ro)
        row_top.addWidget(self.ico_warn)
        row_top.addWidget(self.lbl_stats_warn)
        row_top.addStretch(1)
        # Row 2 — the tools that change the table.
        row_act.addWidget(btn_add)
        row_act.addWidget(btn_del)
        row_act.addWidget(self.btn_clear)
        row_act.addSpacing(4)
        row_act.addWidget(_vsep())
        row_act.addSpacing(4)
        row_act.addWidget(self.btn_open_json)
        row_act.addWidget(self.btn_import)
        row_act.addStretch(1)
        self.btn_json = QPushButton("  " + self.t("jsonToggle"))
        self.btn_json.setObjectName("peToggle")
        self.btn_json.setCheckable(True)
        self.btn_json.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_json.setIcon(icons.icon("code", icon_col, 15))
        self.btn_json.setToolTip(self.t("jsonPreview"))
        self.btn_json.toggled.connect(self._set_json_visible)
        row_act.addWidget(self.btn_json)
        root.addWidget(tb)
        # The commit actions live in a footer, exactly like Settings (Cancel /
        # Save at the bottom right) — not in the top-right corner under the
        # window's own Connect button, where two accent buttons stacked up.
        self._footer = QWidget()
        self._footer.setObjectName("peFooter")
        self._footer.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        fl = QHBoxLayout(self._footer)
        fl.setContentsMargins(16, 10, 16, 10)
        fl.setSpacing(8)
        fl.addWidget(self.btn_save)
        fl.addWidget(self.btn_save_as)
        fl.addStretch(1)
        fl.addWidget(btn_close)
        fl.addWidget(self.btn_apply)

        # Undo / redo: no buttons (removed by request), shortcuts still active.
        sc_undo = QShortcut(QKeySequence("Ctrl+Z"), self)
        sc_undo.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        sc_undo.activated.connect(self._undo)
        sc_redo = QShortcut(QKeySequence("Ctrl+Shift+Z"), self)
        sc_redo.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        sc_redo.activated.connect(self._redo)

        # ── Body (Stacked: Empty vs Editor) ────────────────────────
        self.stacked = QStackedWidget()

        # Page 0: Empty state — the same component every other page uses.
        from gui.widgets import EmptyState
        empty_page = EmptyState("table", self.t("emptyProfile"),
                                self.t("emptyProfileHint"))
        empty_page.add_action(self.t("addRegister"), self._add_row, primary=True)
        empty_page.add_action(self.t("impOpen"), self._import_table)
        empty_page.add_action(self.t("openJson"), self._open_file)
        empty_page.apply_theme(c)

        self.stacked.addWidget(empty_page)

        # Page 1: Editor Splitter
        editor_page = QWidget()
        editor_lo = QVBoxLayout(editor_page)
        editor_lo.setContentsMargins(0, 0, 0, 0)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setStyleSheet(f"QSplitter::handle {{ background: {c['line']}; width: 1px; }}")

        self.table = ReorderableTable(0, 11)
        self.table.setHorizontalHeaderLabels([
            "#",
            self.t("address").upper(),
            self.t("colArea"),
            self.t("nameRu").upper(), self.t("nameEn").upper(),
            self.t("colType"),
            self.t("colSize"),
            self.t("access").upper(),
            self.t("colUnit"),
            self.t("colDefault"),
            self.t("comment").upper(),
        ])
        size_hdr = self.table.horizontalHeaderItem(COL_LEN)
        if size_hdr is not None:
            size_hdr.setToolTip(self.t("colSizeHint"))
        addr_hdr = self.table.horizontalHeaderItem(COL_ADDR)
        if addr_hdr is not None:
            addr_hdr.setToolTip(self.t("colAddrHint"))
        area_hdr = self.table.horizontalHeaderItem(COL_AREA)
        if area_hdr is not None:
            area_hdr.setToolTip(self.t("colAreaHint"))
        # A heading sits where its column's text sits: left over left-aligned
        # names and combos, centred only over the centred cells (#, address,
        # size). Centred headings over left text read as misaligned.
        left = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        for col in range(self.table.columnCount()):
            hdr = self.table.horizontalHeaderItem(col)
            if hdr is not None and col not in (COL_GRIP, COL_ADDR, COL_LEN):
                hdr.setTextAlignment(left)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(False)
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.reorderCommitted.connect(self._on_reorder_committed)

        # Column sizing — names stretch, fixed widths elsewhere so text
        # is readable and doesn't get awkwardly clipped.
        hh = self.table.horizontalHeader()
        hh.setStretchLastSection(True)
        fixed = QHeaderView.ResizeMode.Fixed
        interactive = QHeaderView.ResizeMode.Interactive
        # Grip stays fixed; every other column is user-resizable by dragging
        # its header border (like the main register table). COMMENT stretches
        # to fill the remaining space (stretchLastSection).
        hh.setSectionResizeMode(COL_GRIP, fixed)
        hh.setSectionResizeMode(COL_ADDR, interactive)
        hh.setSectionResizeMode(COL_AREA, interactive)
        hh.setSectionResizeMode(COL_RU, interactive)
        hh.setSectionResizeMode(COL_EN, interactive)
        hh.setSectionResizeMode(COL_TYPE, interactive)
        hh.setSectionResizeMode(COL_LEN, interactive)
        hh.setSectionResizeMode(COL_ACC, interactive)
        hh.setSectionResizeMode(COL_UNIT, interactive)
        hh.setSectionResizeMode(COL_DEF, interactive)
        # Grip icon + the row number: sized from the font so "128" never
        # elides to "…" at a larger UI font.
        from PyQt6.QtGui import QFontMetrics
        grip_font = QFont(self.table.font())
        grip_font.setPointSize(self._fs + 1)      # the table's QSS size
        self.table.setColumnWidth(
            COL_GRIP, 44 + QFontMetrics(grip_font).horizontalAdvance(" 0000"))
        self.table.setColumnWidth(COL_ADDR, 84)
        self.table.setColumnWidth(COL_AREA, 110)
        self.table.setColumnWidth(COL_RU, 200)
        self.table.setColumnWidth(COL_EN, 170)
        self.table.setColumnWidth(COL_TYPE, 98)
        self.table.setColumnWidth(COL_LEN, 74)
        self.table.setColumnWidth(COL_ACC, 78)
        self.table.setColumnWidth(COL_UNIT, 64)
        self.table.setColumnWidth(COL_DEF, 90)
        # The two NAME columns take the spare width (the comment keeps a
        # modest share) until the user drags one of them — before, the names
        # elided at 200 px while an empty COMMENT column held half the row.
        self._names_user_sized = False
        hh.sectionResized.connect(self._on_editor_section_resized)
        self.table.viewport().installEventFilter(self)

        # Context menu
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_ctx_menu)

        # Del key
        sc_del = QShortcut(QKeySequence("Del"), self.table)
        sc_del.activated.connect(self._delete_selected)
        # NOTE: Esc is handled by QDialog (focus inside) and by the main
        # window's keyPressEvent (focus elsewhere). Do NOT register an Escape
        # shortcut here — two identical shortcuts make Qt treat the key as
        # ambiguous and fire neither, which silently breaks Esc.

        json_wrap = self._json_wrap = QWidget()
        json_l = QVBoxLayout(json_wrap)
        json_l.setContentsMargins(0, 0, 0, 0)
        json_l.setSpacing(0)

        json_title = QLabel(self.t("jsonPreview"))
        json_title.setStyleSheet(f"background: {c['bg_1']}; color: {c['text_4']}; padding: 8px 16px; font-size: 8pt; font-weight: 600; text-transform: uppercase; border-bottom: 1px solid {c['line']};")

        self.json_edit = QTextEdit()
        self.json_edit.setReadOnly(True)

        json_l.addWidget(json_title)
        json_l.addWidget(self.json_edit)

        splitter.addWidget(self.table)
        splitter.addWidget(json_wrap)
        splitter.setSizes([760, 320])
        # The JSON is a power-user view: off by default, so the table gets the
        # width (with it on, eleven columns did not fit and scrolled sideways).
        show_json = bool(self.ctx.settings.get("editor_json", False))
        json_wrap.setVisible(show_json)
        self.btn_json.blockSignals(True)
        self.btn_json.setChecked(show_json)
        self.btn_json.blockSignals(False)

        editor_lo.addWidget(splitter)
        self.stacked.addWidget(editor_page)

        root.addWidget(self.stacked, 1)
        root.addWidget(self._footer)

    def _set_json_visible(self, on: bool):
        self._json_wrap.setVisible(bool(on))
        self.ctx.settings["editor_json"] = bool(on)
        if on:
            self._update_json_preview()

    # ── Name columns take the spare width ─────────────────────

    def eventFilter(self, obj, event):
        if (event.type() == event.Type.Resize
                and obj is self.table.viewport()):
            self._fit_name_columns()
        return super().eventFilter(obj, event)

    def _on_editor_section_resized(self, col: int, _old: int, _new: int):
        if col in (COL_RU, COL_EN) and not getattr(self, "_fitting_names", False):
            self._names_user_sized = True

    def _fit_name_columns(self):
        if self._names_user_sized:
            return
        vp = self.table.viewport().width()
        others = sum(self.table.columnWidth(c) for c in range(self.table.columnCount())
                     if c not in (COL_RU, COL_EN, COL_COMMENT)
                     and not self.table.isColumnHidden(c))
        spare = vp - others - 130              # the comment keeps ~130 px
        ru = max(200, int(spare * 0.55))
        en = max(170, spare - ru)
        self._fitting_names = True
        try:
            self.table.setColumnWidth(COL_RU, ru)
            self.table.setColumnWidth(COL_EN, en)
        finally:
            self._fitting_names = False

    # ── History ────────────────────────────────────────────────

    def _push_state(self, init=False):
        if not init:
            self.is_modified = True

        self.history = self.history[:self.history_index + 1]
        self.history.append(copy.deepcopy(self.profile_data))
        self.history_index += 1

    def _undo(self):
        if self.history_index > 0:
            self.history_index -= 1
            self.profile_data = copy.deepcopy(self.history[self.history_index])
            self.is_modified = True
            self._refresh_ui()

    def _redo(self):
        if self.history_index < len(self.history) - 1:
            self.history_index += 1
            self.profile_data = copy.deepcopy(self.history[self.history_index])
            self.is_modified = True
            self._refresh_ui()

    # ── Addressing ──────────────────────────────────────────────

    def _recompute_addresses(self, flags=None):
        """Re-pack chained registers after a structural edit (see
        profile_manager.chained_flags). *flags* must be taken BEFORE the edit;
        without it the current chain is kept as it is."""
        if not self.profile_data:
            return
        rechain(self.profile_data,
                flags if flags is not None else chained_flags(self.profile_data))

    # ── UI refresh ──────────────────────────────────────────────

    def _refresh_ui(self):
        empty = len(self.profile_data) == 0
        if empty:
            self.stacked.setCurrentIndex(0)
        else:
            self.stacked.setCurrentIndex(1)
            self._populate_table()
        self._update_stats()
        self._update_json_preview()
        self._update_dirty_dot()

    def _update_dirty_dot(self):
        """Show the gold dot only when there are unsaved changes."""
        self.lbl_dirty.setVisible(self.is_modified)

    def _populate_table(self):
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        for row, reg in enumerate(self.profile_data):
            self._insert_row(row, reg)
        self.table.blockSignals(False)

    def _insert_row(self, row: int, reg: dict):
        self.table.insertRow(row)

        # COL_GRIP — SVG grip handle + ordinal. Dragging starts here (see
        # ReorderableTable); the grip icon signals that the row is draggable.
        if not hasattr(self, "_grip_icon"):
            self._grip_icon = icons.icon(
                "grip", get_theme(self._theme_name)["text_4"], 12)
        item_num = QTableWidgetItem(self._grip_icon, f" {row + 1}")
        item_num.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        item_num.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

        # COL_ADDR — follows the previous register automatically, but can be
        # typed (double-click) for a map with gaps; rows chained after it
        # move along.
        item_addr = QTableWidgetItem(f"0x{int(reg.get('addr', 0)):04X}")
        item_addr.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
                           | Qt.ItemFlag.ItemIsEditable)
        item_addr.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        item_addr.setFont(self._mono())

        name_ru, name_en = _coerce_name(reg)
        item_ru = QTableWidgetItem(name_ru)
        item_ru.setToolTip(name_ru)
        item_en = QTableWidgetItem(name_en)
        item_en.setToolTip(name_en)

        # COL_AREA — the Modbus table (holding / input / coil / discrete).
        area = datatypes.area_of(reg)
        cb_area = QComboBox()
        for a in datatypes.AREAS.values():
            cb_area.addItem(self.t(a.label_key), a.key)
            cb_area.setItemData(cb_area.count() - 1, self.t(a.label_key + "Hint"),
                                Qt.ItemDataRole.ToolTipRole)
        cb_area.setCurrentIndex(max(0, cb_area.findData(area.key)))
        cb_area.setToolTip(self.t(area.label_key + "Hint"))
        cb_area.currentIndexChanged.connect(
            lambda _i, r=row, cb=cb_area: self._on_area_changed(r, cb.currentData()))

        cb_type = QComboBox()
        cb_type.addItems(ALL_TYPES)
        cur_type = reg.get("type", "SHORT")
        if cur_type not in ALL_TYPES:
            cb_type.addItem(cur_type)
        cb_type.setCurrentText(cur_type)
        cb_type.setToolTip(self.t(f"hint{cur_type}"))
        # The popup defaults to the (narrow) cell width, clipping long type
        # names like "MANY_STR" under the scrollbar. Widen it to the longest
        # entry plus padding + scrollbar allowance so every name is readable.
        fm = cb_type.fontMetrics()
        popup_w = max((fm.horizontalAdvance(t) for t in ALL_TYPES), default=0) + 56
        cb_type.view().setMinimumWidth(popup_w)
        cb_type.currentTextChanged.connect(
            lambda val, r=row: self._on_type_changed(r, val))
        cb_type.setEnabled(not area.bits)          # a coil is one bit, always

        # COL_LEN — for variable/area types use a spin box widget so editing
        # never overlaps the painted cell value; for fixed types it's a
        # greyed read-only item (length is implied by the type).
        is_variable = cur_type not in FIXED_TYPE_LEN
        len_spin = None
        if is_variable:
            len_spin = QSpinBox()
            len_spin.setRange(1, 65535)
            len_spin.setValue(type_size(reg))
            len_spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
            len_spin.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
            len_spin.setFont(self._mono())
            len_spin.valueChanged.connect(
                lambda val, r=row: self._on_len_changed(r, val))
            len_item = None
        else:
            len_item = QTableWidgetItem(str(type_size(reg)))
            len_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            len_item.setFont(self._mono())
            len_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            len_item.setForeground(QColor(get_theme(self._theme_name)["text_4"]))

        cb_acc = QComboBox()
        cb_acc.addItems(["R", "W", "RW"])
        cb_acc.setCurrentText(reg.get("rw", "RW"))
        cb_acc.setEnabled(area.writable)           # input / discrete: R only
        cb_acc.currentTextChanged.connect(
            lambda val, r=row: self._on_access_changed(r, val))

        item_unit = QTableWidgetItem(reg.get("unit", ""))
        item_def = QTableWidgetItem(reg.get("default", ""))
        item_comm = QTableWidgetItem(reg.get("comment", ""))
        item_comm.setToolTip(reg.get("comment", ""))

        self.table.setItem(row, COL_GRIP, item_num)
        self.table.setItem(row, COL_ADDR, item_addr)
        self.table.setCellWidget(row, COL_AREA, cb_area)
        self.table.setItem(row, COL_RU, item_ru)
        self.table.setItem(row, COL_EN, item_en)
        self.table.setCellWidget(row, COL_TYPE, cb_type)
        if len_spin is not None:
            self.table.setCellWidget(row, COL_LEN, len_spin)
        else:
            self.table.setItem(row, COL_LEN, len_item)
        self.table.setCellWidget(row, COL_ACC, cb_acc)
        self.table.setItem(row, COL_UNIT, item_unit)
        self.table.setItem(row, COL_DEF, item_def)
        self.table.setItem(row, COL_COMMENT, item_comm)

    # ── Edits ───────────────────────────────────────────────────

    def _mono(self) -> QFont:
        from gui.register_table import mono_font
        return mono_font(getattr(self, "_fs", 9))

    def _on_type_changed(self, row, val):
        if not (0 <= row < len(self.profile_data)):
            return
        flags = chained_flags(self.profile_data)
        reg = self.profile_data[row]
        reg["type"] = val
        if val in FIXED_TYPE_LEN:
            reg["length"] = FIXED_TYPE_LEN[val]
        else:
            reg["length"] = max(1, int(reg.get("length", 1) or 1))
        self._recompute_addresses(flags)
        self._push_state()
        self._refresh_ui()

    def _on_area_changed(self, row, area_key):
        if not (0 <= row < len(self.profile_data)):
            return
        flags = chained_flags(self.profile_data)
        reg = self.profile_data[row]
        was = datatypes.area_of(reg)
        _apply_area(reg, area_key)
        now = datatypes.area_of(reg)
        if was.bits and not now.bits and reg.get("type") == datatypes.BIT_TYPE:
            reg["type"] = "SHORT"                  # back to a word table
            reg["length"] = 1
        if not was.writable and now.writable and reg.get("rw") == "R":
            reg["rw"] = "RW"
        # Each table has its own address space: the moved row keeps its
        # number, and the next rows of the old table no longer chain to it.
        flags[row] = False
        if row + 1 < len(flags):
            flags[row + 1] = False
        self._recompute_addresses(flags)
        self._push_state()
        self._refresh_ui()

    def _on_access_changed(self, row, val):
        if not (0 <= row < len(self.profile_data)):
            return
        self.profile_data[row]["rw"] = val
        self._push_state()
        self._update_stats()
        self._update_json_preview()

    def _on_len_changed(self, row, val):
        if not (0 <= row < len(self.profile_data)):
            return
        flags = chained_flags(self.profile_data)
        self.profile_data[row]["length"] = max(1, int(val))
        self._recompute_addresses(flags)
        self._push_state()
        # Only the address column needs refreshing; rebuilding the whole table
        # would steal focus from the spin box mid-edit.
        self._refresh_addr_column()
        self._update_json_preview()

    def _refresh_addr_column(self):
        self.table.blockSignals(True)
        for r, reg in enumerate(self.profile_data):
            it = self.table.item(r, COL_ADDR)
            if it:
                it.setText(f"0x{int(reg.get('addr', 0)):04X}")
        self.table.blockSignals(False)

    def _add_row(self):
        # First register of a freshly created profile always starts at
        # address 0; subsequent ones continue the running sum.
        new_addr = 0
        last = self.profile_data[-1] if self.profile_data else None
        if last is not None:
            new_addr = int(last.get("addr", 0)) + type_size(last)

        new_reg = {
            "addr": new_addr,
            "name": self.t("newRegister"),
            "name_en": "" if self.lang == "ru" else "New register",
            "type": "SHORT",
            "length": 1,
            "rw": "RW",
            "unit": "",
            "default": "",
            "comment": "",
        }
        if last is not None:                     # continue the same table
            _apply_area(new_reg, last.get("area"))
        self.profile_data.append(new_reg)
        self._push_state()
        self._refresh_ui()

    def _delete_selected(self, row_idx=None):
        row = self.table.currentRow() if row_idx is None or row_idx is False else row_idx
        if 0 <= row < len(self.profile_data):
            flags = chained_flags(self.profile_data)
            # The row that slides into the gap stays chained only if BOTH
            # links held: it followed the deleted row, and the deleted row
            # followed its own predecessor. Deleting a register never moves
            # one that sits at an explicit address.
            if row + 1 < len(flags):
                flags[row + 1] = flags[row + 1] and flags[row]
            del flags[row]
            del self.profile_data[row]
            if flags:
                flags[0] = False
            self._recompute_addresses(flags)
            self._push_state()
            self._refresh_ui()

    def _clear_all(self):
        if not self.profile_data:
            return
        choice = themed_message(
            self, self._theme_name, "warning",
            self.t("clearAll"), self.t("clearAllConfirm"),
            [(self.t("clear"), QMessageBox.ButtonRole.AcceptRole, False),
             (self.t("cancel"), QMessageBox.ButtonRole.RejectRole, True)])
        if choice != 0:                      # 0 == "clear"
            return
        self.profile_data = []
        self._push_state()
        self._refresh_ui()

    def _duplicate_row(self, row):
        if 0 <= row < len(self.profile_data):
            flags = chained_flags(self.profile_data)
            reg = copy.deepcopy(self.profile_data[row])
            self.profile_data.insert(row + 1, reg)
            flags.insert(row + 1, True)          # the copy follows its original
            self._recompute_addresses(flags)
            self._push_state()
            self._refresh_ui()

    # ── live drag-reorder (ReorderableTable signals) ───────────────
    def _on_reorder_committed(self):
        """Drag released: apply the visual permutation to the data ONCE.

        During the drag only view-level sections moved (zero model churn); here
        the real list is permuted, addresses recomputed, one undo step pushed
        and the table repopulated in its natural order. A no-op drag (row
        returned to where it started) changes nothing."""
        order = self.table.visual_order()
        self.table.reset_visual_order()
        if order == list(range(len(order))):
            return                           # no-op drag — nothing changed
        packed = is_contiguous(self.profile_data)
        start = int(self.profile_data[0].get("addr", 0)) if self.profile_data else 0
        self.profile_data = [self.profile_data[i] for i in order]
        if packed and self.profile_data:
            # A contiguous map IS its row order: re-pack it from the same
            # start address. A map with gaps keeps every address — dragging
            # only changes how the rows are listed.
            self.profile_data[0]["addr"] = start
            self._recompute_addresses([False] + [True] * (len(self.profile_data) - 1))
        self.is_modified = True
        self._push_state()
        self._refresh_ui()

    def _on_item_changed(self, item):
        row = item.row()
        col = item.column()
        if row >= len(self.profile_data):
            return

        reg = self.profile_data[row]
        val = item.text()

        if col == COL_ADDR:
            self._on_addr_edited(row, item)
            return
        if col == COL_RU:
            reg["name"] = val
            item.setToolTip(val)
        elif col == COL_EN:
            reg["name_en"] = val
            item.setToolTip(val)
        elif col == COL_UNIT:
            reg["unit"] = val
        elif col == COL_DEF:
            reg["default"] = val
        elif col == COL_COMMENT:
            reg["comment"] = val
            item.setToolTip(val)

        self._push_state()
        self._update_json_preview()

    def _on_addr_edited(self, row: int, item):
        """A typed address: the register becomes explicit at that address and
        the rows chained after it follow. Accepts 0x10, 10h, $10 or 16."""
        from core import mapimport
        old = int(self.profile_data[row].get("addr", 0))
        new = mapimport._to_int(item.text())
        if new is None or not 0 <= new <= 0xFFFF or new == old:
            self.table.blockSignals(True)
            item.setText(f"0x{old:04X}")             # invalid / unchanged: revert
            self.table.blockSignals(False)
            return
        flags = chained_flags(self.profile_data)
        flags[row] = False                           # typed = explicit
        self.profile_data[row]["addr"] = new
        self._recompute_addresses(flags)
        self._push_state()
        # Rebuild on the next tick: we are inside the table's own itemChanged
        # for the cell being committed, and repopulating here deletes it.
        later(0, self, self._refresh_ui)

    def _update_stats(self):
        total = len(self.profile_data)
        # Writable = "W" anywhere (RW or write-only W); the rest is read-only.
        rw_count = sum(1 for r in self.profile_data
                       if "W" in str(r.get("rw", "R")).upper())
        ro_count = total - rw_count

        self.lbl_stats_total.setText(f"{total} {self.t('registers')}")
        self.lbl_stats_rw.setText(f"·  {rw_count} RW")
        self.lbl_stats_ro.setText(f"·  {ro_count} RO")
        # "0 регистров · 0 RW · 0 RO" over an empty page is noise.
        for lbl in (self.lbl_stats_total, self.lbl_stats_rw, self.lbl_stats_ro):
            lbl.setVisible(total > 0)
        self._update_validation()

    def _update_validation(self):
        """Non-blocking profile validation: overlapping address spans (possible
        in profiles opened from hand-edited JSON — in-editor edits recompute
        addresses sequentially) and duplicate names (shadow each other in macro
        lookups). Shown as a red badge with details in the tooltip."""
        overlaps = find_overlaps(self.profile_data)
        dups     = find_duplicate_names(self.profile_data)
        if not overlaps and not dups:
            self.ico_warn.setVisible(False)
            self.lbl_stats_warn.setVisible(False)
            return
        parts, tips = [], []
        if overlaps:
            parts.append(f"{self.t('addrOverlaps')}: {len(overlaps)}")
            tips.append(self.t("addrOverlaps") + ":\n  " + "\n  ".join(overlaps))
        if dups:
            parts.append(f"{self.t('dupNames')}: {len(dups)}")
            tips.append(self.t("dupNames") + ": " + ", ".join(dups))
        self.lbl_stats_warn.setText("   ".join(parts))
        self.lbl_stats_warn.setToolTip("\n\n".join(tips))
        self.ico_warn.setVisible(True)
        self.lbl_stats_warn.setVisible(True)

    def _update_json_preview(self):
        if hasattr(self, "btn_json") and not self.btn_json.isChecked():
            return                    # hidden: don't re-serialise on every edit
        self.json_edit.setPlainText(
            json.dumps(self._export_list(), indent=2, ensure_ascii=False))

    def _export_list(self) -> list:
        """Canonical flat-array form compatible with the main app."""
        out = []
        for r in self.profile_data:
            reg = {
                "addr": int(r.get("addr", 0)),
                "name": r.get("name", ""),
                "type": r.get("type", "SHORT"),
                "length": int(r.get("length", 1) or 1),
                "rw": r.get("rw", "RW"),
            }
            if r.get("name_en"):
                reg["name_en"] = r["name_en"]
            if r.get("area") and r["area"] != datatypes.DEFAULT_AREA:
                reg["area"] = r["area"]
            for k in ("unit", "default", "comment"):
                if r.get(k):
                    reg[k] = r[k]
            # Engineering scaling / enum (v2), omitted when identity/empty.
            if r.get("scale") not in (None, "", 1.0, 1):
                reg["scale"] = r["scale"]
            if r.get("offset") not in (None, "", 0.0, 0):
                reg["offset"] = r["offset"]
            if isinstance(r.get("enum"), dict) and r["enum"]:
                reg["enum"] = r["enum"]
            out.append(reg)
        return out

    # ── Guide ───────────────────────────────────────────────────

    def _show_guide(self):
        """Coach-mark tour of the profile editor. Reusable from the '?' button."""
        if getattr(self, "_guide", None) is not None:
            return
        from gui.onboarding import OnboardingGuide
        ru = self.lang == "ru"
        L = lambda r, e: r if ru else e
        steps = [
            {"target": None,
             "title": L("Редактор профиля регистров", "Register profile editor"),
             "body":  L("Здесь описывается карта регистров устройства: имена, "
                        "адреса, типы данных и доступ. Полученный файл .json "
                        "затем открывается в главном окне для мониторинга.",
                        "This is where you describe the device's register map: "
                        "names, addresses, data types and access. The resulting "
                        ".json file is then opened in the main window for "
                        "monitoring.")},
            {"target": self.btn_add,
             "title": L("Добавить регистр", "Add a register"),
             "body":  L("Добавляет новую строку в карту. Адрес считается "
                        "автоматически от предыдущего регистра в зависимости от "
                        "типа данных. Строки можно перетаскивать за рукоятку "
                        "слева.",
                        "Adds a new row to the map. The address is computed "
                        "automatically from the previous register based on its "
                        "data type. Rows can be reordered by the grip handle on "
                        "the left.")},
            {"target": self.name_edit,
             "title": L("Имя профиля", "Profile name"),
             "body":  L("Это имя предлагается при сохранении файла. Меняйте его "
                        "здесь, чтобы не вводить имя каждый раз вручную.",
                        "This name is suggested when you save the file. Edit it "
                        "here so you don't have to type a filename each time.")},
            {"target": self.btn_open_json,
             "title": L("Открыть JSON", "Open JSON"),
             "body":  L("Загружает существующий профиль из файла .json для "
                        "редактирования. В пустом редакторе эта же кнопка "
                        "находится по центру.",
                        "Loads an existing profile from a .json file for editing. "
                        "In an empty editor the same button sits in the center.")},
            {"target": self.btn_save,
             "title": L("Сохранить", "Save"),
             "body":  L("Сохраняет карту регистров в файл .json. Имя файла "
                        "берётся из поля имени профиля.",
                        "Saves the register map to a .json file. The filename "
                        "comes from the profile-name field.")},
            {"target": self.btn_apply,
             "title": L("Применить", "Apply"),
             "body":  L("Применяет текущую карту в главном окне без сохранения "
                        "файла — удобно для быстрой проверки.",
                        "Applies the current map to the main window without "
                        "saving a file — handy for a quick check.")},
        ]
        self._guide = OnboardingGuide(self, steps, self._theme_name, None, self.lang)
        self._guide.finished.connect(lambda: setattr(self, "_guide", None))
        self._guide.show_guide()

    # ── File I/O ────────────────────────────────────────────────

    # ── import from a spreadsheet ─────────────────────────────────
    def _import_table(self):
        """CSV/XLSX -> registers, through the column-mapping dialog."""
        from gui.import_dialog import ImportMapDialog
        path, _ = QFileDialog.getOpenFileName(
            self, self.t("impOpen"), "",
            self.t("filterTables") + " (*.csv *.xlsx *.xlsm *.txt);;CSV (*.csv);;"
            "Excel (*.xlsx *.xlsm);;" + self.t("filterAll") + " (*)")
        if not path:
            return
        dlg = ImportMapDialog(self.ctx, path, self)
        if dlg.exec() != QDialog.DialogCode.Accepted or not dlg.registers:
            return
        rows = normalize_registers(dlg.registers)
        if dlg.mode == "append":
            self.profile_data = list(self.profile_data) + list(rows)
        else:
            self.profile_data = rows
        self.is_modified = True
        self._push_state()
        self._refresh_ui()

    def _open_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, self.t("openProfile"), "", self.t("filterMap") + " (*.json)")
        if not path:
            return
        try:
            # Any version (bare array / {"registers":[...]} / versioned
            # envelope) is migrated to the current schema by formats.
            prof = formats.load_profile(path)
            self.profile_data = normalize_registers(prof["registers"])
            self.file_path = path
            self.profile_name = os.path.splitext(os.path.basename(path))[0]
            self.name_edit.setText(self.profile_name)
            self._push_state()
            self._refresh_ui()
        except Exception as e:
            themed_info(self, self._theme_name, "error", self.t("error"),
                        f"{self.t('jsonLoadErr')}:\n{type(e).__name__}: {e}")

    def set_source_file(self, path: str):
        """The map being edited came from *path*: Save writes back to it."""
        self.file_path = path or ""
        if path:
            self.profile_name = os.path.splitext(os.path.basename(path))[0]
            self.name_edit.setText(self.profile_name)

    def _suggested_filename(self) -> str:
        """Default save name: the editable profile name (or 'profile')."""
        name = self.name_edit.text().strip()
        return f"{name or 'profile'}.json"

    def _save(self):
        """Ctrl+S / Save button: replace the existing file in place if this
        profile was already saved/opened; otherwise prompt with Save As."""
        if self.file_path:
            self._write_to(self.file_path)
        else:
            self._save_as_file()

    def _write_to(self, path: str):
        try:
            # Write the current versioned envelope (formats.dump_profile) so
            # the file carries its version + scale/offset/enum, and can be
            # migrated forever.
            formats.dump_profile(path, self._export_list(),
                                 self.name_edit.text().strip())
            self.file_path = path
            self.profile_name = os.path.splitext(os.path.basename(path))[0]
            self.name_edit.setText(self.profile_name)
            self.is_modified = False
            self._update_dirty_dot()
        except Exception as e:
            themed_info(self, self._theme_name, "error", self.t("error"),
                        f"{self.t('jsonSaveErr')}:\n{type(e).__name__}: {e}")

    def _save_as_file(self):
        path, _ = QFileDialog.getSaveFileName(
            self, self.t("saveAs"), self._suggested_filename(),
            self.t("filterMap") + " (*.json)")
        if not path:
            return
        self._write_to(path)

    def _show_ctx_menu(self, pos):
        row = self.table.rowAt(pos.y())
        if row < 0:
            return
        self.table.selectRow(row)

        menu = QMenu(self)
        c = get_theme(self._theme_name)
        menu.setStyleSheet(f"QMenu {{ background: {c['bg_2']}; color: {c['text_1']}; border: 1px solid {c['line']}; border-radius: 6px; padding: 4px; }} QMenu::item {{ padding: 6px 24px; border-radius: 4px; }} QMenu::item:selected {{ background: {c['bg_4']}; }}")

        act_scale = menu.addAction(self.t("engUnits"))
        menu.addSeparator()
        act_dup = menu.addAction(self.t("duplicate"))
        act_del = menu.addAction(self.t("deleteRow"))

        action = menu.exec(self.table.viewport().mapToGlobal(pos))
        if action == act_scale:
            self._edit_scaling(row)
        elif action == act_dup:
            self._duplicate_row(row)
        elif action == act_del:
            self._delete_selected(row)

    def _edit_scaling(self, row: int):
        """Row → engineering-units dialog (scale/offset/unit + enum map)."""
        if not (0 <= row < len(self.profile_data)):
            return
        from gui.scaling_dialog import ScalingDialog
        reg = self.profile_data[row]
        dlg = ScalingDialog(reg, self._theme_name, self.t, self)
        dlg.exec()
        if dlg.result_cfg is not None:
            reg.update(dlg.result_cfg)
            # drop identity/empty keys so files stay lean
            for k in ("scale", "offset", "enum"):
                v = reg.get(k)
                if v in (None, "", {}, 1.0, 0.0) and k in reg:
                    del reg[k]
            self.is_modified = True
            self._push_state()
            self._refresh_ui()

    def reject(self):
        if self.is_modified:
            choice = themed_message(
                self, self._theme_name, "warning",
                self.t("unsavedTitle"), self.t("unsavedText"),
                [(self.t("cancel"), QMessageBox.ButtonRole.RejectRole, False),
                 (self.t("exit"), QMessageBox.ButtonRole.DestructiveRole, False),
                 (self.t("saveAndClose"), QMessageBox.ButtonRole.AcceptRole,
                  True)])
            if choice == 2:                  # Save, then close
                self._save()
                if self.is_modified:         # save failed / was cancelled
                    return
            elif choice != 1:                # anything but Discard -> stay
                return
        super().reject()

    def get_profile_data(self):
        """Flat list compatible with the main app (string `name`)."""
        return self._export_list()
