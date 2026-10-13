# gui_import_dialog.py
"""Column-mapping dialog for importing a register map from CSV / XLSX.

The layout follows the order of the decisions: pick the sheet, say where the
header is, say how addresses are written, then assign each column. Everything
re-previews live, because the only reliable way to know the mapping is right is
to see the resulting registers.

All logic lives in mapimport.py; this file renders it and translates the
problem keys it reports.
"""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QComboBox, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView, QWidget,
    QCheckBox,
)

import mapimport as mi
from dialogs import themed_info
from theme_manager import get_theme

PREVIEW_ROWS = 12


class ImportMapDialog(QDialog):
    """Result in ``registers`` (list) and ``mode`` ("replace" | "append")."""

    def __init__(self, ctx, path: str, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.path = path
        self.registers: list = []
        self.mode = "replace"
        self._rows: list = []
        self._problems: list = []

        self.setWindowFlags(Qt.WindowType.FramelessWindowHint
                            | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setModal(True)
        self._c = get_theme(ctx.theme)
        self._build_ui()
        self._load_file()

    # ── UI ────────────────────────────────────────────────────────────
    def _lbl(self, text, dim=False):
        l = QLabel(text)
        l.setStyleSheet(f"color:{self._c['text_3' if dim else 'text_1']};"
                        f"background:transparent;font-size:12px;")
        return l

    def _build_ui(self):
        c, t = self._c, self.ctx.t
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        card = QFrame(self)
        card.setObjectName("dlgCard")
        card.setStyleSheet(
            f"QFrame#dlgCard {{ background:{c['bg_2']};"
            f" border:1px solid {c['line_strong']}; border-radius:14px; }}"
            f" QWidget#dlgRow {{ background: transparent; }}")
        card.setMinimumWidth(900)
        outer.addWidget(card)
        lo = QVBoxLayout(card)
        lo.setContentsMargins(22, 18, 22, 16)
        lo.setSpacing(10)

        title = QLabel(t("impTitle"))
        title.setStyleSheet(f"color:{c['text_1']};background:transparent;"
                            f"font-size:16px;font-weight:700;")
        lo.addWidget(title)
        self.lbl_file = self._lbl(self.path, dim=True)
        self.lbl_file.setWordWrap(True)
        lo.addWidget(self.lbl_file)

        # ── options row ──
        row = QWidget()
        row.setObjectName("dlgRow")
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(10)

        self.lbl_sheet = self._lbl(t("impSheet"))
        self.combo_sheet = QComboBox()
        self.combo_sheet.setObjectName("stInput")
        self.combo_sheet.setMinimumWidth(150)
        self.combo_sheet.currentIndexChanged.connect(self._load_file)
        rl.addWidget(self.lbl_sheet)
        rl.addWidget(self.combo_sheet)

        self.chk_header = QCheckBox(t("impHasHeader"))
        self.chk_header.setStyleSheet(f"color:{c['text_1']};background:transparent;")
        self.chk_header.stateChanged.connect(self._rebuild)
        rl.addWidget(self.chk_header)

        rl.addWidget(self._lbl(t("impAddrMode")))
        self.combo_addr = QComboBox()
        self.combo_addr.setObjectName("stInput")
        self.combo_addr.setMinimumWidth(210)
        for key in mi.ADDR_MODES:
            self.combo_addr.addItem(t(mi.ADDR_MODE_LABELS[key]), key)
        self.combo_addr.currentIndexChanged.connect(self._rebuild)
        rl.addWidget(self.combo_addr)
        rl.addStretch()
        lo.addWidget(row)

        # ── preview table: row 0 holds the per-column field pickers ──
        self.table = QTableWidget(0, 0)
        self.table.setObjectName("scanTable")
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch)
        self.table.setMinimumHeight(300)
        lo.addWidget(self.table, 1)

        self.lbl_summary = self._lbl("")
        lo.addWidget(self.lbl_summary)
        self.lbl_problems = QLabel("")
        self.lbl_problems.setWordWrap(True)
        self.lbl_problems.setStyleSheet(
            f"color:{c['warn']};background:transparent;font-size:11px;")
        self.lbl_problems.setMaximumHeight(72)
        lo.addWidget(self.lbl_problems)

        # ── buttons ──
        btns = QHBoxLayout()
        btns.addStretch()
        b_cancel = QPushButton(t("cancel"))
        b_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        b_cancel.setStyleSheet(
            f"QPushButton {{ color:{c['text_1']};background:{c['bg_3']};"
            f" border:1px solid {c['line']};border-radius:7px;"
            f" font-size:13px;padding:7px 16px; }}"
            f"QPushButton:hover {{ background:{c['bg_4']}; }}")
        b_cancel.clicked.connect(self.reject)
        self.btn_append = QPushButton(t("impAppend"))
        self.btn_append.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_append.setStyleSheet(b_cancel.styleSheet())
        self.btn_append.clicked.connect(lambda: self._accept("append"))
        self.btn_import = QPushButton(t("impReplace"))
        self.btn_import.setDefault(True)
        self.btn_import.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_import.setStyleSheet(
            f"QPushButton {{ color:{c['accent_fg']};background:{c['accent']};"
            f" border:none;border-radius:7px;font-size:13px;font-weight:600;"
            f" padding:7px 20px; }}"
            f"QPushButton:disabled {{ background:{c['bg_4']};"
            f" color:{c['text_4']}; }}")
        self.btn_import.clicked.connect(lambda: self._accept("replace"))
        btns.addWidget(b_cancel)
        btns.addWidget(self.btn_append)
        btns.addWidget(self.btn_import)
        lo.addLayout(btns)

    # ── loading ───────────────────────────────────────────────────────
    def _load_file(self):
        t = self.ctx.t
        try:
            sheets = mi.sheet_names(self.path)
            if sheets and self.combo_sheet.count() == 0:
                self.combo_sheet.blockSignals(True)
                self.combo_sheet.addItems(sheets)
                self.combo_sheet.blockSignals(False)
            visible = bool(sheets)
            self.lbl_sheet.setVisible(visible)
            self.combo_sheet.setVisible(visible)
            sheet = self.combo_sheet.currentText() if visible else None
            self._rows = mi.read_table(self.path, sheet)
        except mi.ImportError_ as e:
            themed_info(self, self.ctx.theme, "error", t("errTitle"), str(e))
            self._rows = []
            self.btn_import.setEnabled(False)
            return
        self.chk_header.blockSignals(True)
        self.chk_header.setChecked(mi.looks_like_header(self._rows[0]))
        self.chk_header.blockSignals(False)
        self._build_columns()
        self._rebuild()

    def _build_columns(self):
        """One field-picker per column, seeded from the header guess."""
        t = self.ctx.t
        width = len(self._rows[0]) if self._rows else 0
        header = self._rows[0] if (self._rows and self.chk_header.isChecked()) \
            else []
        guess = mi.guess_mapping(header) if header else {}
        by_col = {col: field for field, col in guess.items()}

        self.table.clear()
        self.table.setColumnCount(width)
        self.table.setHorizontalHeaderLabels([
            str(header[i]) if i < len(header) and str(header[i]).strip()
            else t("impColumn").format(n=i + 1) for i in range(width)])
        self._pickers = []
        self.table.setRowCount(1)
        for i in range(width):
            cb = QComboBox()
            cb.setObjectName("stInput")
            cb.addItem(t("impIgnore"), "")
            for key, label, _req in mi.FIELDS:
                cb.addItem(t(label), key)
            want = by_col.get(i, "")
            idx = cb.findData(want)
            cb.setCurrentIndex(idx if idx >= 0 else 0)
            cb.currentIndexChanged.connect(self._rebuild)
            self.table.setCellWidget(0, i, cb)
            self._pickers.append(cb)

    def current_mapping(self) -> dict:
        """``{field: column}`` from the pickers. A field assigned twice keeps
        the FIRST column — silently importing the same column into two fields
        is more confusing than ignoring the duplicate."""
        mapping = {}
        for col, cb in enumerate(getattr(self, "_pickers", [])):
            field = cb.currentData()
            if field and field not in mapping:
                mapping[field] = col
        return mapping

    # ── preview ───────────────────────────────────────────────────────
    def _rebuild(self):
        t = self.ctx.t
        if not self._rows:
            return
        # Re-seed the pickers when the header checkbox flips: the guess only
        # makes sense against a real header row.
        body_start = 1 if self.chk_header.isChecked() else 0
        preview = self._rows[body_start:body_start + PREVIEW_ROWS]
        self.table.setRowCount(1 + len(preview))
        for r, row in enumerate(preview, start=1):
            for col in range(self.table.columnCount()):
                text = str(row[col]) if col < len(row) else ""
                self.table.setItem(r, col, QTableWidgetItem(text))

        mapping = self.current_mapping()
        try:
            regs, problems = mi.build_registers(
                self._rows, mapping,
                addr_mode=self.combo_addr.currentData() or "raw",
                has_header=self.chk_header.isChecked())
        except mi.ImportError_ as e:
            self.registers, self._problems = [], []
            self.lbl_summary.setText(str(e))
            self.lbl_problems.setText("")
            self.btn_import.setEnabled(False)
            self.btn_append.setEnabled(False)
            return
        self.registers, self._problems = regs, problems
        self.lbl_summary.setText(t("impPreview").format(n=len(regs)))
        self.lbl_problems.setText(self._format_problems(problems))
        self.btn_import.setEnabled(True)
        self.btn_append.setEnabled(True)

    def _format_problems(self, problems: list) -> str:
        """Problem tuples are (line, i18n key, params) — translated here so the
        pure module stays language-free."""
        if not problems:
            return ""
        t = self.ctx.t
        shown = []
        for line, key, params in problems[:6]:
            args = dict(params or {})
            args["line"] = line
            try:
                shown.append(t(key).format(**args))
            except (KeyError, IndexError):
                shown.append(key)          # a message we cannot fill is still
                                           # better than swallowing the problem
        more = len(problems) - len(shown)
        text = " · ".join(shown)
        return text + (f"  (+{more})" if more > 0 else "")

    # ── result ────────────────────────────────────────────────────────
    def _accept(self, mode: str):
        if not self.registers:
            themed_info(self, self.ctx.theme, "warning",
                        self.ctx.t("impTitle"), self.ctx.t("impNothing"))
            return
        self.mode = mode
        self.accept()
