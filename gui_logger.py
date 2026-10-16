# gui_logger.py
"""Data-logger view — write register values to CSV for hours or days.

Sampling is driven by a timer here rather than by the poll callback on purpose:
the file is WIDE (one column per register), so a row must be a coherent
snapshot of every register at one instant. Writing a row per incoming value
would produce one row per register with a single filled cell.

The writer itself (rotation, encoding, failure handling) is datalog.py.

The view is a MONITOR, not a form. Four fields on an empty page told you
nothing about an eight-hour run, so most of the page is given to what is
actually being written: the planned column layout before you start, then the
rows as they land. An unattended recorder that shows no output is a recorder
you have to go and verify by hand.
"""

import os
import time

from PyQt6.QtCore import Qt, QSize, QTimer
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QSpinBox,
    QLineEdit, QFileDialog, QCheckBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView,
)

from PyQt6.QtWidgets import QMessageBox

import datalog
from gui_widgets import EmptyState
import datatypes
import icons
from dialogs import themed_info, themed_message
from qt_utils import set_state

PREVIEW_ROWS = 200          # rows kept on screen; the file keeps everything


_SIZE_UNITS = {"ru": ("ГБ", "МБ", "КБ", "Б"), "en": ("GB", "MB", "KB", "B")}


def human_size(n: int, lang: str = "en") -> str:
    """Bytes for people, in the UI language ("1.1 МБ" next to Russian)."""
    gb, mb, kb, b = _SIZE_UNITS.get(lang, _SIZE_UNITS["en"])
    for unit, step in ((gb, 1 << 30), (mb, 1 << 20), (kb, 1 << 10)):
        if n >= step:
            return f"{n / step:.1f} {unit}"
    return f"{n} {b}"


def human_elapsed(seconds: float) -> str:
    s = int(max(0, seconds))
    return f"{s // 3600:d}:{(s // 60) % 60:02d}:{s % 60:02d}"


