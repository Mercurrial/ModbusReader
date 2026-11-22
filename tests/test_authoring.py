"""Contract behavior, runtime parity and the standalone distribution boundary."""
import copy
import inspect
import json
from pathlib import Path
import subprocess
import sys
import zipfile

import pytest

from core import authoring as a, datatypes, formats, macro_api

ROOT = Path(__file__).resolve().parents[1]


def profile(*rows):
    return {"format": formats.PROFILE_KIND, "version": formats.PROFILE_VERSION,
            "name": "Test", "registers": list(rows) or [
                {"addr": 0, "name": "Temperature", "type": "SHORT", "rw": "R"},
                {"addr": 1, "name": "Setpoint", "type": "SHORT", "rw": "RW"}]}


def errors(issues):
    return {d.code for d in issues if d.severity == "error"}


@pytest.mark.parametrize("name", ["demo.mbproj", "demo_en.mbproj"])
def test_shipped_projects_pass_without_modification(name):
    doc = a.read_json(ROOT / "examples" / name)
    before = copy.deepcopy(doc)
    assert not errors(a.validate_document(doc))
    assert doc == before


@pytest.mark.parametrize("value,code", [
    (-1, "schema.range"), (65536, "schema.range"), (True, "schema.type"),
    ("0x10", "schema.type"), (1.5, "schema.type"), (float("inf"), "schema.type"),
])
def test_addresses_are_not_silently_coerced(value, code):
    doc = profile()
    doc["registers"][0]["addr"] = value
    assert code in errors(a.validate_document(doc))


@pytest.mark.parametrize("patch,code", [
    ({"type": "uint16"}, "schema.enum"), ({"word_order": "ABCD"}, "schema.unknown"),
    ({"length": 0}, "schema.range"), ({"scale": float("nan")}, "schema.type"),
    ({"scale": 0}, "register.zero_scale"), ({"name": "  "}, "register.empty_name"),
    ({"addr": 65535, "type": "FLOAT"}, "register.overflow"),
    ({"area": "coil", "type": "FLOAT"}, "register.bit_type"),
    ({"area": "discrete", "type": "BOOL", "rw": "RW"}, "register.read_only"),
    ({"type": "STRING", "length": 126}, "register.text_length"),
])
def test_bad_registers(patch, code):
    doc = profile()
    doc["registers"][0].update(patch)
    assert code in errors(a.validate_document(doc))


def test_separate_areas_are_distinct_but_alias_names_are_not():
    doc = profile({"addr": 0, "name": "A", "type": "SHORT", "rw": "R"},
                  {"addr": 0, "name": "B", "type": "SHORT", "rw": "R", "area": "input"})
    assert not a.validate_document(doc)
    doc["registers"][1]["name_en"] = " a "
    assert "register.ambiguous_name" in errors(a.validate_document(doc))
    doc["registers"][1].pop("area")
    assert "register.duplicate" in errors(a.validate_document(doc))


def test_unknown_codec_is_a_warning_not_an_invented_capability():
    doc = profile({"addr": 0, "name": "Bytes", "type": "BYTE", "rw": "R"})
    assert a.result(a.validate_document(doc))["valid"]
    assert a.validate_document(doc)[0].code == "register.no_codec"
    assert "macro.no_codec" in errors(a.check_macro('read("Bytes")', doc))


def test_legacy_loader_remains_tolerant_but_authoring_is_strict():
    legacy = [{"addr": "0x10", "name": "Old", "type": "SHORT"}]
    assert formats.migrate_profile(legacy)["registers"][0]["addr"] == 16
    assert "document.format" in errors(a.validate_document(legacy))


@pytest.mark.parametrize("text", ['{"a":1,"a":2}', '{"a":NaN}', '{"a":Infinity}'])
def test_invalid_json_is_rejected_at_input(tmp_path, text):
    file = tmp_path / "bad.json"
    file.write_text(text)
    with pytest.raises(ValueError):
        a.read_json(file)


