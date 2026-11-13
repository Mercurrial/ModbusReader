"""tools/check_project.py — the check for a project written by hand or by
an AI (AI_GUIDE.md): it must pass what the app accepts and name what it
would not."""
import os
import sys

from core import formats

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import check_project  # noqa: E402

REGS = [
    {"addr": 0, "type": "FLOAT", "rw": "R", "name": "Температура", "name_en": "Temp"},
    {"addr": 2, "type": "UINT16", "rw": "RW", "name": "Уставка"},
    {"addr": 1, "area": "input", "type": "UINT16", "name": "Расход"},
]


def _project(tmp_path, widgets, links=(), macros=None, regs=REGS):
    home = tmp_path / "plant"
    home.mkdir()
    path = home / "plant.mbproj"
    formats.dump_project(str(path), "plant", {"transport": "serial"}, regs,
                         dashboards=[{"name": "Пульт", "widgets": widgets,
                                      "links": list(links)}])
    if macros:
        (home / "macros").mkdir()
        for name, code in macros.items():
            (home / "macros" / name).write_text(code, encoding="utf-8")
    return str(path)


def _w(uid, kind, reg_id=None, x=0, y=0, **kw):
    w = {"uid": uid, "kind": kind, "title": uid, "x": x, "y": y, "w": 250, "h": 150}
    if reg_id:
        w["reg_id"] = reg_id
    w.update(kw)
    return w


def _errors(found):
    return [m for level, m in found if level == "ERROR"]


def test_the_demo_projects_pass(tmp_path, monkeypatch):
    from app import projects
    monkeypatch.setattr(projects, "projects_dir", lambda: str(tmp_path))
    for name in ("demo.mbproj", "demo_en.mbproj"):
        assert check_project.check(os.path.join(ROOT, "examples", name)) == []


def test_a_good_project_with_wires_and_a_macro_passes(tmp_path):
    path = _project(tmp_path, [
        _w("t", "timer", interval=1000, autostart=False),
        _w("g", "gate", "0x0000", x=300, cond="gt", cmp=50),
        _w("b", "button", "0x0002", x=600, value_on=1),
        _w("v", "value", "0x10001", y=200),            # input register 1
    ], links=[{"from": "t", "to": "g"}, {"from": "g", "to": "b"}],
        macros={"log.py": "record(t=read('Температура'), q=read('IR 1'))\n"
                          "write('Уставка', 5)\nwrite(0x0100, 1, 'UINT16')\n"})
    assert check_project.check(path) == []


def test_external_project_checks_the_same_macros_as_the_app(tmp_path, monkeypatch):
    from app import projects
    root = tmp_path / "Projects"
    monkeypatch.setattr(projects, "projects_dir", lambda: str(root))
    path = tmp_path / "plant.mbproj"
    os.rename(_project(tmp_path, []), path)
    macros = root / "plant" / "macros"
    macros.mkdir(parents=True)
    (macros / "invalid.py").write_text("import os\n", encoding="utf-8")
    assert any("invalid.py" in e for e in _errors(check_project.check(str(path))))


def test_what_the_app_would_refuse_is_named(tmp_path):
    path = _project(tmp_path, [
        _w("a", "button", "0x0000"),                   # control on a read-only register
        _w("b", "gauge", "0x0099", x=300),             # not in the map
        _w("c", "select", "0x0002", x=600),            # no options
        _w("d", "bar", "0x0000", y=200, vmin=10, vmax=10),
        _w("e", "sparkle", y=400),                     # no such kind
    ], links=[{"from": "a", "to": "b"}, {"from": "a", "to": "zz"}],
        macros={"bad.py": "import os\n", "names.py": "read('Давление')\n"})
    errs = "\n".join(_errors(check_project.check(path)))
    for needle in ("read-only register", "'0x0099' is not in the map",
                   "needs options", "vmin must be below vmax", "unknown kind 'sparkle'",
                   "b (gauge) takes no input", "to a missing widget",
                   "macro bad.py", "no register named 'Давление'"):
        assert needle in errs, needle


def test_overlaps_and_duplicate_names_are_errors(tmp_path):
    regs = [{"addr": 0, "type": "FLOAT", "name": "A"},
            {"addr": 1, "type": "UINT16", "name": "a"}]
    errs = _errors(check_project.check(_project(tmp_path, [], regs=regs)))
    assert any("overlapping" in e for e in errs)
    assert any("duplicate name" in e for e in errs)


def test_main_exits_1_on_errors(tmp_path, capsys):
    bad = _project(tmp_path, [_w("a", "button", "0x0000")])
    assert check_project.main([bad]) == 1
    assert "ERROR" in capsys.readouterr().out
