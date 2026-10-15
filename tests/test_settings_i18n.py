"""Settings manager/schema + i18n invariants."""
import json
import os

import i18n
import settings_manager as sm
import settings_schema as ss
from settings_manager import DEFAULT_SETTINGS


def test_load_corrupt_falls_back(tmp_path):
    old = sm.SETTINGS_FILE
    try:
        sm.SETTINGS_FILE = str(tmp_path / "s.json")
        open(sm.SETTINGS_FILE, "w").write("{ not json ")
        s = sm.load_settings()
        assert s["transport"] == "serial" and "port" in s
    finally:
        sm.SETTINGS_FILE = old


def test_load_partial_merges_defaults(tmp_path):
    old = sm.SETTINGS_FILE
    try:
        sm.SETTINGS_FILE = str(tmp_path / "s.json")
        json.dump({"port": "COM9"}, open(sm.SETTINGS_FILE, "w"))
        s = sm.load_settings()
        assert s["port"] == "COM9"
        assert s["baudrate"] == DEFAULT_SETTINGS["baudrate"]
    finally:
        sm.SETTINGS_FILE = old


def test_every_schema_field_has_a_default():
    """Schema/manager drift guard: every editable Field's key must exist in
    DEFAULT_SETTINGS (otherwise the dialog writes keys nothing reads)."""
    for fld in ss.iter_fields():
        assert fld.key in DEFAULT_SETTINGS, f"no default for Field {fld.key!r}"


def test_schema_strings_resolve_in_both_langs():
    """Labels/hints/titles that are i18n keys must resolve identically-shaped
    in ru and en; unknown literals pass through unchanged."""
    for lang in ("ru", "en"):
        for page in ss.PAGES:
            assert ss.tr(page.title, lang)
            for sec in page.sections:
                assert ss.tr(sec.title, lang)
                for fld in sec.fields:
                    assert ss.tr(fld.label, lang), fld.key


def test_tr_literal_passthrough():
    assert ss.tr("Serial / RTU", "ru") == "Serial / RTU"
    assert ss.tr("not-a-key-xyz", "en") == "not-a-key-xyz"
    assert ss.tr(("а", "b"), "ru") == "а"      # legacy tuple still resolves
    assert ss.tr(("а", "b"), "en") == "b"


def test_strings_symmetric_and_fallback():
    assert set(i18n.STRINGS["ru"]) == set(i18n.STRINGS["en"])
    t = i18n.get_translator("ru")
    assert t("missing_key_xyz") == "missing_key_xyz"
    assert i18n.get_translator("zz")("save") == "Save"   # unknown lang -> en


def test_every_used_translation_key_exists():
    """Every t("key") / ctx.t("key") reference in the GUI must resolve.

    Catches the classic 'added a label, forgot the string' — an unresolved key
    renders as the raw key text in the UI."""
    import glob
    import os
    import re
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    pat = re.compile(r'\bt\(\s*["\']([a-zA-Z][a-zA-Z0-9_]*)["\']\s*\)')
    known = set(i18n.STRINGS["ru"])
    missing = {}
    for path in glob.glob(os.path.join(root, "*.py")):
        name = os.path.basename(path)
        if name in ("i18n.py", "settings_schema.py", "bundle_project.py"):
            continue          # the schema stores keys as data (tr passthrough)
        with open(path, encoding="utf-8") as f:
            for lineno, line in enumerate(f, 1):
                for key in pat.findall(line):
                    if key not in known:
                        missing.setdefault(name, []).append((lineno, key))
    assert not missing, f"translation keys used but not defined: {missing}"