def test_shape_failures_are_diagnostics_not_crashes():
    for bad in (None, True, 7, [], {"format": []}, {"format": formats.PROFILE_KIND, "version": True, "registers": [None]}):
        assert errors(a.validate_document(bad))
    doc = profile()
    doc["registers"][0]["enum"] = {"x/y~": "Bad"}
    assert any(d.path.endswith("x~1y~0") for d in a.validate_document(doc))


def dashboard():
    return formats.make_dashboard("Panel", [
        {"uid": "t", "kind": "timer"},
        {"uid": "b", "kind": "button", "reg_id": "0x0001", "reg_type": "SHORT"}],
        [{"from": "t", "to": "b"}])


def test_board_bindings_and_ports():
    board = dashboard()
    assert not a.validate_document(board, profile=profile())
    assert a.validate_document(board)[0].code == "dashboard.unchecked_bindings"
    board["widgets"][1]["reg_id"] = "0x00001"
    assert "dashboard.binding" in errors(a.validate_document(board, profile=profile()))
    board["widgets"][1]["reg_id"] = "0x0000"
    assert "dashboard.read_only" in errors(a.validate_document(board, profile=profile()))
    board["widgets"][1]["reg_id"] = "0x10000"
    assert "dashboard.missing_register" in errors(a.validate_document(board, profile=profile()))
    board["links"][0]["to"] = "absent"
    assert "dashboard.dangling_link" in errors(a.validate_document(board))
    board["links"][0]["to"] = "b"
    board["widgets"][1]["kind"] = "value"
    assert "dashboard.port" in errors(a.validate_document(board))


def test_connection_constraints_follow_transport():
    doc = formats.make_project("P", {"transport": "tcp", "slave_id": 255}, profile()["registers"])
    assert not errors(a.validate_document(doc))
    doc["connection"]["transport"] = "serial"
    assert "connection.unit_id" in errors(a.validate_document(doc))
    doc["connection"].update(transport="sim", slave_id=1)
    assert "connection.simulation" in errors(a.validate_document(doc))


@pytest.mark.parametrize("code,expected", [
    ('read(', "macro.syntax"), ('return 1', "macro.syntax"),
    ('import os', "macro.policy"), ('x = ().__class__', "macro.policy"),
    ('print("x", end="")', "macro.arguments"), ('write("Setpoint")', "macro.arguments"),
    ('read("Absent")', "macro.missing_register"), ('read(True)', "macro.key"),
    ('read(0x40000, "SHORT")', "macro.address"), ('read(12, "NOPE")', "macro.dtype"),
    ('write("Temperature", 1)', "macro.read_only"), ('open("secret")', "macro.unavailable"),
])
def test_macro_diagnostics(code, expected):
    diagnostics = a.check_macro(code, profile())
    assert expected in errors(diagnostics)
    assert next(d for d in diagnostics if d.code == expected).line == 1


def test_unicode_columns_and_custom_function_shadowing():
    issues = a.check_macro('x = "тест"; write("Setpoint")', profile())
    assert issues[0].column == 13
    assert not errors(a.check_macro('def read():\n    return 1\nread()', profile()))


def test_macro_valid_raw_units_and_dynamic_limits():
    doc = profile()
    doc["registers"][0]["scale"] = 0.1
    code = 'for i in range(3):\n    record(t=read("Temperature") * 0.1)\n    wait(1)'
    assert errors(a.check_macro(code, doc)) == set()
    assert "macro.raw_units" in {d.code for d in a.check_macro(code, doc)}
    assert "macro.dynamic_register" in {d.code for d in a.check_macro('read(key)', doc)}
    assert not errors(a.check_macro('read(12, dtype="FLOAT")', doc))


def test_runtime_namespace_signatures_and_policy_match_contract():
    from core.macro_engine import MacroRunner, MacroRejected, _reject_unsafe
    runner = MacroRunner("", object(), [])
    namespace = runner._make_globals()
    assert set(namespace) - {"__builtins__"} == set(macro_api.BY_NAME)
    for spec in macro_api.FUNCTIONS:
        if spec.name == "now":  # C builtin has no introspection signature
            continue
        actual = inspect.signature(namespace[spec.name])
        dummy = ast_signature(spec)
        assert [(p.name, p.kind, p.default) for p in actual.parameters.values()] == dummy
    for code in ('import os', 'x.__class__', '__builtins__', 'read("Temperature")'):
        rejected = "macro.policy" in errors(a.check_macro(code))
        if rejected:
            with pytest.raises(MacroRejected):
                _reject_unsafe(code)
        else:
            _reject_unsafe(code)


