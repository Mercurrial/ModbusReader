# core/transports.py
"""Registry of Modbus transports — the single source of truth for *how* the
Modbus client is built and how the active link is described.

Descriptor + Registry style (mirrors datatypes.py / commands.py): each transport
is one frozen ``Transport`` descriptor in ``TRANSPORTS``. ``ModbusCore`` is
transport-agnostic — it never names a concrete client class; it picks a
descriptor by id (the ``transport`` setting) and calls ``.create()`` /
``.describe()``. The clients are the app's own (core/modbus_client) and offer
the same request API (``read_holding_registers`` / ``write_register`` …) over
every link.

    serial   Modbus RTU on a COM port (RS-485 / RS-232 adapter)
    tcp      Modbus TCP: MBAP header, no CRC — PLCs, meters, gateways
    rtu_tcp  RTU frames through a TCP socket — a serial-to-Ethernet
             converter in transparent mode (USR, Moxa NPort "TCP server")
    sim      the demo project's made-up device (core/simulator.py) — opens
             only while the demo project is open; never a «recent» link

Adding a transport = adding ONE descriptor here. Nothing in ModbusCore changes.

Notes
-----
* ``retries=1`` (one repeat of an unanswered request) is passed on purpose:
  ModbusCore keeps its own authoritative "failed polls in a row" counter, and
  more client-side repeats would multiply it (with pymodbus' default a
  configured "3" once became ~10).
* ``timeout`` is supplied by ModbusCore (the «Таймаут ответа» setting); the
  factory stays agnostic about where it comes from.
* The device address is the ``slave_id`` setting for every transport. Over
  TCP it travels as the MBAP unit id, where 0 and 255 are legal too (a
  device addressed by its IP often expects one of them) — ``id_range``.
"""
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class Transport:
    """One pluggable Modbus link.

    transport_id  settings value that selects this transport
    label         short, language-neutral name (the header chip, logs)
    create        (settings: dict, timeout: float) -> a Modbus client, not yet
                  connected (the caller calls ``.connect()``)
    describe      (settings: dict) -> human link string, e.g. "COM1 (115200)"
    network       True when the link is a TCP connection (host + port)
    """
    transport_id: str
    label: str
    create: Callable
    describe: Callable
    network: bool = False


# ── serial / RTU ──────────────────────────────────────────────────────
# Parity reaches us in every shape the app has ever stored: the settings page
# writes "Even (E)", older files hold "Even" or a bare "E". All of them must
# become the single letter pyserial takes.
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
    from core.modbus_client import RtuMaster
    return RtuMaster(
        str(settings.get("port", "COM1")).strip() or "COM1",
        baudrate=baudrate_value(settings.get("baudrate", 115200)),
        stopbits=stopbits_value(settings.get("stopbits", 1)),
        parity=parity_code(settings.get("parity", "N")),
        timeout=timeout, retries=1,
    )


def _describe_serial(settings):
    return f'{settings.get("port", "COM1")} ({settings.get("baudrate", 115200)})'


# ── TCP ───────────────────────────────────────────────────────────────
DEFAULT_TCP_PORT = 502


def tcp_port_value(value) -> int:
    """Stored TCP port → 1…65535; garbage falls back to 502."""
    try:
        v = int(float(str(value).strip()))
    except (TypeError, ValueError):
        return DEFAULT_TCP_PORT
    return v if 1 <= v <= 65535 else DEFAULT_TCP_PORT


def host_value(settings) -> str:
    """The host to connect to, as typed (an IP or a name); "" when unset."""
    return str(settings.get("host", "") or "").strip()


def _make_tcp(settings, timeout):
    from core.modbus_client import TcpMaster
    return TcpMaster(host_value(settings),
                     port=tcp_port_value(settings.get("tcp_port", DEFAULT_TCP_PORT)),
                     timeout=timeout, retries=1)


def _make_rtu_tcp(settings, timeout):
    from core.modbus_client import RtuOverTcpMaster
    return RtuOverTcpMaster(host_value(settings),
                            port=tcp_port_value(settings.get("tcp_port", DEFAULT_TCP_PORT)),
                            timeout=timeout, retries=1)


def host_port(settings) -> str:
    """"192.168.1.20:502" — "?" stands in for a host not set yet."""
    port = tcp_port_value(settings.get("tcp_port", DEFAULT_TCP_PORT))
    host = host_value(settings) or "?"
    if ":" in host and not host.startswith("["):   # an IPv6 literal
        host = f"[{host}]"
    return f"{host}:{port}"