def test_no_hardcoded_ui_strings_in_qt_calls():
    """Any literal handed to a Qt text setter never switches language.

    This caught a whole English context menu in the register table, the status
    bar, the log placeholder and the memory viewer. Strings that legitimately
    stay put (brand, protocol tokens, a font specimen) are allow-listed."""
    import ast
    import glob
    import os
    import re

    ALLOWED = {
        "ModbusReader", "ProTuner - Industrial SCADA",   # brand
        "SHORT", "FLOAT", "LONG",                        # protocol tokens
        "АаБбВв · AaBbCc · 0123456789",                  # font specimen
        "Serial / RTU",
    }
    # Dialog helpers take the title/body as plain arguments, so the first
    # version of this guard walked straight past a screenful of hardcoded
    # Russian in the profile-loading error dialogs.
    UI_CALLS = {"setText", "setToolTip", "setPlaceholderText", "setWindowTitle",
                "addItem", "addItems", "addAction", "setTitle", "addMenu",
                "themed_info", "themed_message"}
    # Widget constructors and static dialogs take their text as an argument
    # too — QInputDialog.getText(self, "Write value", …) and a memory viewer
    # full of QLabel("Columns:") went straight past the setter-only check.
    CTORS = {"QLabel", "QPushButton", "QCheckBox", "QAction", "QGroupBox",
             "QRadioButton"}
    DIALOGS = {"getText", "getOpenFileName", "getSaveFileName", "getItem",
               "getInt", "getExistingDirectory"}
    cyr = re.compile(r"[А-Яа-яЁё]")
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    skip = {"i18n.py", "styles.py", "icons.py", "theme_manager.py",
            "settings_schema.py", "datatypes.py", "bundle_project.py"}
    bad = []
    for path in glob.glob(os.path.join(root, "*.py")):
        name = os.path.basename(path)
        if name in skip:
            continue
        tree = ast.parse(open(path, encoding="utf-8").read())

        def literals(node):
            """Literal text this expression contributes DIRECTLY.

            Deliberately does not recurse into nested calls: ``t("key")`` and
            ``reg.get("name")`` carry lookup keys, not prose, and treating
            those as UI text drowns the real findings."""
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                return [node]
            if isinstance(node, ast.JoinedStr):     # f-string: only its text
                return [v for v in node.values
                        if isinstance(v, ast.Constant)
                        and isinstance(v.value, str)]
            if isinstance(node, ast.BinOp):         # "a" + something
                return literals(node.left) + literals(node.right)
            if isinstance(node, (ast.List, ast.Tuple)):
                return [x for e in node.elts for x in literals(e)]
            return []

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            if isinstance(fn, ast.Attribute):
                call = fn.attr
            elif isinstance(fn, ast.Name):
                call = fn.id
            else:
                call = None
            if call in CTORS:
                args = node.args                 # QLabel("…"), QPushButton("…")
            elif call in DIALOGS:
                args = node.args[1:2]            # the dialog title
            elif call == "themed_input":
                args = node.args[2:4]            # title, label
            elif call in ("themed_info", "themed_message"):
                # (parent, theme, KIND, title, text, …) — the kind is a token
                args = node.args[3:]
            elif call in UI_CALLS:
                args = node.args
            else:
                continue
            for arg in args:
                for lit in literals(arg):
                    v = lit.value.strip()
                    if len(v) < 4 or v in ALLOWED:
                        continue
                    if cyr.search(v) or re.search(r"[A-Za-z]{4,}", v):
                        bad.append(f"{name}:{lit.lineno} {call}({v[:48]!r})")
    assert not bad, ("hardcoded UI strings (these never translate):\n  "
                     + "\n  ".join(sorted(bad)))


def test_dashboard_kinds_all_have_labels_and_hints():
    import dash_model as dm
    for key in dm.KINDS:
        assert dm.kind(key).label_key in i18n.STRINGS["ru"]
        assert f"dashHint{key.capitalize()}" in i18n.STRINGS["ru"]


def test_datatype_hints_translated():
    import datatypes
    for key in datatypes.TYPES:
        assert f"hint{key}" in i18n.STRINGS["ru"], f"no hint for {key}"
        assert f"hint{key}" in i18n.STRINGS["en"]


def test_com_ports_helper_never_raises():
    ports = ss._com_ports()
    assert isinstance(ports, tuple)
