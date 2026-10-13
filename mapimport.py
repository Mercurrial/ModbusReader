# mapimport.py
"""Import a register map from a spreadsheet — CSV or XLSX.

Every vendor ships a different table, so this module deliberately does NOT try
to be a parser for one shape. It reads the file into plain rows, *guesses* which
column is which, and then hands the mapping to the user to correct. The guess is
a convenience; the mapping is the contract.

PURE module (no Qt): reading, guessing, converting and validating are all
testable headless, and the dialog in gui_import_dialog.py only renders them.

Three things here are more subtle than they look:

* **Encoding.** Vendor CSVs are routinely cp1251 (Russian Windows) or carry a
  UTF-8 BOM. Guessing wrong turns every name into mojibake, so the candidates
  are tried in order and the first that decodes wins.
* **Delimiter.** ``;`` is the norm in locales where the decimal separator is a
  comma. csv.Sniffer is used first and a frequency count is the fallback.
* **Addresses.** A datasheet may write ``40001`` (the 4x convention, meaning
  holding register 0), ``0x1F``, ``1F h``, or a plain decimal. Getting this
  wrong shifts an entire map by one, which is far worse than failing loudly —
  so the 4x/3x convention is an explicit, visible option, never a silent guess.
"""

import csv
import io
import os
import re

import datatypes

# ── the fields a column can be mapped to ────────────────────────────────
# key, i18n label key, required?
FIELDS = (
    ("addr", "impFieldAddr", True),
    # Only the address is truly required. A sheet that is nothing but a column
    # of addresses is a legitimate map — the names fall back to "0xNNNN", which
    # build_registers already does for an empty name cell.
    ("name", "impFieldName", False),
    ("type", "impFieldType", False),
    ("rw", "impFieldRw", False),
    ("length", "impFieldLength", False),
    ("unit", "impFieldUnit", False),
    ("scale", "impFieldScale", False),
    ("offset", "impFieldOffset", False),
    ("comment", "impFieldComment", False),
    ("name_en", "impFieldNameEn", False),
)
FIELD_KEYS = tuple(f[0] for f in FIELDS)
REQUIRED_FIELDS = tuple(f[0] for f in FIELDS if f[2])

# Header words that suggest a field, lowercase, RU + EN. Matched as substrings
# against the header cell, longest first so "register name" beats "register".
_HEADER_HINTS = {
    "addr": ("адрес", "address", "addr", "регистр", "register", "reg", "offset рег"),
    "name": ("наименование", "название", "имя", "name", "description", "описание",
             "параметр", "parameter", "tag", "тег"),
    "type": ("тип", "type", "формат", "format", "data type", "тип данных"),
    "rw": ("доступ", "access", "чтение", "запись", "r/w", "rw", "read/write"),
    "length": ("длина", "length", "size", "размер", "кол-во", "count", "words"),
    "unit": ("ед", "единица", "unit", "units", "изм", "размерность"),
    "scale": ("масштаб", "scale", "множитель", "factor", "gain", "к-т"),
    "offset": ("смещение", "offset", "сдвиг", "bias"),
    "comment": ("комментарий", "comment", "примечание", "note", "remark"),
    "name_en": ("name_en", "english", "англ"),
}

# ── address conventions ─────────────────────────────────────────────────
# The "4x" convention writes holding register 0 as 40001. Vendors mix these
# freely, and picking wrong silently shifts the whole map — so it is a choice.
ADDR_MODES = ("raw", "modbus1", "4x")
ADDR_MODE_LABELS = {"raw": "impAddrRaw", "modbus1": "impAddrOneBased",
                    "4x": "impAddr4x"}

_ENCODINGS = ("utf-8-sig", "utf-8", "cp1251", "cp1252", "latin-1")
MAX_PREVIEW_ROWS = 200


class ImportError_(Exception):
    """Readable failure — the dialog shows str(e) verbatim."""


