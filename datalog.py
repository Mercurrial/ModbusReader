# datalog.py
"""Long-run value logging to CSV.

Design decisions, and why — these are the ones that are painful to change once
files exist:

* **Wide format** (one column per register, one row per sample) rather than
  long (timestamp, address, value). Polling is cyclic and synchronised, so
  every register genuinely has a value at the same instant; wide rows chart
  directly in Excel with no pivoting. The cost is that the column set is fixed
  when the file opens — a register added mid-run cannot appear, so changing the
  map starts a new file instead of silently shifting columns.
* **UTF-8 with BOM.** Excel on Windows reads a plain UTF-8 CSV as cp1251 and
  turns every Cyrillic name into mojibake. The BOM is what makes a
  double-click just work, which is the whole point of choosing CSV.
* **Rotation by size.** An overnight run at 200 ms is ~400 000 rows; a single
  file of that size is slow to open and Excel refuses past ~1M rows. Parts are
  numbered so their order is obvious.
* **Buffered, periodically flushed.** Flushing every sample would hammer the
  disk and add latency to the poll loop. Data is flushed on a row/time budget
  and always on close, so a crash costs at most the last few seconds.
* **Never raise into the caller.** The writer is driven from the UI/poll path.
  A full disk or a file locked by Excel sets ``last_error`` and stops logging;
  it does not take the application down with it.
"""

import csv
import os
import time
from datetime import datetime

import datatypes

DEFAULT_DELIMITER = ";"          # RU locale Excel; "," where the decimal is "."
DEFAULT_DECIMAL = ","
BOM = "﻿"

FLUSH_ROWS = 50                  # whichever comes first
FLUSH_SECONDS = 2.0
MIN_ROTATE_MB = 1
MAX_ROTATE_MB = 2000


def timestamp_name(prefix: str = "modbus_log") -> str:
    """A file name that sorts chronologically and is safe on Windows."""
    return f"{prefix}_{time.strftime('%Y%m%d_%H%M%S')}.csv"


def part_path(path: str, index: int) -> str:
    """Second and later parts of a rotated log: ``name_002.csv``."""
    if index <= 1:
        return path
    root, ext = os.path.splitext(path)
    return f"{root}_{index:03d}{ext or '.csv'}"


class LogWriter:
    """Writes rows for a FIXED set of columns, rotating by size.

    ``columns`` is a list of ``(key, title)``. *key* is whatever the caller
    uses in the value dict (an int address here); *title* is the CSV header.
    """

    def __init__(self, path: str, columns, rotate_mb: int = 50,
                 delimiter: str = DEFAULT_DELIMITER,
                 decimal: str = DEFAULT_DECIMAL,
                 time_format: str = "%Y-%m-%d %H:%M:%S.%f"):
        self.base_path = path
        self.columns = list(columns)
        self.rotate_bytes = max(MIN_ROTATE_MB,
                                min(int(rotate_mb), MAX_ROTATE_MB)) * 1024 * 1024
        self.delimiter = delimiter or DEFAULT_DELIMITER
        self.decimal = decimal
        self.time_format = time_format

        self.rows_written = 0
        self.part = 1
        self.paths: list[str] = []
        self.last_error: str | None = None
        self._fh = None
        self._writer = None
        self._bytes = 0
        self._since_flush = 0
        self._last_flush = 0.0
        self._open()

    # ── file lifecycle ────────────────────────────────────────────────
    @property
    def current_path(self) -> str:
        return part_path(self.base_path, self.part)

    @property
    def active(self) -> bool:
        return self._fh is not None

    def _open(self):
        path = self.current_path
        try:
            directory = os.path.dirname(os.path.abspath(path))
            if directory:
                os.makedirs(directory, exist_ok=True)
            # newline="" is required by csv on Windows or every row gets a
            # blank line between it and the next.
            self._fh = open(path, "w", encoding="utf-8", newline="")
            self._writer = csv.writer(self._fh, delimiter=self.delimiter,
                                      quoting=csv.QUOTE_MINIMAL)
            self._fh.write(BOM)          # so Excel opens Cyrillic correctly
            header = ["timestamp"] + [str(title) for _key, title in self.columns]
            self._writer.writerow(header)
            self._bytes = self._fh.tell()
            self.paths.append(path)
            self._last_flush = time.monotonic()
        except (OSError, ValueError) as e:
            # ValueError covers a path with an embedded null — open() raises
            # that instead of OSError, and this writer must never raise.
            self._fail(e)

    def _fail(self, err):
        """Stop logging and remember why. Never raises at the caller."""
        self.last_error = str(err)
        try:
            if self._fh is not None:
                self._fh.close()
        except OSError:
            pass
        self._fh = None
        self._writer = None

    def close(self):
        if self._fh is None:
            return
        try:
            self._fh.flush()
            self._fh.close()
        except OSError as e:
            self.last_error = str(e)
        finally:
            self._fh = None
            self._writer = None

    # ── writing ───────────────────────────────────────────────────────
    def _format(self, value) -> str:
        if value is None:
            return ""
        text = str(value).strip()
        if self.decimal != "." and text:
            # Only swap the separator on something that is actually a number,
            # or a name like "Ch.1" would be mangled.
            try:
                float(text.replace(",", "."))
            except ValueError:
                return text
            return text.replace(".", self.decimal)
        return text

    def write_row(self, values: dict, when: float | None = None) -> bool:
        """One sample. Returns False when logging has stopped (see last_error).

        Missing keys become empty cells rather than shifting the row — a
        register that failed to read this cycle must not move every later
        column by one."""
        if self._fh is None:
            return False
        # datetime, not time.strftime: only datetime understands %f, and
        # hand-substituting milliseconds got the rounding wrong.
        stamp = datetime.fromtimestamp(
            when if when is not None else time.time()).strftime(self.time_format)
        if self.time_format.endswith("%f"):
            stamp = stamp[:-3]                    # microseconds -> milliseconds
        row = [stamp] + [self._format(values.get(key)) for key, _t in self.columns]
        try:
            self._writer.writerow(row)
            self.rows_written += 1
            self._bytes = self._fh.tell()
            self._since_flush += 1
            now = time.monotonic()
            if (self._since_flush >= FLUSH_ROWS
                    or now - self._last_flush >= FLUSH_SECONDS):
                self._fh.flush()
                self._since_flush = 0
                self._last_flush = now
            if self._bytes >= self.rotate_bytes:
                self._rotate()
        except (OSError, ValueError) as e:
            self._fail(e)
            return False
        return True

    def _rotate(self):
        self.close()
        if self.last_error:
            return
        self.part += 1
        self._open()


def columns_for(registers) -> list:
    """``[(addr, "0x0010 Название")]`` for the log header.

    The address is included because names are not unique in a hand-made map,
    and a column you cannot trace back to a register is useless."""
    out = []
    for reg in registers or []:
        if not isinstance(reg, dict) or "addr" not in reg:
            continue
        try:
            int(str(reg["addr"]).strip(), 0)
        except (TypeError, ValueError):
            continue
        addr = datatypes.reg_key(reg)            # area-aware ("IR 0x0010")
        name = str(reg.get("name", "")).strip()
        unit = str(reg.get("unit", "")).strip()
        title = datatypes.key_label(addr)
        if name:
            title += f" {name}"
        if unit:
            title += f", {unit}"
        out.append((addr, title))
    return out
