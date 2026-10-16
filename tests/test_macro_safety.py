"""Macro engine safety: the escapes that used to work, and Stop that used not to.

Both findings below were verified against the real engine before being fixed:
a two-line script reached ``os`` through the type hierarchy, and a
``while True: pass`` macro could not be interrupted at all.
"""
import time

import pytest

from core import macro_engine as me
from core.macro_engine import MacroRejected, MacroRunner


class _FakeCore:
    """Enough of ModbusCore for the runner to start."""
    is_running = True

    def __init__(self):
        self.ops = []

    def request_op(self, kind, addr, dtype, value=None, timeout=5.0, slave=None):
        self.ops.append((kind, addr, dtype, value))
        return 0


# ── parse-time gate ─────────────────────────────────────────────────────
ESCAPES = [
    pytest.param("import os", id="import"),
    pytest.param("from os import getcwd", id="from-import"),
    pytest.param("__import__('os')", id="dunder-import"),
    # The one that actually worked: walk the type tree to catch_warnings and
    # read its module's __builtins__ back out.
    pytest.param("cls = ().__class__.__base__.__subclasses__()", id="subclass-walk"),
    pytest.param("w = [c for c in ().__class__.__base__.__subclasses__()\n"
                 "     if c.__name__ == 'catch_warnings'][0]\n"
                 "os_mod = w()._module.__builtins__['__import__']('os')",
                 id="catch_warnings-escape"),
    pytest.param("b = (lambda: 0).__globals__['__builtins__']", id="func-globals"),
    pytest.param("t = type(1).__mro__", id="mro"),
    pytest.param("x = ''.__class__", id="class-attr"),
]


@pytest.mark.parametrize("src", ESCAPES)
def test_interpreter_escapes_are_rejected_before_running(src):
    with pytest.raises(MacroRejected):
        me._reject_unsafe(src)


def test_ordinary_macros_still_pass_the_gate():
    """The gate must not get in the way of real work."""
    ok = [
        "for i in range(10):\n    record(value=i)",
        "r = reg(0x10)\nwrite(r, 5)\nlog('done')",
        "vals = [read(a) for a in (1, 2, 3)]\nrecord(avg=sum(vals) / len(vals))",
        "if read(1) > 10:\n    write(2, 0)\nelse:\n    wait(0.1)",
        "def helper(x):\n    return x * 2\nrecord(v=helper(21))",
        "d = {'a': 1}\nfor k, v in d.items():\n    log(f'{k}={v}')",
    ]
    for src in ok:
        me._reject_unsafe(src)          # must not raise


def test_rejected_script_never_executes_a_statement():
    """The gate runs at parse time, so side effects cannot happen first."""
    core = _FakeCore()
    runner = MacroRunner("write(1, 99)\nimport os", core,
                         [{"addr": 1, "type": "SHORT", "name": "r"}])
    result = []
    runner.sig_finished.connect(lambda ok, msg: result.append((ok, msg)))
    runner.run()                        # same thread: deterministic
    assert result and result[0][0] is False
    assert core.ops == [], "a rejected macro must not touch the device"


def test_safe_builtins_expose_no_route_around_the_gate():
    """getattr/vars/dir/globals/type would each reopen the door."""
    exposed = set(me._build_safe_builtins())
    for name in ("getattr", "setattr", "vars", "dir", "globals", "locals",
                 "type", "open", "eval", "exec", "compile", "input",
                 "__import__", "memoryview", "breakpoint", "help"):
        assert name not in exposed, f"{name} is reachable from a macro"


# ── Stop ────────────────────────────────────────────────────────────────
def test_stop_interrupts_a_macro_that_never_calls_the_api():
    """Regression: Stop was only checked inside the domain API, so this macro
    ignored it completely and its thread outlived the request to quit."""
    runner = MacroRunner("while True:\n    pass\n", _FakeCore(), [])
    done = []
    runner.sig_finished.connect(lambda ok, msg: done.append((ok, msg)))
    runner.start()
    try:
        deadline = time.monotonic() + 1.0
        while not runner.isRunning() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert runner.isRunning()
        runner.request_stop()
        assert runner.wait(3000), "a runaway macro must still be stoppable"
    finally:
        if runner.isRunning():          # never leave a spinning thread behind
            runner.terminate()
            runner.wait(500)


def test_stop_is_reported_as_a_user_stop_not_a_crash():
    runner = MacroRunner("while True:\n    pass\n", _FakeCore(), [])
    done = []
    runner.sig_finished.connect(lambda ok, msg: done.append((ok, msg)))
    runner.start()
    time.sleep(0.15)
    runner.request_stop()
    runner.wait(3000)
    # sig_finished crosses threads, so it sits in the queue until the event
    # loop turns — wait() blocks that loop by definition.
    from PyQt6.QtWidgets import QApplication
    for _ in range(10):
        QApplication.processEvents()
    assert done and done[0][0] is False
    assert "станов" in done[0][1].lower() or "stop" in done[0][1].lower()


def test_tracer_is_not_installed_on_application_code():
    """The tracer must ignore frames that are not the macro's own, or it would
    slow the whole thread down and see the app's internals."""
    runner = MacroRunner("pass", _FakeCore(), [])

    class _Frame:
        def __init__(self, name):
            self.f_code = type("C", (), {"co_filename": name})()
    assert runner._trace(_Frame("gui_main.py"), "line", None) is None
    assert runner._trace(_Frame("<macro>"), "line", None) is not None


def test_finished_run_restores_the_global_trace_hook():
    """Leaving sys.settrace installed would cripple every later thread."""
    import sys
    runner = MacroRunner("record(v=1)", _FakeCore(), [])
    runner.run()
    assert sys.gettrace() is None