# ── the demo's simulated device ───────────────────────────────────────
def _make_sim(settings, timeout):
    from core.simulator import SimMaster
    return SimMaster(timeout=timeout, retries=1)


def _describe_sim(settings):
    return "SIM"


# ── the registry (declaration order = preference order) ───────────────
TRANSPORTS: tuple = (
    Transport("serial",  "RTU",     _make_serial,  _describe_serial),
    Transport("tcp",     "TCP",     _make_tcp,     host_port, network=True),
    Transport("rtu_tcp", "RTU/TCP", _make_rtu_tcp, host_port, network=True),
    Transport("sim",     "SIM",     _make_sim,     _describe_sim),
)
SIM_ID = "sim"

BY_ID = {t.transport_id: t for t in TRANSPORTS}
DEFAULT_ID = "serial"


def get(transport_id) -> Transport:
    """Return the ``Transport`` for *transport_id*, falling back to serial."""
    return BY_ID.get(transport_id, BY_ID[DEFAULT_ID])


def active(settings) -> Transport:
    """The transport *settings* select."""
    return get(settings.get("transport", DEFAULT_ID))


def is_network(settings) -> bool:
    return active(settings).network


def id_range(settings_or_id) -> tuple:
    """Legal device addresses for the link: 1…247 on a serial line (0 is
    the broadcast, nobody answers it), 0…255 as a TCP unit id."""
    t = get(settings_or_id) if isinstance(settings_or_id, str) else active(settings_or_id)
    return (0, 255) if t.network else (1, 247)


def summary(settings) -> str:
    """The link on one line, for the header chip and the status bar:
    "COM3 · 115200 · 8E1", "TCP · 192.168.1.20:502",
    "RTU/TCP · 10.0.0.7:4001"."""
    t = active(settings)
    if t.network:
        return f"{t.label} · {host_port(settings)}"
    if t.transport_id == SIM_ID:
        return t.label
    return (f"{settings.get('port', 'COM1')} · {settings.get('baudrate', '115200')}"
            f" · {serial_framing(settings)}")


# The settings keys that make up one connection (the recent-links list and
# the connection card read and write exactly these).
LINK_FIELDS = ("transport", "port", "baudrate", "parity", "stopbits",
               "host", "tcp_port", "slave_id")


def link_of(settings) -> dict:
    """The connection *settings* describe — only the keys that matter for
    its transport, so two entries for the same device compare equal."""
    t = active(settings)
    out = {"transport": t.transport_id}
    if t.network:
        out["host"] = host_value(settings)
        out["tcp_port"] = tcp_port_value(settings.get("tcp_port", DEFAULT_TCP_PORT))
    else:
        out["port"] = str(settings.get("port", "COM1")).strip()
        out["baudrate"] = str(baudrate_value(settings.get("baudrate", 115200)))
        out["parity"] = str(settings.get("parity", "None (N)"))
        out["stopbits"] = str(settings.get("stopbits", "1"))
    try:
        out["slave_id"] = int(settings.get("slave_id", 1))
    except (TypeError, ValueError):
        out["slave_id"] = 1
    return out


def _same_link(a: dict, b: dict) -> bool:
    keys = ("transport", "host", "tcp_port", "port", "slave_id")
    return all(a.get(k) == b.get(k) for k in keys)


RECENT_MAX = 6


def remember(recent, settings, when: float = 0.0) -> list:
    """*recent* (a list of link dicts, newest first) with the connection in
    *settings* moved to the front. Garbage entries are dropped, and so is
    the demo's simulated device: it is not a link anyone reconnects to."""
    if active(settings).transport_id == SIM_ID:
        return [i for i in recent if isinstance(i, dict)
                and i.get("transport") in BY_ID and i.get("transport") != SIM_ID
                ][:RECENT_MAX] if isinstance(recent, list) else []
    entry = dict(link_of(settings))
    if when:
        entry["used"] = float(when)
    out = [entry]
    for item in recent if isinstance(recent, list) else []:
        if (not isinstance(item, dict) or item.get("transport") not in BY_ID
                or item.get("transport") == SIM_ID):
            continue
        if _same_link(item, entry):
            continue
        out.append(item)
    return out[:RECENT_MAX]
