# macro_engine.py
"""Macro engine — runs a user-written *real Python* script in a worker thread.

The script gets a small domain API (reg / read / write / wait / record /
read_all / log / now / timestamp) and runs behind two gates:

1. **Parse-time rejection** (`_reject_unsafe`) — no `import`, no dunder names.
   Withheld builtins alone were NOT enough: a two-line script could walk
   ``().__class__.__base__.__subclasses__()`` to ``catch_warnings``, read its
   ``_module.__builtins__`` and get ``__import__`` back. That was verified
   against this namespace before the gate existed. Blocking dunder attribute
   access removes the first step, and the safe-builtins list deliberately has
   no getattr/vars/dir/globals/type to route around it.
2. **Restricted builtins** — a whitelist; no `open`, `eval`, `exec`, `compile`.

Stop always works, whatever the script does: a line tracer polls the stop flag
(see `_trace`). Before that, Stop was only checked inside the domain API, so
`while True: pass` produced a thread that could not be interrupted at all.

NOTE: this is still a guard-rail, not a security boundary. It stops the
realistic escapes and every accidental foot-gun, but a determined author with
CPython knowledge should be assumed to win. Treat a macro from someone else the
way you would treat any downloaded script — the app warns before running code
that was loaded from a file rather than typed here.

All Modbus I/O is delegated to ModbusCore.request_op(), which executes inside the
ModbusCore thread (single owner of the serial port). The macro thread only
enqueues + blocks, so there is never concurrent serial access.
"""

import sys
import time
import builtins
import traceback

from PyQt6.QtCore import QThread, pyqtSignal

import datatypes
from i18n import get_translator

# Modbus scalar register types the macro may read/write (from the registry).
_SCALAR_TYPES = datatypes.SCALAR_KEYS


class MacroStopped(BaseException):
    """Raised inside the script when the user presses Stop.

    A BaseException on purpose: macros are ordinary Python and routinely wrap
    device calls in ``try: … except Exception: …`` to ride out a timeout. If
    Stop were an Exception, that handler would swallow it and a looping
    script could never be stopped (the tracer raises again 200 lines later,
    and gets swallowed again)."""


class MacroRejected(Exception):
    """The script uses a construct the engine refuses to run."""


# Attribute names that open the door to the whole interpreter. Withholding
# builtins is not enough on its own: from any object you can walk
#   ().__class__.__base__.__subclasses__()
# to `catch_warnings`, read its `_module.__builtins__` and get `__import__`
# back — which was verified to work against this very namespace. Refusing
# dunder ATTRIBUTE access at parse time removes the first step, and the safe
# builtins deliberately contain no getattr/vars/dir/globals/type to route
# around it. Still not a security boundary (see the module docstring) — but no
# longer a one-liner.
def _reject_unsafe(code: str, t=None) -> None:
    """Raise MacroRejected for imports and dunder access. Parse-time, so a
    rejected script never executes a single statement."""
    import ast
    t = t or get_translator("ru")
    tree = ast.parse(code)                     # SyntaxError handled by caller
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            raise MacroRejected(t("macNoImport"))
        name = None
        if isinstance(node, ast.Attribute):
            name = node.attr
        elif isinstance(node, ast.Name):
            name = node.id
        if name and name.startswith("__") and name.endswith("__"):
            raise MacroRejected(t("macNoDunder").format(name=name))


# Whitelisted builtins exposed to the script namespace.
_SAFE_BUILTIN_NAMES = [
    "abs", "min", "max", "round", "sum", "len", "range", "enumerate", "zip",
    "map", "filter", "sorted", "reversed", "int", "float", "str", "bool",
    "list", "dict", "tuple", "set", "frozenset", "divmod", "pow", "bin", "hex",
    "oct", "ord", "chr", "format", "repr", "any", "all", "isinstance",
]


def _build_safe_builtins() -> dict:
    safe = {name: getattr(builtins, name) for name in _SAFE_BUILTIN_NAMES
            if hasattr(builtins, name)}
    safe["True"] = True
    safe["False"] = False
    safe["None"] = None
    return safe


