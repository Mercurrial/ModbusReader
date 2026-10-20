# gui/dashboard_dialog.py
"""Add / edit dialog for one dashboard widget.

The kind is chosen from a **tile picker** (icon + name, grouped by section) —
the way insert panels work in professional editors — instead of a long combo
where the group headers had to live inside the list. The remaining fields
follow the chosen kind, so the dialog never shows a control that does nothing.

Note on backgrounds: plain ``QWidget`` row containers inherit the global
``QWidget { background: bg_1 }`` rule and would paint a lighter block inside
the bg_2 dialog card. Every container here is therefore explicitly transparent
(``#dlgRow``) — that mismatch was a visible bug.
"""

import uuid

from PyQt6.QtCore import Qt, QSize
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QFrame, QLabel, QLineEdit,
    QPushButton, QToolButton, QComboBox, QWidget, QSizePolicy,
)

from core import datatypes
from gui import icons
from core import scaling
from core import dash_model as dm
from gui.widgets import ToggleSwitch
from gui.theme_manager import get_theme, _mix

# 5 tiles per row keeps each group to one or two rows: with 14 kinds a 4-wide
# grid pushed the dialog past 780 px, which does not fit a 768 px laptop.
TILE_W = 80
TILES_PER_ROW = 5
CARD_W = 506             # sized so 5 tiles + spacing fit the row exactly

# One row = caption + control. Fixed height and a fixed number of visible rows
# keep the dialog EXACTLY the same size for every widget kind — the sizes used
# to jump by ~170 px between kinds, which is what made the spacing look random.
ROW_H = 48
ROW_GAP = 8
MAX_ROWS = 4             # the busiest kind (led, slider, bar…) shows four
HINT_H = 40              # three lines at 11 px — never resizes the card


def _f(text, default=0.0) -> float:
    try:
        return float(str(text).replace(",", "."))
    except (TypeError, ValueError):
        return default


def _opt_f(text):
    s = str(text).strip()
    if not s:
        return None
    try:
        return float(s.replace(",", "."))
    except ValueError:
        return None


class KindTile(QToolButton):
    """One widget kind in the picker: icon above, name below (a QToolButton is
    the only Qt button that lays icon+text out vertically)."""

    def __init__(self, kind_key: str, label: str, colors: dict, parent=None):
        super().__init__(parent)
        self.kind_key = kind_key
        self._c = colors
        self.setObjectName("kindTile")
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        # Fixed height, elastic width: the grid hands out the leftover row
        # width so a long label gets every pixel there is before it elides.
        self.setFixedHeight(62)
        self.setMinimumWidth(TILE_W)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Fixed)
        self.setText(label)
        self.setToolTip(label)
        self._icon_name = dm.kind(kind_key).icon
        self._refresh_icon()

    def _refresh_icon(self):
        col = self._c["accent"] if self.isChecked() else self._c["text_3"]
        self.setIcon(icons.icon(self._icon_name, col, 20))
        self.setIconSize(QSize(20, 20))

    def setChecked(self, on: bool):
        super().setChecked(on)
        self._refresh_icon()


