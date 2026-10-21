# core/linestats.py
"""Line statistics — what the serial link is actually doing.

Counted in the core thread for EVERY exchange (poll, macro/scanner ops,
writes, memory reads, raw console frames), read by the GUI as a snapshot.

The outcomes are deliberately separated, because they point at different
faults on a real RS-485 line:

* **timeout**   — nothing came back: wiring, slave ID, baud rate, power;
* **crc**       — a frame came back but its checksum is wrong: noise,
                  missing termination, a long unshielded cable;
* **exception** — the device answered "no" (illegal address/function): the
                  link is fine, the register map is not;
* **ok**        — a valid answer.

The app's own Modbus client (core/modbus_client) tells these apart itself
and hands the outcome over with every answer. (With pymodbus, which dropped a
bad frame inside its RTU framer, a CRC error looked like a timeout unless a
probe was wrapped around that framer.)

Pure Python — fully testable.
"""

import threading
import time

OUTCOMES = ("ok", "exception", "timeout", "crc")


class LineStats:
    """Thread-safe counters + response-time statistics."""

    def __init__(self):
        self._lock = threading.Lock()
        self.reset()

    def reset(self):
        with self._lock:
            self._n = {k: 0 for k in OUTCOMES}
            self._requests = 0
            self._rt_last = None
            self._rt_sum = 0.0
            self._rt_n = 0
            self._rt_min = None
            self._rt_max = None
            self._since = time.monotonic()

    def record(self, outcome: str, rtt: float | None = None):
        """One finished exchange. *rtt* (seconds) only when an answer came."""
        if outcome not in OUTCOMES:
            outcome = "timeout"
        with self._lock:
            self._requests += 1
            self._n[outcome] += 1
            if rtt is not None and outcome in ("ok", "exception"):
                ms = rtt * 1000.0
                self._rt_last = ms
                self._rt_sum += ms
                self._rt_n += 1
                self._rt_min = ms if self._rt_min is None else min(self._rt_min, ms)
                self._rt_max = ms if self._rt_max is None else max(self._rt_max, ms)

    def snapshot(self) -> dict:
        with self._lock:
            answered = self._n["ok"] + self._n["exception"]
            req = self._requests
            return {
                "requests": req,
                "responses": answered,
                "ok": self._n["ok"],
                "exceptions": self._n["exception"],
                "timeouts": self._n["timeout"],
                "crc": self._n["crc"],
                "errors": self._n["timeout"] + self._n["crc"] + self._n["exception"],
                "quality": (100.0 * answered / req) if req else None,
                "rt_last": self._rt_last,
                "rt_avg": (self._rt_sum / self._rt_n) if self._rt_n else None,
                "rt_min": self._rt_min,
                "rt_max": self._rt_max,
                "elapsed": time.monotonic() - self._since,
            }


def classify(res) -> str:
    """A client's answer → outcome. core/modbus_client says it outright
    (.outcome); anything else is judged by isError() and the exception bit
    of its function code."""
    if res is None:
        return "timeout"
    outcome = getattr(res, "outcome", None)
    if outcome in OUTCOMES:
        return outcome
    is_error = getattr(res, "isError", None)
    if is_error is None or not is_error():
        return "ok"
    fc = getattr(res, "function_code", 0) or 0
    return "exception" if fc >= 0x80 else "timeout"
