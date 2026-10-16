import json

from core import datatypes
from core import formats


def load_profile_data(file_path):
    """Считывает профиль ЛЮБОЙ версии и возвращает плоский список регистров.

    Старые форматы (голый JSON-массив, ``{"registers":[...]}`` без версии) и
    новый версионированный конверт мигрируются в formats.migrate_profile до
    текущей версии — так файлы, записанные любой прошлой сборкой, открываются
    вечно, а все существующие потребители по-прежнему получают плоский список.
    Бросает исключение при ошибке чтения/разбора."""
    # A profile can arrive from a colleague, a backup or a half-finished
    # write. Every failure mode must surface as a readable message (the UI
    # shows str(e) verbatim), not as a bare UnicodeDecodeError.
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            doc = json.load(f)
    except UnicodeDecodeError:
        raise ValueError(
            "Профиль: файл не в кодировке UTF-8 (или это не текстовый файл).")
    except json.JSONDecodeError as e:
        raise ValueError(
            f"Профиль: некорректный JSON в строке {e.lineno}: {e.msg}")
    return formats.migrate_profile(doc)["registers"]


# ── profile validation (warnings, not errors) ────────────────────────
def find_overlaps(registers: list) -> list[str]:
    """Detect overlapping address spans in a register list.

    Each register occupies ``[addr, addr + datatypes.addr_span(reg))``.
    Returns human-readable conflict strings ("0x0010 «Temp» ∩ 0x0011 «Flow»"),
    empty when the profile is clean. Non-dict rows and rows with non-numeric
    addresses are skipped (they can't be polled anyway)."""
    # Each Modbus table is its own address space: coil 0x10 and holding 0x10
    # never overlap. The composite key (area << 16 | addr) sorts per table.
    spans = []
    for reg in registers:
        if not isinstance(reg, dict):
            continue
        addr = reg.get("addr")
        if isinstance(addr, bool) or not isinstance(addr, int):
            continue
        key = datatypes.reg_key(reg)
        spans.append((key, key + datatypes.addr_span(reg),
                      str(reg.get("name", f"0x{addr:04X}"))))
    spans.sort()
    out = []
    for (a0, a1, n_a), (b0, b1, n_b) in zip(spans, spans[1:]):
        if b0 < a1 and (a0 >> 16) == (b0 >> 16):
            out.append(f"{datatypes.key_label(a0)} «{n_a}» ∩ "
                       f"{datatypes.key_label(b0)} «{n_b}»")
    return out


def find_duplicate_names(registers: list) -> list[str]:
    """Register names appearing more than once — case-insensitive, matching
    the macro engine's name lookup (duplicates silently shadow each other)."""
    seen: dict[str, int] = {}
    for reg in registers:
        if not isinstance(reg, dict):
            continue
        name = str(reg.get("name", "")).strip().lower()
        if name:
            seen[name] = seen.get(name, 0) + 1
    return [name for name, count in seen.items() if count > 1]


# ── address chaining (the editor's addressing model) ─────────────────
# A register map built in the editor is usually CONTIGUOUS: each register sits
# right where the previous one ends, so changing a type from SHORT to FLOAT
# must push everything after it by one address. A map imported from a vendor
# sheet is not: it has gaps (0x0000, 0x0010, 0x0100…) because the device has
# them. The editor used to renumber EVERY row from 0 on any structural edit,
# which silently destroyed such a map — and polled the wrong registers.
#
# So each register is either CHAINED (it starts where its predecessor ends, or
# overlaps it — a broken spot that packing fixes) and moves with it, or
# EXPLICIT (there is a gap before it, or it is out of order) and keeps its
# address. The first register is always explicit: it is the anchor.
def _addr_of(reg) -> int:
    try:
        return int(reg.get("addr", 0))
    except (TypeError, ValueError):
        return 0


def chained_flags(registers: list) -> list:
    """``flags[i]`` is True when register *i* follows register *i-1* without a
    gap (touching or overlapping). ``flags[0]`` is always False."""
    flags = [False] * len(registers)
    for i in range(1, len(registers)):
        prev = registers[i - 1]
        if datatypes.area_of(prev).key != datatypes.area_of(registers[i]).key:
            continue                 # another Modbus table: its own anchor
        start = _addr_of(prev)
        end = start + datatypes.addr_span(prev)
        flags[i] = start <= _addr_of(registers[i]) <= end
    return flags


def rechain(registers: list, flags: list) -> None:
    """Re-pack every chained register right after its predecessor, in place.
    Explicit ones (flag False) keep their address."""
    for i in range(1, len(registers)):
        if i < len(flags) and flags[i]:
            prev = registers[i - 1]
            registers[i]["addr"] = min(0xFFFF, _addr_of(prev) + datatypes.addr_span(prev))


def is_contiguous(registers: list) -> bool:
    """No gaps anywhere: the whole map is one chain from its first address."""
    return all(chained_flags(registers)[1:])
