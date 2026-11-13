# tools/check_project.py
"""Check a project file (and its macros) the way the app will read them —
for a project written by hand or by an AI (see AI_GUIDE.md):

    python tools/check_project.py Projects/AirHeat/AirHeat.mbproj [more…]

What it checks:
  * the file loads (format, migrations) and the map has no overlapping
    spans, duplicate names, unknown types or access values;
  * every dashboard widget: a known kind, a register behind every bound one,
    controls on a writable register, vmin < vmax, options on a «select»,
    a size not below the kind's minimum, unique uids, no two widgets on
    the same spot;
  * every wire joins existing widgets, from one that emits a pulse to one
    that takes it;
  * macros in the project's ``macros/`` folder parse and pass the engine's
    gate (no import, no dunder), and the register names they use exist.

Prints ERROR / WARN lines; exits 1 when there is an ERROR.
"""
import ast
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import datatypes, formats  # noqa: E402
from core import dash_model as dm  # noqa: E402
from core.profile_manager import find_overlaps, find_duplicate_names  # noqa: E402

MACRO_CALLS = ("read", "write", "reg")


def check_registers(regs: list, out: list):
    for r in regs:
        label = f"{datatypes.key_label(datatypes.reg_key(r))} «{r.get('name', '')}»"
        if r.get("type") not in datatypes.TYPES:
            out.append(("ERROR", f"{label}: unknown type {r.get('type')!r}"))
        if r.get("rw") not in ("R", "W", "RW"):
            out.append(("ERROR", f"{label}: rw must be R, W or RW, not {r.get('rw')!r}"))
        if not str(r.get("name", "")).strip():
            out.append(("WARN", f"{label}: no name (macros and widgets find registers by it)"))
    for o in find_overlaps(regs):
        out.append(("ERROR", f"overlapping registers: {o}"))
    for n in find_duplicate_names(regs):
        out.append(("ERROR", f"duplicate name {n!r}: a macro's read({n!r}) gets only one"))


def _writable(reg: dict) -> bool:
    return "W" in str(reg.get("rw", "")) and datatypes.area_of(reg).writable


def check_board(board: dict, by_id: dict, out: list):
    name = board.get("name") or "(unnamed)"
    widgets = board.get("widgets") or []
    uids, spots = set(), {}
    for w in widgets:
        uid, k = w.get("uid"), w.get("kind")
        where = f"board «{name}», widget {uid} «{w.get('title', '')}»"
        if not uid or uid in uids:
            out.append(("ERROR", f"{where}: missing or duplicate uid"))
        uids.add(uid)
        if k not in dm.KINDS:
            out.append(("ERROR", f"{where}: unknown kind {k!r}"))
            continue
        spec = dm.kind(k)
        if spec.bound:
            reg = by_id.get(str(w.get("reg_id", "")).lower())
            if reg is None:
                out.append(("ERROR", f"{where}: reg_id {w.get('reg_id')!r} is not in the map"))
            elif spec.writes and not _writable(reg):
                out.append(("ERROR", f"{where}: a control on a read-only register"))
        if k in dm.RANGE_KINDS and not float(w.get("vmin", 0)) < float(w.get("vmax", 100)):
            out.append(("ERROR", f"{where}: vmin must be below vmax"))
        if k == "select" and not w.get("options"):
            out.append(("ERROR", f"{where}: a select needs options [[value, label], …]"))
        mw, mh = dm.min_size(k)
        if int(w.get("w") or mw) < mw or int(w.get("h") or mh) < mh:
            out.append(("WARN", f"{where}: smaller than the minimum {mw}×{mh}"))
        spot = (w.get("x"), w.get("y"))
        if None not in spot:
            if spot in spots:
                out.append(("WARN", f"{where}: on the same spot as {spots[spot]}"))
            spots[spot] = uid
    kinds = {w.get("uid"): w.get("kind") for w in widgets}
    for link in board.get("links") or []:
        src, dst = link.get("from"), link.get("to")
        if src not in kinds or dst not in kinds:
            out.append(("ERROR", f"board «{name}»: wire {src}→{dst} to a missing widget"))
            continue
        if kinds[src] in dm.KINDS and not dm.kind(kinds[src]).has_out:
            out.append(("ERROR", f"board «{name}»: {src} ({kinds[src]}) has no output"))
        if kinds[dst] in dm.KINDS and not dm.kind(kinds[dst]).has_in:
            out.append(("ERROR", f"board «{name}»: {dst} ({kinds[dst]}) takes no input"))


def check_macro(path: str, names: set, keys: set, out: list):
    from core.macro_engine import _reject_unsafe, MacroRejected
    rel = os.path.basename(path)
    try:
        with open(path, encoding="utf-8") as f:
            code = f.read()
        _reject_unsafe(code)
        tree = ast.parse(code)
    except SyntaxError as e:
        out.append(("ERROR", f"macro {rel}: syntax error at line {e.lineno}: {e.msg}"))
        return
    except MacroRejected as e:
        out.append(("ERROR", f"macro {rel}: {e}"))
        return
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id in MACRO_CALLS and node.args \
                and isinstance(node.args[0], ast.Constant) \
                and isinstance(node.args[0].value, str):
            key = node.args[0].value
            has_type = len(node.args) > (2 if node.func.id == "write" else 1)
            if key.strip().lower() in names:
                continue
            addr = datatypes.parse_key(key)
            if addr is None:
                out.append(("ERROR", f"macro {rel}, line {node.lineno}: "
                                     f"no register named {key!r} in the map"))
            elif addr not in keys and not has_type:
                out.append(("WARN", f"macro {rel}, line {node.lineno}: address {key!r} "
                                    f"is not in the map; give its type"))


def check(path: str) -> list:
    out: list = []
    try:
        doc = formats.load_project(path)
    except Exception as e:
        return [("ERROR", f"does not load: {type(e).__name__}: {e}")]
    regs = (doc.get("profile") or {}).get("registers") or []
    check_registers(regs, out)
    by_id = {datatypes.reg_id(datatypes.reg_key(r)).lower(): r for r in regs}
    for board in doc.get("dashboards") or []:
        check_board(board, by_id, out)
    names = set()
    for r in regs:
        for n in (r.get("name"), r.get("name_en")):
            if n:
                names.add(str(n).strip().lower())
    from app import projects
    macros = os.path.join(projects.project_home(path), projects.MACROS)
    if os.path.isdir(macros):
        for fn in sorted(os.listdir(macros)):
            if fn.endswith(".py"):
                check_macro(os.path.join(macros, fn), names,
                            {datatypes.reg_key(r) for r in regs}, out)
    return out


def main(argv) -> int:
    if not argv:
        print(__doc__)
        return 2
    try:                                 # Cyrillic names on a cp1251 console
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    bad = False
    for path in argv:
        found = check(path)
        print(f"{path}: {'OK' if not found else ''}")
        for level, msg in found:
            print(f"  {level}: {msg}")
            bad = bad or level == "ERROR"
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
