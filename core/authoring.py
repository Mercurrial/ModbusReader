"""Strict, offline authoring contract. Legacy runtime loaders remain unchanged.

The JSON Schemas describe current files, not every shape accepted by migrations.
Only the schema keywords emitted here are interpreted by _shape; semantic checks
are additional to JSON Schema. No Qt, network, device access or script execution.
"""
import ast
from dataclasses import asdict, dataclass
import json
import math
import re

from core import byteorder, dash_model, datatypes, formats, macro_api, transports

CONTRACT_VERSION = 1


@dataclass(frozen=True)
class Diagnostic:
    code: str
    message: str
    path: str = ""
    severity: str = "error"
    line: int | None = None
    column: int | None = None


def result(diagnostics):
    return {"contract_version": CONTRACT_VERSION,
            "valid": not any(d.severity == "error" for d in diagnostics),
            "diagnostics": [asdict(d) for d in diagnostics]}


def _obj(properties, required=(), additional=False):
    return {"type": "object", "properties": properties,
            "required": list(required), "additionalProperties": additional}


def _array(items):
    return {"type": "array", "items": items}


def _integer(lo, hi):
    return {"type": "integer", "minimum": lo, "maximum": hi}


def schemas():
    """Return fresh, self-contained JSON Schema 2020-12 documents."""
    text = {"type": "string"}
    nonempty = {"type": "string", "minLength": 1}
    number = {"type": "number"}
    boolean = {"type": "boolean"}
    register = _obj({
        "addr": _integer(0, 65535), "name": nonempty,
        "name_en": text, "type": {"enum": list(datatypes.TYPES)},
        "length": _integer(1, 65535), "rw": {"enum": ["R", "W", "RW", "RO", "WO"]},
        "area": {"enum": list(datatypes.AREAS)},
        "unit": text, "comment": text, "default": {"type": ["string", "number", "boolean"]},
        "scale": number, "offset": number,
        "enum": {"type": "object", "propertyNames": {"pattern": r"^-?(0|[1-9][0-9]*)$"},
                 "additionalProperties": text},
    }, ("addr", "name", "type", "rw"))
    profile = _obj({"format": {"const": formats.PROFILE_KIND},
                    "version": {"const": formats.PROFILE_VERSION}, "name": text,
                    "registers": _array(register)}, ("format", "version", "registers"))
    widget = _obj({
        "uid": nonempty, "kind": {"enum": list(dash_model.KINDS)},
        "x": _integer(0, 1000000), "y": _integer(0, 1000000),
        "w": _integer(1, 1000000), "h": _integer(1, 1000000),
        "reg_id": {"type": "string", "pattern": r"^0x[0-9a-fA-F]{4,5}$"},
        "reg_type": {"enum": list(datatypes.TYPES)}, "name": text, "title": text, "unit": text,
        "vmin": number, "vmax": number, "thr": number, "invert": boolean,
        "alo": {"type": ["number", "null"]}, "ahi": {"type": ["number", "null"]},
        "value_on": {"type": ["number", "string"]}, "value_off": {"type": ["number", "string"]},
        "interval": _integer(50, 2147483647), "autostart": boolean,
        "cond": {"enum": list(dash_model.CONDITIONS)}, "cmp": number,
        "step": {"type": "number", "exclusiveMinimum": 0}, "live": boolean,
        "options": _array({"type": "array", "prefixItems": [{"type": "integer"}, text],
                           "items": False, "minItems": 2, "maxItems": 2}),
    }, ("uid", "kind"))
    board = _obj({"format": {"const": formats.DASHBOARD_KIND},
                  "version": {"const": formats.DASHBOARD_VERSION}, "name": text,
                  "widgets": _array(widget),
                  "links": _array(_obj({"from": nonempty, "to": nonempty}, ("from", "to")))},
                 ("widgets", "links"))
    dashboard = dict(board, required=["format", "version", "widgets", "links"])
    connection_fields = {
        "transport": {"enum": list(transports.BY_ID)}, "port": text, "host": text,
        "baudrate": {"type": ["integer", "string"], "pattern": r"^[1-9][0-9]{0,6}$", "minimum": 1, "maximum": 4000000}, "tcp_port": _integer(1, 65535),
        "parity": {"enum": ["N", "E", "O", "M", "S", "None (N)", "Even (E)", "Odd (O)", "Mark (M)", "Space (S)", "None", "Even", "Odd", "Mark", "Space"]},
        "stopbits": {"enum": ["1", "1.5", "2", 1, 1.5, 2]},
        "slave_id": _integer(0, 255), "timeout": _integer(100, 5000),
        "poll_rate": _integer(100, 5000), "interframe_delay": _integer(0, 500),
        "retry_count": _integer(1, 1000),
        "order_short": {"enum": list(byteorder.ORDERS_16)},
        "order_long": {"enum": list(byteorder.ORDERS_32)},
        "order_float": {"enum": list(byteorder.ORDERS_32)},
    }
    # Missing a new persisted connection key is a maintenance error, not a
    # silently permissive contract. The generator/test catches it immediately.
    if set(connection_fields) != set(formats.PROJECT_CONNECTION_KEYS):
        raise ValueError("Update authoring schema for PROJECT_CONNECTION_KEYS")
    layout_fields = {"pinned_views": _array(text), "last_view": text,
                     "log_height": _integer(0, 1000000), "show_log": boolean,
                     "graph_width": _integer(0, 1000000)}
    if set(layout_fields) != set(formats.PROJECT_LAYOUT_KEYS):
        raise ValueError("Update authoring schema for PROJECT_LAYOUT_KEYS")
    project = _obj({"format": {"const": formats.PROJECT_KIND},
                    "version": {"const": formats.PROJECT_VERSION}, "name": text,
                    "connection": _obj(connection_fields), "profile": profile,
                    "dashboards": _array(board), "layout": _obj(layout_fields),
                    "simulation": {"enum": ["thermo"]}},
                   ("format", "version", "connection", "profile", "dashboards"))
    return {key: dict(schema, **{"$schema": "https://json-schema.org/draft/2020-12/schema",
                                "title": f"ModbusReader {key} authoring contract"})
            for key, schema in (("profile", profile), ("dashboard", dashboard), ("project", project))}


