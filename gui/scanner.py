# gui/scanner.py
"""Bus scanner view — find devices on the line / live registers on a device.

Runs a ScannerWorker (scanner_engine.py) which enqueues "probe" ops onto the
ModbusCore sync channel — the port stays owned by the core thread. Requires an
open connection; scan speed = the response timeout from Settings (silent IDs
each cost a full timeout)."""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QSpinBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QProgressBar, QAbstractItemView,
)
from PyQt6.QtCore import Qt, QSize

from gui import icons
from gui.widgets import EmptyState, EmptyOverlay, Segmented
from gui.qt_utils import later
from gui.dialogs import themed_info
from gui.qt_utils import set_state
from core.scanner_engine import ScannerWorker


class ScannerView(QWidget):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self._worker: ScannerWorker | None = None
        # Last finished scan, so a language switch can re-render the summary
        # instead of replacing it with "ready".
        self._last_result: tuple | None = None
        self._status_is_result = False
        self.setObjectName("scannerView")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._build_ui()

    # ── UI ────────────────────────────────────────────────────────────
    def _spin(self, lo, hi, val, width=76) -> QSpinBox:
        sp = QSpinBox()
        sp.setObjectName("stInput")
        sp.setRange(lo, hi)
        sp.setValue(val)
        sp.setFixedWidth(width)
        return sp

    def _build_ui(self):
        t = self.ctx.t
        lo = QVBoxLayout(self)
        lo.setContentsMargins(14, 10, 14, 10)
        lo.setSpacing(10)

        bar = QHBoxLayout()
        bar.setSpacing(10)

        self.seg_mode = Segmented(
            [("devices", t("scanDevices")), ("registers", t("scanRegisters"))],
            "devices")
        self.seg_mode.valueChanged.connect(self._on_mode_changed)
        bar.addWidget(self.seg_mode)

        self.lbl_from = QLabel(t("scanFrom"))
        self.lbl_from.setObjectName("mhCrumb")
        self.spin_from = self._spin(0, 65535, 1)
        self.lbl_to = QLabel(t("scanTo"))
        self.lbl_to.setObjectName("mhCrumb")
        self.spin_to = self._spin(0, 65535, 32)
        bar.addWidget(self.lbl_from)
        bar.addWidget(self.spin_from)
        bar.addWidget(self.lbl_to)
        bar.addWidget(self.spin_to)

        self.lbl_sid = QLabel(self.ctx.t("slaveIdLbl"))
        self.lbl_sid.setObjectName("mhCrumb")
        self.spin_sid = self._spin(1, 247, int(self.ctx.settings.get("slave_id", 10)))
        bar.addWidget(self.lbl_sid)
        bar.addWidget(self.spin_sid)

        bar.addStretch()

        self.btn_start = QPushButton("  " + t("scanStart"))
        self.btn_start.setObjectName("btnPrimary")
        self.btn_start.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_start.setIcon(icons.icon(
            "play", self.ctx.theme_tokens()["accent_fg"], 14))
        self.btn_start.setIconSize(QSize(13, 13))
        self.btn_start.clicked.connect(self._toggle_scan)
        bar.addWidget(self.btn_start)
        lo.addLayout(bar)

        # Only on screen while a scan is running. An empty groove is still a
        # filled bar in a colour that is not the background, so at rest it
        # read as a stray grey stripe under the mode switch rather than as a
        # progress indicator at 0 %.
        self.progress = QProgressBar()
        self.progress.setObjectName("scanProgress")
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(4)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setVisible(False)
        lo.addWidget(self.progress)

        self.table = QTableWidget(0, 3)
        self.table.horizontalHeader().setDefaultAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.table.setObjectName("scanTable")
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        lo.addWidget(self.table, 1)
        self.empty = EmptyState("radar", t("scanEmptyTitle"), t("scanEmptyBody"))
        # Outline, not filled: the toolbar right above already carries the
        # same action as the page's one accent button.
        self.empty.add_action(t("scanStart"), self._toggle_scan)
        self.empty.apply_theme(self.ctx.theme_tokens())
        self._empty_ov = EmptyOverlay(
            self.table, self.empty,
            when=lambda: not (self._worker and self._worker.isRunning()))

        self.lbl_status = QLabel(t("scanIdle"))
        self.lbl_status.setObjectName("mhCrumb")
        lo.addWidget(self.lbl_status)

        self._on_mode_changed(self.seg_mode.value())

    # ── mode / headers ────────────────────────────────────────────────
    def _on_mode_changed(self, mode, clear: bool = True):
        t = self.ctx.t
        devices = mode == "devices"
        self.lbl_sid.setVisible(not devices)
        self.spin_sid.setVisible(not devices)
        if devices:
            self.spin_from.setRange(1, 247)
            self.spin_to.setRange(1, 247)
            if self.spin_to.value() > 247:
                self.spin_to.setValue(247)
            headers = ["Slave ID", t("scanState"), t("scanTime")]
        else:
            self.spin_from.setRange(0, 65535)
            self.spin_to.setRange(0, 65535)
            headers = [t("address"), t("current"), t("scanTime")]
        if clear:
            # Only a genuine mode switch invalidates the rows; retranslating
            # must not throw away a finished scan.
            self.table.setRowCount(0)
        self.table.setHorizontalHeaderLabels(headers)

    # ── scan lifecycle ────────────────────────────────────────────────
    def _toggle_scan(self):
        if self._worker is not None and self._worker.isRunning():
            self._worker.request_stop()
            return
        if self._worker is not None:
            # The previous thread may still be unwinding; two workers on one
            # port produce phantom timeouts.
            self._worker.wait(2000)
        core = self.ctx.core
        if not core.is_running:
            themed_info(self, self.ctx.theme, "warning",
                        self.ctx.t("scanNotConnectedTitle"),
                        self.ctx.t("scanNotConnectedText"))
            return
        start, end = self.spin_from.value(), self.spin_to.value()
        if end < start:
            start, end = end, start
        self.table.setRowCount(0)
        self.progress.setValue(0)
        self.progress.setVisible(True)
        later(0, self, self._empty_ov.refresh)   # once the worker is running
        mode = self.seg_mode.value()
        self._worker = ScannerWorker(core, mode, start, end,
                                     slave_id=self.spin_sid.value())
        self._worker.progress.connect(self._on_progress)
        self._worker.found.connect(self._on_found)
        self._worker.finished_scan.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.start()
        self.btn_start.setText("  " + self.ctx.t("scanStop"))
        self.btn_start.setIcon(icons.icon(
            "stop", self.ctx.theme_tokens()["accent_fg"], 14))
        self._status_is_result = False
        set_state(self.lbl_status, "")
        self.lbl_status.setText(self.ctx.t("scanRunning"))

    def _on_error(self, msg: str):
        self._status_is_result = False
        self.lbl_status.setText(msg)
        set_state(self.lbl_status, "error")

    def _on_progress(self, done, total):
        self.progress.setValue(int(done * 100 / max(1, total)))

    def _on_found(self, hit: dict):
        t = self.ctx.t
        row = self.table.rowCount()
        self.table.insertRow(row)
        if hit["mode"] == "devices":
            c0 = str(hit["id"])
            c1 = t("scanAlive") if hit["state"] == "alive" else t("scanException")
        else:
            c0 = f"0x{hit['addr']:04X}"
            c1 = "—" if hit.get("value") is None else str(hit["value"])
        cells = [c0, c1, f"{hit['ms']:.0f}{t('unitMsSuffix')}"]
        for col, text in enumerate(cells):
            it = QTableWidgetItem(text)
            it.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(row, col, it)

    def _on_finished(self, hits, total, seconds):
        self.btn_start.setText("  " + self.ctx.t("scanStart"))
        self.btn_start.setIcon(icons.icon(
            "play", self.ctx.theme_tokens()["accent_fg"], 14))
        self.progress.setValue(100)
        self.progress.setVisible(False)     # the result line carries the news
        later(0, self, self._empty_ov.refresh)
        if self.lbl_status.property("state") == "error":
            return                          # keep the reason it stopped
        self._last_result = (hits, total, seconds)
        self._status_is_result = True
        self.lbl_status.setText(
            self.ctx.t("scanDone").format(hits=hits, total=total,
                                          sec=f"{seconds:.1f}"))

    def stop_if_running(self):
        if self._worker is not None and self._worker.isRunning():
            self._worker.request_stop()
            self._worker.wait(2000)

    # ── app plumbing ──────────────────────────────────────────────────
    def apply_settings(self):
        self.empty.apply_theme(self.ctx.theme_tokens())
        running = bool(self._worker and self._worker.isRunning())
        self.btn_start.setIcon(icons.icon(
            "stop" if running else "play",
            self.ctx.theme_tokens()["accent_fg"], 14))

    def retranslate(self, t):
        self.btn_start.setText("  " + (t("scanStop") if (
            self._worker and self._worker.isRunning()) else t("scanStart")))
        self.lbl_from.setText(t("scanFrom"))
        self.lbl_to.setText(t("scanTo"))
        self.empty.set_content(t("scanEmptyTitle"), t("scanEmptyBody"))
        self.empty.buttons[0].setText(t("scanStart"))
        self.lbl_sid.setText(t("slaveIdLbl"))
        # Never overwrite a live/finished status line with "ready".
        running = bool(self._worker and self._worker.isRunning())
        if self.lbl_status.property("state") == "error":
            pass                            # an error stays until the next scan
        elif running:
            self.lbl_status.setText(t("scanRunning"))
        elif self._status_is_result and self._last_result:
            hits, total, seconds = self._last_result
            self.lbl_status.setText(t("scanDone").format(
                hits=hits, total=total, sec=f"{seconds:.1f}"))
        else:
            self.lbl_status.setText(t("scanIdle"))
        self.seg_mode._buttons["devices"].setText(t("scanDevices"))
        self.seg_mode._buttons["registers"].setText(t("scanRegisters"))
        self._on_mode_changed(self.seg_mode.value(), clear=False)

    # ── guide (F1 / Справка) ──────────────────────────────────────────
    def _show_guide(self):
        """Coach marks for the scanner. Reachable from F1 while this view is
        the active page — the feature is useless if nobody knows that an
        exception response still counts as a found device."""
        from gui.onboarding import OnboardingGuide
        ru = self.ctx.lang == "ru"
        L = (lambda r, e: r) if ru else (lambda r, e: e)
        steps = [
            {"target": None,
             "title": L("Сканер шины", "Bus scanner"),
             "body": L(
                 "Находит, кто вообще есть на линии, и какие адреса отвечают. "
                 "Работает через уже открытый порт — сначала «Подключить» (F5).",
                 "Finds who is on the line and which addresses answer. It works "
                 "through the already-open port — press Connect (F5) first.")},
            {"target": self.seg_mode,
             "title": L("Два режима", "Two modes"),
             "body": L(
                 "«Устройства» — перебор slave ID 1…247. «Регистры» — перебор "
                 "адресов у ОДНОГО устройства.",
                 "Devices — sweep slave IDs 1…247. Registers — sweep addresses "
                 "on ONE device.")},
            {"target": [self.spin_from, self.spin_to],
             "title": L("Диапазон", "Range"),
             "body": L(
                 "Молчащий адрес стоит целый таймаут ответа, поэтому широкий "
                 "диапазон на медленной скорости идёт долго. Таймаут — в "
                 "Настройках → Опрос.",
                 "A silent address costs a full response timeout, so a wide "
                 "range at a low baud rate takes a while. The timeout lives in "
                 "Settings → Polling.")},
            {"target": self.table,
             "title": L("Что значит «Жив (исключение)»",
                        "What \"alive (exception)\" means"),
             "body": L(
                 "Устройство ответило ошибкой Modbus — значит оно на линии и "
                 "разобрало запрос, просто не отдаёт этот адрес. Это НАХОДКА, "
                 "а не сбой.",
                 "The device replied with a Modbus exception — so it is on the "
                 "line and decoded the request, it just will not serve that "
                 "address. That is a HIT, not a failure.")},
            {"target": self.btn_start,
             "title": L("Старт и стоп", "Start and stop"),
             "body": L(
                 "Скан идёт в отдельном потоке и не блокирует программу. "
                 "Повторное нажатие останавливает перебор.",
                 "The scan runs on its own thread and never freezes the app. "
                 "Press again to stop.")},
        ]
        g = OnboardingGuide(self.window(), steps, self.ctx.theme,
                            self.ctx.settings.get("accent"), self.ctx.lang)
        g.show_guide()
