# core/simulator.py
"""The demo project's device: a made-up temperature controller that lives
inside the program — the transport "sim" (core/transports.py).

Only the demo project may use it (the user, 2026-10-28: «демо-проект должен
показывать выдуманные значения, и только у него должна быть такая
симуляция»). The project file says so — ``"simulation": "thermo"`` in
examples/demo*.mbproj (tools/make_demo_project.py) — and the window attaches
the device while that project is open (``attach``) and detaches it for any
other project or map (``detach``). With nothing attached the transport does
not open.

Everything past the "wire" is the real program: the master builds RTU
frames, the emulator's responder (core/slave_core.build_response) answers
them from a SlaveStore, and the model below moves the values in between. So
the log, the line statistics, writes, trends and the dashboard behave as
with a device on a cable — and the device answers its own address only (1,
the demo's), like a real one.

The model reacts to writes: raise the setpoint and the temperature follows
(a PI controller drives the heater); «Стоп» or the heater switched off and
it cools down; the fan and an open door cost heat. Leave the door open
longer than the alarm delay — or let it overheat — and the device goes to
«Авария» with an error code until the mode is set back to «Работа».
"""
import math
import random
import threading
import time

from core import datatypes
from core.slave_core import SlaveStore, build_response
from core.modbus_client import (Response, ModbusLinkError, answer_length,
                                crc16, with_crc, _Client)

KINDS = ("thermo",)
DEVICE_ID = 1                          # the demo's own address
LATENCY_S = (0.006, 0.016)             # how long the made-up device "thinks"

# The demo map, by role (examples/demo.mbproj — tools/make_demo_project.py).
_TEMP, _SETPOINT, _MODE, _POWER, _HOURS = 0x0000, 0x0002, 0x0004, 0x0005, 0x0006
_STATUS, _ERROR, _ALARM_DELAY = 0x0008, 0x0009, 0x000A
_INPUT, _COIL, _DISCRETE = (datatypes.AREAS[k].code << 16 for k in ("input", "coil", "discrete"))
_VOLTAGE, _CURRENT = _INPUT | 0, _INPUT | 1
_HEATER, _FAN, _DOOR = _COIL | 0, _COIL | 1, _DISCRETE | 0

MODE_STOP, MODE_RUN, MODE_FAULT = 0, 1, 2
ERR_NONE, ERR_OVERHEAT, ERR_DOOR = 0, 1, 2

# Status word bits.
BIT_RUN, BIT_HEATING, BIT_AT_SETPOINT, BIT_FAN, BIT_DOOR, BIT_FAULT = range(6)