def catalog():
    return {"contract_version": CONTRACT_VERSION,
            "schemas": schemas(),
            "types": [{"key": d.key, "span": d.fixed_span, "codec": d.is_scalar,
                       "text": d.text, "service_area": d.is_area, "hint": d.hint}
                      for d in datatypes.TYPES.values()],
            "areas": [asdict(a) for a in datatypes.AREAS.values()],
            "widgets": [asdict(k) for k in dash_model.KINDS.values()],
            "macro_api": [dict(asdict(f), signature=f.signature) for f in macro_api.FUNCTIONS],
            "macro_builtins": list(macro_api.SAFE_BUILTIN_NAMES)}


def _pointer(path, key):
    return path + "/" + str(key).replace("~", "~0").replace("/", "~1")


def _type(value, kind):
    return {"object": lambda: isinstance(value, dict),
            "array": lambda: isinstance(value, list),
            "string": lambda: isinstance(value, str),
            "boolean": lambda: isinstance(value, bool),
            "null": lambda: value is None,
            "integer": lambda: type(value) is int,
            "number": lambda: type(value) in (int, float) and (not isinstance(value, float) or math.isfinite(value))}[kind]()


def _shape(value, schema, path, issues):
    """Interpreter for this module's emitted keywords, NOT a general schema engine."""
    def fail(code, message, at=path):
        issues.append(Diagnostic(code, message, at))
    if schema is False:
        fail("schema.extra_item", "Unexpected array item")
        return
    kinds = schema.get("type")
    if kinds and not any(_type(value, k) for k in ([kinds] if isinstance(kinds, str) else kinds)):
        fail("schema.type", f"Expected {kinds}")
        return
    # bool must never satisfy an integer enum/const (Python True == 1).
    def equal(a, b):
        return (type(a) is bool) == (type(b) is bool) and a == b
    if "const" in schema and not equal(value, schema["const"]):
        fail("schema.const", f"Expected {schema['const']!r}")
    if "enum" in schema and not any(equal(value, v) for v in schema["enum"]):
        fail("schema.enum", f"Expected one of {schema['enum']}")
    if type(value) in (int, float):
        if isinstance(value, float) and not math.isfinite(value):
            fail("schema.finite", "Non-finite numbers are not JSON values")
        for key, bad in (("minimum", lambda x: value < x), ("maximum", lambda x: value > x),
                         ("exclusiveMinimum", lambda x: value <= x)):
            if key in schema and bad(schema[key]):
                fail("schema.range", f"Requires {key} {schema[key]}")
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            fail("schema.empty", "Must not be empty")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            fail("schema.pattern", f"Must match {schema['pattern']}")
    if isinstance(value, dict):
        props = schema.get("properties", {})
        for key in schema.get("required", ()):
            if key not in value:
                fail("schema.required", f"Missing field: {key}", _pointer(path, key))
        for key, item in value.items():
            at = _pointer(path, key)
            if "propertyNames" in schema:
                _shape(key, schema["propertyNames"], at, issues)
            if key in props:
                _shape(item, props[key], at, issues)
            else:
                extra = schema.get("additionalProperties", True)
                if extra is False:
                    fail("schema.unknown", f"Unknown field: {key}", at)
                elif isinstance(extra, dict):
                    _shape(item, extra, at, issues)
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0) or len(value) > schema.get("maxItems", math.inf):
            fail("schema.length", "Invalid array length")
        prefix = schema.get("prefixItems", [])
        for i, item in enumerate(value):
            _shape(item, prefix[i] if i < len(prefix) else schema.get("items", {}), _pointer(path, i), issues)


