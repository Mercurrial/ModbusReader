# gui/statusbar.py

from PyQt6.QtWidgets import (
    QStatusBar, QLabel, QFrame, QWidget, QGridLayout, QVBoxLayout,
    QHBoxLayout, QLineEdit, QSizePolicy, QPushButton,
)
from PyQt6.QtCore import Qt, QEvent, QSize, QPoint, pyqtSignal
from PyQt6.QtGui import QPainter, QColor

from gui import icons
from gui.qt_utils import set_state


def _ms(v) -> str:
    return "—" if v is None else (f"{v:.0f}" if v >= 10 else f"{v:.1f}")


def _elapsed(sec: float) -> str:
    s = int(max(0, sec))
    return f"{s // 3600:d}:{(s // 60) % 60:02d}:{s % 60:02d}"


class LineStatsChip(QWidget):
    """Bottom-right line statistics: TX · RX · ERR · average response time.
    Click opens the full breakdown (LineStatsPopup)."""

    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("sbStats")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        lo = QHBoxLayout(self)
        lo.setContentsMargins(8, 0, 8, 0)
        lo.setSpacing(4)
        self._vals = {}
        for key in ("tx", "rx", "err", "rt"):
            if key != "rt":
                cap = QLabel(key.upper())
                cap.setObjectName("sbItem")
                lo.addWidget(cap)
            val = QLabel("0" if key != "rt" else "— ms")
            val.setObjectName("sbVal")
            lo.addWidget(val)
            if key != "rt":
                lo.addSpacing(6)
            self._vals[key] = val

    def set_stats(self, snap: dict, ms_unit: str = "ms"):
        self._vals["tx"].setText(str(snap["requests"]))
        self._vals["rx"].setText(str(snap["responses"]))
        err = self._vals["err"]
        err.setText(str(snap["errors"]))
        set_state(err, "error" if snap["errors"] else "idle")
        self._vals["rt"].setText(f"{_ms(snap['rt_avg'])} {ms_unit}")

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(e)


class LineStatsPopup(QFrame):
    """The full line-statistics card, popped up above the chip."""

    reset_requested = pyqtSignal()

    # (snapshot key, i18n key, kind)
    _ROWS = (("requests", "statRequests", "n"), ("responses", "statResponses", "n"),
             ("timeouts", "statTimeouts", "bad"), ("crc", "statCrc", "bad"),
             ("exceptions", "statExceptions", "warn"), ("quality", "statQuality", "pct"),
             ("rt_last", "statRtLast", "ms"), ("rt_avg", "statRtAvg", "ms"),
             ("rt_min", "statRtMin", "ms"), ("rt_max", "statRtMax", "ms"),
             ("elapsed", "statElapsed", "time"))

    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.Popup)
        self.setObjectName("statsCard")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        lo = QVBoxLayout(self)
        lo.setContentsMargins(16, 14, 16, 12)
        lo.setSpacing(8)
        self.lbl_title = QLabel()
        self.lbl_title.setObjectName("statsTitle")
        lo.addWidget(self.lbl_title)
        grid = QGridLayout()
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(4)
        self._keys, self._vals = {}, {}
        for i, (key, _tk, _kind) in enumerate(self._ROWS):
            k = QLabel()
            k.setObjectName("statsKey")
            v = QLabel("—")
            v.setObjectName("statsVal")
            v.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            grid.addWidget(k, i, 0)
            grid.addWidget(v, i, 1)
            self._keys[key], self._vals[key] = k, v
        lo.addLayout(grid)
        self.lbl_hint = QLabel()
        self.lbl_hint.setObjectName("statsHint")
        self.lbl_hint.setWordWrap(True)
        self.lbl_hint.setFixedWidth(300)
        lo.addWidget(self.lbl_hint)
        self.btn_reset = QPushButton()
        self.btn_reset.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_reset.clicked.connect(self.reset_requested.emit)
        lo.addWidget(self.btn_reset, 0, Qt.AlignmentFlag.AlignRight)

    def retranslate(self, t):
        self.lbl_title.setText(t("statTitle"))
        for key, tk, _kind in self._ROWS:
            self._keys[key].setText(t(tk))
        self.lbl_hint.setText(t("statHint"))
        self.btn_reset.setText(t("statReset"))
        self._ms = t("unitMs")

    def set_stats(self, snap: dict):
        ms = getattr(self, "_ms", "ms")
        for key, _tk, kind in self._ROWS:
            v = snap.get(key)
            if kind == "ms":
                text = f"{_ms(v)} {ms}"
            elif kind == "pct":
                text = "—" if v is None else f"{v:.1f} %"
            elif kind == "time":
                text = _elapsed(v or 0)
            else:
                text = str(v)
            lbl = self._vals[key]
            lbl.setText(text)
            if kind in ("bad", "warn"):
                set_state(lbl, ("error" if kind == "bad" else "warn") if v else "")

    def show_above(self, anchor: QWidget):
        self.adjustSize()
        pos = anchor.mapToGlobal(QPoint(anchor.width(), 0))
        self.move(pos.x() - self.width(), pos.y() - self.height() - 6)
        self.show()