class ThermoModel:
    """A small oven: heater power in, temperature out.

    dT/dt = heat · power − loss · (T − ambient) − fan and door losses, with
    a PI controller choosing the power while the mode is «Работа» and the
    heater is switched on. A slow drift of the room temperature keeps the
    trend from being a flat line; the door opens now and then by itself."""

    AMBIENT = 20.0
    HEAT = 0.6           # °C/s at full power
    LOSS = 0.05          # 1/s
    FAN_LOSS = 0.04
    DOOR_LOSS = 0.08
    KP, KI = 20.0, 1.0   # %/°C, %/(°C·s)
    OVERHEAT = 10.0      # °C over the setpoint that counts as overheating
    STEP = 0.1           # s, the integration step

    def __init__(self, seed: int | None = None):
        self.rng = random.Random(seed)
        self.temp = 24.0
        self.power = 0.0
        # The controller starts near the power that holds 25 °C, so the
        # first minute is a calm approach, not a dip while it winds up.
        self.integ = 35.0
        self.hours = 1834.0
        self.clock = 0.0                 # model seconds since start
        self.door = False
        self.door_until = 0.0
        self.next_door = self.rng.uniform(60.0, 150.0)
        self.door_open_s = 0.0
        self.overheat_s = 0.0
        self.error = ERR_NONE

    def step(self, dt: float, setpoint: float, mode: int, heater: bool,
             fan: bool, alarm_delay: float) -> int:
        """Advance by *dt* seconds; returns the mode (a fault changes it)."""
        dt = max(0.0, min(dt, 120.0))    # a long pause is not simulated in full
        while dt > 1e-9:
            h = min(self.STEP, dt)
            dt -= h
            mode = self._tick(h, setpoint, mode, heater, fan, alarm_delay)
        return mode

    def _tick(self, h, setpoint, mode, heater, fan, alarm_delay) -> int:
        self.clock += h
        # the door: shut most of the time, open for a few seconds now and then
        if not self.door and self.clock >= self.next_door:
            self.door = True
            self.door_until = self.clock + self.rng.uniform(5.0, 14.0)
        elif self.door and self.clock >= self.door_until:
            self.door = False
            self.next_door = self.clock + self.rng.uniform(60.0, 150.0)

        if mode == MODE_RUN and heater:
            e = setpoint - self.temp
            self.integ = min(max(self.integ + e * h, 0.0), 100.0 / self.KI)
            self.power = min(max(self.KP * e + self.KI * self.integ, 0.0), 100.0)
            self.hours += h / 60.0       # one "hour" a minute: the counter moves
        else:
            self.power = 0.0
            if mode != MODE_RUN:
                self.integ = 0.0

        ambient = self.AMBIENT + 0.6 * math.sin(2 * math.pi * self.clock / 90.0)
        over = self.temp - ambient
        loss = self.LOSS + (self.FAN_LOSS if fan else 0.0) + (self.DOOR_LOSS if self.door else 0.0)
        self.temp += (self.HEAT * self.power / 100.0 - loss * over) * h

        # alarms: a door left open, an oven running away
        self.door_open_s = self.door_open_s + h if (self.door and mode == MODE_RUN) else 0.0
        hot = mode == MODE_RUN and self.temp > setpoint + self.OVERHEAT
        self.overheat_s = self.overheat_s + h if hot else 0.0
        if mode == MODE_RUN:
            if self.door_open_s > alarm_delay:
                mode, self.error = MODE_FAULT, ERR_DOOR
            elif self.overheat_s > alarm_delay:
                mode, self.error = MODE_FAULT, ERR_OVERHEAT
            else:
                self.error = ERR_NONE
        return mode


class DemoDevice:
    """The model + a register store the responder answers from."""

    def __init__(self, registers, kind: str = "thermo", seed: int | None = None):
        self.kind = kind
        self.lock = threading.Lock()
        self.model = ThermoModel(seed)
        self._last = time.monotonic()
        self.store = SlaveStore()
        self.remap(registers)

    def remap(self, registers):
        """A new register map (the demo map was edited): keep the model,
        rebuild the store, put the device's state back into it."""
        with self.lock:
            old = self.store
            self.store = SlaveStore.from_registers(registers)
            if old.words:
                for key, word in old.words.items():
                    if key in self.store.words:
                        self.store.words[key] = word
            else:
                self._put_float(_SETPOINT, 25.0)
                self._put(_MODE, MODE_RUN)
                self._put(_HEATER, 1)
                self._put(_FAN, 0)
                if not self._get(_ALARM_DELAY):
                    self._put(_ALARM_DELAY, 30)
            self._publish()

    # ── store access (absent registers simply do nothing) ────────────
    def _get(self, key: int, default: int = 0) -> int:
        return self.store.words.get(key, default)

    def _put(self, key: int, value: int):
        if key in self.store.words:
            self.store.words[key] = int(value) & 0xFFFF

    def _get_float(self, key: int, default: float) -> float:
        if key in self.store.words and key + 1 in self.store.words:
            try:
                return float(datatypes.read_to_str("FLOAT", [self.store.words[key],
                                                             self.store.words[key + 1]]))
            except (ValueError, TypeError):
                return default
        return default

    def _put_float(self, key: int, value: float):
        words = datatypes.encode("FLOAT", f"{value:.3f}")
        for i, w in enumerate(words[:2]):
            self._put(key + i, w)

    def _publish(self):
        """The model's state → the registers a master reads."""
        m = self.model
        noise = m.rng.gauss(0.0, 0.03)
        self._put_float(_TEMP, round(m.temp + noise, 2))
        self._put(_POWER, int(round(m.power * 10)))              # 0.1 %
        for i, w in enumerate(datatypes.encode("UINT32", str(int(m.hours)))[:2]):
            self._put(_HOURS + i, w)                              # the map's word order
        mode = self._get(_MODE)
        setpoint = self._get_float(_SETPOINT, 25.0)
        bits = ((mode == MODE_RUN) << BIT_RUN
                | (m.power > 0.5) << BIT_HEATING
                | (abs(m.temp - setpoint) < 0.5) << BIT_AT_SETPOINT
                | bool(self._get(_FAN)) << BIT_FAN
                | m.door << BIT_DOOR
                | (mode == MODE_FAULT) << BIT_FAULT)
        self._put(_STATUS, bits)
        self._put(_ERROR, m.error)
        volts = 24.3 - 0.4 * m.power / 100.0 + m.rng.gauss(0.0, 0.02)
        self._put(_VOLTAGE, int(round(volts * 100)))              # 0.01 V
        self._put(_CURRENT, int(round(4 + 0.32 * min(max(m.temp, 0.0), 50.0))))  # 4–20 mA
        self._put(_DOOR, int(m.door))

    def advance(self):
        """Move the model to now (called with the lock held)."""
        now = time.monotonic()
        dt, self._last = now - self._last, now
        mode = self._get(_MODE)
        new_mode = self.model.step(
            dt, self._get_float(_SETPOINT, 25.0), mode, bool(self._get(_HEATER)),
            bool(self._get(_FAN)), float(self._get(_ALARM_DELAY, 30)))
        if new_mode != mode:
            self._put(_MODE, new_mode)
        self._publish()

    def answer(self, request: bytes) -> bytes | None:
        """One RTU request frame → the device's answer (None: silent)."""
        with self.lock:
            before = self._get(_MODE)
            self.advance()
            out = build_response(request, self.store, DEVICE_ID)
            if self._get(_MODE) == MODE_RUN and before != MODE_RUN:
                # «Работа» written after a fault: the alarm is acknowledged
                self.model.error = ERR_NONE
                self.model.door_open_s = self.model.overheat_s = 0.0
                self._publish()
        return out.get("response")


