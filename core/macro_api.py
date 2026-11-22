"""Pure macro contract shared by runtime, editor, documentation and offline tools."""
import ast
from dataclasses import dataclass
import inspect


@dataclass(frozen=True)
class Function:
    name: str
    parameters: str
    returns: str
    target: str
    ru: str
    en: str

    @property
    def signature(self):
        return f"{self.name}({self.parameters})"

    def bind(self, args, kwargs):
        # Parse only our own trusted declaration, never user code.
        node = ast.parse(f"def f({self.parameters}): pass").body[0].args
        params = []
        start = len(node.args) - len(node.defaults)
        for i, arg in enumerate(node.args):
            default = inspect.Parameter.empty if i < start else ast.literal_eval(node.defaults[i - start])
            params.append(inspect.Parameter(arg.arg, inspect.Parameter.POSITIONAL_OR_KEYWORD, default=default))
        if node.vararg:
            params.append(inspect.Parameter(node.vararg.arg, inspect.Parameter.VAR_POSITIONAL))
        if node.kwarg:
            params.append(inspect.Parameter(node.kwarg.arg, inspect.Parameter.VAR_KEYWORD))
        return inspect.Signature(params).bind(*args, **kwargs)


FUNCTIONS = tuple(Function(*row) for row in [
    ("reg", "key, dtype=None", "Register", "api_reg",
     "Объект регистра: .read(), .write(value), .value (новое чтение), .addr, .type, .name.",
     "Register handle: .read(), .write(value), .value (a fresh read), .addr, .type, .name."),
    ("read", "key, dtype=None", "object", "api_read",
     "Прочитать декодированное значение без scale/offset. Ключ: имя, адрес или строка IR/CO/DI.",
     "Read a decoded value before scale/offset. Key: map name, address, or IR/CO/DI address string."),
    ("write", "key, value, dtype=None", "object", "api_write",
     "Записать значение без scale/offset; вернуть переданное value. Учитывайте доступ регистра.",
     "Write a value before scale/offset; return the supplied value. Respect register access permissions."),
    ("read_all", "", "dict", "api_read_all",
     "Прочитать все типы с кодеками из карты, включая STRING; результат {имя: значение}.",
     "Read all codec-backed map entries, including STRING; return {name: value}."),
    ("wait", "seconds", "None", "api_wait", "Прерываемая пауза в секундах.", "Interruptible delay in seconds."),
    ("sleep", "seconds", "None", "api_wait", "Псевдоним wait.", "Alias of wait."),
    ("record", "row=None, **kwargs", "None", "api_record",
     "Добавить строку результатов: словарь и/или именованные колонки; kwargs имеют приоритет.",
     "Append a result row: a dict and/or named columns; keyword columns override dict keys."),
    ("log", "*args", "None", "api_log", "Сообщение в журнал; аргументы разделены пробелами.", "Log arguments joined with spaces."),
    ("print", "*args", "None", "api_log", "Псевдоним log; sep/end/file не поддерживаются.", "Alias of log; sep/end/file are not supported."),
    ("now", "", "float", "time.time", "Unix-время в секундах, не монотонные часы.", "Unix time in seconds, not a monotonic clock."),
    ("timestamp", "", "str", "api_timestamp", "Локальное время: YYYY-MM-DD HH:MM:SS.", "Local time: YYYY-MM-DD HH:MM:SS."),
])
BY_NAME = {f.name: f for f in FUNCTIONS}
SAFE_BUILTIN_NAMES = (
    "abs", "min", "max", "round", "sum", "len", "range", "enumerate", "zip",
    "map", "filter", "sorted", "reversed", "int", "float", "str", "bool",
    "list", "dict", "tuple", "set", "frozenset", "divmod", "pow", "bin", "hex",
    "oct", "ord", "chr", "format", "repr", "any", "all", "isinstance",
)


def policy_issues(tree):
    """Yield (node, translation key, parameters), matching runtime's AST gate."""
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            yield node, "macNoImport", {}
        name = node.attr if isinstance(node, ast.Attribute) else node.id if isinstance(node, ast.Name) else None
        if name and name.startswith("__") and name.endswith("__"):
            yield node, "macNoDunder", {"name": name}


def completion_items(registers=(), language="en"):
    """Structured suggestions for editors; no Qt dependency or script execution."""
    from core import datatypes
    items = [{"label": f.signature, "insert_text": f.name, "kind": "function",
              "detail": f.ru if language == "ru" else f.en} for f in FUNCTIONS]
    for reg in registers:
        if not datatypes.is_scalar(reg.get("type")):
            continue
        for name in dict.fromkeys((reg.get("name"), reg.get("name_en"))):
            if name:
                items.append({"label": name, "insert_text": name, "kind": "register",
                              "detail": f"{datatypes.key_label(datatypes.reg_key(reg))}: {reg['type']}"})
    return items