# ═══════════════════════════════════════════════════════════════════════
#  READING
# ═══════════════════════════════════════════════════════════════════════
def read_table(path: str, sheet=None) -> list:
    """File → list of rows, every cell a string. Never returns None."""
    ext = os.path.splitext(path)[1].lower()
    if ext in (".xlsx", ".xlsm"):
        return _read_xlsx(path, sheet)
    return _read_csv(path)


def sheet_names(path: str) -> list:
    """Sheets of an XLSX (empty list for CSV) so the user can pick one."""
    if os.path.splitext(path)[1].lower() not in (".xlsx", ".xlsm"):
        return []
    try:
        from openpyxl import load_workbook
    except ImportError:
        raise ImportError_("Для чтения XLSX установите пакет openpyxl "
                           "(pip install openpyxl).")
    try:
        wb = load_workbook(path, read_only=True, data_only=True)
        try:
            return list(wb.sheetnames)
        finally:
            wb.close()
    except ImportError_:
        raise
    except Exception as e:
        raise ImportError_(f"Не удалось открыть книгу: {e}")


def _read_xlsx(path: str, sheet=None) -> list:
    try:
        from openpyxl import load_workbook
    except ImportError:
        raise ImportError_("Для чтения XLSX установите пакет openpyxl "
                           "(pip install openpyxl).")
    try:
        # data_only: take the cached VALUE of a formula, not "=A1*2".
        wb = load_workbook(path, read_only=True, data_only=True)
    except Exception as e:
        raise ImportError_(f"Не удалось открыть книгу: {e}")
    try:
        ws = wb[sheet] if sheet and sheet in wb.sheetnames else wb.worksheets[0]
        rows = []
        for row in ws.iter_rows(values_only=True):
            rows.append(["" if c is None else str(c).strip() for c in row])
    finally:
        wb.close()
    return _trim(rows)


def _decode(raw: bytes) -> str:
    """Vendor CSVs are often cp1251; guessing wrong ruins every name."""
    for enc in _ENCODINGS:
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def sniff_delimiter(text: str) -> str:
    """``;`` is the norm where the decimal separator is a comma."""
    sample = "\n".join(text.splitlines()[:20])
    try:
        return csv.Sniffer().sniff(sample, delimiters=";,\t|").delimiter
    except csv.Error:
        # Sniffer gives up on short or ragged files — count instead.
        counts = {d: sample.count(d) for d in ";,\t|"}
        best = max(counts, key=counts.get)
        return best if counts[best] else ","


def _read_csv(path: str) -> list:
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except OSError as e:
        raise ImportError_(f"Не удалось прочитать файл: {e}")
    if not raw.strip():
        raise ImportError_("Файл пуст.")
    text = _decode(raw)
    delim = sniff_delimiter(text)
    rows = [[(c or "").strip() for c in r]
            for r in csv.reader(io.StringIO(text), delimiter=delim)]
    return _trim(rows)


def _trim(rows: list) -> list:
    """Drop fully empty leading/trailing rows and right-pad to a rectangle."""
    rows = [r for r in rows if any(str(c).strip() for c in r)]
    if not rows:
        raise ImportError_("В файле нет ни одной непустой строки.")
    width = max(len(r) for r in rows)
    return [list(r) + [""] * (width - len(r)) for r in rows]