def _registers(rows, path, issues):
    names, keys, spans = {}, {}, {}
    for i, reg in enumerate(rows):
        at = _pointer(path, i)
        dtype = datatypes.TYPES[reg["type"]]
        area = datatypes.area_of(reg)
        key = datatypes.reg_key(reg)
        length = reg.get("length", 1)
        span = dtype.fixed_span or length
        if reg["addr"] + span > 65536:
            issues.append(Diagnostic("register.overflow", "Register span exceeds address 65535", at))
        if area.bits and (reg["type"] != "BOOL" or length != 1):
            issues.append(Diagnostic("register.bit_type", "Bit tables require BOOL with length 1", at))
        if not area.writable and "W" in reg["rw"]:
            issues.append(Diagnostic("register.read_only", "Input/discrete tables cannot be writable", at))
        if dtype.text and length > datatypes.MAX_READ:
            issues.append(Diagnostic("register.text_length", f"STRING reads are limited to {datatypes.MAX_READ} words", at))
        if reg.get("scale", 1) == 0:
            issues.append(Diagnostic("register.zero_scale", "Scale must be nonzero for reversible conversion", at))
        if not dtype.is_scalar and not dtype.is_area:
            issues.append(Diagnostic("register.no_codec", "Type has no scalar codec; macro read/write is unavailable", at, "warning"))
        for field in ("name", "name_en"):
            if field not in reg:
                continue
            name = reg[field].strip().lower()
            if not name:
                issues.append(Diagnostic("register.empty_name", "Name must contain non-whitespace characters", _pointer(at, field)))
            elif name in names and names[name] != i:
                issues.append(Diagnostic("register.ambiguous_name", "Name/translation collides with another register", _pointer(at, field)))
            names[name] = i
        if key in keys:
            issues.append(Diagnostic("register.duplicate", "Duplicate address in the same Modbus table", at))
        keys[key] = reg
        spans.setdefault(area.key, []).append((reg["addr"], reg["addr"] + span, at))
    # Sweep, rather than pairwise comparisons over large maps.
    for ranges in spans.values():
        end = -1
        for start, stop, at in sorted(ranges):
            if start < end:
                issues.append(Diagnostic("register.overlap", "Overlapping register spans in the same table", at, "warning"))
            end = max(end, stop)
    return keys


