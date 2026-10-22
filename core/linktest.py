# core/linktest.py
"""«Проверить связь»: one request to the device, and a diagnosis in words.

The connection card runs this before (or instead of) connecting, so a wrong
setting is named before the operator stares at a table of dashes:

    open_fail  the link did not open — WHY comes from
               modbus_client.link_error_kind (refused / timeout / resolve …)
    ok         the device answered with data
    exception  the device answered with a Modbus exception — the link
               works, the register is just not there
    silent     the link opened, nobody answered
    garbled    something answered, but not a valid Modbus answer

Things a newcomer to Modbus TCP cannot know are tried on the spot:
* a TCP device that keeps silent may want unit id 1, 255 or 0 instead;
* "Modbus TCP" and "RTU over TCP" look the same from the outside (an IP
  and a port) but frame differently — when one stays silent, the other is
  tried, and the card offers to switch.

Pure Python, no Qt: the card calls ``run`` from a worker thread.
"""
import time
from dataclasses import dataclass

from core import datatypes
from core import transports
from core.modbus_client import ModbusLinkError

# Unit ids a TCP device addressed by its IP usually answers to.
UNIT_GUESSES = (1, 255, 0)

_READERS = {"holding": "read_holding_registers", "input": "read_input_registers",
            "coil": "read_coils", "discrete": "read_discrete_inputs"}


@dataclass
class LinkReport:
    status: str                    # ok | exception | silent | garbled | open_fail
    unit: int = 1                  # the device address that was asked
    ms: float | None = None        # answer time
    kind: str = ""                 # open_fail: link_error_kind
    error_text: str = ""           # open_fail: the OS text
    exception_code: int = 0
    suggest_unit: int | None = None          # TCP: this unit id answers
    suggest_transport: str | None = None     # the other framing answers

    @property
    def alive(self) -> bool:
        return self.status in ("ok", "exception")


def probe_target(registers) -> tuple:
    """(area key, address) to ask: the first register of the open map — a
    device may keep silent about an address it does not have — or holding
    register 0 when there is no map."""
    for reg in registers or []:
        if not isinstance(reg, dict):
            continue
        try:
            area = datatypes.area_of(reg)
            return area.key, int(reg.get("addr", 0)) & 0xFFFF
        except (TypeError, ValueError, KeyError):
            continue
    return "holding", 0


def _ask(client, area: str, addr: int, unit: int):
    fn = getattr(client, _READERS.get(area, "read_holding_registers"))
    t0 = time.monotonic()
    res = fn(address=addr, count=1, device_id=unit)
    return res, (time.monotonic() - t0) * 1000.0


def run(settings: dict, unit: int, timeout: float, area: str = "holding",
        addr: int = 0, guess: bool = True) -> LinkReport:
    """Open the link *settings* describe, ask once, close. *guess* lets it
    try other unit ids / the other TCP framing when the device is silent."""
    unit = int(unit)
    transport = transports.active(settings)
    client = transport.create(settings, timeout)
    if not client.connect():
        return LinkReport("open_fail", unit=unit,
                          kind=getattr(client, "last_error", "") or "other",
                          error_text=getattr(client, "last_error_text", ""))
    try:
        try:
            res, ms = _ask(client, area, addr, unit)
        except ModbusLinkError as e:
            report = LinkReport("open_fail", unit=unit, kind="closed", error_text=str(e))
        else:
            if res.outcome == "ok":
                return LinkReport("ok", unit=unit, ms=ms)
            if res.outcome == "exception":
                return LinkReport("exception", unit=unit, ms=ms,
                                  exception_code=res.exception_code)
            report = LinkReport("garbled" if res.outcome == "crc" else "silent", unit=unit)
        if guess and transport.transport_id == "tcp" and report.status != "open_fail":
            report.suggest_unit = _guess_unit(client, area, addr, unit)
    finally:
        client.close()
    if guess and transport.network and report.suggest_unit is None:
        report.suggest_transport = _guess_framing(settings, transport.transport_id,
                                                  unit, timeout, area, addr)
    return report


def _guess_unit(client, area, addr, unit):
    for other in UNIT_GUESSES:
        if other == unit:
            continue
        try:
            res, _ms = _ask(client, area, addr, other)
        except ModbusLinkError:
            return None
        if res.outcome in ("ok", "exception"):
            return other
    return None


def _guess_framing(settings, current, unit, timeout, area, addr):
    other = "rtu_tcp" if current == "tcp" else "tcp"
    trial = dict(settings, transport=other)
    client = transports.get(other).create(trial, timeout)
    if not client.connect():
        return None
    try:
        res, _ms = _ask(client, area, addr, unit)
        return other if res.outcome in ("ok", "exception") else None
    except ModbusLinkError:
        return None
    finally:
        client.close()


# ── words ─────────────────────────────────────────────────────────────
# i18n key per link_error_kind: why a link did not open.
WHY_KEYS = {
    "resolve": "linkWhyResolve", "refused": "linkWhyRefused",
    "timeout": "linkWhyTimeout", "unreachable": "linkWhyUnreachable",
    "closed": "linkWhyClosed", "busy": "linkWhyBusy", "denied": "linkWhyDenied",
    "missing": "linkWhyMissing",
}

# i18n key per Modbus exception code (what the device said).
EXCEPTION_KEYS = {1: "excIllegalFunction", 2: "excIllegalAddress",
                  3: "excIllegalValue", 4: "excDeviceFailure",
                  6: "excBusy", 10: "excGatewayPath", 11: "excGatewayTarget"}


def why(kind: str, settings: dict, error_text: str, t) -> str:
    """Why the link did not open, in the operator's words (*t* translates)."""
    key = WHY_KEYS.get(kind)
    params = {"port": settings.get("port", ""),
              "host": transports.host_value(settings),
              "tcp_port": transports.tcp_port_value(settings.get("tcp_port")),
              "err": error_text}
    if key is None:
        return error_text or t("linkWhyOther")
    try:
        return t(key).format(**params)
    except (KeyError, IndexError, ValueError):
        return t(key)


def exception_name(code: int, t) -> str:
    key = EXCEPTION_KEYS.get(int(code))
    return t(key) if key else f"0x{int(code):02X}"
