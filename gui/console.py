# gui_console.py
"""Raw-frame console — the command input strip under the transaction log.

Two rows:
  «Команда» — frame payload as hex; the Modbus CRC16 is computed live and
              shown in gray next to the field;
  «Пакет»   — the resulting wire packet (payload + CRC), auto-synced from the
              command row but freely editable: garbage/foreign-protocol frames
              are a supported use-case, so what is in THIS row is exactly what
              goes to the port. Manual edits are marked with an «изменён» badge
              until the command row is touched again (which re-syncs).

Enter in either row / the Send button emits ``send_requested(bytes)``; the
window routes it to ModbusCore.queue_raw() (core thread owns the port). The
exchange itself lands in the log as normal TX/RX lines. ↑/↓ recall command
history (persisted in settings via ctx)."""

from PyQt6.QtWidgets import (
    QWidget, QGridLayout, QLabel, QLineEdit, QPushButton,
)
from PyQt6.QtCore import Qt, pyqtSignal

_HISTORY_MAX = 20


def parse_hex(text: str):
    """Free-form hex → bytes. Accepts spaces/commas/«0x» prefixes, any case
    («0A 03», «0a,0x03», «0a030010»). Returns None for invalid/odd input."""
    cleaned = text.replace(",", " ").replace("0x", " ").replace("0X", " ")
    cleaned = "".join(cleaned.split())
    if not cleaned or len(cleaned) % 2:
        return None
    try:
        return bytes.fromhex(cleaned)
    except ValueError:
        return None


def crc16(data: bytes) -> bytes:
    """Modbus RTU CRC16, low byte first (the wire order)."""
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return bytes((crc & 0xFF, crc >> 8))


def fmt_hex(data: bytes) -> str:
    return " ".join(f"{b:02X}" for b in data)