class WidgetDialog(QDialog):
    """cfg=None → add; cfg given → edit. Result in ``result_cfg``."""

    def __init__(self, ctx, registers: list, cfg: dict | None = None,
                 parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self._edit_cfg = cfg
        self.result_cfg = None
        self._kind = (cfg or {}).get("kind", "value")
        self._tiles: dict[str, KindTile] = {}
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint
                            | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setModal(True)

        c = get_theme(ctx.theme)
        t = ctx.t
        self._c = c
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        card = QFrame(self)
        card.setObjectName("dlgCard")
        card.setStyleSheet(
            f"QFrame#dlgCard {{ background: {c['bg_2']};"
            f" border: 1px solid {c['line_strong']}; border-radius: 14px; }}"
            # Row containers must not paint the global QWidget background.
            f" QWidget#dlgRow {{ background: transparent; }}"
            # Tiles: flat and quiet by default (no hard borders — that grid of
            # boxes is what made the picker look busy), lifted on hover, and
            # clearly filled when chosen.
            f" QToolButton#kindTile {{ background: transparent;"
            f"   border: 1px solid transparent; border-radius: 10px;"
            f"   color: {c['text_3']}; font-size: 10px; padding: 6px 1px 4px; }}"
            f" QToolButton#kindTile:hover {{ background: {c['bg_3']};"
            f"   color: {c['text_1']}; }}"
            f" QToolButton#kindTile:checked {{ background: {c['accent_tint']};"
            f"   border: 1px solid {c['accent']}; color: {c['text_1']};"
            f"   font-weight: 600; }}"
            f" QWidget#kindPanel {{ background: {c['bg_1']};"
            f"   border: 1px solid {c['line']}; border-radius: 10px; }}")
        card.setFixedWidth(CARD_W)
        outer.addWidget(card)
        lo = QVBoxLayout(card)
        lo.setContentsMargins(22, 16, 22, 14)
        lo.setSpacing(8)
        self._lo = lo

        title = QLabel(t("dashEditTitle") if cfg else t("dashAddTitle"))
        title.setStyleSheet(f"color:{c['text_1']}; background:transparent;"
                            f"font-size:16px; font-weight:700;")
        lo.addWidget(title)

        # ── kind tiles: one calm panel, groups as light captions ──
        picker = QWidget()
        picker.setObjectName("kindPanel")
        pv = QVBoxLayout(picker)
        pv.setContentsMargins(10, 8, 10, 10)
        pv.setSpacing(2)
        for gi, (group_key, keys) in enumerate(dm.KIND_GROUPS):
            if gi:
                pv.addSpacing(6)
            pv.addWidget(self._section(t(group_key)))
            # A grid, not a row: the display group outgrew a single line and a
            # horizontally overflowing picker was clipping tiles.
            grid_host = QWidget()
            grid_host.setObjectName("dlgRow")
            grid = QGridLayout(grid_host)
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setSpacing(4)
            for i, k in enumerate(keys):
                tile = KindTile(k, t(dm.kind(k).label_key), c, grid_host)
                tile.clicked.connect(lambda _=False, kk=k: self._select_kind(kk))
                self._tiles[k] = tile
                grid.addWidget(tile, i // TILES_PER_ROW, i % TILES_PER_ROW)
            for col in range(TILES_PER_ROW):
                grid.setColumnStretch(col, 1)
            pv.addWidget(grid_host)
        lo.addWidget(picker)

        # ── field area ──
        # Every optional row lives in a host of FIXED height. Showing/hiding
        # rows used to resize the dialog per kind (541…710 px), which read as
        # random padding; now the frame never moves and only its contents swap.
        fields = QWidget()
        fields.setObjectName("dlgRow")
        fields.setFixedHeight(MAX_ROWS * ROW_H + (MAX_ROWS - 1) * ROW_GAP)
        fl = QVBoxLayout(fields)
        fl.setContentsMargins(0, 0, 0, 0)
        fl.setSpacing(ROW_GAP)
        fl.setAlignment(Qt.AlignmentFlag.AlignTop)
        lo.addWidget(fields)
        self._fields_lo = fl

        # ── register (bound kinds only) ──
        self.row_reg = self._row()
        rr = QVBoxLayout(self.row_reg)
        rr.setContentsMargins(0, 0, 0, 0)
        rr.setSpacing(3)
        rr.addWidget(self._lbl(t("dashRegister")))
        self.combo_reg = QComboBox()
        self.combo_reg.setObjectName("stInput")
        # Full pool; the visible subset depends on the kind (a control widget
        # must not be able to pick a read-only register).
        self._all_regs = [r for r in (registers or [])
                          if not datatypes.is_area(r.get("type", "SHORT"))]
        self._regs = list(self._all_regs)
        self.combo_reg.currentIndexChanged.connect(self._prefill_from_reg)
        rr.addWidget(self.combo_reg)
        fl.addWidget(self.row_reg)

        # ── title + unit ──
        row_t = self._row()
        rt = QHBoxLayout(row_t)
        rt.setContentsMargins(0, 0, 0, 0)
        rt.setSpacing(8)
        self.ed_title = QLineEdit()
        self.ed_title.setObjectName("stInput")
        rt.addLayout(self._field(t("dashTitleLbl"), self.ed_title))
        self.ed_unit = QLineEdit()
        self.ed_unit.setObjectName("stInput")
        self.ed_unit.setFixedWidth(96)
        rt.addLayout(self._field(t("dashUnit"), self.ed_unit))
        fl.addWidget(row_t)

        # ── range (bar / gauge) ──
        self.row_range = self._row()
        rg = QHBoxLayout(self.row_range)
        rg.setContentsMargins(0, 0, 0, 0)
        rg.setSpacing(8)
        self.ed_min = QLineEdit("0")
        self.ed_max = QLineEdit("100")
        self.ed_min.setObjectName("stInput")
        self.ed_max.setObjectName("stInput")
        rg.addLayout(self._field(t("dashMin"), self.ed_min))
        rg.addLayout(self._field(t("dashMax"), self.ed_max))
        fl.addWidget(self.row_range)

        # ── LED threshold + invert ──
        self.row_led = self._row()
        rl2 = QHBoxLayout(self.row_led)
        rl2.setContentsMargins(0, 0, 0, 0)
        rl2.setSpacing(8)
        self.ed_thr = QLineEdit("0.5")
        self.ed_thr.setObjectName("stInput")
        rl2.addLayout(self._field(t("dashThr"), self.ed_thr))
        self.tgl_invert = ToggleSwitch(False, theme=c)
        rl2.addLayout(self._field(t("dashInvert"), self.tgl_invert))
        rl2.addStretch()
        fl.addWidget(self.row_led)

        # ── alarms (display kinds) ──
        self.row_alarm = self._row()
        ra = QHBoxLayout(self.row_alarm)
        ra.setContentsMargins(0, 0, 0, 0)
        ra.setSpacing(8)
        self.ed_alo = QLineEdit()
        self.ed_ahi = QLineEdit()
        for ed, key in ((self.ed_alo, "dashAlarmLo"), (self.ed_ahi, "dashAlarmHi")):
            ed.setObjectName("stInput")
            ed.setPlaceholderText(t("dashAlarmOff"))
            ra.addLayout(self._field(t(key), ed))
        fl.addWidget(self.row_alarm)

        # ── button / toggle write values ──
        self.row_write = self._row()
        rw = QHBoxLayout(self.row_write)
        rw.setContentsMargins(0, 0, 0, 0)
        rw.setSpacing(8)
        self.ed_val_on = QLineEdit("1")
        self.ed_val_off = QLineEdit("0")
        self.ed_val_on.setObjectName("stInput")
        self.ed_val_off.setObjectName("stInput")
        self.lbl_on = self._lbl(t("dashWriteValue"))
        self.lbl_off = self._lbl(t("dashWriteValueOff"))
        rw.addLayout(self._field_w(self.lbl_on, self.ed_val_on))
        rw.addLayout(self._field_w(self.lbl_off, self.ed_val_off))
        fl.addWidget(self.row_write)

        # ── timer interval ──
        self.row_timer = self._row()
        rti = QHBoxLayout(self.row_timer)
        rti.setContentsMargins(0, 0, 0, 0)
        rti.setSpacing(8)
        self.ed_interval = QLineEdit("1000")
        self.ed_interval.setObjectName("stInput")
        rti.addLayout(self._field(t("dashInterval"), self.ed_interval))
        self.tgl_autostart = ToggleSwitch(False, theme=c)
        rti.addLayout(self._field(t("dashAutostart"), self.tgl_autostart))
        rti.addStretch()
        fl.addWidget(self.row_timer)

        # ── gate condition ──
        self.row_gate = self._row()
        rgt = QHBoxLayout(self.row_gate)
        rgt.setContentsMargins(0, 0, 0, 0)
        rgt.setSpacing(8)
        self.combo_cond = QComboBox()
        self.combo_cond.setObjectName("stInput")
        for cond in dm.CONDITIONS:
            self.combo_cond.addItem(dm.CONDITION_SIGNS[cond], cond)
        self.combo_cond.setFixedWidth(78)
        rgt.addLayout(self._field(t("dashCondition"), self.combo_cond))
        self.ed_cmp = QLineEdit("0")
        self.ed_cmp.setObjectName("stInput")
        rgt.addLayout(self._field(t("dashCompareWith"), self.ed_cmp))
        fl.addWidget(self.row_gate)

        # ── slider step + live write ──
        self.row_slider = self._row()
        rsl = QHBoxLayout(self.row_slider)
        rsl.setContentsMargins(0, 0, 0, 0)
        rsl.setSpacing(8)
        self.ed_step = QLineEdit("1")
        self.ed_step.setObjectName("stInput")
        self.ed_step.setFixedWidth(96)
        rsl.addLayout(self._field(t("dashStep"), self.ed_step))
        self.tgl_live = ToggleSwitch(False, theme=c)
        rsl.addLayout(self._field(t("dashLive"), self.tgl_live))
        rsl.addStretch()
        fl.addWidget(self.row_slider)

        self.lbl_hint = QLabel("")
        self.lbl_hint.setWordWrap(True)
        self.lbl_hint.setFixedHeight(HINT_H)      # longer hints must not resize
        self.lbl_hint.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.lbl_hint.setStyleSheet(f"color:{c['text_4']}; background:transparent;"
                                    f"font-size:11px;")
        lo.addWidget(self.lbl_hint)

        # ── buttons ──
        btns = QHBoxLayout()
        btns.addStretch()
        b_cancel = QPushButton(t("cancel"))
        b_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        b_cancel.setStyleSheet(
            f"QPushButton {{ color:{c['text_1']}; background:{c['bg_3']};"
            f" border:1px solid {c['line']}; border-radius:7px;"
            f" font-size:13px; padding:7px 16px; }}"
            f"QPushButton:hover {{ background:{c['bg_4']}; }}")
        b_cancel.clicked.connect(self.reject)
        b_ok = QPushButton(t("apply") if cfg else t("dashAdd"))
        b_ok.setDefault(True)
        b_ok.setCursor(Qt.CursorShape.PointingHandCursor)
        b_ok.setStyleSheet(
            f"QPushButton {{ color:{c['accent_fg']}; background:{c['accent']};"
            f" border:none; border-radius:7px; font-size:13px;"
            f" font-weight:600; padding:7px 20px; }}"
            f"QPushButton:hover {{ background:{_mix(c['accent'], c['text_1'], 0.16)}; }}")
        b_ok.clicked.connect(self._accept)
        btns.addWidget(b_cancel)
        btns.addWidget(b_ok)
        lo.addLayout(btns)

        if cfg:
            self._prefill_from_cfg(cfg)
        else:
            self._prefill_from_reg(self.combo_reg.currentIndex())
        self._select_kind(self._kind)

    # ── small builders ───────────────────────────────────────────────
    def _row(self) -> QWidget:
        w = QWidget()
        w.setObjectName("dlgRow")       # transparent per the card stylesheet
        w.setFixedHeight(ROW_H)         # uniform rows, uniform rhythm
        return w

    def _section(self, text) -> QLabel:
        l = QLabel(text.upper())
        l.setStyleSheet(f"color:{self._c['text_4']}; background:transparent;"
                        f"font-size:10px; font-weight:700; letter-spacing:.8px;")
        return l

    def _lbl(self, text) -> QLabel:
        l = QLabel(text)
        l.setStyleSheet(f"color:{self._c['text_3']}; background:transparent;"
                        f"font-size:12px;")
        return l

    def _field(self, label, widget) -> QVBoxLayout:
        return self._field_w(self._lbl(label), widget)

    def _field_w(self, label_widget, widget) -> QVBoxLayout:
        box = QVBoxLayout()
        box.setSpacing(3)
        box.addWidget(label_widget)
        box.addWidget(widget)
        return box

    # ── kind selection ───────────────────────────────────────────────
    def current_kind(self) -> str:
        return self._kind

    def _select_kind(self, key: str):
        self._kind = key if key in dm.KINDS else "value"
        for k, tile in self._tiles.items():
            tile.setChecked(k == self._kind)
        self._sync_fields()

    def _reload_registers(self):
        """Show only the registers this kind may legally use.

        A button/input/slider WRITES, so offering a read-only register is at
        best confusing and at worst a write that the device rejects. Access is
        the register's ``rw`` field ("R" / "W" / "RW")."""
        spec = dm.kind(self._kind)
        if spec.writes:
            regs = [r for r in self._all_regs
                    if isinstance(r, dict) and datatypes.is_writable(r)]
        else:
            regs = list(self._all_regs)
        keep = None
        if 0 <= self.combo_reg.currentIndex() < len(self._regs):
            keep = datatypes.reg_key(self._regs[self.combo_reg.currentIndex()])
        self._regs = regs
        self.combo_reg.blockSignals(True)
        self.combo_reg.clear()
        for r in regs:
            self.combo_reg.addItem(
                f"{datatypes.key_label(datatypes.reg_key(r))}  ·  {r.get('name', '')}")
        if keep is not None:
            for i, r in enumerate(regs):
                if datatypes.reg_key(r) == keep:
                    self.combo_reg.setCurrentIndex(i)
                    break
        self.combo_reg.blockSignals(False)
        # An empty list is a real state (a read-only map + a control widget):
        # say so instead of showing a blank combo the user cannot use.
        empty = not regs
        self.combo_reg.setEnabled(not empty)
        self.combo_reg.setPlaceholderText(
            self.ctx.t("dashNoWritableReg") if empty else "")

    def _sync_fields(self):
        k = self._kind
        spec = dm.kind(k)
        t = self.ctx.t
        self._reload_registers()
        self.row_reg.setVisible(spec.bound)
        self.row_range.setVisible(k in dm.RANGE_KINDS)
        self.row_led.setVisible(k == "led")
        self.row_alarm.setVisible(k in dm.DISPLAY_KINDS)
        self.row_write.setVisible(k in ("button", "toggle"))
        self.lbl_off.setVisible(k == "toggle")
        self.ed_val_off.setVisible(k == "toggle")
        self.row_timer.setVisible(k == "timer")
        self.row_gate.setVisible(k == "gate")
        self.row_slider.setVisible(k == "slider")
        self.ed_unit.setEnabled(
            k not in ("label", "timer", "button", "gate", "bits", "select"))
        # Every kind explains itself — the picker doubles as documentation.
        self.lbl_hint.setText(t(f"dashHint{k.capitalize()}"))
        self.adjustSize()

    # ── prefill ──────────────────────────────────────────────────────
    def _prefill_from_reg(self, idx: int):
        if self._edit_cfg is None and 0 <= idx < len(self._regs):
            reg = self._regs[idx]
            self.ed_title.setPlaceholderText(str(reg.get("name", "")))
            self.ed_unit.setText(str(reg.get("unit", "")))

    def _prefill_from_cfg(self, cfg: dict):
        rid = cfg.get("reg_id", "")
        for i, r in enumerate(self._regs):
            if datatypes.reg_id(datatypes.reg_key(r)) == rid:
                self.combo_reg.setCurrentIndex(i)
                break
        self.ed_title.setText(cfg.get("title", ""))
        self.ed_title.setPlaceholderText(cfg.get("name", ""))
        self.ed_unit.setText(cfg.get("unit", ""))
        self.ed_min.setText(str(cfg.get("vmin", 0)))
        self.ed_max.setText(str(cfg.get("vmax", 100)))
        self.ed_thr.setText(str(cfg.get("thr", 0.5)))
        self.tgl_invert.setChecked(bool(cfg.get("invert")))
        self.ed_alo.setText("" if cfg.get("alo") is None else str(cfg["alo"]))
        self.ed_ahi.setText("" if cfg.get("ahi") is None else str(cfg["ahi"]))
        self.ed_val_on.setText(str(cfg.get("value_on", 1)))
        self.ed_val_off.setText(str(cfg.get("value_off", 0)))
        self.ed_interval.setText(str(cfg.get("interval", 1000)))
        self.tgl_autostart.setChecked(bool(cfg.get("autostart")))
        idx = self.combo_cond.findData(str(cfg.get("cond", "gt")))
        self.combo_cond.setCurrentIndex(max(0, idx))
        self.ed_cmp.setText(str(cfg.get("cmp", 0)))
        self.ed_step.setText(str(cfg.get("step", 1)))
        self.tgl_live.setChecked(bool(cfg.get("live")))

    # ── result ───────────────────────────────────────────────────────
    def _accept(self):
        k = self._kind
        spec = dm.kind(k)
        old = self._edit_cfg or {}
        cfg = {
            "uid": old.get("uid", uuid.uuid4().hex[:8]),
            "kind": k,
            "title": self.ed_title.text().strip(),
            "unit": self.ed_unit.text().strip(),
        }
        # Geometry only when it already exists — a new widget must NOT carry
        # None values (int(None) used to crash the add handler silently).
        for key in ("x", "y", "w", "h"):
            if old.get(key) is not None:
                cfg[key] = old[key]
        if spec.bound:
            idx = self.combo_reg.currentIndex()
            if idx < 0 or idx >= len(self._regs):
                # Nothing to bind to. This used to reject() — the dialog just
                # vanished and no widget appeared, with no reason given.
                from gui.dialogs import themed_info
                t = self.ctx.t
                if self._all_regs:
                    themed_info(self, self.ctx.theme, "info",
                                t("dashNoProfileTitle"), t("dashNoWritableReg"))
                else:
                    themed_info(self, self.ctx.theme, "info",
                                t("dashNoProfileTitle"), t("dashNoProfileText"))
                return
            reg = self._regs[idx]
            cfg["reg_id"] = datatypes.reg_id(datatypes.reg_key(reg))
            cfg["name"] = str(reg.get("name", ""))
            cfg["reg_type"] = str(reg.get("type", "SHORT"))
        if k in dm.RANGE_KINDS:
            cfg["vmin"] = _f(self.ed_min.text(), 0.0)
            cfg["vmax"] = _f(self.ed_max.text(), 100.0)
        if k == "gate":
            cfg["cond"] = self.combo_cond.currentData() or "gt"
            cfg["cmp"] = _f(self.ed_cmp.text(), 0.0)
        if k == "slider":
            cfg["step"] = _f(self.ed_step.text(), 1.0) or 1.0
            cfg["live"] = bool(self.tgl_live.isChecked())
        if k == "select":
            # Snapshot the register's enum so the widget keeps its labels even
            # when the dashboard is opened without that profile loaded.
            reg = self._regs[self.combo_reg.currentIndex()] \
                if 0 <= self.combo_reg.currentIndex() < len(self._regs) else {}
            cfg["options"] = [[v, label]
                              for v, label in sorted(scaling.get_enum(reg).items())]
        if k == "led":
            cfg["thr"] = _f(self.ed_thr.text(), 0.5)
            cfg["invert"] = bool(self.tgl_invert.isChecked())
        if k in dm.DISPLAY_KINDS:
            cfg["alo"] = _opt_f(self.ed_alo.text())
            cfg["ahi"] = _opt_f(self.ed_ahi.text())
        if k in ("button", "toggle"):
            cfg["value_on"] = _f(self.ed_val_on.text(), 1.0)
        if k == "toggle":
            cfg["value_off"] = _f(self.ed_val_off.text(), 0.0)
        if k == "timer":
            cfg["interval"] = max(50, int(_f(self.ed_interval.text(), 1000)))
            cfg["autostart"] = bool(self.tgl_autostart.isChecked())
        self.result_cfg = cfg
        self.accept()
