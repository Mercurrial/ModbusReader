# gui/connection.py
"""The connection card — what a click on the header's link chip opens.

    ┌ Подключение ───────────────────────────────── ⚙ ┐
    │ [ COM-порт | Modbus TCP | RTU по TCP ]           │
    │ IP-адрес  [192.168.1.20         ]   Порт [502]   │
    │           ПЛК, счётчики, шлюзы…  · Найти в сети  │
    │ Unit ID   [1  ]  Обычно 1. Молчит — 255 или 0.   │
    │ ┌ ✓ Связь есть · ответ за 12 мс ───────────────┐ │
    │ НЕДАВНИЕ                                         │
    │   TCP · 192.168.1.20:502 · ID 1                  │
    │   COM3 · 9600 · 8E1 · ID 10                      │
    │ [Проверить связь]                  [Подключить]  │
    └──────────────────────────────────────────────────┘

Everything needed to reach a device is here, next to the button that uses
it — the full Settings page keeps the rest (timeouts, codecs, reconnects).

* The card edits a DRAFT of the link. Connect applies it and connects (or
  reconnects); closing the card keeps it for the next connect — the card is
  the connection, there is no separate "apply".
* «Проверить связь» asks the device once and says what is wrong in words
  (core/linktest). For TCP it also tries what a newcomer cannot know: other
  unit ids, and the other framing (Modbus TCP vs RTU over TCP) — a working
  alternative is offered as one click.
* A connect that fails opens this card with the reason (ModbusCore.open_failed).
* «Демо» — the demo project's made-up device (core/simulator.py): offered
  only while the demo project is open (``set_sim_available``).
"""

import threading

from PyQt6.QtCore import Qt, QObject, QPoint, QRect, QSize, pyqtSignal
from PyQt6.QtGui import QIntValidator
from PyQt6.QtWidgets import (
    QFrame, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QPushButton, QComboBox, QLineEdit, QSpinBox, QAbstractSpinBox,
)

from core import datatypes, linktest, transports
from gui import icons
from gui.qt_utils import set_state
from gui.widgets import Segmented

_BAUDS = ("1200", "2400", "4800", "9600", "19200", "38400", "57600",
          "115200", "230400")
_PARITIES = (("None (N)", "N"), ("Even (E)", "E"), ("Odd (O)", "O"))
_RECENT_SHOWN = 4
_CARD_WIDTH = 404
_LABEL_W = 86                       # the left column (field names)
_FIELD_W = _CARD_WIDTH - 2 * 18 - _LABEL_W - 12 - 4  # the right column (−4: air)


def _com_ports() -> list:
    try:
        from serial.tools import list_ports
        return sorted(p.device for p in list_ports.comports())
    except Exception:
        return []


def _invalidate_tree(layout):
    """Drop the cached size hints of *layout* and every layout inside it —
    a sub-layout (not a widget's own) keeps a stale hint otherwise."""
    for i in range(layout.count()):
        item = layout.itemAt(i)
        if item.layout() is not None:
            _invalidate_tree(item.layout())
        elif item.widget() is not None and item.widget().layout() is not None:
            _invalidate_tree(item.widget().layout())
    layout.invalidate()


class _Relay(QObject):
    """Carries a worker thread's result back to the GUI thread."""
    done = pyqtSignal(object)


