# core/transports.py
"""Registry of Modbus transports — the single source of truth for *how* the
pymodbus client is built and how the active link is described.

Descriptor + Registry style (mirrors datatypes.py / commands.py): each transport
is one frozen ``Transport`` descriptor in ``TRANSPORTS``. ``ModbusCore`` is
transport-agnostic — it never names a concrete pymodbus class; it picks a
descriptor by id (the ``transport`` setting) and calls ``.create()`` /
``.describe()``. The PDU API it uses afterwards (``read_holding_registers`` /
``write_register``) is identical across serial and TCP clients.

Adding a transport = adding ONE descriptor here. Nothing in ModbusCore changes.

Notes
-----
* ``retries=1`` is passed to every client on purpose: ModbusCore keeps its own
  authoritative "failed polls in a row" counter, and pymodbus' built-in retries
  would otherwise multiply it (a configured "3" became ~10).
* ``timeout`` is supplied by ModbusCore (the «Таймаут ответа» setting); the
  factory stays agnostic about where it comes from.
* TCP is implemented but intentionally **not** surfaced in the Settings UI — the
  product is serial-first (the connection dialog shows only Serial / RTU). Select
  it by setting ``"transport": "tcp"`` (+ optional ``host`` / ``tcp_port``) in
  app_settings.json. Surfacing it later = a transport selector field in
  settings_schema.py; no core change.
* Verbose frame logging in ModbusCore assumes RTU framing (slave + PDU + CRC16).
  Over TCP the real wire frame is MBAP-wrapped, so the logged bytes are
  RTU-style — the decoded data shown is still correct.
"""
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class Transport:
    """One pluggable Modbus link.

    transport_id  settings value that selects this transport ("serial" | "tcp")
    label         short, language-neutral name (for logs / a future selector)
    create        (settings: dict, timeout: float) -> a pymodbus client, not yet
                  connected (the caller calls ``.connect()``)
    describe      (settings: dict) -> human link string, e.g. "COM1 (115200)"
    """
    transport_id: str
    label: str
    create: Callable
    describe: Callable


# ── serial / RTU ──────────────────────────────────────────────────────
# Parity reaches us in every shape the app has ever stored: the settings page
# writes "Even (E)", older files hold "Even" or a bare "E". All of them must
# become pymodbus' single letter.
#
# The first version of this map only knew "None"/"Even"/"Odd" — so the value
# the Settings page actually saves, "Even (E)", fell through to the default and
# EVERY connection was opened 8N1 whatever the user picked. Modbus RTU's own
# default is 8E1, so on a typical device the master simply never got an
# answer. Hence one tolerant normaliser, shared with the sniffer.
_PARITY_WORDS = {"none": "N", "even": "E", "odd": "O", "mark": "M",
                 "space": "S"}


def parity_code(value) -> str:
    """Any stored parity spelling → "N" / "E" / "O" / "M" / "S" ("N" if junk)."""
    text = str(value or "").strip()
    if "(" in text and ")" in text:                 # "Even (E)" → "E"
        inner = text[text.index("(") + 1:text.index(")")].strip().upper()
        if inner in ("N", "E", "O", "M", "S"):
            return inner
    low = text.split("(")[0].strip().lower()
    if low in _PARITY_WORDS:
        return _PARITY_WORDS[low]
    up = text.upper()
    return up if up in ("N", "E", "O", "M", "S") else "N"


def stopbits_value(value) -> float:
    """Stored stop bits ("1" / "2" / 1.5) → the number pyserial expects."""
    try:
        v = float(str(value).strip().replace(",", "."))
    except (TypeError, ValueError):
        return 1.0
    return v if v in (1.0, 1.5, 2.0) else 1.0


def baudrate_value(value) -> int:
    """Stored baud rate → int; garbage falls back to 115200 instead of
    raising inside the connection thread (where nobody would see it)."""
    try:
        v = int(float(str(value).strip()))
    except (TypeError, ValueError):
        return 115200
    return v if v > 0 else 115200


def serial_framing(settings) -> str:
    """Compact line framing for the status bar, e.g. "8E1"."""
    stop = stopbits_value(settings.get("stopbits", 1))
    stop_txt = "1.5" if stop == 1.5 else str(int(stop))
    return f"8{parity_code(settings.get('parity', 'N'))}{stop_txt}"


def _make_serial(settings, timeout):
    from pymodbus.client import ModbusSerialClient
    return ModbusSerialClient(
        port=str(settings.get("port", "COM1")).strip() or "COM1",
        baudrate=baudrate_value(settings.get("baudrate", 115200)),
        stopbits=stopbits_value(settings.get("stopbits", 1)),
        parity=parity_code(settings.get("parity", "N")),
        timeout=timeout, retries=1,
    )


def _describe_serial(settings):
    return f'{settings.get("port", "COM1")} ({settings.get("baudrate", 115200)})'


# ── TCP ───────────────────────────────────────────────────────────────
def _make_tcp(settings, timeout):
    from pymodbus.client import ModbusTcpClient
    try:
        port = int(settings.get("tcp_port", 502))
    except (TypeError, ValueError):
        port = 502
    return ModbusTcpClient(
        host=settings.get("host", "127.0.0.1"),
        port=port, timeout=timeout, retries=1,
    )


def _describe_tcp(settings):
    return f'{settings.get("host", "127.0.0.1")}:{settings.get("tcp_port", 502)}'


# ── the registry (declaration order = preference order) ───────────────
TRANSPORTS: tuple = (
    Transport("serial", "Serial / RTU", _make_serial, _describe_serial),
    Transport("tcp",    "TCP",          _make_tcp,    _describe_tcp),
)

BY_ID = {t.transport_id: t for t in TRANSPORTS}
DEFAULT_ID = "serial"


def get(transport_id) -> Transport:
    """Return the ``Transport`` for *transport_id*, falling back to serial."""
    return BY_ID.get(transport_id, BY_ID[DEFAULT_ID])