def _dashboard(board, path, registers, issues):
    cards = {}
    for i, w in enumerate(board["widgets"]):
        at = _pointer(path + "/widgets", i)
        spec = dash_model.KINDS[w["kind"]]
        if w["uid"] in cards:
            issues.append(Diagnostic("dashboard.duplicate_uid", "Widget uid is not unique", at + "/uid"))
        cards[w["uid"]] = w
        if spec.bound:
            rid = w.get("reg_id", "")
            key = int(rid, 16) if rid else -1
            if key < 0 or key >> 16 not in {a.code for a in datatypes.AREAS.values()}:
                issues.append(Diagnostic("dashboard.binding", "Expected area-aware reg_id (hex composite key)", at + "/reg_id"))
            elif rid != datatypes.reg_id(key):
                issues.append(Diagnostic("dashboard.binding", f"Use canonical reg_id {datatypes.reg_id(key)}", at + "/reg_id"))
            elif registers is not None:
                reg = registers.get(key)
                if reg is None:
                    issues.append(Diagnostic("dashboard.missing_register", "Binding does not exist in profile", at + "/reg_id"))
                elif not datatypes.is_scalar(reg["type"]) or datatypes.is_text(reg["type"]):
                    issues.append(Diagnostic("dashboard.non_numeric", "Dashboard requires a numeric codec-backed register", at))
                elif spec.writes and not datatypes.is_writable(reg):
                    issues.append(Diagnostic("dashboard.read_only", "Control is bound to a read-only register", at))
                if reg and "reg_type" in w and w["reg_type"] != reg["type"]:
                    issues.append(Diagnostic("dashboard.type_mismatch", "reg_type differs from the map", at + "/reg_type"))
        if w.get("vmin", 0) >= w.get("vmax", 100) and w["kind"] in dash_model.RANGE_KINDS:
            issues.append(Diagnostic("dashboard.range", "vmin must be less than vmax", at))
        for field, minimum in (("w", spec.min_w), ("h", spec.min_h)):
            if field in w and w[field] < minimum:
                issues.append(Diagnostic("dashboard.geometry", f"{field} must be at least {minimum} for {spec.key}", at + "/" + field))
    edges = set()
    for i, link in enumerate(board["links"]):
        at = _pointer(path + "/links", i)
        source, target = cards.get(link["from"]), cards.get(link["to"])
        if source is None or target is None:
            issues.append(Diagnostic("dashboard.dangling_link", "Link endpoint does not exist", at))
        elif not dash_model.KINDS[source["kind"]].has_out or not dash_model.KINDS[target["kind"]].has_in:
            issues.append(Diagnostic("dashboard.port", "Link uses an unavailable input/output port", at))
        edge = (link["from"], link["to"])
        if edge in edges or edge[0] == edge[1]:
            issues.append(Diagnostic("dashboard.redundant_link", "Duplicate or self link", at, "warning"))
        edges.add(edge)
    if registers is None and any(dash_model.KINDS[w["kind"]].bound for w in board["widgets"]):
        issues.append(Diagnostic("dashboard.unchecked_bindings", "Use --profile to check bindings against a map", path, "warning"))


def document_kind(doc):
    kinds = {formats.PROFILE_KIND: "profile", formats.PROJECT_KIND: "project", formats.DASHBOARD_KIND: "dashboard"}
    return kinds.get(doc.get("format")) if isinstance(doc, dict) and isinstance(doc.get("format"), str) else None


def validate_document(doc, kind=None, profile=None):
    """Validate without migration, coercion, mutation or opening a device."""
    issues = []
    kind = kind or document_kind(doc)
    if kind not in schemas():
        return [Diagnostic("document.format", "Specify a current format envelope: profile, project or dashboard")]
    _shape(doc, schemas()[kind], "", issues)
    if issues:
        return issues  # semantics only see structurally valid values
    regs = None
    if profile is not None:
        external = validate_document(profile, "profile")
        issues.extend(Diagnostic(d.code, d.message, "/external_profile" + d.path, d.severity) for d in external)
        if any(d.severity == "error" for d in external):
            return issues
        regs = {datatypes.reg_key(r): r for r in profile["registers"]}
    if kind == "profile":
        _registers(doc["registers"], "/registers", issues)
    elif kind == "dashboard":
        _dashboard(doc, "", regs, issues)
    else:
        regs = _registers(doc["profile"]["registers"], "/profile/registers", issues)
        for i, board in enumerate(doc["dashboards"]):
            _dashboard(board, f"/dashboards/{i}", regs, issues)
        conn = doc["connection"]
        if "baudrate" in conn and int(conn["baudrate"]) > 4000000:
            issues.append(Diagnostic("connection.baudrate", "Baudrate exceeds 4000000", "/connection/baudrate"))
        lo, hi = transports.id_range(conn)
        if "slave_id" in conn and not lo <= conn["slave_id"] <= hi:
            issues.append(Diagnostic("connection.unit_id", f"Unit id must be {lo}..{hi} for this transport", "/connection/slave_id"))
        if conn.get("transport") == "sim" and doc.get("simulation") != "thermo":
            issues.append(Diagnostic("connection.simulation", "sim transport requires simulation=thermo", "/simulation"))
    return issues


def read_json(path):
    """Reject duplicate keys and non-JSON constants before any normalization."""
    def pairs(items):
        out = {}
        for key, value in items:
            if key in out:
                raise ValueError(f"Duplicate JSON key: {key}")
            out[key] = value
        return out
    def constant(value):
        raise ValueError(f"Non-JSON constant: {value}")
    with open(path, encoding="utf-8-sig") as stream:
        return json.load(stream, object_pairs_hook=pairs, parse_constant=constant)


