# core/scanner_engine.py
"""Bus scanner worker — finds devices and live registers.

Two modes, both built on ModbusCore's synchronous op channel (the serial port
still has exactly ONE owner — the core thread; this worker only enqueues
"probe" ops and waits):

    devices    ping every slave ID in a range with a 1-register read.
               A data response OR a Modbus exception both mean the device is
               ALIVE (an exception proves someone decoded our request).
    registers  read a range of addresses on ONE slave id; every address that
               answers with data is reported with its raw value.

Scan speed is bounded by the response timeout from Settings → Опрос — silent
IDs cost a full timeout each."""

import time

from PyQt6.QtCore import QThread, pyqtSignal


class ScannerWorker(QThread):
    progress = pyqtSignal(int, int)          # done, total
    found = pyqtSignal(dict)                 # one hit
    finished_scan = pyqtSignal(int, int, float)   # found_count, total, seconds
    error = pyqtSignal(str)

    def __init__(self, core, mode: str, start: int, end: int,
                 slave_id: int = 1, parent=None):
        super().__init__(parent)
        self.core = core
        self.mode = mode                     # "devices" | "registers"
        self.start_n = int(start)
        self.end_n = int(end)
        self.slave_id = int(slave_id)        # registers mode: the ID to scan
        self._stop = False

    def request_stop(self):
        self._stop = True

    def run(self):
        t0 = time.monotonic()
        total = self.end_n - self.start_n + 1
        hits = 0
        try:
            for i, n in enumerate(range(self.start_n, self.end_n + 1), 1):
                if self._stop:
                    break
                if self.mode == "devices":
                    hits += self._probe_device(n)
                else:
                    hits += self._probe_register(n)
                self.progress.emit(i, total)
        except RuntimeError as e:
            # Core went away mid-scan (disconnect) — report and stop cleanly.
            self.error.emit(str(e))
        self.finished_scan.emit(hits, total, time.monotonic() - t0)

    # ── probes ────────────────────────────────────────────────────────
    def _probe_device(self, sid: int) -> int:
        t0 = time.perf_counter()
        state = self.core.request_op("probe", 0, "SHORT", slave=sid,
                                     timeout=30.0)
        ms = (time.perf_counter() - t0) * 1000.0
        if state in ("alive", "exception"):
            self.found.emit({"mode": "devices", "id": sid, "state": state,
                             "ms": ms})
            return 1
        return 0

    def _probe_register(self, addr: int) -> int:
        t0 = time.perf_counter()
        state = self.core.request_op("probe", addr, "SHORT",
                                     slave=self.slave_id, timeout=30.0)
        ms = (time.perf_counter() - t0) * 1000.0
        if state == "alive":
            # A second read to fetch the actual value for display.
            try:
                value = self.core.request_op("read", addr, "SHORT",
                                             slave=self.slave_id, timeout=30.0)
            except RuntimeError:
                value = None
            self.found.emit({"mode": "registers", "addr": addr,
                             "state": state, "ms": ms, "value": value})
            return 1
        return 0