def ast_signature(spec):
    # Only trusted contract declarations are executed in this test.
    ns = {}
    exec(f"def f({spec.parameters}): pass", ns)
    return [(p.name, p.kind, p.default) for p in inspect.signature(ns["f"]).parameters.values()]


def cli(*args, cwd=ROOT):
    return subprocess.run([sys.executable, "-S", *map(str, args)], cwd=cwd,
                          capture_output=True, text=True, encoding="utf-8", timeout=20)


def test_cli_exit_codes_and_no_execution(tmp_path):
    file = tmp_path / "macro.py"
    marker = tmp_path / "executed"
    file.write_text(f'open({str(marker)!r}, "w").write("bad")')
    p = cli("-m", "core.authoring_cli", "check-macro", file)
    assert p.returncode == 1
    assert not json.loads(p.stdout)["valid"]
    assert not marker.exists()
    p = cli("-m", "core.authoring_cli", "validate", tmp_path / "missing")
    assert p.returncode == 2
    assert json.loads(p.stdout)["diagnostics"][0]["code"] == "input.invalid"
    file.write_text("log(1)")
    assert cli("-m", "core.authoring_cli", "check-macro", file).returncode == 0
    assert cli("-m", "core.authoring_cli", "check-macro", file, "--warnings-as-errors").returncode == 1


def test_generated_files_and_portable_zip(tmp_path):
    bundle = tmp_path / "skill.zip"
    p = cli("tools/build_authoring.py", "--check", "--zip", bundle)
    assert p.returncode == 0, p.stderr
    with zipfile.ZipFile(bundle) as archive:
        assert "modbusreader-authoring/SKILL.md" in archive.namelist()
        assert not any("__pycache__" in p for p in archive.namelist())
        archive.extractall(tmp_path)
    skill = tmp_path / "modbusreader-authoring"
    entry = skill / "scripts/validate.py"
    map_file = skill / "assets/example-map.json"
    p = cli(entry, "validate", map_file, cwd=tmp_path)
    assert p.returncode == 0, p.stdout + p.stderr
    p = cli(entry, "check-macro", skill / "assets/example-macro.py", "--profile", map_file, cwd=tmp_path)
    assert p.returncode == 0, p.stdout + p.stderr
    # -S hides installed packages; importing Qt/serial/numpy would fail here.
    p = cli(entry, "describe", cwd=tmp_path)
    assert json.loads(p.stdout)["contract_version"] == a.CONTRACT_VERSION


def test_editor_completion_uses_live_registers_and_shared_help(qt_app):
    from gui.macros import CodeEditor, _MACRO_API
    from app.app_context import AppContext
    from PyQt6.QtGui import QTextCursor
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest
    from app.settings_manager import DEFAULT_SETTINGS
    editor = CodeEditor(AppContext(copy.deepcopy(DEFAULT_SETTINGS)).theme_tokens())
    editor.get_registers = lambda: profile()["registers"]
    editor.setPlainText('read("Temp')
    editor.moveCursor(QTextCursor.MoveOperation.End)
    QTest.keyClick(editor, Qt.Key.Key_Space, Qt.KeyboardModifier.ControlModifier)
    assert "Temperature" in editor._completion_values
    editor._insert_completion("Temperature")
    assert editor.toPlainText() == 'read("Temperature'
    editor._completer.popup().hide()
    editor.setPlainText("rea")
    editor.moveCursor(QTextCursor.MoveOperation.End)
    QTest.keyClick(editor, Qt.Key.Key_Space, Qt.KeyboardModifier.ControlModifier)
    editor._insert_completion("read(key, dtype=None)")
    assert editor.toPlainText() == "read"
    assert {row[0] for row in _MACRO_API} == {s.signature for s in macro_api.FUNCTIONS}
    editor._completer.popup().hide()
    editor.deleteLater()