class LoggerView(QWidget):
    """Start/stop CSV logging of the current register values."""

    def __init__(self, ctx, get_registers, get_values, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.get_registers = get_registers
        self.get_values = get_values
        self.writer: datalog.LogWriter | None = None
        self._last_result: tuple | None = None
        self._columns: list = []
        self._started_at = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self.setObjectName("loggerView")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._build_ui()
        self.refresh_columns()

    # ── UI ────────────────────────────────────────────────────────────
    def _lbl(self, text, obj="mhCrumb"):
        l = QLabel(text)
        l.setObjectName(obj)
        return l

    def _build_ui(self):
        t, c = self.ctx.t, self.ctx.theme_tokens()
        lo = QVBoxLayout(self)
        lo.setContentsMargins(14, 10, 14, 10)
        lo.setSpacing(10)

        # ── file row ──
        # Deliberately NOT full width. A path is a fixed-length thing, so a
        # field stretched across a 1920 monitor is empty space with a browse
        # button marooned on the far edge.
        row1 = QHBoxLayout()
        row1.setSpacing(6)
        self.lbl_file = self._lbl(t("logFile"))
        row1.addWidget(self.lbl_file)
        # A fresh timestamped name per run (see _next_default_path): reusing
        # one fixed name made the second run overwrite the first one's file.
        self._auto_path = os.path.join(os.path.expanduser("~"),
                                       datalog.timestamp_name())
        self.ed_path = QLineEdit(self._auto_path)
        self.ed_path.setObjectName("stInput")
        self.ed_path.setMaximumWidth(520)
        self.ed_path.setMinimumWidth(260)
        self.ed_path.setCursorPosition(len(self.ed_path.text()))
        row1.addWidget(self.ed_path, 1)
        self.btn_browse = QPushButton()
        self.btn_browse.setObjectName("tbBtn")
        self.btn_browse.setIcon(icons.icon("folder", c["text_2"], 15))
        self.btn_browse.setFixedWidth(34)
        self.btn_browse.setToolTip(t("logChoose"))
        self.btn_browse.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_browse.clicked.connect(self._browse)
        row1.addWidget(self.btn_browse)
        row1.addStretch()
        lo.addLayout(row1)

        # ── options row ──
        row2 = QHBoxLayout()
        row2.setSpacing(8)
        self.lbl_every = self._lbl(t("logEvery"))
        row2.addWidget(self.lbl_every)
        self.spin_period = QSpinBox()
        self.spin_period.setObjectName("stInput")
        self.spin_period.setRange(100, 3600000)
        self.spin_period.setSingleStep(100)
        self.spin_period.setValue(1000)
        self.spin_period.setSuffix(self.ctx.t("unitMsSuffix"))
        self.spin_period.setFixedWidth(110)
        self.spin_period.valueChanged.connect(lambda _v: self._update_forecast())
        row2.addWidget(self.spin_period)

        self.lbl_rotate = self._lbl(t("logRotate"))
        row2.addWidget(self.lbl_rotate)
        self.spin_rotate = QSpinBox()
        self.spin_rotate.setObjectName("stInput")
        self.spin_rotate.setRange(datalog.MIN_ROTATE_MB, datalog.MAX_ROTATE_MB)
        self.spin_rotate.setValue(50)
        self.spin_rotate.setSuffix(self.ctx.t("unitMbSuffix"))
        self.spin_rotate.setFixedWidth(100)
        row2.addWidget(self.spin_rotate)

        self.chk_comma = QCheckBox(t("logDecimalComma"))
        self.chk_comma.setChecked(True)
        self.chk_comma.setStyleSheet(
            f"color:{c['text_1']}; background:transparent;")
        row2.addWidget(self.chk_comma)

        row2.addStretch()
        self.btn_start = QPushButton("  " + t("logStart"))
        self.btn_start.setObjectName("btnPrimary")
        self.btn_start.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_start.setIcon(icons.icon("play", c["accent_fg"], 14))
        self.btn_start.setIconSize(QSize(13, 13))
        self.btn_start.clicked.connect(self.toggle)
        row2.addWidget(self.btn_start)
        lo.addLayout(row2)

        # ── the body: what the file will contain / does contain ──
        head = QHBoxLayout()
        head.setSpacing(8)
        self.lbl_section = self._lbl(t("logColumns"), "mhTitle")
        head.addWidget(self.lbl_section)
        self.lbl_forecast = self._lbl("")
        head.addWidget(self.lbl_forecast)
        head.addStretch()
        lo.addLayout(head)

        self.table = QTableWidget(0, 4)
        self.table.horizontalHeader().setDefaultAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.table.setObjectName("scanTable")
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch)
        lo.addWidget(self.table, 1)

        self.lbl_empty = EmptyState("logfile", t("noMapTitle"), "")
        self.lbl_empty.apply_theme(self.ctx.theme_tokens())
        lo.addWidget(self.lbl_empty, 1)

        self.lbl_hint = QLabel(t("logHint"))
        self.lbl_hint.setObjectName("mhCrumb")
        self.lbl_hint.setWordWrap(True)
        lo.addWidget(self.lbl_hint)

        self.lbl_status = QLabel(t("logIdle"))
        self.lbl_status.setObjectName("mhCrumb")
        lo.addWidget(self.lbl_status)

    # ── the column plan (shown before a run) ─────────────────────────
    def refresh_columns(self):
        """Show exactly which columns the file will have.

        Checked BEFORE committing to an overnight run, because the column set
        is frozen when the file opens — discovering a missing register in the
        morning means the night is gone."""
        if self.running:
            return
        t = self.ctx.t
        self._columns = datalog.columns_for(self.get_registers() or [])
        self.lbl_section.setText(t("logColumns"))
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(
            ["#", t("address"), t("name"), t("dashUnit")])
        # Narrow columns for the short facts, the name takes the rest. (All
        # four used to stretch equally: a 350 px column for a row number.)
        hh = self.table.horizontalHeader()
        for col, mode in ((0, QHeaderView.ResizeMode.ResizeToContents),
                          (1, QHeaderView.ResizeMode.ResizeToContents),
                          (2, QHeaderView.ResizeMode.Stretch),
                          (3, QHeaderView.ResizeMode.ResizeToContents)):
            hh.setSectionResizeMode(col, mode)
        empty = not self._columns
        self.lbl_empty.setText(t("logNoProfile") if empty else "")
        self.lbl_empty.setVisible(empty)
        self.table.setVisible(not empty)
        self.table.setRowCount(len(self._columns))
        regs = {datatypes.reg_key(r): r for r in (self.get_registers() or [])
                if isinstance(r, dict) and "addr" in r}
        for i, (addr, _title) in enumerate(self._columns):
            reg = regs.get(addr, {})
            for col, text in enumerate((str(i + 1), datatypes.key_label(addr),
                                        str(reg.get("name", "")),
                                        str(reg.get("unit", "")))):
                it = QTableWidgetItem(text)
                it.setTextAlignment(Qt.AlignmentFlag.AlignCenter if col == 0
                                    else Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                if col == 1:                     # addresses are monospace everywhere
                    from gui_table import mono_font
                    it.setFont(mono_font(int(self.ctx.settings.get("font_size", 9))))
                self.table.setItem(i, col, it)
        self._update_forecast()

    def _update_forecast(self):
        """Rows and bytes per hour at the current period — the number that
        decides whether a run is a good idea before it starts."""
        if self.running or not self._columns:
            self.lbl_forecast.setText("")
            return
        per_hour = 3600_000 // max(1, self.spin_period.value())
        # ~10 bytes a cell plus the timestamp; deliberately a rough estimate,
        # and labelled as one.
        bytes_hour = per_hour * (24 + len(self._columns) * 10)
        self.lbl_forecast.setText(self.ctx.t("logForecast").format(
            n=len(self._columns), rows=per_hour,
            size=human_size(bytes_hour, self.ctx.lang)))

    # ── lifecycle ─────────────────────────────────────────────────────
    @property
    def running(self) -> bool:
        return self.writer is not None and self.writer.active

    def _browse(self):
        path, _ = QFileDialog.getSaveFileName(
            self, self.ctx.t("logFile"), self.ed_path.text(),
            "CSV (*.csv);;All files (*)")
        if path:
            self.ed_path.setText(path)

    def toggle(self):
        self.stop() if self.running else self.start()

    def _confirm_target(self, path: str) -> str:
        """The file to write to, or "" to cancel.

        The writer opens with "w": an existing file is REPLACED. One
        accidental second Start used to wipe an overnight log without a word,
        so an existing file now gets a question (a fresh name is the default
        answer)."""
        if not path or not os.path.exists(path):
            return path
        t = self.ctx.t
        choice = themed_message(
            self, self.ctx.theme, "warning", t("logExistsTitle"),
            t("logExistsText").format(name=os.path.basename(path)),
            [(t("cancel"), QMessageBox.ButtonRole.RejectRole, False),
             (t("logOverwrite"), QMessageBox.ButtonRole.DestructiveRole, False),
             (t("logNewName"), QMessageBox.ButtonRole.AcceptRole, True)])
        if choice == 1:
            return path
        if choice == 2:
            fresh = os.path.join(os.path.dirname(path) or os.path.expanduser("~"),
                                 datalog.timestamp_name())
            self.ed_path.setText(fresh)
            return fresh
        return ""

    def start(self):
        t = self.ctx.t
        columns = datalog.columns_for(self.get_registers() or [])
        if not columns:
            themed_info(self, self.ctx.theme, "info", t("logTitle"),
                        t("logNoProfile"))
            return
        path = self._confirm_target(self.ed_path.text().strip())
        if not path:
            return
        set_state(self.lbl_status, "")
        self.writer = datalog.LogWriter(
            path, columns,
            rotate_mb=self.spin_rotate.value(),
            decimal="," if self.chk_comma.isChecked() else ".",
            delimiter=";" if self.chk_comma.isChecked() else ",")
        if not self.writer.active:
            themed_info(self, self.ctx.theme, "error", t("errTitle"),
                        self.writer.last_error or "")
            self.writer = None
            return
        self._last_result = None
        self._columns = columns
        self._started_at = time.time()
        self._prepare_preview()
        self._timer.start(self.spin_period.value())
        self._set_running(True)
        self._tick()                       # first row immediately
        self._update_status()

    def stop(self):
        self._timer.stop()
        if self.writer is not None:
            self.writer.close()
            # Keep the result visible: "not logging" throws away the one
            # fact the operator wants after a long run.
            self._last_result = (self.writer.rows_written,
                                 os.path.basename(self.writer.base_path))
            self.writer = None
        self._next_default_path()
        self._set_running(False)
        self._update_status()
        self.refresh_columns()             # back to the plan view

    def _next_default_path(self):
        """If the path is still the auto-generated one, move it to a fresh
        timestamped name so the next Start begins a NEW file."""
        current = self.ed_path.text().strip()
        if current == self._auto_path:
            self._auto_path = os.path.join(os.path.dirname(current),
                                           datalog.timestamp_name())
            if self._auto_path == current:          # same second: add a part
                root, ext = os.path.splitext(current)
                self._auto_path = f"{root}_2{ext}"
            self.ed_path.setText(self._auto_path)

    def _set_running(self, on: bool):
        t, c = self.ctx.t, self.ctx.theme_tokens()
        self.btn_start.setText("  " + (t("logStop") if on else t("logStart")))
        self.btn_start.setIcon(icons.icon("stop" if on else "play",
                                          c["accent_fg"], 14))
        for w in (self.ed_path, self.btn_browse, self.spin_period,
                  self.spin_rotate, self.chk_comma):
            w.setEnabled(not on)           # the column set is fixed while open

    # ── live preview (shown during a run) ────────────────────────────
    def _prepare_preview(self):
        t = self.ctx.t
        self.lbl_section.setText(t("logLive"))
        self.lbl_forecast.setText("")
        self.lbl_empty.setVisible(False)
        self.table.setVisible(True)
        self.table.setColumnCount(1 + len(self._columns))
        self.table.setHorizontalHeaderLabels(
            # «timestamp» is the CSV column name; on screen it is just time.
            [t("time")] + [title for _addr, title in self._columns])
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch)
        self.table.setRowCount(0)

    def _append_preview(self, values: dict):
        """Newest row on TOP. During a long run the interesting row is the one
        that just arrived, and scrolling to the bottom of 40 000 rows to find
        it is not monitoring."""
        self.table.insertRow(0)
        cells = [time.strftime("%H:%M:%S")] + [
            "" if values.get(addr) is None else str(values.get(addr))
            for addr, _title in self._columns]
        for col, text in enumerate(cells):
            it = QTableWidgetItem(text)
            it.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(0, col, it)
        while self.table.rowCount() > PREVIEW_ROWS:
            self.table.removeRow(self.table.rowCount() - 1)

    def _tick(self):
        if self.writer is None:
            return
        values = self.get_values() or {}
        if not self.writer.write_row(values):
            # Disk full, file locked by Excel… stop cleanly and say why.
            self._timer.stop()
            err = self.writer.last_error or ""
            self.writer = None
            self._set_running(False)
            self.lbl_status.setText(err)
            set_state(self.lbl_status, "error")
            return
        self._append_preview(values)
        self._update_status()

    def _file_size(self) -> int:
        try:
            return os.path.getsize(self.writer.current_path)
        except (OSError, AttributeError, TypeError):
            return 0               # rotated away or not flushed yet — not news

    def _update_status(self):
        t = self.ctx.t
        if self.writer is None:
            if self.lbl_status.property("state") == "error":
                return
            if self._last_result:
                rows, name = self._last_result
                self.lbl_status.setText(
                    t("logStopped").format(rows=rows, name=name))
            else:
                self.lbl_status.setText(t("logIdle"))
            return
        self.lbl_status.setText(t("logRunning").format(
            rows=self.writer.rows_written,
            parts=self.writer.part,
            size=human_size(self._file_size(), self.ctx.lang),
            elapsed=human_elapsed(time.time() - self._started_at),
            name=os.path.basename(self.writer.current_path)))

    # ── app plumbing ──────────────────────────────────────────────────
    def stop_if_running(self):
        if self.running:
            self.stop()

    def apply_settings(self):
        self.lbl_empty.apply_theme(self.ctx.theme_tokens())
        self.btn_browse.setIcon(icons.icon(
            "folder", self.ctx.theme_tokens()["text_2"], 15))
        self.refresh_columns()

    def retranslate(self, t):
        self.lbl_empty.set_content(title=t("noMapTitle"))
        self._set_running(self.running)
        self.lbl_file.setText(t("logFile"))
        self.btn_browse.setToolTip(t("logChoose"))
        self.lbl_every.setText(t("logEvery"))
        self.spin_period.setSuffix(t("unitMsSuffix"))
        self.spin_rotate.setSuffix(t("unitMbSuffix"))
        self.lbl_rotate.setText(t("logRotate"))
        self.chk_comma.setText(t("logDecimalComma"))
        self.lbl_hint.setText(t("logHint"))
        if self.running:
            self.lbl_section.setText(t("logLive"))
        else:
            self.refresh_columns()
        if self.lbl_status.property("state") != "error":
            self._update_status()

    def showEvent(self, e):
        # The column plan follows the register map; refreshing on show keeps
        # it right however the map changed while this page was hidden.
        if not self.running:
            self.refresh_columns()
        super().showEvent(e)
