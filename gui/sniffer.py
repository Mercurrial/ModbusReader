# gui_sniffer.py
"""Passive RTU sniffer view — watch a bus without transmitting a byte.

Owns its OWN serial port via SnifferWorker (sniffer_core.py). The
one-port-one-owner rule is enforced here: starting on the port the master is
currently polling is refused (stop polling first, or tap the line with a
second USB-RS485 adapter — the intended professional setup)."""

from PyQt6.QtCore import Qt, QSize, QDateTime
from PyQt6.QtGui import QColor, QIntValidator
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
)

from gui import icons
from gui.widgets import EmptyState, EmptyOverlay
from core import transports
from gui.dialogs import themed_info
from gui.qt_utils import set_state
from core.sniffer_core import SnifferWorker

_MAX_ROWS = 2000


class SnifferView(QWidget):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self._worker: SnifferWorker | None = None
        self.setObjectName("snifferView")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._build_ui()

    def _build_ui(self):
        t = self.ctx.t
        lo = QVBoxLayout(self)
        lo.setContentsMargins(14, 10, 14, 10)
        lo.setSpacing(10)

        bar = QHBoxLayout()
        bar.setSpacing(10)

        self.lbl_port = QLabel(t("port"))
        self.lbl_port.setObjectName("mhCrumb")
        self.combo_port = QComboBox()
        self.combo_port.setObjectName("stInput")
        self.combo_port.setEditable(True)
        self.combo_port.setFixedWidth(130)
        self._fill_ports()
        bar.addWidget(self.lbl_port)
        bar.addWidget(self.combo_port)

        self.lbl_baud = QLabel(t("baudrate"))
        self.lbl_baud.setObjectName("mhCrumb")
        self.combo_baud = QComboBox()
        self.combo_baud.setObjectName("stInput")
        self.combo_baud.addItems(["1200", "2400", "4800", "9600", "19200",
                                  "38400", "57600", "115200", "230400"])
        # A tapped line runs at whatever rate somebody else chose.
        self.combo_baud.setEditable(True)
        self.combo_baud.setValidator(QIntValidator(50, 4000000, self))
        self.combo_baud.setCurrentText(
            str(self.ctx.settings.get("baudrate", "115200")))
        self.combo_baud.setFixedWidth(110)
        bar.addWidget(self.lbl_baud)
        bar.addWidget(self.combo_baud)

        bar.addStretch()

        self.btn_clear = QPushButton("  " + t("clear"))
        self.btn_clear.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_clear.setIcon(icons.icon(
            "trash", self.ctx.theme_tokens()["text_2"], 14))
        self.btn_clear.clicked.connect(lambda: self.table.setRowCount(0))
        bar.addWidget(self.btn_clear)

        self.btn_start = QPushButton("  " + t("snifStart"))
        self.btn_start.setObjectName("btnPrimary")
        self.btn_start.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_start.setIcon(icons.icon(
            "play", self.ctx.theme_tokens()["accent_fg"], 14))
        self.btn_start.setIconSize(QSize(13, 13))
        self.btn_start.clicked.connect(self._toggle)
        bar.addWidget(self.btn_start)
        lo.addLayout(bar)

        self.table = QTableWidget(0, 6)
        self.table.horizontalHeader().setDefaultAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.table.setObjectName("snifTable")
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self._set_headers()
        hh = self.table.horizontalHeader()
        for col, w in ((0, 96), (1, 48), (2, 130), (3, 96), (5, 64)):
            hh.setSectionResizeMode(col, QHeaderView.ResizeMode.Fixed)
            self.table.setColumnWidth(col, w)
        hh.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        lo.addWidget(self.table, 1)

        self.empty = EmptyState("eye", t("snifEmptyTitle"), t("snifEmptyBody"))
        # Outline, not filled: the toolbar right above already carries the
        # same action as the page's one accent button.
        self.empty.add_action(t("snifStart"), self._toggle)
        self.empty.apply_theme(self.ctx.theme_tokens())
        self._empty_ov = EmptyOverlay(
            self.table, self.empty,
            when=lambda: not (self._worker is not None and self._worker.isRunning()))

        self.lbl_status = QLabel(t("snifIdle"))
        self.lbl_status.setObjectName("mhCrumb")
        lo.addWidget(self.lbl_status)

    def _set_headers(self):
        t = self.ctx.t
        self.table.setHorizontalHeaderLabels(
            [t("time"), "ID", t("snifFunc"), t("snifKind"), t("snifData"), "CRC"])

    def _fill_ports(self):
        current = self.combo_port.currentText()
        self.combo_port.clear()
        try:
            from serial.tools import list_ports
            ports = [p.device for p in list_ports.comports()]
        except Exception:
            ports = []
        if not ports:
            ports = [self.ctx.settings.get("port", "COM1")]
        self.combo_port.addItems(ports)
        if current:
            self.combo_port.setCurrentText(current)

    # ── start/stop ────────────────────────────────────────────────────
    def _toggle(self):
        if self._worker is not None and self._worker.isRunning():
            self._worker.request_stop()
            return
        port = self.combo_port.currentText().strip()
        try:
            baud = int(self.combo_baud.currentText())
        except ValueError:
            baud = 0
        if baud <= 0:
            self.lbl_status.setText(self.ctx.t("snifBadBaud"))
            set_state(self.lbl_status, "error")
            return
        # One port — one owner: refuse to fight the master for its port.
        # (Windows port names are case-insensitive: "com3" IS "COM3".)
        if (self.ctx.core.is_running
                and port.casefold() == str(self.ctx.settings.get("port", "")).casefold()):
            themed_info(self, self.ctx.theme, "warning",
                        self.ctx.t("snifBusyTitle"),
                        self.ctx.t("snifBusyText"))
            return
        # Framing follows Settings → Подключение (same normaliser as the master).
        parity = transports.parity_code(self.ctx.settings.get("parity", "N"))
        stopbits = transports.stopbits_value(self.ctx.settings.get("stopbits", 1))
        self._worker = SnifferWorker(port, baud, parity=parity, stopbits=stopbits)
        self._worker.frame_captured.connect(self._on_frame)
        self._worker.error.connect(self._on_error)
        self._worker.stopped.connect(self._on_stopped)
        self._worker.start()
        self.btn_start.setText("  " + self.ctx.t("snifStop"))
        self.btn_start.setIcon(icons.icon(
            "stop", self.ctx.theme_tokens()["accent_fg"], 14))
        set_state(self.lbl_status, "ok")
        self.lbl_status.setText(self.ctx.t("snifListening").format(port=port))

    def _on_error(self, err):
        """The worker reports (i18n_key, params) so it stays language-free."""
        if isinstance(err, tuple) and len(err) == 2:
            key, params = err
            msg = self.ctx.t(key).format(**(params or {}))
        else:
            msg = str(err)
        self.lbl_status.setText(msg)
        set_state(self.lbl_status, "error")

    def _on_stopped(self):
        self.btn_start.setText("  " + self.ctx.t("snifStart"))
        self.btn_start.setIcon(icons.icon(
            "play", self.ctx.theme_tokens()["accent_fg"], 14))
        if self.lbl_status.property("state") != "error":
            set_state(self.lbl_status, "")
            self.lbl_status.setText(self.ctx.t("snifIdle"))

    def stop_if_running(self):
        if self._worker is not None and self._worker.isRunning():
            self._worker.request_stop()
            self._worker.wait(2000)

    # ── frame rendering ───────────────────────────────────────────────
    def _describe(self, f: dict) -> str:
        """Frame description: protocol data stays as-is, but the decoder's
        verbal notes arrive as i18n keys and are translated here."""
        key = f.get("describe_key")
        if key:
            return self.ctx.t(key).format(**(f.get("describe_args") or {}))
        return f.get("describe", "") or f.get("hex", "")

    def _on_frame(self, f: dict):
        c = self.ctx.theme_tokens()
        # Follow new frames only while the operator is at the bottom: always
        # jumping there made it impossible to read a frame mid-capture.
        sb = self.table.verticalScrollBar()
        follow = sb.value() >= sb.maximum() - 2
        row = self.table.rowCount()
        if row >= _MAX_ROWS:
            self.table.removeRow(0)
            row = self.table.rowCount()
        self.table.insertRow(row)
        kind_txt = {"request": "→ req", "response": "← resp",
                    "req/resp": "req/resp", "exception": "EXC",
                    "junk": "junk"}.get(f.get("kind", "?"), "?")
        cells = [
            QDateTime.currentDateTime().toString("HH:mm:ss.zzz"),
            str(f.get("slave", "?")),
            f.get("fc_name", "?"),
            kind_txt,
            self._describe(f),
            "OK" if f.get("crc_ok") else "BAD",
        ]
        for col, text in enumerate(cells):
            it = QTableWidgetItem(text)
            it.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            it.setToolTip(f.get("hex", ""))
            self.table.setItem(row, col, it)
        crc_item = self.table.item(row, 5)
        crc_item.setForeground(QColor(c["ok"] if f.get("crc_ok") else c["error"]))
        if f.get("kind") == "exception":
            self.table.item(row, 3).setForeground(QColor(c["warn"]))
        if follow:
            self.table.scrollToBottom()

    # ── app plumbing ──────────────────────────────────────────────────
    def showEvent(self, e):
        # An adapter plugged in after start-up should appear in the list.
        if self._worker is None or not self._worker.isRunning():
            self._fill_ports()
        super().showEvent(e)

    def apply_settings(self):
        c = self.ctx.theme_tokens()
        self.empty.apply_theme(c)
        running = self._worker is not None and self._worker.isRunning()
        self.btn_clear.setIcon(icons.icon("trash", c["text_2"], 14))
        self.btn_start.setIcon(icons.icon("stop" if running else "play",
                                          c["accent_fg"], 14))

    def retranslate(self, t):
        running = self._worker is not None and self._worker.isRunning()
        self.btn_start.setText("  " + (t("snifStop") if running else t("snifStart")))
        self.btn_clear.setText("  " + t("clear"))
        self.lbl_port.setText(t("port"))
        self.lbl_baud.setText(t("baudrate"))
        self.empty.set_content(t("snifEmptyTitle"), t("snifEmptyBody"))
        self.empty.buttons[0].setText(t("snifStart"))
        if not running and self.lbl_status.property("state") != "error":
            self.lbl_status.setText(t("snifIdle"))
        self._set_headers()

    # ── guide (F1 / Справка) ──────────────────────────────────────────
    def _show_guide(self):
        """Coach marks for the sniffer. The two things nobody guesses on their
        own: it needs a SECOND adapter, and CRC BAD usually means merged
        frames rather than a broken device."""
        from gui.onboarding import OnboardingGuide
        ru = self.ctx.lang == "ru"
        L = (lambda r, e: r) if ru else (lambda r, e: e)
        steps = [
            {"target": None,
             "title": L("Сниффер линии", "Bus sniffer"),
             "body": L(
                 "Пассивно слушает RS-485 и разбирает чужой обмен. Программа "
                 "не передаёт в линию ни одного байта.",
                 "Passively listens to RS-485 and decodes somebody else's "
                 "traffic. This app never puts a single byte on the line.")},
            {"target": self.combo_port,
             "title": L("Нужен отдельный адаптер", "You need a second adapter"),
             "body": L(
                 "Порт может держать только один владелец. Чтобы слушать чужой "
                 "обмен, подключите ВТОРОЙ адаптер параллельно линии A/B и "
                 "выберите его здесь.",
                 "A port has exactly one owner. To watch someone else's "
                 "traffic, wire a SECOND adapter in parallel with A/B and pick "
                 "it here.")},
            {"target": self.combo_baud,
             "title": L("Скорость должна совпадать", "The baud rate must match"),
             "body": L(
                 "При неверной скорости кадры разъезжаются и почти всё будет "
                 "с CRC BAD. Начните с той же скорости, что у мастера.",
                 "At the wrong rate frames shear apart and almost everything "
                 "shows CRC BAD. Start from the master's own rate.")},
            {"target": self.table,
             "title": L("Как читать таблицу", "Reading the table"),
             "body": L(
                 "Направление (→ req / ← resp) — это догадка по длине кадра: "
                 "пассивный слушатель не знает, кто передавал. CRC OK — кадр "
                 "собран верно.",
                 "The direction (→ req / ← resp) is inferred from the frame "
                 "length: a passive tap cannot know who transmitted. CRC OK "
                 "means the frame was reassembled correctly.")},
            {"target": self.btn_start,
             "title": L("Старт", "Start"),
             "body": L(
                 "Захват идёт в отдельном потоке. Если адаптер выдернуть, "
                 "сниффер сообщит об обрыве и корректно закроет порт.",
                 "Capture runs on its own thread. If the adapter is unplugged "
                 "the sniffer reports it and releases the port cleanly.")},
        ]
        g = OnboardingGuide(self.window(), steps, self.ctx.theme,
                            self.ctx.settings.get("accent"), self.ctx.lang)
        g.show_guide()