class ConnectionCard(QFrame):
    """The popover. One instance per window, reused."""

    connect_requested = pyqtSignal(dict)    # the draft link → connect / reconnect
    disconnect_requested = pyqtSignal()
    committed = pyqtSignal(dict)            # closed with a changed draft
    settings_requested = pyqtSignal()       # «Все настройки подключения»
    find_requested = pyqtSignal()           # «Найти в сети» → scanner

    def __init__(self, ctx, registers_fn=None, parent=None):
        super().__init__(parent, Qt.WindowType.Popup)
        self.ctx = ctx
        self._registers_fn = registers_fn or (lambda: [])
        self._handled = False          # Connect already applied the draft
        self._testing = False
        self._test_seq = 0             # a stale result must not overwrite a newer one
        self._suggestion = None        # ("unit", n) | ("transport", id)
        self._relay = _Relay(self)
        self._relay.done.connect(self._on_test_done)
        self.setObjectName("connCard")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedWidth(_CARD_WIDTH)
        self._build()
        self.retranslate(ctx.t)

    # ── build ─────────────────────────────────────────────────────────
    def _label(self, obj="connLabel") -> QLabel:
        lb = QLabel()
        lb.setObjectName(obj)
        return lb

    def _build(self):
        lo = QVBoxLayout(self)
        lo.setContentsMargins(18, 14, 18, 16)
        lo.setSpacing(12)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        self.lbl_title = self._label("connCardTitle")
        head.addWidget(self.lbl_title)
        head.addStretch(1)
        self.btn_settings = QPushButton()
        self.btn_settings.setObjectName("iconBtn")
        self.btn_settings.setFixedSize(28, 28)
        self.btn_settings.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_settings.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_settings.setIconSize(QSize(15, 15))
        self.btn_settings.clicked.connect(self._open_settings)
        head.addWidget(self.btn_settings)
        lo.addLayout(head)

        self.seg = Segmented([(t.transport_id, t.transport_id)
                              for t in transports.TRANSPORTS], "serial")
        self.seg.valueChanged.connect(self._on_transport)
        self.seg._buttons[transports.SIM_ID].setVisible(False)   # the demo only
        lo.addWidget(self.seg)

        # ── the demo's simulated device: nothing to fill in ──
        self.lbl_sim = self._label("connHint")
        self.lbl_sim.setWordWrap(True)
        self.lbl_sim.setFixedWidth(_CARD_WIDTH - 2 * 18)
        lo.addWidget(self.lbl_sim)

        # ── serial ──
        self.box_serial = QWidget()
        self.box_serial.setObjectName("connBox")
        g = QGridLayout(self.box_serial)
        g.setContentsMargins(0, 0, 0, 0)
        g.setHorizontalSpacing(12)
        g.setVerticalSpacing(8)
        self.lbl_port = self._label()
        port_row = QHBoxLayout()
        port_row.setSpacing(6)
        self.cb_port = QComboBox()
        self.cb_port.setObjectName("stInput")
        self.cb_port.setEditable(True)
        self.cb_port.setMinimumWidth(150)
        self.cb_port.currentTextChanged.connect(self._on_edited)
        self.btn_refresh = QPushButton()
        self.btn_refresh.setObjectName("iconBtn")
        self.btn_refresh.setFixedSize(28, 28)
        self.btn_refresh.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_refresh.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_refresh.clicked.connect(lambda: self._fill_ports(self.cb_port.currentText()))
        port_row.addWidget(self.cb_port, 1)
        port_row.addWidget(self.btn_refresh)
        self.lbl_baud = self._label()
        self.cb_baud = QComboBox()
        self.cb_baud.setObjectName("stInput")
        self.cb_baud.setEditable(True)
        self.cb_baud.addItems(_BAUDS)
        self.cb_baud.setValidator(QIntValidator(50, 4000000, self))
        self.cb_baud.currentTextChanged.connect(self._on_edited)
        self.lbl_parity = self._label()
        self.seg_parity = Segmented([(v, short) for v, short in _PARITIES], "None (N)")
        self.seg_parity.valueChanged.connect(self._on_edited)
        self.lbl_stop = self._label()
        self.seg_stop = Segmented([("1", "1"), ("2", "2")], "1")
        self.seg_stop.valueChanged.connect(self._on_edited)
        g.addWidget(self.lbl_port, 0, 0)
        g.addLayout(port_row, 0, 1)
        g.addWidget(self.lbl_baud, 1, 0)
        g.addWidget(self.cb_baud, 1, 1)
        line = QHBoxLayout()
        line.setSpacing(14)
        line.addWidget(self.seg_parity)
        line.addWidget(self.lbl_stop)
        line.addWidget(self.seg_stop)
        line.addStretch(1)
        g.addWidget(self.lbl_parity, 2, 0)
        g.addLayout(line, 2, 1)
        g.setColumnMinimumWidth(0, _LABEL_W)
        g.setColumnStretch(1, 1)
        lo.addWidget(self.box_serial)

        # ── network ──
        self.box_net = QWidget()
        self.box_net.setObjectName("connBox")
        n = QGridLayout(self.box_net)
        n.setContentsMargins(0, 0, 0, 0)
        n.setHorizontalSpacing(12)
        n.setVerticalSpacing(6)
        self.lbl_host = self._label()
        host_row = QHBoxLayout()
        host_row.setSpacing(8)
        self.ed_host = QLineEdit()
        self.ed_host.setObjectName("stInput")
        self.ed_host.setPlaceholderText("192.168.1.10")
        self.ed_host.textEdited.connect(self._on_edited)
        self.ed_host.returnPressed.connect(self._primary)
        self.lbl_tcp_port = self._label()
        self.sp_tcp_port = QSpinBox()
        self.sp_tcp_port.setObjectName("stInput")
        self.sp_tcp_port.setRange(1, 65535)
        self.sp_tcp_port.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.sp_tcp_port.setFixedWidth(64)
        self.sp_tcp_port.valueChanged.connect(self._on_edited)
        host_row.addWidget(self.ed_host, 1)
        host_row.addWidget(self.lbl_tcp_port)
        host_row.addWidget(self.sp_tcp_port)
        # Wrapped labels get a FIXED width: inside a popup that sizes itself
        # with adjustSize(), a free word-wrapped label is measured one line
        # short and its last line is cut off.
        self.lbl_net_hint = self._label("connHint")
        self.lbl_net_hint.setWordWrap(True)
        self.lbl_net_hint.setFixedWidth(_FIELD_W)
        self.btn_find = QPushButton()
        self.btn_find.setObjectName("connLink")
        self.btn_find.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_find.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_find.setIconSize(QSize(13, 13))
        self.btn_find.clicked.connect(self._find)
        under = QVBoxLayout()               # one cell: a hidden link leaves no gap
        under.setContentsMargins(0, 0, 0, 0)
        under.setSpacing(6)
        under.addWidget(self.lbl_net_hint)
        under.addWidget(self.btn_find, 0, Qt.AlignmentFlag.AlignLeft)
        n.addWidget(self.lbl_host, 0, 0)
        n.addLayout(host_row, 0, 1)
        n.addLayout(under, 1, 1)
        n.setColumnMinimumWidth(0, _LABEL_W)
        n.setColumnStretch(1, 1)
        lo.addWidget(self.box_net)

        # ── device address ──
        idg = QGridLayout()
        idg.setContentsMargins(0, 0, 0, 0)
        idg.setHorizontalSpacing(12)
        self.lbl_id = self._label()
        id_row = QHBoxLayout()
        id_row.setSpacing(10)
        self.sp_id = QSpinBox()
        self.sp_id.setObjectName("stInput")
        self.sp_id.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.sp_id.setFixedWidth(64)
        self.sp_id.valueChanged.connect(self._on_edited)
        self.lbl_id_hint = self._label("connHint")
        self.lbl_id_hint.setWordWrap(True)
        self.lbl_id_hint.setFixedWidth(_FIELD_W - 64 - 10)
        id_row.addWidget(self.sp_id)
        id_row.addWidget(self.lbl_id_hint)
        id_row.addStretch(1)
        idg.addWidget(self.lbl_id, 0, 0)
        idg.addLayout(id_row, 0, 1)
        idg.setColumnMinimumWidth(0, _LABEL_W)
        idg.setColumnStretch(1, 1)
        lo.addLayout(idg)

        # ── test result ──
        self.box_result = QFrame()
        self.box_result.setObjectName("connResult")
        self.box_result.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        r = QHBoxLayout(self.box_result)
        r.setContentsMargins(10, 8, 10, 8)
        r.setSpacing(10)
        self.ico_result = QLabel()
        self.ico_result.setObjectName("connResultIcon")
        self.ico_result.setFixedSize(16, 16)
        r.addWidget(self.ico_result, 0, Qt.AlignmentFlag.AlignTop)
        texts = QVBoxLayout()
        texts.setContentsMargins(0, 0, 0, 0)
        texts.setSpacing(2)
        self.lbl_result = self._label("connResultText")
        self.lbl_result.setWordWrap(True)
        self.lbl_result_more = self._label("connResultMore")
        self.lbl_result_more.setWordWrap(True)
        for lb in (self.lbl_result, self.lbl_result_more):
            lb.setMinimumWidth(1)
        texts.addWidget(self.lbl_result)
        texts.addWidget(self.lbl_result_more)
        r.addLayout(texts, 1)
        self.btn_suggest = QPushButton()
        self.btn_suggest.setObjectName("connSuggest")
        self.btn_suggest.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_suggest.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_suggest.clicked.connect(self._take_suggestion)
        r.addWidget(self.btn_suggest, 0, Qt.AlignmentFlag.AlignVCenter)
        self.box_result.setVisible(False)
        lo.addWidget(self.box_result)

        # ── recent ──
        self.box_recent = QWidget()
        self.box_recent.setObjectName("connBox")
        rv = QVBoxLayout(self.box_recent)
        rv.setContentsMargins(0, 2, 0, 0)
        rv.setSpacing(2)
        self.lbl_recent = self._label("connCaption")
        rv.addWidget(self.lbl_recent)
        self._recent_btns = []
        for _ in range(_RECENT_SHOWN):
            b = QPushButton()
            b.setObjectName("connRecentRow")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.setIconSize(QSize(13, 13))
            b.clicked.connect(lambda _=False, btn=b: self._load_recent(btn))
            rv.addWidget(b)
            self._recent_btns.append(b)
        lo.addWidget(self.box_recent)

        # ── footer ──
        foot = QHBoxLayout()
        foot.setContentsMargins(0, 4, 0, 0)
        foot.setSpacing(8)
        self.btn_test = QPushButton()
        self.btn_test.setObjectName("btnSecondary")
        self.btn_test.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_test.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_test.setFixedHeight(32)
        self.btn_test.clicked.connect(self.run_test)
        self.btn_primary = QPushButton()
        self.btn_primary.setObjectName("btnPrimary")
        self.btn_primary.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_primary.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_primary.setFixedHeight(32)
        self.btn_primary.setIconSize(QSize(14, 14))
        self.btn_primary.clicked.connect(self._primary)
        foot.addWidget(self.btn_test)
        foot.addStretch(1)
        foot.addWidget(self.btn_primary)
        lo.addLayout(foot)

    # ── public API ────────────────────────────────────────────────────
    def open_below(self, anchor: QWidget, failure: tuple | None = None,
                   link: dict | None = None):
        """Show under *anchor* (the link chip), its right edge on the
        chip's; load the saved link unless the card is already open.
        *link* (a device the scanner found) is loaded as the draft and
        tested at once."""
        if link:
            merged = dict(self.ctx.settings)
            merged.update(link)
            self.load(merged)
            self._clear_result()
        elif not self.isVisible():
            self.load(self.ctx.settings)
            self._clear_result()
        if failure:
            self.show_failure(*failure)
        self._sync_state()
        self._fit()
        pos = anchor.mapToGlobal(QPoint(anchor.width(), anchor.height()))
        x, y = pos.x() - self.width(), pos.y() + 8
        screen = anchor.screen()
        if screen is not None:
            geo = screen.availableGeometry()
            x = max(geo.left() + 8, min(x, geo.right() - self.width() - 8))
            y = min(y, geo.bottom() - self.height() - 8)
        self.move(x, y)
        self._handled = False
        self.show()
        self.raise_()
        if self.seg.value() != "serial" and not self.ed_host.text().strip():
            self.ed_host.setFocus()
        if link:
            self.run_test()

    def load(self, settings: dict):
        """Fill the controls from *settings* (or a recent-link dict)."""
        widgets = (self.seg, self.cb_port, self.cb_baud, self.seg_parity,
                   self.seg_stop, self.ed_host, self.sp_tcp_port, self.sp_id)
        for w in widgets:
            w.blockSignals(True)
        try:
            tid = transports.active(settings).transport_id
            self.seg.setValue(tid)
            self._fill_ports(str(settings.get("port", "") or ""))
            self.cb_baud.setCurrentText(str(transports.baudrate_value(
                settings.get("baudrate", 115200))))
            parity = transports.parity_code(settings.get("parity", "N"))
            self.seg_parity.setValue(next((v for v, c in _PARITIES if c == parity),
                                          "None (N)"))
            self.seg_stop.setValue("2" if transports.stopbits_value(
                settings.get("stopbits", 1)) == 2.0 else "1")
            self.ed_host.setText(transports.host_value(settings))
            self.sp_tcp_port.setValue(transports.tcp_port_value(settings.get("tcp_port")))
            self._apply_id_range(tid)
            try:
                self.sp_id.setValue(int(settings.get("slave_id", 1)))
            except (TypeError, ValueError):
                self.sp_id.setValue(1)
        finally:
            for w in widgets:
                w.blockSignals(False)
        self._show_blocks()
        self._fill_recent()

    def draft(self) -> dict:
        """The link the card shows, as settings keys."""
        tid = self.seg.value()
        out = {"transport": tid, "slave_id": int(self.sp_id.value()),
               "host": self.ed_host.text().strip(),
               "tcp_port": int(self.sp_tcp_port.value()),
               "port": self.cb_port.currentText().strip(),
               "baudrate": str(transports.baudrate_value(self.cb_baud.currentText())),
               "parity": self.seg_parity.value(),
               "stopbits": self.seg_stop.value()}
        if transports.get(tid).network or tid == transports.SIM_ID:
            # The serial fields keep their saved values: switching to TCP and
            # back must not lose the COM port the user had.
            for k in ("port", "baudrate", "parity", "stopbits"):
                out[k] = self.ctx.settings.get(k, out[k])
        if not transports.get(tid).network:
            for k in ("host", "tcp_port"):
                out[k] = self.ctx.settings.get(k, out[k])
        return out

    def set_sim_available(self, on: bool):
        """The demo project is open: offer its simulated device."""
        self.seg._buttons[transports.SIM_ID].setVisible(bool(on))

    def changed(self) -> bool:
        return transports.link_of(self.draft()) != transports.link_of(self.ctx.settings)

    def show_failure(self, kind: str, text: str):
        """A connect that did not open (ModbusCore.open_failed)."""
        why = linktest.why(kind, self.draft(), text, self.ctx.t)
        self._show_result("error", self.ctx.t("connTestFail").format(why=why))

    def sync_state(self):
        """The window calls this when the connection opens or closes."""
        if self.isVisible():
            self._sync_state()

    # ── behaviour ─────────────────────────────────────────────────────
    def _on_transport(self, tid):
        self._apply_id_range(tid)
        self._show_blocks()
        self._clear_result()
        self._on_edited()
        self._fit()
        if transports.get(tid).network and not self.ed_host.text().strip():
            self.ed_host.setFocus()

    def _apply_id_range(self, tid):
        lo, hi = transports.id_range(tid)
        value = self.sp_id.value()
        self.sp_id.setRange(lo, hi)
        self.sp_id.setValue(min(max(value, lo), hi))

    def _show_blocks(self):
        tid = self.seg.value()
        net = transports.get(tid).network
        sim = tid == transports.SIM_ID
        self.box_serial.setVisible(not net and not sim)
        self.box_net.setVisible(net)
        self.lbl_sim.setVisible(sim)
        self.btn_find.setVisible(tid == "tcp")
        t = self.ctx.t
        self.lbl_id.setText(t("connUnitId") if tid == "tcp" else t("connSlaveId"))
        self.lbl_id_hint.setText(t("connUnitHint") if tid == "tcp"
                                 else t("connSimIdHint") if sim else "")
        self.lbl_id_hint.setVisible(tid == "tcp" or sim)
        self.lbl_sim.setText(t("connSimHint"))
        self.lbl_net_hint.setText(t("connTcpHint") if tid == "tcp" else t("connRtuTcpHint"))

    def _on_edited(self, *_):
        set_state(self.ed_host, "")
        if self.box_result.isVisible() and not self._testing:
            self._clear_result()
        self._sync_state()

    def _sync_state(self):
        t = self.ctx.t
        core = self.ctx.core
        running = bool(core.is_running)
        if running and not self.changed():
            text, icon = t("disconnect"), "plug"
        elif running:
            text, icon = t("connReconnect"), "plug"
        else:
            text, icon = t("connect"), "plug"
        self.btn_primary.setText("  " + text)
        c = self.ctx.theme_tokens()
        self.btn_primary.setIcon(icons.icon(icon, c["accent_fg"], 14))
        self.btn_test.setEnabled(not self._testing)
        self.btn_test.setText(t("connTesting") if self._testing else t("connTest"))

    def _fill_ports(self, current: str = ""):
        ports = _com_ports()
        current = current.strip()
        if current and current not in ports:
            ports.insert(0, current)
        was = self.cb_port.blockSignals(True)
        self.cb_port.clear()
        self.cb_port.addItems(ports)
        self.cb_port.setCurrentText(current or (ports[0] if ports else ""))
        self.cb_port.blockSignals(was)

    def _fill_recent(self):
        current = transports.link_of(self.ctx.settings)
        items = [r for r in self.ctx.settings.get("recent_links") or []
                 if isinstance(r, dict) and r.get("transport") in transports.BY_ID
                 and transports.link_of(r) != current][:_RECENT_SHOWN]
        c = self.ctx.theme_tokens()
        for i, b in enumerate(self._recent_btns):
            if i < len(items):
                link = items[i]
                b._link = link
                b.setText("  " + transports.summary(link) + f" · ID {link.get('slave_id', 1)}")
                b.setIcon(icons.icon("network" if transports.get(link["transport"]).network
                                     else "plug", c["text_3"], 13))
                b.setVisible(True)
            else:
                b._link = None
                b.setVisible(False)
        self.box_recent.setVisible(bool(items))

    def _load_recent(self, btn):
        link = getattr(btn, "_link", None)
        if not link:
            return
        merged = dict(self.ctx.settings)
        merged.update(link)
        self.load(merged)
        self._clear_result()
        self._sync_state()
        self._fit()

    def _validate(self) -> bool:
        d = self.draft()
        t = self.ctx.t
        if transports.get(d["transport"]).network and not d["host"]:
            set_state(self.ed_host, "error")
            self.ed_host.setFocus()
            self._show_result("error", t("connNeedHost"))
            return False
        if d["transport"] == "serial" and not d["port"]:
            self._show_result("error", t("connNeedPort"))
            return False
        return True

    def _primary(self):
        core = self.ctx.core
        if core.is_running and not self.changed():
            self._handled = True
            self.hide()
            self.disconnect_requested.emit()
            return
        if not self._validate():
            return
        self._handled = True
        draft = self.draft()
        self.hide()
        self.connect_requested.emit(draft)

    def _open_settings(self):
        self._commit()
        self.hide()
        self.settings_requested.emit()

    def _find(self):
        self._commit()
        self.hide()
        self.find_requested.emit()

    def _commit(self):
        if not self._handled and self.changed():
            self._handled = True
            self.committed.emit(self.draft())

    # ── the link test ─────────────────────────────────────────────────
    def run_test(self):
        if self._testing or not self._validate():
            return
        draft = self.draft()
        core = self.ctx.core
        area, addr = linktest.probe_target(self._registers_fn())
        unit = int(draft["slave_id"])
        if core.is_running:
            if not self.changed():
                job = lambda: self._probe_via_core(core, area, addr, unit)
            elif (not transports.is_network(draft)
                  and not transports.is_network(self.ctx.settings)
                  and draft["port"].casefold()
                  == str(self.ctx.settings.get("port", "")).casefold()):
                self._show_result("warn", self.ctx.t("connBusyPort"))
                return
            else:
                job = lambda: self._probe_alone(draft, unit, area, addr)
        else:
            job = lambda: self._probe_alone(draft, unit, area, addr)
        self._testing = True
        self._test_seq += 1
        seq = self._test_seq
        self._clear_result()
        self._sync_state()
        relay = self._relay

        def work():
            try:
                report = job()
            except Exception as e:                # never leave "Testing…" up
                report = linktest.LinkReport("open_fail", unit=unit, kind="other",
                                             error_text=str(e))
            relay.done.emit((seq, report, draft, area, addr))

        threading.Thread(target=work, daemon=True, name="link-test").start()

    def _timeout(self) -> float:
        try:
            ms = float(self.ctx.settings.get("timeout", 1000))
        except (TypeError, ValueError):
            ms = 1000.0
        return min(5.0, max(0.3, ms / 1000.0))

    def _probe_alone(self, draft, unit, area, addr):
        settings = dict(self.ctx.settings)
        settings.update(draft)
        return linktest.run(settings, unit, self._timeout(), area, addr)

    def _probe_via_core(self, core, area, addr, unit):
        import time
        key = (datatypes.AREAS[area].code << 16) | addr
        t0 = time.perf_counter()
        try:
            got = core.request_op("ping", key, "SHORT", slave=unit,
                                  timeout=self._timeout() * 3 + 2)
        except RuntimeError as e:
            return linktest.LinkReport("open_fail", unit=unit, kind="closed",
                                       error_text=str(e))
        ms = got.get("ms") or (time.perf_counter() - t0) * 1000.0
        state = got.get("state")
        if state == "ok":
            return linktest.LinkReport("ok", unit=unit, ms=ms)
        if state == "exception":
            return linktest.LinkReport("exception", unit=unit, ms=ms,
                                       exception_code=got.get("code", 0))
        return linktest.LinkReport("garbled" if state == "crc" else "silent", unit=unit)

    def _on_test_done(self, payload):
        seq, report, draft, area, addr = payload
        if seq != self._test_seq:
            return
        self._testing = False
        self._sync_state()
        t = self.ctx.t
        tid = draft["transport"]
        self._suggestion = None
        more = ""
        if report.status == "ok":
            self._show_result("ok", t("connTestOk").format(ms=f"{report.ms:.0f}"))
            return
        if report.status == "exception":
            text = t("connTestExc").format(
                name=linktest.exception_name(report.exception_code, t),
                code=report.exception_code)
            if report.exception_code == 2:
                key = (datatypes.AREAS[area].code << 16) | addr
                more = t("connTestExcAddr").format(addr=datatypes.key_label(key))
            self._show_result("ok", text, more)
            return
        if report.status == "open_fail":
            why = linktest.why(report.kind, draft, report.error_text, t)
            text = t("connTestFail").format(why=why)
        elif report.status == "garbled":
            text = t("connTestGarbledTcp" if tid == "tcp" else "connTestGarbled")
        else:
            text = t({"tcp": "connTestSilentTcp", "rtu_tcp": "connTestSilentRtuTcp",
                      transports.SIM_ID: "connTestSilentSim"}
                     .get(tid, "connTestSilentSerial")).format(id=report.unit)
        if report.suggest_unit is not None:
            self._suggestion = ("unit", report.suggest_unit)
            more = t("connSuggestUnit").format(unit=report.suggest_unit)
        elif report.suggest_transport:
            self._suggestion = ("transport", report.suggest_transport)
            more = t("connSuggestRtuTcp" if report.suggest_transport == "rtu_tcp"
                     else "connSuggestTcp")
        self._show_result("warn" if self._suggestion or report.status != "open_fail"
                          else "error", text, more)

    def _take_suggestion(self):
        kind, value = self._suggestion or (None, None)
        if kind == "unit":
            self.sp_id.setValue(int(value))
        elif kind == "transport":
            self.seg.setValue(value)
        self._suggestion = None
        self._clear_result()
        self.run_test()

    # ── the result banner ─────────────────────────────────────────────
    def _show_result(self, state: str, text: str, more: str = ""):
        c = self.ctx.theme_tokens()
        color = {"ok": c["ok"], "warn": c["warn"], "error": c["error"]}[state]
        glyph = {"ok": "check", "warn": "warning", "error": "x"}[state]
        self.ico_result.setPixmap(icons.pixmap(glyph, color, 16))
        self.lbl_result.setText(text)
        self.lbl_result_more.setText(more)
        self.lbl_result_more.setVisible(bool(more))
        set_state(self.box_result, state)
        set_state(self.lbl_result, state)
        sug = self._suggestion
        if sug:
            t = self.ctx.t
            self.btn_suggest.setText(t("connUseUnit").format(unit=sug[1])
                                     if sug[0] == "unit" else t("connSwitch"))
        self.btn_suggest.setVisible(bool(sug))
        # inner width: card − margins − banner padding − icon − gaps
        width = _CARD_WIDTH - 2 * 18 - 2 * 10 - 16 - 10
        if sug:
            width -= self.btn_suggest.sizeHint().width() + 10
        for lb in (self.lbl_result, self.lbl_result_more):
            lb.setFixedWidth(width)
        self.box_result.setVisible(True)
        self._fit()

    def _clear_result(self):
        self._suggestion = None
        self.box_result.setVisible(False)
        self._fit()

    def _fit(self):
        """Size the card to its content at its fixed width.

        adjustSize() and the layouts' height-for-width both measured the
        word-wrapped rows wrong once the card had been shown in another
        state (another transport, another result) — rows came out squeezed
        or with holes. Every wrapped label has a fixed width, so its height
        is known exactly: it is measured here and FIXED, and the card is
        then simply the sum of its rows."""
        for lb in (self.lbl_net_hint, self.lbl_id_hint, self.lbl_result,
                   self.lbl_result_more):
            if not (lb.wordWrap() and lb.maximumWidth() == lb.minimumWidth()):
                continue
            lb.ensurePolished()                   # the QSS font, not the default
            lb.setMinimumHeight(0)
            lb.setMaximumHeight(16777215)
            lb.setFixedHeight(lb.heightForWidth(lb.maximumWidth()) if lb.text() else 0)
        lo = self.layout()
        _invalidate_tree(lo)                      # nested layouts cache their hints
        lo.activate()
        h = max(lo.totalSizeHint().height(), lo.totalMinimumSize().height())
        self.setFixedSize(_CARD_WIDTH, h)
        # Lay the children out NOW: a hidden popup keeps the geometry of
        # its previous state (another transport) until something forces it.
        lo.setGeometry(QRect(0, 0, _CARD_WIDTH, h))

    def showEvent(self, e):
        super().showEvent(e)
        self._fit()

    def hideEvent(self, e):
        self._commit()
        super().hideEvent(e)

    def apply_theme(self):
        c = self.ctx.theme_tokens()
        self.btn_settings.setIcon(icons.icon("sliders", c["text_2"], 15))
        self.btn_find.setIcon(icons.icon("radar", c["text_3"], 13))
        self.btn_refresh.setIcon(icons.icon("refresh", c["text_2"], 14))
        self._sync_state()
        self._fill_recent()

    def retranslate(self, t):
        self.lbl_title.setText(t("connTitle"))
        for tid, key in (("serial", "connSerial"), ("tcp", "connTcp"),
                         ("rtu_tcp", "connRtuTcp"), (transports.SIM_ID, "connSim")):
            self.seg._buttons[tid].setText(t(key))
        self.lbl_port.setText(t("port"))
        self.lbl_baud.setText(t("baudrate"))
        self.lbl_parity.setText(t("parity"))
        self.lbl_stop.setText(t("stopbits"))
        self.lbl_host.setText(t("connHost"))
        self.lbl_tcp_port.setText(t("connTcpPort"))
        self.btn_find.setText(" " + t("connFindNet"))
        self.lbl_recent.setText(t("connRecent").upper())
        self.btn_settings.setToolTip(t("connAllSettings"))
        self.btn_refresh.setToolTip(t("connRefreshPorts"))
        self._show_blocks()
        self.apply_theme()
