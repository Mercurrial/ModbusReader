# gui_statusbar.py

from PyQt6.QtWidgets import (
    QStatusBar, QLabel, QFrame, QWidget,
    QHBoxLayout, QLineEdit, QSizePolicy, QPushButton,
)
from PyQt6.QtCore import Qt, QEvent, QSize, pyqtSignal
from PyQt6.QtGui import QPainter, QColor

import icons


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
    """Click-to-edit inline Slave ID field (1–247)."""

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

        lo = QHBoxLayout(self)
        lo.setContentsMargins(4, 0, 4, 0)
        lo.setSpacing(3)

        lbl = QLabel("ID:")
        lbl.setObjectName("sbItem")

        self._lbl_val = QLabel(str(value))
        self._lbl_val.setObjectName("sbVal")
        self._lbl_val.setFixedWidth(36)
        self._lbl_val.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._edit = QLineEdit(str(value))
        self._edit.setObjectName("sbIdInput")
        self._edit.setMaxLength(3)
        self._edit.setFixedWidth(36)
        self._edit.setFixedHeight(18)
        self._edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._edit.hide()
        self._edit.editingFinished.connect(self._commit)
        self._edit.installEventFilter(self)

        lo.addWidget(lbl)
        lo.addWidget(self._lbl_val)
        lo.addWidget(self._edit)

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
            if 1 <= n <= 247:
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

        self.addWidget(self._sep())

        self.lbl_params = self._lbl("")
        self.addWidget(self.lbl_params)

        # Right side (permanent). The counter counts READINGS received — it
        # used to be labelled "Tx", i.e. the opposite direction.
        self.lbl_tx_rx = self._lbl("RX: 0", "sbVal")
        self.addPermanentWidget(self.lbl_tx_rx)

        self.addPermanentWidget(self._sep())

        # Muted at zero, red only once there is something to look at.
        self.lbl_errors = self._lbl("ERR: 0", "sbVal")
        self.lbl_errors.setProperty("state", "idle")
        self.addPermanentWidget(self.lbl_errors)

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
        self.btn_log.setText(f"  {label}")
        self.btn_log.setIcon(icons.icon(
            "chevron" if visible else "chevron_up", icon_color, 12))

    def update_tx_rx(self, count: int):
        self.lbl_tx_rx.setText(f"RX: {count}")

    def set_error_count(self, count: int):
        self.lbl_errors.setText(f"ERR: {count}")
        state = "error" if count else "idle"
        if self.lbl_errors.property("state") != state:
            self.lbl_errors.setProperty("state", state)
            self.lbl_errors.style().unpolish(self.lbl_errors)
            self.lbl_errors.style().polish(self.lbl_errors)

    def set_tooltips(self, rx: str, err: str, link: str):
        self.lbl_tx_rx.setToolTip(rx)
        self.lbl_errors.setToolTip(err)
        self.lbl_params.setToolTip(link)

    def apply_theme(self, tokens: dict):
        self._conn_dot.set_colors(tokens.get("ok", "#42c070"),
                                  tokens.get("text_4", "#868d97"))

    def set_slave_id(self, value: int):
        self._slave_ed.set_value(value)
