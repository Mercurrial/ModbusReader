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

pymodbus checks the CRC inside its RTU framer and simply drops a bad frame,
so on its own a CRC error is indistinguishable from a timeout.
``install_crc_probe`` wraps the framer of a client and raises a flag when a
COMPLETE frame failed its CRC; the core turns that flag into a "crc" outcome.

Pure Python apart from the optional pymodbus probe — fully testable.
"""

import threading
import time

OUTCOMES = ("ok", "exception", "timeout", "crc")


class LineStats:
    """Thread-safe counters + response-time statistics."""

    def __init__(self):
        self._lock = threading.Lock()
        self.crc_flag = False           # set by the framer probe per request
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

    def begin(self):
        """A request is about to go out."""
        self.crc_flag = False

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
    """pymodbus result → outcome (without the CRC refinement)."""
    if res is None:
        return "timeout"
    is_error = getattr(res, "isError", None)
    if is_error is None or not is_error():
        return "ok"
    fc = getattr(res, "function_code", 0) or 0
    return "exception" if fc >= 0x80 else "timeout"


def install_crc_probe(client, stats: LineStats) -> bool:
    """Wrap the client's RTU framer so a complete frame with a bad CRC sets
    ``stats.crc_flag``. Returns False (and changes nothing) when the client
    has no RTU framer — TCP, a stub in tests, a future pymodbus layout."""
    framer = getattr(client, "framer", None)
    try:
        from pymodbus.framer import FramerRTU
    except ImportError:              # pragma: no cover
        return False
    if not isinstance(framer, FramerRTU) or getattr(framer, "_mbr_probe", False):
        return False
    original = framer.decode

    def decode(data: bytes):
        result = original(data)
        try:
            # No frame came out (empty payload). pymodbus up to 3.13 leaves a
            # bad-CRC frame in the buffer (used length 0); 3.16 swallows it
            # (used length = all) — only "no payload" holds for both.
            if not result[3] and frame_has_bad_crc(framer, data):
                stats.crc_flag = True
        except Exception:
            pass                     # the probe must never break the read
        return result

    framer.decode = decode
    framer._mbr_probe = True
    return True


def frame_has_bad_crc(framer, data: bytes) -> bool:
    """True when *data* starts with a COMPLETE frame (its length is known from
    the function code) whose CRC does not match. Partial frames are not
    errors — more bytes may still be on the way."""
    if len(data) < 4:
        return False
    pdu_class = framer.decoder.lookupPduClass(data)
    if not pdu_class:
        return False
    size = pdu_class.calculateRtuFrameSize(data)
    if not size or len(data) < size:
        return False
    crc_val = (data[size - 2] << 8) | data[size - 1]
    return not framer.check_CRC(data[:size - 2], crc_val)
