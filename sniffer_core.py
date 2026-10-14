# sniffer_core.py
"""Passive Modbus RTU bus sniffer.

Listens on a serial port WITHOUT ever transmitting, splits the byte stream
into frames by inter-frame silence (the RTU t3.5 rule), validates CRC16 and
decodes the common function codes. Designed for tapping the line between a
third-party master and a device (or watching this app's own exchange from a
second adapter).

Pure, testable pieces:
    crc16(data)          — Modbus CRC-16 (poly 0xA001, init 0xFFFF)
    decode_frame(raw)    — bytes -> dict (slave, fc, kind, describe, crc_ok)
The `SnifferWorker` QThread owns the serial port (its OWN port — the
one-port-one-owner rule holds: gui_sniffer refuses to open the port the
master is currently polling)."""

import time

from PyQt6.QtCore import QThread, pyqtSignal

FC_NAMES = {
    0x01: "Read Coils", 0x02: "Read Discrete", 0x03: "Read Holding",
    0x04: "Read Input", 0x05: "Write Coil", 0x06: "Write Register",
    0x08: "Diagnostics", 0x0F: "Write Coils", 0x10: "Write Registers",
    0x16: "Mask Write", 0x17: "Read/Write",
}


def _make_crc_table() -> tuple:
    table = []
    for i in range(256):
        crc = i
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
        table.append(crc)
    return tuple(table)


_CRC_TABLE = _make_crc_table()


def crc16(data: bytes) -> int:
    """Modbus RTU CRC-16 (poly 0xA001 reflected, init 0xFFFF)."""
    crc = 0xFFFF
    for byte in data:
        crc = (crc >> 8) ^ _CRC_TABLE[(crc ^ byte) & 0xFF]
    return crc


def frame_crc_ok(raw: bytes) -> bool:
    if len(raw) < 4:
        return False
    return crc16(raw[:-2]) == raw[-2] | (raw[-1] << 8)   # CRC is little-endian


# Shortest legal RTU frame: id + fc + crc.
_MIN_FRAME = 4
# Longest legal RTU ADU is 256 bytes. A buffer far past that means the line
# never fell silent (wrong baud rate, a chattering device): it is flushed as
# it is instead of growing without bound.
MAX_BUFFER = 1024


def carve_frames(raw: bytes) -> list:
    """Split a captured buffer into CRC-valid frames.

    Timing alone is not enough on a busy line: a master that answers back to
    back, or a USB adapter that hands over a big chunk at once, merges several
    frames into one buffer and every one of them then reads as junk. CRC is the
    ground truth — walk forward and cut wherever the checksum closes a frame.

    Returns the list of frames found; a trailing remainder that does not
    validate is returned as its own (bad-CRC) piece, so nothing is silently
    dropped. A buffer that yields no valid frame comes back unchanged.

    The CRC is carried forward byte by byte for each candidate start, so a
    scan is linear in the buffer length. Recomputing it from scratch for every
    candidate end made a long junk buffer cubic — seconds of CPU per flush."""
    out, start = [], 0
    n = len(raw)
    table = _CRC_TABLE
    while start + _MIN_FRAME <= n:
        crc = 0xFFFF
        for b in raw[start:start + 2]:                  # id + function code
            crc = (crc >> 8) ^ table[(crc ^ b) & 0xFF]
        cut = None
        j = start + 2                                   # first CRC byte
        while j + 2 <= n:
            if crc == raw[j] | (raw[j + 1] << 8):
                cut = j + 2
                break
            crc = (crc >> 8) ^ table[(crc ^ raw[j]) & 0xFF]
            j += 1
        if cut is None:
            break
        out.append(raw[start:cut])
        start = cut
    if not out:
        return [raw]
    if start < n:
        out.append(raw[start:])            # leftover: reported, not swallowed
    return out