class _ConnectionDot(QWidget):
    """6 px circle: theme "ok" green while connected, a muted grey otherwise.

    Disconnected is the normal resting state of the app, not a fault — a red
    dot at rest read as an error before anything had happened."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(10, 10)
        self._connected = False
        self._on = QColor("#42c070")
        self._off = QColor("#868d97")

    def set_colors(self, on: str, off: str):
        self._on, self._off = QColor(on), QColor(off)
        self.update()

    def set_state(self, connected: bool):
        self._connected = connected
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self._on if self._connected else self._off)
        p.drawEllipse(2, 2, 6, 6)


class _SlaveIdEditor(QWidget):
    """Click-to-edit inline Slave ID field: 1–247 on a serial line, 0–255
    as a Modbus TCP unit id (set_range)."""

    value_changed = pyqtSignal(int)

    def __init__(self, value: int = 1, parent=None):
        super().__init__(parent)
        self.setObjectName("sbIdEdit")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(26)
        # Fixed width so toggling between the value label and the edit field
        # never reflows the status bar (was: panel slid right on edit).
        self.setFixedWidth(78)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        self._value   = value
        self._editing = False
        self._lo, self._hi = 1, 247

        lo = QHBoxLayout(self)
        lo.setContentsMargins(4, 0, 4, 0)
        lo.setSpacing(0)

        lbl = QLabel("ID:")
        lbl.setObjectName("sbItem")

        # Left-aligned against its "ID:" — centred in a fixed box it floated
        # a gap away and read as two unrelated labels.
        left = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        self._lbl_val = QLabel(str(value))
        self._lbl_val.setObjectName("sbVal")
        self._lbl_val.setFixedWidth(36)
        self._lbl_val.setAlignment(left)

        self._edit = QLineEdit(str(value))
        self._edit.setObjectName("sbIdInput")
        self._edit.setMaxLength(3)
        self._edit.setFixedWidth(36)
        self._edit.setFixedHeight(18)
        self._edit.setAlignment(left)
        self._edit.hide()
        self._edit.editingFinished.connect(self._commit)
        self._edit.installEventFilter(self)

        lo.addWidget(lbl)
        lo.addWidget(self._lbl_val)
        lo.addWidget(self._edit)
        lo.addStretch(1)                 # spare width goes AFTER the number

    def mousePressEvent(self, _):
        if not self._editing:
            self._start_edit()

    def _start_edit(self):
        self._editing = True
        self._lbl_val.hide()
        self._edit.setText(str(self._value))
        self._edit.show()
        self._edit.setFocus()
        self._edit.selectAll()

    def _commit(self):
        try:
            n = int(self._edit.text())
            if self._lo <= n <= self._hi:
                self._value = n
                self.value_changed.emit(n)
        except ValueError:
            pass
        self._finish()

    def _finish(self):
        self._editing = False
        self._lbl_val.setText(str(self._value))
        self._edit.hide()
        self._lbl_val.show()

    def eventFilter(self, obj, event):
        if obj is self._edit and event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Escape:
                self._edit.setText(str(self._value))
                self._finish()
                return True
        return super().eventFilter(obj, event)

    def set_value(self, value: int):
        self._value = value
        self._lbl_val.setText(str(value))
        if not self._editing:
            self._edit.setText(str(value))

    def set_range(self, lo: int, hi: int):
        self._lo, self._hi = int(lo), int(hi)


class MainStatusBar(QStatusBar):

    slave_id_changed  = pyqtSignal(int)
    log_toggle_clicked = pyqtSignal()   # the "Журнал ▴/▾" chip

    _connected = False
    _conn_label = ""

    def __init__(self, parent=None, initial_slave_id: int = 1):
        super().__init__(parent)
        self.setObjectName("MainStatusBar")
        self.setSizeGripEnabled(False)
        self._build_ui(initial_slave_id)

    # ──────────────────────────────────────── helpers

    def _lbl(self, text: str, obj: str = "sbItem") -> QLabel:
        l = QLabel(text)
        l.setObjectName(obj)
        return l

    def _sep(self) -> QFrame:
        f = QFrame()
        f.setObjectName("sbSep")
        f.setFrameShape(QFrame.Shape.VLine)
        f.setFixedSize(1, 14)
        return f

    # ──────────────────────────────────────── build

    def _build_ui(self, slave_id: int):
        # Left side
        self._conn_dot = _ConnectionDot()
        self.addWidget(self._conn_dot)

        # Texts arrive from the window (it owns the translator).
        self.lbl_status = self._lbl("")
        self.addWidget(self.lbl_status)

        self.addWidget(self._sep())

        self.lbl_config = self._lbl("")
        self.addWidget(self.lbl_config)

        self.addWidget(self._sep())

        self._slave_ed = _SlaveIdEditor(slave_id)
        self._slave_ed.value_changed.connect(self.slave_id_changed.emit)
        self.addWidget(self._slave_ed)

        # The link summary moved to the header bar (2.2); the label stays for
        # the callers that still feed it, but is not shown twice.
        self.lbl_params = self._lbl("")
        self.lbl_params.setVisible(False)

        # Right side (permanent): what the line is doing — requests sent,
        # answers received, failed exchanges, average response time. Click
        # for the breakdown (timeouts / CRC / exceptions, min/max time).
        self.stats_chip = LineStatsChip()
        self.addPermanentWidget(self.stats_chip)
        self.stats_popup = LineStatsPopup(self)
        self.stats_chip.clicked.connect(self._toggle_stats)

        self.addPermanentWidget(self._sep())

        # Terminal show/hide chip — a big, obvious alternative to the tiny
        # layout-menu checkbox in the top-right corner.
        self.btn_log = QPushButton()   # label set by set_log_state (i18n)
        self.btn_log.setObjectName("sbTermBtn")
        self.btn_log.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_log.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_log.setIconSize(QSize(12, 12))
        self.btn_log.clicked.connect(self.log_toggle_clicked.emit)
        self.addPermanentWidget(self.btn_log)
        self._log_label = ""
        self._log_errors = 0

    # ──────────────────────────────────────── public API

    def set_connection_status(self, connected: bool, label: str = ""):
        """*label* comes from the caller because the status bar owns no
        translator; it used to hardcode English here."""
        self._conn_dot.set_state(connected)
        self._connected = connected
        if label:
            self._conn_label = label
        self.lbl_status.setText(getattr(self, "_conn_label", "") or label)

    def set_log_state(self, visible: bool, label: str, icon_color: str):
        """Sync the terminal chip: label + a chevron pointing where a click
        will move the panel (down = collapse, up = expand)."""
        self._log_label = label
        self._render_log_chip()
        self.btn_log.setIcon(icons.icon(
            "chevron" if visible else "chevron_up", icon_color, 12))

    def set_error_count(self, count: int):
        """Errors written to the LOG live on the log chip ("Журнал · 3") —
        the statistics chip next to it counts failed exchanges on the line,
        and two "ERR" counters side by side would read as the same thing."""
        self._log_errors = int(count)
        self._render_log_chip()

    def _render_log_chip(self):
        n = self._log_errors
        self.btn_log.setText(f"  {self._log_label}" + (f"  · {n}" if n else ""))
        set_state(self.btn_log, "error" if n else "")

    # ── line statistics ────────────────────────────────────────────
    def set_line_stats(self, snap: dict, t):
        self.stats_chip.set_stats(snap, t("unitMs"))
        if self.stats_popup.isVisible():
            self.stats_popup.set_stats(snap)
        self._last_snap = snap

    def _toggle_stats(self):
        if self.stats_popup.isVisible():
            self.stats_popup.hide()
            return
        snap = getattr(self, "_last_snap", None)
        if snap is not None:
            self.stats_popup.set_stats(snap)
        self.stats_popup.show_above(self.stats_chip)

    def set_tooltips(self, stats: str, log_errors: str, link: str):
        self.stats_chip.setToolTip(stats)
        self.btn_log.setToolTip(log_errors)
        self.lbl_params.setToolTip(link)

    def apply_theme(self, tokens: dict):
        self._conn_dot.set_colors(tokens.get("ok", "#42c070"),
                                  tokens.get("text_4", "#868d97"))

    def set_slave_id(self, value: int):
        self._slave_ed.set_value(value)

    def set_id_range(self, lo: int, hi: int):
        self._slave_ed.set_range(lo, hi)