# ═══════════════════════════════════════════════════════════════════════
#  GUESSING
# ═══════════════════════════════════════════════════════════════════════
def looks_like_header(row: list) -> bool:
    """True when this row names the columns rather than holding data.

    Deliberately strict: ANY cell that parses as a number means data. A looser
    rule counted ``["16", "Температура", "FLOAT"]`` as a header — one number and
    two words — and treating a data row as a header silently DROPS the first
    register of the map. Erring the other way is harmless: the row shows up in
    the preview and the user can flip the checkbox."""
    cells = [str(c).strip() for c in row if str(c).strip()]
    if not cells:
        return False
    if any(_to_int(c) is not None for c in cells):
        return False
    wordy = sum(1 for c in cells if re.search(r"[A-Za-zА-Яа-я]{2,}", c))
    return wordy >= max(1, len(cells) // 2)


def guess_mapping(header: list) -> dict:
    """Header cells → ``{field: column index}``. Only a starting point: the
    user confirms it, because no two vendor sheets agree."""
    mapping = {}
    used = set()
    # Longest hints first: "тип данных" must win over "тип".
    ranked = sorted(
        ((field, hint) for field, hints in _HEADER_HINTS.items() for hint in hints),
        key=lambda fh: -len(fh[1]))
    for field, hint in ranked:
        if field in mapping:
            continue
        for i, cell in enumerate(header):
            if i in used:
                continue
            if hint in str(cell).strip().lower():
                mapping[field] = i
                used.add(i)
                break
    return mapping


# ═══════════════════════════════════════════════════════════════════════
#  CONVERSION
# ═══════════════════════════════════════════════════════════════════════
def _to_int(text):
    """Parse an address/number written the way datasheets write them."""
    s = str(text).strip().replace(" ", "").replace(" ", "")
    if not s:
        return None
    s = s.rstrip(".")
    neg = s.startswith("-")
    if neg:
        s = s[1:]
    try:
        if s.lower().startswith(("0x", "$", "#")):
            v = int(s.lstrip("$#").replace("0x", "", 1).replace("0X", "", 1), 16)
        elif s.lower().endswith("h"):                 # "1F h" / "1Fh"
            v = int(s[:-1], 16)
        elif re.fullmatch(r"\d+", s):
            v = int(s)
        elif re.fullmatch(r"\d+[.,]0*", s):           # "17,0" from a spreadsheet
            v = int(s.split(".")[0].split(",")[0])
        else:
            return None
    except ValueError:
        return None
    return -v if neg else v


def _to_float(text, default=None):
    s = str(text).strip().replace(" ", "").replace(" ", "").replace(",", ".")
    if not s:
        return default
    try:
        return float(s)
    except ValueError:
        return default


def apply_addr_mode(value: int, mode: str) -> int:
    """Convert a datasheet address to a zero-based Modbus address."""
    if mode == "modbus1":
        return value - 1
    if mode == "4x":
        # 40001 -> 0, 30001 -> 0 (input registers). A value below the block
        # base is a short-form address in the same sheet — those are written
        # one-based too, so 1 -> 0. Never goes negative.
        # Bases are tried highest-first WITHIN each block: with 30001 tested
        # before 40000, the value 40000 matched the 3x block and came out as
        # register 9999 instead of 0.
        for base in (40001, 40000, 30001, 30000):
            if value >= base:
                return value - base
        return max(0, value - 1) if value >= 1 else value
    return value


# Free-text type names seen in the wild → registry keys.
_TYPE_ALIASES = {
    "uint16": "SHORT", "int16": "SHORT", "word": "SHORT", "u16": "SHORT",
    "i16": "SHORT", "short": "SHORT", "холдинг": "SHORT", "hold": "SHORT",
    "uint32": "LONG", "int32": "LONG", "dword": "LONG", "u32": "LONG",
    "i32": "LONG", "long": "LONG",
    "float": "FLOAT", "real": "FLOAT", "float32": "FLOAT", "single": "FLOAT",
    "byte": "BYTE", "uint8": "BYTE", "u8": "BYTE",
    "string": "STR_LEN", "str": "STR_LEN", "строка": "STR_LEN",
    "array": "ARR", "массив": "ARR",
}


def normalize_type(text, default="SHORT") -> str:
    s = str(text).strip()
    if not s:
        return default
    upper = s.upper()
    if upper in datatypes.TYPES:                  # already a registry key
        return upper
    low = s.lower()
    if low in _TYPE_ALIASES:
        return _TYPE_ALIASES[low]
    for alias, key in sorted(_TYPE_ALIASES.items(), key=lambda kv: -len(kv[0])):
        if alias in low:
            return key
    return default


# Access is read token by token. Matching substrings was wrong both ways:
# "write" contains an "r" and came out read-write, while "R/O" matched nothing
# and fell back to read-write as well.
_READ_TOKENS = {"r", "ro", "read", "readonly", "чт", "чтение"}
_WRITE_TOKENS = {"w", "wo", "write", "writeonly", "зп", "з", "запись"}
_BOTH_TOKENS = {"rw", "wr", "чз", "чтзп"}


def normalize_rw(text, default="RW") -> str:
    s = str(text).strip().lower()
    if not s:
        return default
    toks = {t for t in re.split(r"[^a-zа-яё0-9]+", s) if t}
    if toks & _BOTH_TOKENS:
        return "RW"
    r, w = bool(toks & _READ_TOKENS), bool(toks & _WRITE_TOKENS)
    if r and w:
        return "RW"
    if r:
        return "R"
    if w:
        return "W"
    return default


def build_registers(rows, mapping, addr_mode="raw", has_header=True,
                    default_type="SHORT") -> tuple:
    """Rows + mapping → ``(registers, problems)``.

    Never raises on a bad row: a row that cannot yield an address is reported
    in *problems* and skipped, so one broken line in a 500-row sheet does not
    cost the whole import. ``problems`` entries are
    ``(row_number, i18n_key, params)`` — the dialog translates them."""
    missing = [f for f in REQUIRED_FIELDS if f not in mapping]
    if missing:
        raise ImportError_(
            "Не назначены обязательные колонки: " + ", ".join(missing))

    body = rows[1:] if has_header else rows
    first_line = 2 if has_header else 1
    registers, problems, seen = [], [], {}

    def cell(row, field):
        i = mapping.get(field)
        return str(row[i]).strip() if i is not None and i < len(row) else ""

    for n, row in enumerate(body, first_line):
        raw_addr = cell(row, "addr")
        if not raw_addr and not any(cell(row, f) for f in FIELD_KEYS):
            continue                                   # blank row: silent skip
        value = _to_int(raw_addr)
        if value is None:
            problems.append((n, "impBadAddr", {"value": raw_addr or "—"}))
            continue
        addr = apply_addr_mode(value, addr_mode)
        if not 0 <= addr <= 0xFFFF:
            problems.append((n, "impAddrRange", {"value": raw_addr}))
            continue

        reg = {
            "addr": addr,
            "name": cell(row, "name") or f"0x{addr:04X}",
            "type": normalize_type(cell(row, "type"), default_type),
            "rw": normalize_rw(cell(row, "rw")),
        }
        length = _to_int(cell(row, "length"))
        reg["length"] = max(1, min(length, 0xFFFF)) if length else 1
        for key in ("unit", "comment", "name_en"):
            v = cell(row, key)
            if v:
                reg[key] = v
        scale = _to_float(cell(row, "scale"))
        if scale is not None and scale != 1.0:
            reg["scale"] = scale
        offset = _to_float(cell(row, "offset"))
        if offset is not None and offset != 0.0:
            reg["offset"] = offset

        if addr in seen:
            # "dup", not "line": the tuple's first element already carries the
            # CURRENT line, and two different meanings under one key made the
            # message point at itself.
            problems.append((n, "impDuplicateAddr",
                             {"addr": f"0x{addr:04X}", "dup": seen[addr]}))
        else:
            seen[addr] = n
        registers.append(reg)

    if not registers:
        raise ImportError_(
            "Не удалось прочитать ни одного регистра. Проверьте, какая "
            "колонка назначена адресом и правильно ли выбрана строка "
            "заголовка.")

    # 40001 IS a legal 16-bit address, so "raw" cannot be proven wrong — but a
    # sheet where most addresses sit in the 4xxxx/3xxxx block is almost
    # certainly using that convention, and reading it raw shifts the entire map.
    # Say so instead of guessing: a silent shift is the worst outcome here.
    if addr_mode == "raw":
        high = sum(1 for r in registers if r["addr"] >= 30000)
        if high >= max(2, len(registers) * 0.6):
            problems.insert(0, (0, "impMaybe4x", {"n": high}))
    return registers, problems