class RawConsole(QWidget):
    """The two-row console strip. Emits send_requested(bytes)."""

    send_requested = pyqtSignal(bytes)

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self._syncing = False          # guard against edit-loop recursion
        self._manual = False           # packet row was hand-edited
        self._hist_pos = len(self._history)
        self.setObjectName("console")
        self._build_ui()
        self.retranslate(ctx.t)

    def _build_ui(self):
        lo = QGridLayout(self)
        lo.setContentsMargins(8, 4, 8, 6)
        lo.setHorizontalSpacing(8)
        lo.setVerticalSpacing(3)

        self.lbl_cmd = QLabel()
        self.lbl_cmd.setObjectName("consoleLabel")
        self.edit_cmd = QLineEdit()
        self.edit_cmd.setObjectName("consoleInput")
        self.edit_cmd.textEdited.connect(self._on_cmd_edited)
        self.edit_cmd.returnPressed.connect(self._send)
        self.edit_cmd.installEventFilter(self)
        self.lbl_crc = QLabel("CRC: —")
        self.lbl_crc.setObjectName("consoleCrc")

        self.lbl_pkt = QLabel()
        self.lbl_pkt.setObjectName("consoleLabel")
        self.edit_pkt = QLineEdit()
        self.edit_pkt.setObjectName("consoleInput")
        self.edit_pkt.textEdited.connect(self._on_pkt_edited)
        self.edit_pkt.returnPressed.connect(self._send)
        self.lbl_edited = QLabel()
        self.lbl_edited.setObjectName("consoleEdited")
        self.lbl_edited.setVisible(False)
        self.btn_send = QPushButton()
        self.btn_send.setObjectName("consoleSend")
        self.btn_send.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_send.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_send.clicked.connect(self._send)

        lo.addWidget(self.lbl_cmd,    0, 0)
        lo.addWidget(self.edit_cmd,   0, 1)
        lo.addWidget(self.lbl_crc,    0, 2)
        lo.addWidget(self.lbl_pkt,    1, 0)
        lo.addWidget(self.edit_pkt,   1, 1)
        lo.addWidget(self.lbl_edited, 1, 2)
        # Spans both rows: it sends whichever line you are on, and centred
        # between them it no longer hangs off the second row's baseline.
        lo.addWidget(self.btn_send,   0, 3, 2, 1,
                     alignment=Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)
        lo.setColumnStretch(1, 1)

    # ── command row: live CRC + packet sync ────────────────────────
    def _on_cmd_edited(self, _text=None):
        payload = parse_hex(self.edit_cmd.text())
        self._set_invalid(self.edit_cmd, bool(self.edit_cmd.text().strip()) and payload is None)
        self._manual = False
        self.lbl_edited.setVisible(False)
        self._syncing = True
        if payload is None:
            self.lbl_crc.setText("CRC: —")
            self.edit_pkt.setText("")
        else:
            crc = crc16(payload)
            self.lbl_crc.setText(f"CRC: {fmt_hex(crc)}")
            self.edit_pkt.setText(fmt_hex(payload + crc))
        self._set_invalid(self.edit_pkt, False)
        self._syncing = False

    def _on_pkt_edited(self, _text=None):
        if self._syncing:
            return
        self._manual = True
        self.lbl_edited.setVisible(True)
        self._set_invalid(
            self.edit_pkt,
            bool(self.edit_pkt.text().strip()) and parse_hex(self.edit_pkt.text()) is None)

    @staticmethod
    def _set_invalid(edit: QLineEdit, invalid: bool):
        edit.setProperty("invalid", "true" if invalid else "false")
        edit.style().unpolish(edit)
        edit.style().polish(edit)

    # ── history (shared through settings) ──────────────────────────
    # There are two consoles (bottom strip + the full-screen view). Each one
    # used to keep a PRIVATE copy of the history and write it back whole, so
    # whichever sent last overwrote the other's commands. The list now lives
    # in one place — the settings dict — and both read it on every access.
    @property
    def _history(self) -> list:
        hist = self.ctx.settings.get("console_history")
        return hist if isinstance(hist, list) else []

    def reload_history(self):
        """Point the ↑/↓ cursor past the newest entry (after another console
        added to the shared list)."""
        self._hist_pos = len(self._history)

    # ── sending ────────────────────────────────────────────────────
    def _send(self):
        frame = parse_hex(self.edit_pkt.text())
        if not frame:
            self._set_invalid(self.edit_pkt, True)
            return
        self._push_history(self.edit_cmd.text().strip())
        self.send_requested.emit(bytes(frame))

    def _push_history(self, cmd: str):
        hist = list(self._history)
        if cmd:
            # A NEW list is stored, never the old one edited in place: the
            # settings value may still be the very list object that lives in
            # DEFAULT_SETTINGS, and mutating that would leak into every
            # "defaults" copy made afterwards.
            hist = [c for c in hist if c != cmd] + [cmd]
            hist = hist[-_HISTORY_MAX:]
            self.ctx.settings["console_history"] = hist
        self._hist_pos = len(hist)

    # ── ↑/↓ history on the command row ─────────────────────────────
    def eventFilter(self, obj, event):
        if obj is self.edit_cmd and event.type() == event.Type.KeyPress:
            if event.key() == Qt.Key.Key_Up:
                self._recall(-1)
                return True
            if event.key() == Qt.Key.Key_Down:
                self._recall(+1)
                return True
        return super().eventFilter(obj, event)

    def _recall(self, step: int):
        if not self._history:
            return
        self._hist_pos = max(0, min(len(self._history), self._hist_pos + step))
        text = ("" if self._hist_pos == len(self._history)
                else self._history[self._hist_pos])
        self.edit_cmd.setText(text)
        self._on_cmd_edited()

    # ── i18n ───────────────────────────────────────────────────────
    def retranslate(self, t):
        self.lbl_cmd.setText(t("cmdLabel"))
        self.lbl_pkt.setText(t("packetLabel"))
        self.btn_send.setText(t("send"))
        self.lbl_edited.setText(t("editedBadge"))
        self.edit_cmd.setPlaceholderText("0A 03 00 10 00 02")
        self.setToolTip(t("consoleTip"))