class _Register:
    """Lightweight handle to one register — `r.read()`, `r.write(v)`, `r.value`."""

    def __init__(self, runtime, addr: int, dtype: str, name: str):
        self._rt = runtime
        self.addr = addr
        self.type = dtype
        self.name = name

    def read(self):
        return self._rt._read(self.addr, self.type, self.name)

    def write(self, value):
        self._rt._write(self.addr, self.type, value, self.name)
        return value

    @property
    def value(self):
        return self.read()

    def __repr__(self):
        return f"<reg {self.name} @0x{self.addr:04X} {self.type}>"


class MacroRunner(QThread):
    """Executes a macro script in its own thread."""

    sig_started  = pyqtSignal()
    sig_finished = pyqtSignal(bool, str)   # success, message
    sig_log      = pyqtSignal(str, str)    # level, message
    sig_row      = pyqtSignal(dict)        # one recorded results row
    sig_progress = pyqtSignal(int)         # rows recorded so far

    def __init__(self, code: str, modbus_core, registers: list[dict],
                 op_timeout: float = 5.0, parent=None, t=None):
        super().__init__(parent)
        self.code = code
        # Messages the operator reads (status line, log) follow the UI language.
        self.t = t or get_translator("ru")
        self.core = modbus_core
        self.op_timeout = op_timeout

        # Build lookup tables from the loaded profile.
        self._by_name: dict[str, dict] = {}
        self._by_addr: dict[int, dict] = {}
        self._scalars: list[dict] = []
        for r in registers:
            dtype = r.get("type", "SHORT")
            if dtype not in _SCALAR_TYPES:
                continue
            addr_raw = r.get("addr", 0)
            try:
                addr = int(addr_raw, 0) if isinstance(addr_raw, str) else int(addr_raw)
            except (TypeError, ValueError):
                continue                     # unusable row: not addressable
            info = {"addr": addr, "type": dtype,
                    "name": r.get("name", f"0x{addr:04X}")}
            self._by_addr[info["addr"]] = info
            self._by_name[info["name"].strip().lower()] = info
            self._scalars.append(info)

        self._stop = False
        self._rows = 0
        self._trace_ticks = 0

    # ──────────────────────────── control

    def request_stop(self):
        self._stop = True

    def _check_stop(self):
        if self._stop:
            raise MacroStopped()

    # Tracing every single line is measurable overhead, so the flag is polled
    # once per _TRACE_EVERY lines. Macros are dominated by serial round trips
    # (milliseconds each), so this is invisible in practice while keeping the
    # worst-case Stop latency to a few thousand bytecode lines.
    _TRACE_EVERY = 200

    def _trace(self, frame, event, _arg):
        """Line tracer installed for the macro's own frames only."""
        if frame.f_code.co_filename != "<macro>":
            return None                      # do not trace the app's own code
        if event == "line":
            self._trace_ticks += 1
            if self._trace_ticks >= self._TRACE_EVERY:
                self._trace_ticks = 0
                if self._stop:
                    raise MacroStopped()
        return self._trace

    # ──────────────────────────── register lookup

    def _lookup(self, key, dtype=None) -> dict:
        if isinstance(key, _Register):
            return {"addr": key.addr, "type": dtype or key.type, "name": key.name}
        if isinstance(key, bool):
            raise TypeError("Ключ регистра не может быть bool")
        if isinstance(key, int):
            info = self._by_addr.get(key)
            if info is None:
                if dtype is None:
                    raise KeyError(
                        f"Регистр 0x{key:04X} не найден в профиле; "
                        f"укажите тип: reg(0x{key:04X}, 'FLOAT')")
                return {"addr": key, "type": dtype, "name": f"0x{key:04X}"}
            return {"addr": info["addr"], "type": dtype or info["type"], "name": info["name"]}
        if isinstance(key, str):
            info = self._by_name.get(key.strip().lower())
            if info is None:
                # allow "0x1234" style string addresses
                try:
                    addr = int(key, 0)
                except ValueError:
                    raise KeyError(f"Регистр не найден: {key!r}")
                return self._lookup(addr, dtype)
            return {"addr": info["addr"], "type": dtype or info["type"], "name": info["name"]}
        raise TypeError(f"Недопустимый ключ регистра: {key!r}")

    # ──────────────────────────── I/O primitives

    def _read(self, addr, dtype, name):
        self._check_stop()
        return self.core.request_op("read", addr, dtype, timeout=self.op_timeout)

    def _write(self, addr, dtype, value, name):
        self._check_stop()
        self.core.request_op("write", addr, dtype, value=value, timeout=self.op_timeout)
        self.sig_log.emit("SYS", f"write {name} (0x{addr:04X}) = {value}")

    # ──────────────────────────── script-facing API

    def api_reg(self, key, dtype=None) -> _Register:
        info = self._lookup(key, dtype)
        return _Register(self, info["addr"], info["type"], info["name"])

    def api_read(self, key, dtype=None):
        info = self._lookup(key, dtype)
        return self._read(info["addr"], info["type"], info["name"])

    def api_write(self, key, value, dtype=None):
        info = self._lookup(key, dtype)
        self._write(info["addr"], info["type"], value, info["name"])
        return value

    def api_read_all(self) -> dict:
        """Read every scalar register from the profile → {name: value}."""
        out = {}
        for info in self._scalars:
            self._check_stop()
            out[info["name"]] = self.core.request_op(
                "read", info["addr"], info["type"], timeout=self.op_timeout)
        return out

    def api_wait(self, seconds):
        """Interruptible sleep — wakes promptly when Stop is pressed."""
        seconds = float(seconds)
        end = time.monotonic() + seconds
        while True:
            self._check_stop()
            remaining = end - time.monotonic()
            if remaining <= 0:
                return
            time.sleep(min(remaining, 0.05))

    def api_record(self, row=None, **kwargs):
        """Append a row to the results table. Accepts a dict and/or keywords."""
        data = {}
        if row is not None:
            if not isinstance(row, dict):
                raise TypeError("record() ожидает dict или именованные аргументы")
            data.update(row)
        data.update(kwargs)
        self._rows += 1
        self.sig_row.emit(data)
        self.sig_progress.emit(self._rows)

    def api_log(self, *args):
        msg = " ".join(str(a) for a in args)
        self.sig_log.emit("LOG", msg)

    @staticmethod
    def api_timestamp():
        return time.strftime("%Y-%m-%d %H:%M:%S")

    # ──────────────────────────── namespace

    def _make_globals(self) -> dict:
        return {
            "__builtins__": _build_safe_builtins(),
            # register access
            "reg": self.api_reg,
            "read": self.api_read,
            "write": self.api_write,
            "read_all": self.api_read_all,
            # flow
            "wait": self.api_wait,
            "sleep": self.api_wait,
            # output
            "record": self.api_record,
            "log": self.api_log,
            "print": self.api_log,
            # time
            "now": time.time,
            "timestamp": self.api_timestamp,
        }

    # ──────────────────────────── thread entry

    def run(self):
        self.sig_started.emit()
        t = self.t
        if not self.core.is_running:
            self.sig_finished.emit(False, t("macNotConnected"))
            return
        try:
            _reject_unsafe(self.code, t)
            compiled = compile(self.code, "<macro>", "exec")
        except SyntaxError as e:
            self.sig_finished.emit(False, t("macSyntax").format(line=e.lineno, err=e.msg))
            return
        except ValueError as e:
            # e.g. a NUL byte pasted into the editor. Uncaught, this ended the
            # thread without sig_finished — the window stayed "running" forever.
            self.sig_finished.emit(False, t("macSyntax").format(line="?", err=e))
            return
        except MacroRejected as e:
            self.sig_log.emit("ERR", str(e))
            self.sig_finished.emit(False, str(e))
            return

        t0 = time.monotonic()
        try:
            # Stop used to be checked only inside the domain API, so a macro
            # that never called it — `while True: pass` — could not be
            # interrupted at all and its thread outlived every attempt to quit.
            # A line tracer makes Stop work regardless of what the script does.
            sys.settrace(self._trace)
            try:
                exec(compiled, self._make_globals())
            finally:
                sys.settrace(None)
        except MacroStopped:
            self.sig_finished.emit(False, t("macStopped").format(rows=self._rows))
            return
        except Exception as e:
            tb = traceback.extract_tb(e.__traceback__)
            line = next((f.lineno for f in reversed(tb) if f.filename == "<macro>"), "?")
            self.sig_log.emit("ERR", f"{type(e).__name__} "
                              + t("macAtLine").format(line=line) + f": {e}")
            self.sig_finished.emit(False, t("macError").format(line=line, err=e))
            return

        dt = time.monotonic() - t0
        self.sig_finished.emit(True, t("macDone").format(rows=self._rows,
                                                         sec=f"{dt:.1f}"))