def check_macro(code, profile=None):
    """Static checks, never eval/exec/import a user script. Not a sandbox/type checker."""
    issues = []
    try:
        tree = ast.parse(code, filename="<macro>")
        # Compilation also rejects return/break outside their enclosing constructs.
        compile(tree, "<macro>", "exec")
    except (SyntaxError, ValueError, RecursionError) as exc:
        return [Diagnostic("macro.syntax", str(exc), line=getattr(exc, "lineno", None), column=getattr(exc, "offset", None))]
    source_lines = code.splitlines()
    def add(node, diagnostic_code, message, severity="error"):
        # AST columns are UTF-8 byte offsets, editor columns count characters.
        prefix = source_lines[node.lineno - 1].encode("utf-8")[:node.col_offset]
        issues.append(Diagnostic(diagnostic_code, message, severity=severity,
                                 line=node.lineno, column=len(prefix.decode("utf-8")) + 1))
    for node, key, params in macro_api.policy_issues(tree):
        add(node, "macro.policy", "Imports are unavailable" if key == "macNoImport" else f"Dunder access is unavailable: {params['name']}")
    names, keys = {}, {}
    if profile is not None:
        validation = validate_document(profile, "profile")
        issues.extend(validation)
        if any(d.severity == "error" for d in validation):
            return issues
        for reg in profile["registers"]:
            keys[datatypes.reg_key(reg)] = reg
            for name in (reg["name"], reg.get("name_en")):
                if name:
                    names[name.strip().lower()] = reg
    # Rebinding/shadowing makes call inference unsafe. Skip these names instead
    # of reporting false arity/register errors for user-defined functions.
    assigned = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)}
    assigned.update(n.arg for n in ast.walk(tree) if isinstance(n, ast.arg))
    assigned.update(n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name) or node.func.id in assigned:
            continue
        name = node.func.id
        spec = macro_api.BY_NAME.get(name)
        if not spec:
            if name in ("open", "eval", "exec", "compile", "__import__", "getattr", "globals", "locals", "Exception", "ValueError", "RuntimeError"):
                add(node, "macro.unavailable", f"{name} is not exposed by the macro runtime")
            continue
        if any(isinstance(a, ast.Starred) for a in node.args) or any(k.arg is None for k in node.keywords):
            add(node, "macro.dynamic_call", "Unpacked arguments are not statically checked", "warning")
            continue
        try:
            bound = spec.bind(node.args, {k.arg: k.value for k in node.keywords}).arguments
        except TypeError as exc:
            add(node, "macro.arguments", f"{spec.signature}: {exc}")
            continue
        if name not in ("reg", "read", "write"):
            continue
        key_node = bound["key"]
        if not isinstance(key_node, ast.Constant):
            add(node, "macro.dynamic_register", "Computed register keys require runtime verification", "warning")
            continue
        key = key_node.value
        reg = names.get(key.strip().lower()) if isinstance(key, str) else None
        numeric = datatypes.parse_key(key) if isinstance(key, str) and reg is None else key
        if reg is None and type(numeric) is int:
            if not 0 <= numeric <= 0x3FFFF:
                add(node, "macro.address", "Address key must be within the four Modbus tables")
                continue
            reg = keys.get(numeric)
        elif reg is None and not isinstance(key, str):
            add(node, "macro.key", "Key must be a register name or integer address (not bool)")
            continue
        dtype_node = bound.get("dtype")
        dtype = dtype_node.value if isinstance(dtype_node, ast.Constant) else None
        if dtype is not None and (not isinstance(dtype, str) or dtype not in datatypes.SCALAR_KEYS):
            add(node, "macro.dtype", "dtype must name a codec-backed type")
        if profile is not None and reg is None:
            if type(numeric) is int and dtype in datatypes.SCALAR_KEYS:
                add(node, "macro.outside_map", "Explicit address/type is outside the map; device access is unverified", "warning")
            else:
                add(node, "macro.missing_register", "Register is not in the map; numeric addresses outside the map require dtype")
        if reg:
            if not datatypes.is_scalar(reg["type"]):
                add(node, "macro.no_codec", "This map entry is not available to macros")
            if name == "write" and not datatypes.is_writable(reg):
                add(node, "macro.read_only", "Writing to a read-only map entry is not allowed by the authoring contract")
            if reg.get("scale", 1) != 1 or reg.get("offset", 0) != 0:
                add(node, "macro.raw_units", "Macro I/O bypasses scale/offset; convert engineering values explicitly", "warning")
    if profile is None:
        issues.append(Diagnostic("macro.unchecked_registers", "Use --profile to check literal register references", severity="warning"))
    return issues
