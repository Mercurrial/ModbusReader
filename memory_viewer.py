import struct

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTableWidget,
    QTableWidgetItem, QLabel, QSpinBox, QComboBox,
    QPushButton, QCheckBox, QSplitter, QWidget, QAbstractItemView,
)
from PyQt6.QtCore import Qt
import pyqtgraph as pg

import datatypes
import icons
from theme_manager import get_theme
from gui_widgets import RowNumberHeader


class MemoryViewerDialog(QDialog):

    def __init__(self, addr, length, name, ctx=None,
                 profile_name="", parent=None):
        super().__init__(
            parent,
            Qt.WindowType.Window
            | Qt.WindowType.WindowMinMaxButtonsHint
            | Qt.WindowType.WindowCloseButtonHint,
        )
        # The translator must exist BEFORE the title uses it. The title line
        # used to come first, so opening a memory area raised AttributeError
        # and the viewer could not be opened at all.
        self.ctx          = ctx
        self.t            = ctx.t if ctx else (lambda k: k)
        self.setWindowTitle(self.t("memTitle").format(
            name=f"{name} ({datatypes.key_label(addr)})", words=length))
        self.resize(1100, 650)

        self.addr         = addr
        self.length       = length
        self.modbus_core  = ctx.core if ctx else None
        self.raw_data     = []

        self.app_settings = ctx.settings if ctx else {}
        self.config_key   = f"{profile_name}_0x{addr:02X}" if profile_name else ""

        # Theme colors
        c = get_theme(self.app_settings.get("theme", "Dark"))
        self._c = c

        self._init_ui()
        self._apply_theme()
        self.load_viewer_config()

        if self.modbus_core and self.modbus_core.is_running:
            self.request_real_data()
        else:
            self._set_status(self.t("memOffline"), error=True)

    # ──────────────────────────────────────── UI

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # ── Toolbar row ───────────────────────────────────────────
        ctrl = QHBoxLayout()
        ctrl.setSpacing(8)

        def lbl(text):
            l = QLabel(text)
            l.setStyleSheet(f"color: {self._c['text_3']}; font-size: 9pt;")
            return l

        ctrl.addWidget(lbl(self.t("memColumns") + ":"))
        self.spin_cols = QSpinBox()
        self.spin_cols.setRange(1, 16)
        self.spin_cols.setValue(1)
        self.spin_cols.setFixedWidth(72)
        self.spin_cols.setFixedHeight(30)
        ctrl.addWidget(self.spin_cols)

        ctrl.addSpacing(6)
        ctrl.addWidget(lbl(self.t("memLayout") + ":"))
        self.combo_layout = QComboBox()
        self.combo_layout.addItems([self.t("memInterleaved"),
                                    self.t("memBlocked")])
        self.combo_layout.setMinimumWidth(250)
        self.combo_layout.setFixedHeight(30)
        ctrl.addWidget(self.combo_layout)

        ctrl.addSpacing(6)
        ctrl.addWidget(lbl(self.t("memType") + ":"))
        self.combo_dtype = QComboBox()
        self.combo_dtype.addItems(["SHORT", "FLOAT", "LONG"])
        self.combo_dtype.setFixedWidth(96)
        self.combo_dtype.setFixedHeight(30)
        ctrl.addWidget(self.combo_dtype)

        ctrl.addSpacing(6)
        ctrl.addWidget(lbl(self.t("memByteOrder") + ":"))
        self.combo_endian = QComboBox()
        self.combo_endian.addItems([
            self.t("memOrderBig"), self.t("memOrderLittle"),
            self.t("memOrderWord"), self.t("memOrderByte"),
        ])
        self.combo_endian.setCurrentIndex(1)
        self.combo_endian.setMinimumWidth(210)
        self.combo_endian.setFixedHeight(30)
        ctrl.addWidget(self.combo_endian)

        ctrl.addStretch()

        self.btn_refresh = QPushButton("  " + self.t("memRequest"))
        self.btn_refresh.setObjectName("btnPrimary")
        self.btn_refresh.setIcon(icons.icon("download", self._c["accent_fg"], 15))
        self.btn_refresh.setFixedHeight(30)
        self.btn_refresh.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_refresh.clicked.connect(self.request_real_data)
        ctrl.addWidget(self.btn_refresh)

        layout.addLayout(ctrl)

        # ── Status label ──────────────────────────────────────────
        self.status_label = QLabel("")
        self.status_label.setStyleSheet(f"color: {self._c['text_3']}; font-size: 8pt;")
        layout.addWidget(self.status_label)

        # ── Channel checkboxes ────────────────────────────────────
        check_container = QWidget()
        self.check_layout = QHBoxLayout(check_container)
        self.check_layout.setContentsMargins(0, 0, 0, 2)
        self.check_layout.setSpacing(6)
        self.checkboxes = []
        for i in range(16):
            chk = QCheckBox(self.t("memChannel").format(n=i + 1))
            chk.setChecked(True)
            chk.stateChanged.connect(self.draw_plot)
            chk.hide()
            self.check_layout.addWidget(chk)
            self.checkboxes.append(chk)
        self.check_layout.addStretch()
        layout.addWidget(check_container)

        # ── Main splitter: table | plot ───────────────────────────
        splitter = QSplitter(Qt.Orientation.Horizontal)

        self.table = QTableWidget()
        # One channel used to be a 100 px column beside an empty slab.
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.table.setAlternatingRowColors(True)
        # Stripes, not stripes AND row lines; numbers on their own stripe.
        self.table.setProperty("zebra", "true")
        self.table.setVerticalHeader(RowNumberHeader(self.table))
        self.table.verticalHeader().setDefaultAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        splitter.addWidget(self.table)

        self.plot_widget = pg.PlotWidget()
        self.plot_widget.showGrid(x=True, y=True, alpha=0.2)
        self.plot_widget.addLegend()
        splitter.addWidget(self.plot_widget)

        splitter.setSizes([400, 640])
        layout.addWidget(splitter, 1)

        # ── Signal connections ────────────────────────────────────
        self.spin_cols.valueChanged.connect(self.update_view)
        self.combo_layout.currentIndexChanged.connect(self.update_view)
        self.combo_dtype.currentIndexChanged.connect(self.update_view)
        self.combo_endian.currentIndexChanged.connect(self.update_view)

    def _apply_theme(self):
        c = self._c
        self.plot_widget.setBackground(c["plot_bg"])
        for ax_name in ("left", "bottom"):
            ax = self.plot_widget.getAxis(ax_name)
            ax.setPen(pg.mkPen(c["plot_axis"]))
            ax.setTextPen(pg.mkPen(c["plot_text"]))

    def _set_status(self, text: str, error: bool = False, info: bool = False):
        if error:
            color = self._c["error"]
        elif info:
            color = self._c["g_1"]
        else:
            color = self._c["text_3"]
        self.status_label.setStyleSheet(f"color: {color}; font-size: 8pt;")
        self.status_label.setText(text)

    # ──────────────────────────────────────── config persistence

    def load_viewer_config(self):
        if not self.config_key:
            return
        cfg = self.app_settings.get("viewer_configs", {}).get(self.config_key)
        if not cfg:
            return

        self.spin_cols.blockSignals(True)
        self.spin_cols.setValue(cfg.get("cols", 1))
        self.spin_cols.blockSignals(False)

        self.combo_layout.setCurrentIndex(cfg.get("layout", 0))
        self.combo_dtype.setCurrentIndex(cfg.get("dtype", 0))
        self.combo_endian.setCurrentIndex(cfg.get("endian", 1))

        checks = cfg.get("checks", [])
        for i, chk in enumerate(self.checkboxes):
            if i < len(checks):
                chk.blockSignals(True)
                chk.setChecked(checks[i])
                chk.blockSignals(False)

    def closeEvent(self, event):
        if self.config_key and isinstance(self.app_settings, dict):
            self.app_settings.setdefault("viewer_configs", {})[self.config_key] = {
                "cols":   self.spin_cols.value(),
                "layout": self.combo_layout.currentIndex(),
                "dtype":  self.combo_dtype.currentIndex(),
                "endian": self.combo_endian.currentIndex(),
                "checks": [chk.isChecked() for chk in self.checkboxes],
            }
            if self.ctx is not None:
                self.ctx.save()
        super().closeEvent(event)

    # ──────────────────────────────────────── data acquisition

    def request_real_data(self):
        if self.modbus_core and self.modbus_core.is_running:
            self.btn_refresh.setEnabled(False)
            self.btn_refresh.setText(self.t("memLoading"))
            self._set_status(self.t("memFetching"), info=True)
            self.modbus_core.queue_array_read(self.addr, self.length)
        else:
            self._set_status(self.t("memNotConnected"), error=True)

    def set_real_data(self, word_list):
        self.btn_refresh.setEnabled(True)
        self.btn_refresh.setText(self.t("memRequest"))
        if not word_list:
            self._set_status(self.t("memNoAnswer"), error=True)
            return
        self._set_status(self.t("memLoaded").format(n=len(word_list)))
        self.raw_data = word_list
        self.update_view()

    # ──────────────────────────────────────── parsing

    def parse_raw_data(self, cols, layout_type, dtype, endianness):
        words_per_element = datatypes.read_count(dtype)
        total_elements    = len(self.raw_data) // words_per_element
        if total_elements < cols or total_elements == 0:
            return []

        parsed_1d = []
        for i in range(0, len(self.raw_data) - words_per_element + 1, words_per_element):
            chunk = self.raw_data[i:i + words_per_element]
            if words_per_element == 1:
                w0 = chunk[0]
                if endianness in (1, 3):
                    w0 = ((w0 & 0xFF) << 8) | (w0 >> 8)
                val = struct.unpack(">h", struct.pack(">H", w0))[0]
            else:
                w0, w1 = chunk[0], chunk[1]
                if endianness == 1:
                    w0 = ((w0 & 0xFF) << 8) | (w0 >> 8)
                    w1 = ((w1 & 0xFF) << 8) | (w1 >> 8)
                    w0, w1 = w1, w0
                elif endianness == 2:
                    w0, w1 = w1, w0
                elif endianness == 3:
                    w0 = ((w0 & 0xFF) << 8) | (w0 >> 8)
                    w1 = ((w1 & 0xFF) << 8) | (w1 >> 8)
                if dtype == "FLOAT":
                    val = struct.unpack(">f", struct.pack(">HH", w0, w1))[0]
                else:  # LONG
                    val = struct.unpack(">i", struct.pack(">HH", w0, w1))[0]
            parsed_1d.append(val)

        rows     = len(parsed_1d) // cols
        parsed_2d = []
        if layout_type == 0:  # interleaved
            for r in range(rows):
                parsed_2d.append([parsed_1d[r * cols + c] for c in range(cols)])
        else:                  # blocked
            for r in range(rows):
                parsed_2d.append([parsed_1d[c * rows + r] for c in range(cols)])
        return parsed_2d

    # ──────────────────────────────────────── render

    def update_view(self):
        cols        = self.spin_cols.value()
        layout_type = self.combo_layout.currentIndex()
        dtype       = self.combo_dtype.currentText()
        endianness  = self.combo_endian.currentIndex()

        data_2d = self.parse_raw_data(cols, layout_type, dtype, endianness)

        for i, chk in enumerate(self.checkboxes):
            chk.setVisible(i < cols)

        self.table.setRowCount(len(data_2d))
        self.table.setColumnCount(cols)
        self.table.setHorizontalHeaderLabels(
            [self.t("memChannel").format(n=i + 1) for i in range(cols)])

        from gui_table import mono_font
        mono = mono_font(self.app_settings.get("font_size", 9)
                         if isinstance(self.app_settings, dict) else 9)

        for r, row in enumerate(data_2d):
            for c, val in enumerate(row):
                text = f"{val:.4f}" if dtype == "FLOAT" else str(val)
                item = QTableWidgetItem(text)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                item.setFont(mono)
                self.table.setItem(r, c, item)

        self.parsed_data = data_2d
        self.draw_plot()

    def draw_plot(self):
        self.plot_widget.clear()
        if not hasattr(self, "parsed_data") or not self.parsed_data:
            return

        cols   = self.spin_cols.value()
        colors = self._c["plot_colors"]

        for c in range(cols):
            if self.checkboxes[c].isChecked():
                y_data = [row[c] for row in self.parsed_data]
                pen    = pg.mkPen(color=colors[c % len(colors)], width=2)
                self.plot_widget.plot(y_data, pen=pen,
                                      name=self.t("memChannel").format(n=c + 1))
