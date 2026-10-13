"""Macro engine: register lookup variants + sandbox namespace."""
import pytest

from macro_engine import MacroRunner, _build_safe_builtins


class _Core:
    is_running = True


def _runner(regs=None):
    regs = regs if regs is not None else [
        {"addr": 0x10, "name": "Temp", "type": "SHORT", "rw": "RW"},
        {"addr": 0x14, "name": "Flow", "type": "FLOAT", "rw": "R"},
        {"addr": 0x20, "name": "Mem", "type": "MEMORY_AREA", "rw": "R"},
    ]
    return MacroRunner("pass", _Core(), regs)


def test_addr_forms_accepted():
    for a, expect in (("0x10", 16), (16, 16), ("16", 16), ("0b10000", 16)):
        r = MacroRunner("pass", _Core(),
                        [{"addr": a, "name": "T", "type": "SHORT"}])
        assert expect in r._by_addr


def test_lookup_variants():
    r = _runner()
    assert r._lookup("Temp")["addr"] == 0x10          # by name
    assert r._lookup(" temp ")["addr"] == 0x10        # trimmed, case-insensitive
    assert r._lookup(0x14)["type"] == "FLOAT"         # by addr
    assert r._lookup("0x10")["name"] == "Temp"        # hex-string addr
    assert r._lookup(0x99, "SHORT")["addr"] == 0x99   # unknown + explicit dtype


def test_lookup_rejections():
    r = _runner()
    with pytest.raises(TypeError):
        r._lookup(True)                                # bool is not an addr
    with pytest.raises(KeyError):
        r._lookup(0x99)                                # unknown addr, no dtype
    with pytest.raises(KeyError):
        r._lookup("no-such-register")


def test_non_scalars_excluded():
    r = _runner()
    assert 0x20 not in r._by_addr                      # MEMORY_AREA not scriptable


def test_sandbox_withholds_dangerous_builtins():
    safe = _build_safe_builtins()
    for name in ("__import__", "open", "eval", "exec", "compile",
                 "globals", "locals", "vars", "getattr", "setattr"):
        assert name not in safe, name
    for name in ("min", "max", "range", "len", "int", "float"):
        assert name in safe, name


def test_namespace_has_domain_api():
    g = _runner()._make_globals()
    for fn in ("reg", "read", "write", "read_all", "wait", "sleep",
               "record", "log", "print", "now", "timestamp"):
        assert callable(g[fn]), fn