def decode_frame(raw: bytes) -> dict:
    """Decode one captured RTU frame into a display dict.

    Direction is a heuristic (a passive tap can't know who transmitted): for
    FC 01-04 an 8-byte frame parses as a request (addr+count) and a
    bytecount+data frame as a response. Ambiguous frames are labelled by what
    they parse as."""
    info = {
        "raw": raw,
        "hex": " ".join(f"{b:02X}" for b in raw),
        "slave": raw[0] if raw else None,
        "fc": raw[1] if len(raw) > 1 else None,
        "crc_ok": frame_crc_ok(raw),
        "kind": "?",
        "describe": "",
    }
    if len(raw) < 4:
        info["kind"] = "junk"
        # Descriptions are i18n KEYS (+ params) — the view translates them, so
        # this module stays pure and language-agnostic.
        info["describe_key"] = "snifShortFrame"
        return info
    fc = raw[1]
    body = raw[2:-2]
    info["fc_name"] = FC_NAMES.get(fc & 0x7F, f"FC {fc & 0x7F:02X}")
    if fc >= 0x80:                                     # exception response
        info["kind"] = "exception"
        code = body[0] if body else 0
        info["describe_key"] = "snifException"
        info["describe_args"] = {"code": f"{code:#04x}"}
        return info
    if fc in (0x03, 0x04):
        if len(raw) == 8:                              # addr + count
            addr, count = int.from_bytes(body[0:2], "big"), int.from_bytes(body[2:4], "big")
            info["kind"] = "request"
            info["describe"] = f"addr 0x{addr:04X}, count {count}"
        elif body and len(body) == 1 + body[0]:        # bytecount + data
            words = [int.from_bytes(body[1 + i:3 + i], "big")
                     for i in range(0, body[0], 2)]
            info["kind"] = "response"
            info["describe"] = ("data " + " ".join(f"{w:04X}" for w in words[:8])
                                + (" …" if len(words) > 8 else ""))
        else:
            info["describe_key"] = "snifOddLength"
    elif fc in (0x01, 0x02):
        if len(raw) == 8:                              # addr + count
            addr, count = int.from_bytes(body[0:2], "big"), int.from_bytes(body[2:4], "big")
            info["kind"] = "request"
            info["describe"] = f"addr 0x{addr:04X}, count {count}"
        elif body and len(body) == 1 + body[0]:        # bytecount + packed bits
            bits = "".join("1" if (byte >> i) & 1 else "0"
                           for byte in body[1:] for i in range(8))
            info["kind"] = "response"
            info["describe"] = ("bits " + bits[:32] + (" …" if len(bits) > 32 else ""))
        else:
            info["describe_key"] = "snifOddLength"
    elif fc == 0x05 and len(raw) == 8:                 # echo: request == response
        addr, value = int.from_bytes(body[0:2], "big"), int.from_bytes(body[2:4], "big")
        info["kind"] = "req/resp"
        state = {0xFF00: "ON", 0x0000: "OFF"}.get(value, f"0x{value:04X}?")
        info["describe"] = f"coil 0x{addr:04X} = {state}"
    elif fc == 0x0F:
        if len(raw) == 8:                              # response: addr + count
            addr, count = int.from_bytes(body[0:2], "big"), int.from_bytes(body[2:4], "big")
            info["kind"] = "response"
            info["describe"] = f"coils 0x{addr:04X}, count {count}"
        elif len(body) >= 5 and len(body) == 5 + body[4]:
            addr, count = int.from_bytes(body[0:2], "big"), int.from_bytes(body[2:4], "big")
            info["kind"] = "request"
            info["describe"] = f"coils 0x{addr:04X}, count {count}"
        else:
            info["describe_key"] = "snifOddLength"
    elif fc == 0x06 and len(raw) == 8:                 # echo: request == response
        addr, value = int.from_bytes(body[0:2], "big"), int.from_bytes(body[2:4], "big")
        info["kind"] = "req/resp"
        info["describe"] = f"addr 0x{addr:04X} = {value} (0x{value:04X})"
    elif fc == 0x10:
        if len(raw) == 8:                              # response: addr + count
            addr, count = int.from_bytes(body[0:2], "big"), int.from_bytes(body[2:4], "big")
            info["kind"] = "response"
            info["describe"] = f"addr 0x{addr:04X}, count {count}"
        elif len(body) >= 5 and len(body) == 5 + body[4]:
            addr, count = int.from_bytes(body[0:2], "big"), int.from_bytes(body[2:4], "big")
            info["kind"] = "request"
            info["describe"] = f"addr 0x{addr:04X}, count {count}"
        else:
            info["describe_key"] = "snifOddLength"
    else:
        info["describe_key"] = "snifBytes"
        info["describe_args"] = {"n": len(raw)}
    return info


class SnifferWorker(QThread):
    """Owns its serial port; splits the stream on t3.5 silence and emits
    decoded frames. Never writes a single byte to the line."""

    frame_captured = pyqtSignal(dict)
    error = pyqtSignal(object)      # (i18n_key, params) — the view translates
    stopped = pyqtSignal()

    def __init__(self, port: str, baudrate: int, parity: str = "N",
                 stopbits: int = 1, parent=None):
        super().__init__(parent)
        self.port = port
        self.baudrate = int(baudrate)
        self.parity = parity
        self.stopbits = int(stopbits)
        self._stop = False

    def request_stop(self):
        self._stop = True

    def run(self):
        try:
            import serial
            ser = serial.Serial(
                self.port, self.baudrate, parity=self.parity,
                stopbits=self.stopbits, timeout=0.001)
        except Exception as e:
            self.error.emit(("snifPortFail", {"err": str(e)}))
            self.stopped.emit()
            return

        # t3.5: 3.5 char times (11 bits/char), but никогда меньше 1.75 мс.
        gap = max(0.00175, 3.5 * 11.0 / self.baudrate)
        buf = bytearray()
        last_rx = time.monotonic()
        try:
            while not self._stop:
                chunk = ser.read(256)
                now = time.monotonic()
                if chunk:
                    # Silence before this chunk closed the previous frame.
                    if buf and (now - last_rx) > gap:
                        self._flush(buf)
                    buf.extend(chunk)
                    last_rx = now
                    if len(buf) > MAX_BUFFER:
                        self._flush(buf)        # the line never went quiet
                elif buf and (now - last_rx) > gap:
                    self._flush(buf)
        except Exception as e:
            # The adapter can be unplugged mid-capture; report it instead of
            # letting the thread die with a bare traceback.
            self.error.emit(("snifReadFail", {"err": str(e)}))
        finally:
            self._flush(buf)
            try:
                ser.close()
            except Exception:
                pass
            self.stopped.emit()

    def _flush(self, buf: bytearray):
        """Emit whatever the buffer holds, split on CRC boundaries."""
        if not buf:
            return
        for frame in carve_frames(bytes(buf)):
            self.frame_captured.emit(decode_frame(frame))
        buf.clear()
