# gui/scanner.py
"""Bus scanner view — find devices on the line / live registers on a device /
Modbus TCP devices on the network.

«Устройства» and «Регистры» run a ScannerWorker (scanner_engine.py) which
enqueues "probe" ops onto the ModbusCore sync channel — the port stays owned
by the core thread. They need an open connection; scan speed = the response
timeout from Settings (silent IDs each cost a full timeout). Over TCP the
device sweep covers unit ids 0…255.

«Сеть (TCP)» runs a NetScanWorker (netscan.py): many IP addresses at once,
each with its own short-lived socket — no connection needed. A double-click
on a found device hands it to the connection card."""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QSpinBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QProgressBar, QAbstractItemView,
    QLineEdit, QComboBox, QAbstractSpinBox,
)
from PyQt6.QtCore import Qt, QSize, pyqtSignal

from core import netscan, transports
from gui import icons
from gui.widgets import EmptyState, EmptyOverlay, Segmented
from gui.qt_utils import later
from gui.dialogs import themed_info
from gui.qt_utils import set_state
from core.scanner_engine import ScannerWorker


class ScannerView(QWidget):
    # A device found on the network, double-clicked: a link for the card.
    connect_requested = pyqtSignal(dict)

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self._worker = None                 # ScannerWorker | NetScanWorker
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

    def _crumb(self, text="") -> QLabel:
        lb = QLabel(text)
        lb.setObjectName("mhCrumb")
        return lb

    def _build_ui(self):
        t = self.ctx.t
        lo = QVBoxLayout(self)
        lo.setContentsMargins(14, 10, 14, 10)
        lo.setSpacing(10)

        bar = QHBoxLayout()
        bar.setSpacing(10)

        self.seg_mode = Segmented(
            [("devices", t("scanDevices")), ("registers", t("scanRegisters")),
             ("network", t("scanNetwork"))],
            "devices")
        self.seg_mode.valueChanged.connect(self._on_mode_changed)
        bar.addWidget(self.seg_mode)

        # Network mode: a local /24 from the list (the likeliest LAN
        # first), or «Свой диапазон» which shows the from / to fields.
        self.cb_subnet = QComboBox()
        self.cb_subnet.setObjectName("stInput")
        self.cb_subnet.setFixedWidth(170)
        self.cb_subnet.activated.connect(self._on_subnet)
        bar.addWidget(self.cb_subnet)

        self.lbl_from = self._crumb(t("scanFrom"))
        self.spin_from = self._spin(0, 65535, 1)
        self.lbl_to = self._crumb(t("scanTo"))
        self.spin_to = self._spin(0, 65535, 32)
        bar.addWidget(self.lbl_from)
        bar.addWidget(self.spin_from)
        # The network range sits between the same "from" / "to" words.
        self.ed_ip_from = QLineEdit()
        self.ed_ip_to = QLineEdit()
        for ed in (self.ed_ip_from, self.ed_ip_to):
            ed.setObjectName("stInput")
            ed.setFixedWidth(128)
            ed.setPlaceholderText("192.168.1.1")
            ed.textEdited.connect(lambda _t, e=ed: set_state(e, ""))
        first, last = netscan.suggest_range()
        self.ed_ip_from.setText(first)
        self.ed_ip_to.setText(last)
        bar.addWidget(self.ed_ip_from)
        bar.addWidget(self.lbl_to)
        bar.addWidget(self.spin_to)
        bar.addWidget(self.ed_ip_to)

        self.lbl_net_port = self._crumb(t("connTcpPort"))
        self.spin_net_port = self._spin(1, 65535, transports.DEFAULT_TCP_PORT, width=64)
        self.spin_net_port.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        bar.addWidget(self.lbl_net_port)
        bar.addWidget(self.spin_net_port)

        self.lbl_sid = self._crumb(self.ctx.t("slaveIdLbl"))
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
        self.table.cellDoubleClicked.connect(self._on_row_activated)
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

        self.lbl_status = self._crumb(t("scanIdle"))
        lo.addWidget(self.lbl_status)

        self._fill_subnets()
        self._on_mode_changed(self.seg_mode.value())

    def _fill_subnets(self):
        """Local /24 networks to pick from (the likeliest LAN first), then
        «Свой диапазон»."""
        self.cb_subnet.clear()
        seen = set()
        for ip in netscan.local_ipv4():
            first, last = netscan.subnet_range(ip)
            if first in seen:
                continue
            seen.add(first)
            net = first.rsplit(".", 1)[0] + ".0/24"
            self.cb_subnet.addItem(net, (first, last))
        self.cb_subnet.addItem(self.ctx.t("scanNetCustom"), None)
        self.cb_subnet.setCurrentIndex(0)
        self._on_subnet(0)

    def _custom_range(self) -> bool:
        return self.cb_subnet.currentData() is None

    def _on_subnet(self, index: int):
        rng = self.cb_subnet.itemData(index)
        if rng:
            self.ed_ip_from.setText(rng[0])
            self.ed_ip_to.setText(rng[1])
        if self.seg_mode.value() == "network":
            self._on_mode_changed("network", clear=False)

    # ── mode / headers ────────────────────────────────────────────────
    def show_network_mode(self):
        """«Найти в сети» from the connection card."""
        self.seg_mode.setValue("network")

    def _on_mode_changed(self, mode, clear: bool = True):
        t = self.ctx.t
        devices, net = mode == "devices", mode == "network"
        self.lbl_sid.setVisible(mode == "registers")
        self.spin_sid.setVisible(mode == "registers")
        custom = net and self._custom_range()
        for w in (self.spin_from, self.spin_to):
            w.setVisible(not net)
        for w in (self.lbl_from, self.lbl_to):
            w.setVisible(not net or custom)
        for w in (self.ed_ip_from, self.ed_ip_to):
            w.setVisible(custom)
        for w in (self.cb_subnet, self.lbl_net_port, self.spin_net_port):
            w.setVisible(net)
        if devices:
            lo_id, hi_id = transports.id_range(self.ctx.settings)
            self.spin_from.setRange(lo_id, hi_id)
            self.spin_to.setRange(lo_id, hi_id)
            if self.spin_to.value() > hi_id:
                self.spin_to.setValue(hi_id)
            headers = [t("scanUnitId") if transports.is_network(self.ctx.settings)
                       else "Slave ID", t("scanState"), t("scanTime")]
        elif net:
            headers = [t("scanNetHost"), t("scanNetAnswer"), t("scanTime")]
        else:
            self.spin_from.setRange(0, 65535)
            self.spin_to.setRange(0, 65535)
            headers = [t("address"), t("current"), t("scanTime")]
        if net:
            self.empty.set_content(t("scanNetEmptyTitle"), t("scanNetEmptyBody"))
        else:
            self.empty.set_content(t("scanEmptyTitle"), t("scanEmptyBody"))
        if clear:
            # Only a genuine mode switch invalidates the rows; retranslating
            # must not throw away a finished scan.
            self.table.setRowCount(0)
            self._status_is_result = False
            if not (self._worker and self._worker.isRunning()):
                set_state(self.lbl_status, "")
                self.lbl_status.setText(t("scanNetIdle" if net else "scanIdle"))
        self.table.setHorizontalHeaderLabels(headers)
        later(0, self, self._empty_ov.refresh)

    # ── scan lifecycle ────────────────────────────────────────────────
    def _toggle_scan(self):
        if self._worker is not None and self._worker.isRunning():
            self._worker.request_stop()
            return
        if self._worker is not None:
            # The previous thread may still be unwinding; two workers on one
            # port produce phantom timeouts.
            self._worker.wait(2000)
        mode = self.seg_mode.value()
        if mode == "network":
            worker = self._network_worker()
            if worker is None:
                return
        else:
            core = self.ctx.core
            if not core.is_running:
                themed_info(self, self.ctx.theme, "warning",
                            self.ctx.t("scanNotConnectedTitle"),
                            self.ctx.t("scanNotConnectedText"))
                return
            start, end = self.spin_from.value(), self.spin_to.value()
            if end < start:
                start, end = end, start
            worker = ScannerWorker(core, mode, start, end,
                                   slave_id=self.spin_sid.value())
            worker.error.connect(self._on_error)
        self.table.setRowCount(0)
        self.progress.setValue(0)
        self.progress.setVisible(True)
        later(0, self, self._empty_ov.refresh)   # once the worker is running
        self._worker = worker
        worker.progress.connect(self._on_progress)
        worker.found.connect(self._on_found)
        worker.finished_scan.connect(self._on_finished)
        worker.start()
        self.btn_start.setText("  " + self.ctx.t("scanStop"))
        self.btn_start.setIcon(icons.icon(
            "stop", self.ctx.theme_tokens()["accent_fg"], 14))
        self._status_is_result = False
        set_state(self.lbl_status, "")
        self.lbl_status.setText(self.ctx.t("scanRunning"))

    def _network_worker(self):
        try:
            hosts = netscan.hosts_between(self.ed_ip_from.text(), self.ed_ip_to.text())
        except ValueError:
            for ed in (self.ed_ip_from, self.ed_ip_to):
                set_state(ed, "error")
            self._on_error(self.ctx.t("scanNetBadRange"))
            return None
        return netscan.NetScanWorker(hosts, self.spin_net_port.value())

    def _on_error(self, msg: str):
        self._status_is_result = False
        self.lbl_status.setText(msg)
        set_state(self.lbl_status, "error")

    def _on_progress(self, done, total):
        self.progress.setValue(int(done * 100 / max(1, total)))

    def _on_found(self, hit: dict):
        t = self.ctx.t
        mode = hit.get("mode")
        if "ip" in hit:
            c0 = hit["ip"] if hit["port"] == transports.DEFAULT_TCP_PORT \
                else f"{hit['ip']}:{hit['port']}"
            if hit["state"] == "modbus":
                c1 = (t("scanNetModbusExc").format(unit=hit["unit"], code=hit["exception"])
                      if hit["exception"] else t("scanNetModbus").format(unit=hit["unit"]))
            else:
                c1 = t("scanNetOpen")
        elif mode == "devices":
            c0 = str(hit["id"])
            c1 = t("scanAlive") if hit["state"] == "alive" else t("scanException")
        else:
            c0 = f"0x{hit['addr']:04X}"
            c1 = "—" if hit.get("value") is None else str(hit["value"])
        cells = [c0, c1, f"{hit['ms']:.0f}{t('unitMsSuffix')}"]
        row = self._row_for(hit)
        self.table.insertRow(row)
        for col, text in enumerate(cells):
            it = QTableWidgetItem(text)
            it.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            if col == 0:
                it.setData(Qt.ItemDataRole.UserRole, hit)
            self.table.setItem(row, col, it)

    def _row_for(self, hit: dict) -> int:
        """Network hits arrive in completion order; keep them sorted by IP."""
        if "ip" not in hit:
            return self.table.rowCount()
        key = tuple(int(p) for p in hit["ip"].split("."))
        for row in range(self.table.rowCount()):
            other = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole) or {}
            ip = other.get("ip")
            if ip and tuple(int(p) for p in ip.split(".")) > key:
                return row
        return self.table.rowCount()

    def _on_row_activated(self, row: int, _col: int):
        it = self.table.item(row, 0)
        hit = it.data(Qt.ItemDataRole.UserRole) if it is not None else None
        if not hit or "ip" not in hit:
            return
        link = {"transport": "tcp", "host": hit["ip"], "tcp_port": hit["port"]}
        if hit.get("unit") is not None:
            link["slave_id"] = hit["unit"]
        self.connect_requested.emit(link)

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
        self._render_result()

    def _render_result(self):
        hits, total, seconds = self._last_result
        t = self.ctx.t
        text = t("scanDone").format(hits=hits, total=total, sec=f"{seconds:.1f}")
        if hits and self.seg_mode.value() == "network":
            text += "  ·  " + t("scanNetHint")
        self.lbl_status.setText(text)

    def stop_if_running(self):
        if self._worker is not None and self._worker.isRunning():
            self._worker.request_stop()
            self._worker.wait(2000)

    # ── app plumbing ──────────────────────────────────────────────────
    def showEvent(self, e):
        if self.seg_mode.value() == "devices" and not (
                self._worker and self._worker.isRunning()):
            self._on_mode_changed("devices", clear=False)   # the ID range follows the link
        super().showEvent(e)

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
        self.lbl_net_port.setText(t("connTcpPort"))
        self.cb_subnet.setItemText(self.cb_subnet.count() - 1, t("scanNetCustom"))
        self.empty.buttons[0].setText(t("scanStart"))
        self.lbl_sid.setText(t("slaveIdLbl"))
        # Never overwrite a live/finished status line with "ready".
        running = bool(self._worker and self._worker.isRunning())
        if self.lbl_status.property("state") == "error":
            pass                            # an error stays until the next scan
        elif running:
            self.lbl_status.setText(t("scanRunning"))
        elif self._status_is_result and self._last_result:
            self._render_result()
        else:
            self.lbl_status.setText(t("scanNetIdle" if self.seg_mode.value() == "network"
                                      else "scanIdle"))
        self.seg_mode._buttons["devices"].setText(t("scanDevices"))
        self.seg_mode._buttons["registers"].setText(t("scanRegisters"))
        self.seg_mode._buttons["network"].setText(t("scanNetwork"))
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
             "title": L("Сканер", "Scanner"),
             "body": L(
                 "Находит, кто вообще есть на линии или в сети, и какие адреса "
                 "отвечают. «Устройства» и «Регистры» работают через уже "
                 "открытое подключение — сначала «Подключить» (F5).",
                 "Finds who is on the line or the network and which addresses "
                 "answer. Devices and Registers work through the open "
                 "connection — press Connect (F5) first.")},
            {"target": self.seg_mode,
             "title": L("Три режима", "Three modes"),
             "body": L(
                 "«Устройства» — перебор адресов 1…247 (по TCP — Unit ID "
                 "0…255). «Регистры» — перебор адресов у ОДНОГО устройства. "
                 "«Сеть (TCP)» — поиск приборов Modbus TCP по IP-адресам, "
                 "подключение не нужно.",
                 "Devices — sweep addresses 1…247 (unit IDs 0…255 over TCP). "
                 "Registers — sweep addresses on ONE device. Network (TCP) — "
                 "find Modbus TCP devices by IP address, no connection "
                 "needed.")},
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
