# gui/slave.py
"""Slave view — the app pretends to be a device (slave_core.py does the work).

Top bar: the port it listens on (its OWN port — one port, one owner), line
speed, the slave ID it answers to, an optional response delay, Start/Stop.
Body: the served register map with live, editable values (what the master
will read) and how often the master touched each register; beside it, the
exchange log.

The served map is a snapshot of the current register map, taken when the
view is shown and whenever the map changes while the server is stopped.
Values typed here are encoded with the SAME codecs the master side decodes
with, so a map read in master mode and served in slave mode always agree.
"""

import time

from PyQt6.QtCore import Qt, QSize, QDateTime
from PyQt6.QtGui import QColor, QIntValidator
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox,
    QSpinBox, QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QSplitter, QTextEdit,
)

from core import datatypes
from gui import icons
from gui.widgets import EmptyState
from core import transports
from gui.dialogs import themed_info
from gui.qt_utils import set_state
from core.slave_core import SlaveServer, SlaveStore

COL_ADDR, COL_NAME, COL_TYPE, COL_VALUE, COL_READS, COL_WRITES, COL_LAST = range(7)
_LOG_MAX = 500


class SlaveView(QWidget):
    def __init__(self, ctx, get_registers, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.get_registers = get_registers
        self._server: SlaveServer | None = None
        self.store = SlaveStore()
        self._row_of: dict[int, int] = {}
        self._counts = {"requests": 0, "answered": 0, "exceptions": 0, "ignored": 0}
        self._map_dirty = False
        self.setObjectName("slaveView")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._build_ui()
        self.retranslate(ctx.t)
        self.reload_map()

    # ── UI ────────────────────────────────────────────────────────────
    def _lbl(self, key=""):
        lb = QLabel(self.ctx.t(key) if key else "")
        lb.setObjectName("mhCrumb")
        return lb

    def _build_ui(self):
        s = self.ctx.settings
        lo = QVBoxLayout(self)
        lo.setContentsMargins(14, 10, 14, 10)
        lo.setSpacing(10)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.lbl_port = self._lbl()
        self.combo_port = QComboBox()
        self.combo_port.setObjectName("stInput")
        self.combo_port.setEditable(True)
        self.combo_port.setFixedWidth(120)
        self._fill_ports()
        self.lbl_baud = self._lbl()
        self.combo_baud = QComboBox()
        self.combo_baud.setObjectName("stInput")
        self.combo_baud.addItems(["1200", "2400", "4800", "9600", "19200",
                                  "38400", "57600", "115200", "230400"])
        self.combo_baud.setEditable(True)
        self.combo_baud.setValidator(QIntValidator(50, 4000000, self))
        self.combo_baud.setCurrentText(str(s.get("slave_baud") or s.get("baudrate", "115200")))
        self.combo_baud.setFixedWidth(100)
        self.lbl_sid = self._lbl()
        self.spin_sid = QSpinBox()
        self.spin_sid.setObjectName("stInput")
        self.spin_sid.setRange(1, 247)
        try:
            self.spin_sid.setValue(int(s.get("slave_sid") or s.get("slave_id", 1)))
        except (TypeError, ValueError):
            self.spin_sid.setValue(1)
        self.spin_sid.setFixedWidth(72)
        self.lbl_delay = self._lbl()
        self.spin_delay = QSpinBox()
        self.spin_delay.setObjectName("stInput")
        self.spin_delay.setRange(0, 5000)
        self.spin_delay.setSingleStep(10)
        self.spin_delay.setSuffix(self.ctx.t("unitMsSuffix"))
        try:
            self.spin_delay.setValue(int(s.get("slave_delay", 0)))
        except (TypeError, ValueError):
            pass
        self.spin_delay.setFixedWidth(92)
        for w in (self.lbl_port, self.combo_port, self.lbl_baud, self.combo_baud,
                  self.lbl_sid, self.spin_sid, self.lbl_delay, self.spin_delay):
            bar.addWidget(w)
        bar.addStretch(1)
        self.btn_reload = QPushButton()
        self.btn_reload.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_reload.clicked.connect(self.reload_map)
        bar.addWidget(self.btn_reload)
        self.btn_start = QPushButton()
        self.btn_start.setObjectName("btnPrimary")
        self.btn_start.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_start.setIconSize(QSize(13, 13))
        self.btn_start.clicked.connect(self.toggle)
        bar.addWidget(self.btn_start)
        lo.addLayout(bar)

        self.lbl_info = self._lbl()
        self.lbl_info.setWordWrap(True)
        lo.addWidget(self.lbl_info)

        split = QSplitter(Qt.Orientation.Horizontal)

        self.table = QTableWidget(0, 7)
        self.table.horizontalHeader().setDefaultAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.table.setObjectName("scanTable")
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked
                                   | QAbstractItemView.EditTrigger.EditKeyPressed
                                   | QAbstractItemView.EditTrigger.AnyKeyPressed)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(COL_NAME, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(COL_VALUE, QHeaderView.ResizeMode.Interactive)
        self.table.setColumnWidth(COL_VALUE, 140)
        self.table.cellChanged.connect(self._on_cell_changed)
        split.addWidget(self.table)

        self.log = QTextEdit()
        self.log.setObjectName("txLog")
        self.log.setReadOnly(True)
        # An empty exchange log is a blank slab without this line. Keep it to
        # ONE short line: Qt clips a QTextEdit placeholder to the empty
        # document's height, so a wrapped second line is cut off.
        self.log.setPlaceholderText(self.ctx.t("slvLogEmpty"))
        split.addWidget(self.log)
        split.setStretchFactor(0, 2)
        split.setStretchFactor(1, 1)
        split.setSizes([760, 380])
        lo.addWidget(split, 1)

        self.lbl_empty = EmptyState("cpu", self.ctx.t("noMapTitle"), "")
        self.lbl_empty.apply_theme(self.ctx.theme_tokens())
        lo.addWidget(self.lbl_empty, 1)
        self._split = split

        self.lbl_status = self._lbl()
        lo.addWidget(self.lbl_status)
        self._paint_icons()

    def _paint_icons(self):
        c = self.ctx.theme_tokens()
        self.btn_start.setIcon(icons.icon("stop" if self.running else "play",
                                          c["accent_fg"], 14))
        self.btn_reload.setIcon(icons.icon("table", c["text_2"], 14))

    def _fill_ports(self):
        current = self.combo_port.currentText().strip() or \
            str(self.ctx.settings.get("slave_port", "") or "")
        self.combo_port.clear()
        try:
            from serial.tools import list_ports
            ports = sorted(p.device for p in list_ports.comports())
        except Exception:
            ports = []
        if current and current not in ports:
            ports.insert(0, current)
        self.combo_port.addItems(ports or [str(self.ctx.settings.get("port", "COM1"))])
        if current:
            self.combo_port.setCurrentText(current)

    # ── the served map ────────────────────────────────────────────────
    @property
    def running(self) -> bool:
        return self._server is not None and self._server.isRunning()

    def reload_map(self):
        """Take a fresh snapshot of the register map (values typed earlier
        are kept for addresses that are still served)."""
        if self.running:
            return
        old = self.store
        self.store = SlaveStore.from_registers(self.get_registers() or [])
        for a in self.store.words:
            if a in old.words:
                self.store.words[a] = old.words[a]
        self._map_dirty = False
        self._render_table()
        self._update_info()

    def map_changed(self):
        """Called by the window when the main register map changes."""
        if self.running:
            self._map_dirty = True           # applied at the next start
            self._update_info()
        else:
            self.reload_map()

    def _render_table(self):
        t = self.ctx.t
        regs = self.store.registers
        mono_size = self.ctx.settings.get("font_size", 9)
        from gui.register_table import mono_font
        mono = mono_font(mono_size)
        muted = QColor(self.ctx.theme_tokens()["text_4"])
        self._row_of = {}
        self.table.blockSignals(True)
        try:
            self.table.setRowCount(len(regs))
            for i, reg in enumerate(regs):
                addr = datatypes.reg_key(reg)
                self._row_of[addr] = i
                dtype = reg.get("type", "SHORT")
                editable = datatypes.is_scalar(dtype)
                cells = [datatypes.key_label(addr),
                         (reg.get("name_en") if self.ctx.lang == "en" and reg.get("name_en")
                          else reg.get("name", "")),
                         dtype, self.store.get_value(reg), "0", "0", "—"]
                for col, text in enumerate(cells):
                    it = QTableWidgetItem(str(text))
                    flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
                    if col == COL_VALUE and editable:
                        flags |= Qt.ItemFlag.ItemIsEditable
                        it.setToolTip(t("slvValueTip"))
                    it.setFlags(flags)
                    it.setTextAlignment(
                        Qt.AlignmentFlag.AlignCenter if col in (COL_READS, COL_WRITES)
                        else Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                    if col in (COL_ADDR, COL_VALUE, COL_READS, COL_WRITES):
                        it.setFont(mono)
                    if not editable and col == COL_VALUE:
                        it.setForeground(muted)
                    self.table.setItem(i, col, it)
        finally:
            self.table.blockSignals(False)
        for addr in self._row_of:
            self._refresh_row(addr)
        empty = not regs
        self._split.setVisible(not empty)
        self.lbl_empty.setVisible(empty)
        self.lbl_empty.setText(t("slvNoMap"))

    def _refresh_row(self, addr: int):
        i = self._row_of.get(addr)
        if i is None:
            return
        reg = self.store.registers[i]
        reads, writes, last = self.store.access_of(addr)
        self.table.blockSignals(True)
        try:
            for col, text in ((COL_VALUE, self.store.get_value(reg)),
                              (COL_READS, str(reads)), (COL_WRITES, str(writes)),
                              (COL_LAST, time.strftime("%H:%M:%S", time.localtime(last))
                               if last else "—")):
                it = self.table.item(i, col)
                if it is not None and it.text() != text:
                    it.setText(text)
        finally:
            self.table.blockSignals(False)

    def _on_cell_changed(self, row: int, col: int):
        if col != COL_VALUE or not 0 <= row < len(self.store.registers):
            return
        reg = self.store.registers[row]
        text = self.table.item(row, col).text()
        try:
            self.store.set_value(reg, text)
        except (ValueError, TypeError, OverflowError) as e:
            self.lbl_status.setText(self.ctx.t("slvBadValue").format(
                addr=datatypes.key_label(datatypes.reg_key(reg)), err=e))
            set_state(self.lbl_status, "error")
        else:
            set_state(self.lbl_status, "")
            self._update_status()
        self._refresh_row(datatypes.reg_key(reg))

    # ── start / stop ──────────────────────────────────────────────────
    def serving_port(self) -> str:
        """The port the server holds right now ("" when stopped) — the
        window refuses to open the same port as a master."""
        return self._server.port if self.running else ""

    def toggle(self):
        if self.running:
            self._server.request_stop()
            return
        t = self.ctx.t
        port = self.combo_port.currentText().strip()
        try:
            baud = int(self.combo_baud.currentText())
        except ValueError:
            baud = 0
        if not port or baud <= 0:
            self.lbl_status.setText(t("snifBadBaud"))
            set_state(self.lbl_status, "error")
            return
        # One port, one owner: the master poller may hold this very port.
        core = self.ctx.core
        if core.is_running and port.casefold() == \
                str(self.ctx.settings.get("port", "")).casefold():
            themed_info(self, self.ctx.theme, "warning", t("slvBusyTitle"),
                        t("slvBusyText"))
            return
        if self._map_dirty or not self.store.registers:
            self.reload_map()
        if not self.store.registers:
            themed_info(self, self.ctx.theme, "info", t("slvTitle"), t("slvNoMap"))
            return
        s = self.ctx.settings
        s["slave_port"], s["slave_baud"] = port, str(baud)
        s["slave_sid"], s["slave_delay"] = self.spin_sid.value(), self.spin_delay.value()
        self._server = SlaveServer(
            port, baud, self.store, self.spin_sid.value(),
            parity=transports.parity_code(s.get("parity", "N")),
            stopbits=transports.stopbits_value(s.get("stopbits", 1)),
            delay_ms=self.spin_delay.value())
        self._server.exchange.connect(self._on_exchange)
        self._server.error.connect(self._on_error)
        self._server.stopped.connect(self._on_stopped)
        self._counts = {k: 0 for k in self._counts}
        set_state(self.lbl_status, "ok")
        self._server.start()
        self._set_controls(True)
        self._update_info()
        self._update_status()

    def _set_controls(self, running: bool):
        t = self.ctx.t
        self.btn_start.setText("  " + (t("slvStop") if running else t("slvStart")))
        for w in (self.combo_port, self.combo_baud, self.spin_sid,
                  self.spin_delay, self.btn_reload):
            w.setEnabled(not running)
        self._paint_icons()

    def _on_stopped(self):
        self._set_controls(False)
        if self.lbl_status.property("state") != "error":
            set_state(self.lbl_status, "")
        self._update_info()
        self._update_status()
        if self._map_dirty:
            self.reload_map()

    def _on_error(self, err):
        if isinstance(err, tuple) and len(err) == 2:
            key, params = err
            msg = self.ctx.t(key).format(**(params or {}))
        else:
            msg = str(err)
        self.lbl_status.setText(msg)
        set_state(self.lbl_status, "error")

    def stop_if_running(self):
        if self.running:
            self._server.request_stop()
            self._server.wait(2000)

    # ── live exchange ─────────────────────────────────────────────────
    def _on_exchange(self, info: dict):
        kind = info.get("kind")
        if info.get("reason") == "other":
            return                            # another device's traffic
        self._counts["requests"] += 1
        if kind == "exception":
            self._counts["exceptions"] += 1
        if info.get("response") is not None:
            self._counts["answered"] += 1
        elif kind == "ignored":
            self._counts["ignored"] += 1
        for a in info.get("touched") or []:
            self._refresh_row(a)
        self._append_log(info)
        self._update_status()

    def _append_log(self, info: dict):
        import html
        c = self.ctx.theme_tokens()
        ts = QDateTime.currentDateTime().toString("HH:mm:ss.zzz")
        req = " ".join(f"{b:02X}" for b in info.get("request", b""))
        resp = info.get("response")
        kind = info.get("kind")
        what = self._describe(info)
        color = {"read": c["info"], "write": c["accent"],
                 "exception": c["warn"]}.get(kind, c["text_4"])
        line = (f'<span style="color:{c["text_4"]}">[{ts}]</span> '
                f'<span style="color:{color};font-weight:bold">{html.escape(what)}</span><br>'
                f'<span style="color:{c["text_3"]}">&nbsp;&nbsp;← {req}</span>')
        if resp is not None:
            line += (f'<br><span style="color:{c["text_2"]}">&nbsp;&nbsp;→ '
                     f'{" ".join(f"{b:02X}" for b in resp)}</span>')
        doc = self.log.document()
        if doc.blockCount() > _LOG_MAX * 3:
            self.log.clear()
        sb = self.log.verticalScrollBar()
        follow = sb.value() >= sb.maximum() - 2
        self.log.append(line)
        if follow:
            sb.setValue(sb.maximum())

    def _describe(self, info: dict) -> str:
        t = self.ctx.t
        kind = info.get("kind")
        fc = info.get("fc")
        key = info.get("key")
        addr = info.get("addr")
        a = (datatypes.key_label(key) if isinstance(key, int)
             else f"0x{addr:04X}" if isinstance(addr, int) else "—")
        if kind == "read":
            return t("slvLogRead").format(fc=f"{fc:02X}", addr=a, n=info.get("count"))
        if kind == "write":
            return t("slvLogWrite").format(fc=f"{fc:02X}", addr=a, n=info.get("count"))
        if kind == "exception":
            return t("slvLogExc").format(fc=f"{(fc or 0):02X}", code=info.get("exception"),
                                         addr=a)
        return t("slvLogIgnored").format(reason=t({"crc": "slvWhyCrc",
                                                   "short": "slvWhyShort",
                                                   "broadcast": "slvWhyBroadcast"}
                                                  .get(info.get("reason"), "slvWhyOther")))

    # ── status lines ──────────────────────────────────────────────────
    def _update_info(self):
        t = self.ctx.t
        lo, hi = self.store.span()
        n = len(self.store.registers)
        if self.running:
            text = t("slvServing").format(
                sid=self._server.slave_id, port=self._server.port,
                baud=self._server.baudrate,
                framing=transports.serial_framing(self.ctx.settings), n=n,
                lo=datatypes.key_label(lo) if lo is not None else "—",
                hi=datatypes.key_label(hi) if hi is not None else "—")
            if self._map_dirty:
                text += " " + t("slvMapChanged")
        else:
            text = t("slvIdleInfo")
        self.lbl_info.setText(text)

    def _update_status(self):
        if self.lbl_status.property("state") == "error":
            return
        c = self._counts
        self.lbl_status.setText(self.ctx.t("slvCounts").format(
            req=c["requests"], ans=c["answered"], exc=c["exceptions"],
            ign=c["ignored"]) if self.running or c["requests"]
            else self.ctx.t("slvIdle"))

    # ── app plumbing ──────────────────────────────────────────────────
    def showEvent(self, e):
        if not self.running:
            self._fill_ports()
            self.reload_map()
        super().showEvent(e)

    def apply_settings(self):
        self.lbl_empty.apply_theme(self.ctx.theme_tokens())
        self._paint_icons()
        self._render_table()

    def retranslate(self, t):
        self.lbl_empty.set_content(title=t("noMapTitle"))
        self.lbl_port.setText(t("port"))
        self.lbl_baud.setText(t("baudrate"))
        self.lbl_sid.setText(t("slaveIdLbl"))
        self.lbl_delay.setText(t("slvDelay"))
        self.log.setPlaceholderText(t("slvLogEmpty"))
        self.spin_delay.setSuffix(t("unitMsSuffix"))
        self.spin_delay.setToolTip(t("slvDelayTip"))
        self.btn_reload.setText("  " + t("slvReload"))
        self.btn_reload.setToolTip(t("slvReloadTip"))
        self._set_controls(self.running)
        self.table.setHorizontalHeaderLabels(
            [t("address"), t("name"), t("type"), t("slvValue"),
             t("slvReads"), t("slvWrites"), t("slvLast")])
        self._render_table()
        self._update_info()
        self._update_status()

    # ── guide (F1) ────────────────────────────────────────────────────
    def _show_guide(self):
        from gui.onboarding import OnboardingGuide
        ru = self.ctx.lang == "ru"
        L = (lambda r, e: r) if ru else (lambda r, e: e)
        steps = [
            {"target": None,
             "title": L("Эмулятор устройства", "Device emulator"),
             "body": L(
                 "Программа отвечает мастеру как прибор: карта регистров — та "
                 "же, что открыта в окне карты, значения вы задаёте здесь.",
                 "The app answers a master like a device would: the register "
                 "map is the one open in the map view, the values are set here.")},
            {"target": self.combo_port,
             "title": L("Свой порт", "Its own port"),
             "body": L(
                 "Порт может держать только один владелец. Чтобы проверить "
                 "мастер этой же программы, нужны два адаптера и нуль-модем "
                 "(или пара виртуальных COM-портов).",
                 "A port has exactly one owner. To test this app's own master "
                 "you need two adapters and a null-modem link (or a virtual "
                 "COM pair).")},
            {"target": self.table,
             "title": L("Значения", "Values"),
             "body": L(
                 "Двойной щелчок по значению — задать, что прочитает мастер. "
                 "Запись мастера сразу видна здесь. «Чтений/Записей» "
                 "показывают, к каким регистрам мастер обращается.",
                 "Double-click a value to set what the master reads. A master "
                 "write shows up here at once. Reads/Writes show which "
                 "registers the master actually touches.")},
            {"target": self.spin_delay,
             "title": L("Задержка ответа", "Response delay"),
             "body": L(
                 "Медленный прибор: проверьте, правильно ли мастер выставляет "
                 "таймауты.",
                 "A slow device: check that the master's timeouts are right.")},
            {"target": self.log,
             "title": L("Обмен", "Exchange"),
             "body": L(
                 "Каждый запрос и ответ. На чужой адрес и кадр с плохим CRC "
                 "настоящий прибор молчит — эмулятор тоже.",
                 "Every request and answer. A real device stays silent on "
                 "another slave ID or a bad CRC — so does the emulator.")},
        ]
        g = OnboardingGuide(self.window(), steps, self.ctx.theme,
                            self.ctx.settings.get("accent"), self.ctx.lang)
        g.show_guide()