# ── the one device the demo project has (attached by the window) ──────
_device: DemoDevice | None = None
_device_lock = threading.Lock()


def attach(registers, kind: str = "thermo") -> DemoDevice:
    """The demo project is open: its device answers on the "sim" link."""
    global _device
    with _device_lock:
        if _device is not None and _device.kind == kind:
            _device.remap(registers)
        else:
            _device = DemoDevice(registers, kind)
        return _device


def detach():
    """Another project or map: no simulated device any more."""
    global _device
    with _device_lock:
        _device = None


def current() -> DemoDevice | None:
    return _device


class SimMaster(_Client):
    """The master side of the "sim" link: frames go to the attached
    device instead of a port. Same request API and Response as the others."""

    def __init__(self, timeout: float = 1.0, retries: int = 1):
        self.timeout = float(timeout)
        self.retries = retries
        self._open = False
        self.last_error = self.last_error_text = ""
        self.last_request = self.last_answer = b""

    def connect(self) -> bool:
        if current() is None:
            self.last_error, self.last_error_text = "sim_off", ""
            return False
        self._open = True
        self.last_error = self.last_error_text = ""
        return True

    def close(self):
        self._open = False

    @property
    def connected(self) -> bool:
        return self._open and current() is not None

    def _exchange(self, device_id: int, pdu: bytes) -> Response:
        dev = current()
        if not self._open or dev is None:
            raise ModbusLinkError("the demo device is gone")
        request = with_crc(bytes((device_id,)) + pdu)
        fc = pdu[0]
        self.last_request, self.last_answer = request, b""
        answer = dev.answer(request)
        if device_id == 0:                       # broadcast: nobody answers
            return Response(function_code=fc, outcome="ok")
        if not answer:
            time.sleep(self.timeout)             # silent, like a real device
            return Response(function_code=0, outcome="timeout", device_id=device_id)
        time.sleep(random.uniform(*LATENCY_S))
        raw = bytes(answer)
        self.last_answer = raw
        need = answer_length(raw, fc)
        if (need is None or len(raw) < need or raw[0] != device_id
                or crc16(raw[:-2]) != (raw[-2] | raw[-1] << 8)):
            return Response(function_code=0, outcome="crc", device_id=device_id, raw=raw)
        if raw[1] == (fc | 0x80):
            return Response(function_code=raw[1], exception_code=raw[2],
                            outcome="exception", device_id=device_id, raw=raw,
                            pdu=raw[1:-2])
        return Response(function_code=fc, outcome="ok", device_id=device_id,
                        raw=raw, pdu=raw[1:-2])
