"""Importing a register map from a vendor spreadsheet.

Every vendor ships a different table, so the risky parts are the ones that look
trivial: which encoding, which delimiter, and above all which ADDRESS
convention. Getting the last one wrong shifts an entire map by one, which is
much worse than failing loudly.
"""
import pytest

from core import mapimport as mi


def _csv(tmp_path, text, name="map.csv", encoding="utf-8"):
    p = tmp_path / name
    p.write_bytes(text.encode(encoding))
    return str(p)


# ═══════════════ reading ═══════════════
def test_reads_a_comma_csv(tmp_path):
    rows = mi.read_table(_csv(tmp_path, "Адрес,Имя\n1,Температура\n2,Давление\n"))
    assert rows == [["Адрес", "Имя"], ["1", "Температура"], ["2", "Давление"]]


def test_reads_a_semicolon_csv(tmp_path):
    """The norm wherever the decimal separator is a comma."""
    rows = mi.read_table(_csv(tmp_path, "Адрес;Имя;Масштаб\n1;Ток;0,01\n"))
    assert rows[1] == ["1", "Ток", "0,01"]


def test_reads_a_tab_separated_file(tmp_path):
    rows = mi.read_table(_csv(tmp_path, "Adr\tName\n1\tTemp\n"))
    assert rows[1] == ["1", "Temp"]


def test_reads_cp1251_without_mojibake(tmp_path):
    """Vendor CSVs on Russian Windows are routinely cp1251."""
    rows = mi.read_table(_csv(tmp_path, "Адрес;Имя\n1;Температура\n",
                              encoding="cp1251"))
    assert rows[1][1] == "Температура"


def test_reads_utf8_with_bom(tmp_path):
    rows = mi.read_table(_csv(tmp_path, "Адрес;Имя\n1;Ток\n",
                              encoding="utf-8-sig"))
    assert rows[0][0] == "Адрес", "the BOM leaked into the first header cell"


def test_blank_rows_and_ragged_widths_are_normalised(tmp_path):
    rows = mi.read_table(_csv(tmp_path, "A;B;C\n\n1;x\n\n2;y;z;extra\n"))
    assert all(len(r) == len(rows[0]) for r in rows), "not a rectangle"
    assert len(rows) == 3                       # blank lines dropped


def test_an_empty_file_says_so(tmp_path):
    with pytest.raises(mi.ImportError_):
        mi.read_table(_csv(tmp_path, "   \n\n"))


def test_missing_file_is_reported_readably(tmp_path):
    with pytest.raises(mi.ImportError_):
        mi.read_table(str(tmp_path / "nope.csv"))


def test_reads_an_xlsx(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Карта"
    for row in (["Адрес", "Имя", "Тип"], [16, "Температура", "FLOAT"],
                [18, "Давление", "uint16"]):
        ws.append(row)
    path = str(tmp_path / "map.xlsx")
    wb.save(path)

    assert mi.sheet_names(path) == ["Карта"]
    rows = mi.read_table(path)
    assert rows[1] == ["16", "Температура", "FLOAT"]


def test_xlsx_sheet_can_be_chosen(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    wb.active.title = "Инфо"
    wb.active.append(["не карта"])
    ws2 = wb.create_sheet("Регистры")
    ws2.append(["Адрес", "Имя"])
    ws2.append([5, "Поток"])
    path = str(tmp_path / "two.xlsx")
    wb.save(path)

    assert mi.sheet_names(path) == ["Инфо", "Регистры"]
    rows = mi.read_table(path, sheet="Регистры")
    assert rows[1] == ["5", "Поток"]


# ═══════════════ header detection + guessing ═══════════════
def test_header_row_is_recognised():
    assert mi.looks_like_header(["Адрес", "Наименование", "Тип"])
    assert mi.looks_like_header(["Address", "Name", "Access"])
    assert not mi.looks_like_header(["1", "16", "40001"])
    assert not mi.looks_like_header(["16", "Температура", "FLOAT"])


def test_guess_finds_the_obvious_columns():
    m = mi.guess_mapping(["Адрес", "Наименование", "Тип данных", "Ед. изм.",
                          "Доступ", "Комментарий"])
    assert m["addr"] == 0 and m["name"] == 1 and m["type"] == 2
    assert m["unit"] == 3 and m["rw"] == 4 and m["comment"] == 5


def test_guess_works_on_english_headers():
    m = mi.guess_mapping(["Register", "Description", "Format", "Units",
                          "Access", "Scale"])
    assert m["addr"] == 0 and m["name"] == 1 and m["type"] == 2
    assert m["scale"] == 5


def test_guess_never_assigns_one_column_to_two_fields():
    m = mi.guess_mapping(["Адрес", "Имя", "Тип", "Тип данных"])
    assert len(set(m.values())) == len(m)


def test_guess_returns_empty_for_a_headerless_sheet():
    m = mi.guess_mapping(["1", "2", "3"])
    assert m == {}


# ═══════════════ address parsing — the dangerous part ═══════════════
@pytest.mark.parametrize("text,expected", [
    ("16", 16), ("0x10", 16), ("0X10", 16), ("1Fh", 31), ("1F h", 31),
    ("$10", 16), ("#10", 16), ("17,0", 17), ("17.0", 17), (" 42 ", 42),
    ("1 000", 1000), ("", None), ("abc", None), ("—", None), ("0x", None),
])
def test_address_notations_from_real_datasheets(text, expected):
    assert mi._to_int(text) == expected


@pytest.mark.parametrize("mode,given,expected", [
    ("raw", 0, 0), ("raw", 16, 16),
    ("modbus1", 1, 0), ("modbus1", 17, 16),
    ("4x", 40001, 0), ("4x", 40017, 16), ("4x", 30001, 0),
    ("4x", 1, 0),                       # already zero-ish: don't go negative
])
def test_address_conventions(mode, given, expected):
    assert mi.apply_addr_mode(given, mode) == expected


def test_the_4x_convention_is_never_applied_silently():
    """40001 IS a legal 16-bit address, so raw mode cannot be *proven* wrong —
    it must be obeyed. But reading a 4x sheet raw shifts the whole map, so a
    sheet that looks like 4x is flagged rather than silently converted."""
    rows = [["Адрес", "Имя"], ["40001", "Температура"], ["40002", "Давление"]]
    regs, problems = mi.build_registers(rows, {"addr": 0, "name": 1},
                                        addr_mode="raw")
    assert [r["addr"] for r in regs] == [40001, 40002], "raw must stay raw"
    assert any(p[1] == "impMaybe4x" for p in problems), "no warning was raised"

    regs, problems = mi.build_registers(rows, {"addr": 0, "name": 1},
                                        addr_mode="4x")
    assert [r["addr"] for r in regs] == [0, 1]
    assert not problems


def test_a_normal_low_address_sheet_is_not_flagged_as_4x():
    rows = [["Адрес", "Имя"], ["16", "A"], ["18", "B"], ["20", "C"]]
    _regs, problems = mi.build_registers(rows, {"addr": 0, "name": 1})
    assert not any(p[1] == "impMaybe4x" for p in problems)


# ═══════════════ type / access normalisation ═══════════════
@pytest.mark.parametrize("text,expected", [
    # Unsigned names map to the unsigned types (2.1): before they existed,
    # "uint16" became a signed SHORT and read negative above 32767.
    ("uint16", "UINT16"), ("INT16", "SHORT"), ("word", "UINT16"),
    ("uint32", "UINT32"), ("DWORD", "UINT32"), ("int32", "LONG"),
    ("float", "FLOAT"), ("REAL", "FLOAT"), ("float32", "FLOAT"),
    ("double", "DOUBLE"), ("LREAL", "DOUBLE"), ("int64", "INT64"),
    ("BCD", "BCD16"), ("bcd32", "BCD32"), ("bit field", "BITS16"),
    ("SHORT", "SHORT"), ("FLOAT", "FLOAT"), ("UINT16", "UINT16"),
    ("string", "STRING"), ("строка", "STRING"),
    ("", "SHORT"), ("нечто", "SHORT"),             # unknown -> default
])
def test_type_aliases(text, expected):
    assert mi.normalize_type(text) == expected


def test_every_alias_maps_to_a_real_registry_type():
    from core import datatypes
    for key in mi._TYPE_ALIASES.values():
        assert key in datatypes.TYPES, key


@pytest.mark.parametrize("text,expected", [
    ("R", "R"), ("ro", "R"), ("чтение", "R"), ("Read Only", "R"),
    ("RW", "RW"), ("r/w", "RW"), ("чт/зп", "RW"),
    ("", "RW"),
])
def test_access_normalisation(text, expected):
    assert mi.normalize_rw(text) == expected


# ═══════════════ building registers ═══════════════
def _rows():
    return [
        ["Адрес", "Наименование", "Тип", "Доступ", "Ед. изм.", "Масштаб"],
        ["16", "Температура", "FLOAT", "R", "°C", "0,1"],
        ["18", "Давление", "uint16", "RW", "бар", "1"],
        ["20", "Ток", "int32", "чтение", "А", "0,01"],
    ]


def test_a_normal_sheet_imports_cleanly():
    m = mi.guess_mapping(_rows()[0])
    regs, problems = mi.build_registers(_rows(), m)
    assert problems == []
    assert [r["addr"] for r in regs] == [16, 18, 20]
    assert [r["type"] for r in regs] == ["FLOAT", "UINT16", "LONG"]
    assert [r["rw"] for r in regs] == ["R", "RW", "R"]
    assert regs[0]["unit"] == "°C"
    assert regs[0]["scale"] == pytest.approx(0.1)
    assert "scale" not in regs[1], "an identity scale must not be written out"


def test_result_is_a_valid_profile_for_the_rest_of_the_app():
    """The import must produce rows the editor and poller already understand."""
    from core import formats
    regs, _ = mi.build_registers(_rows(), mi.guess_mapping(_rows()[0]))
    doc = formats.migrate_profile({"registers": regs})
    assert len(doc["registers"]) == 3
    for r in doc["registers"]:
        assert 0 <= r["addr"] <= 0xFFFF and r["length"] >= 1


def test_one_bad_row_does_not_lose_the_others():
    rows = _rows()
    rows.insert(2, ["не адрес", "Мусор", "", "", "", ""])
    regs, problems = mi.build_registers(rows, mi.guess_mapping(rows[0]))
    assert len(regs) == 3
    assert problems and problems[0][1] == "impBadAddr"
    assert problems[0][0] == 3, "the reported line number must match the file"


def test_duplicate_addresses_are_reported_but_kept():
    rows = _rows() + [["16", "Дубль", "SHORT", "R", "", ""]]
    regs, problems = mi.build_registers(rows, mi.guess_mapping(rows[0]))
    assert len(regs) == 4
    dupes = [p for p in problems if p[1] == "impDuplicateAddr"]
    assert dupes and dupes[0][2]["addr"] == "0x0010"


def test_out_of_range_addresses_are_rejected_with_their_line():
    rows = [["Адрес", "Имя"], ["10", "ok"], ["99999", "слишком большой"]]
    regs, problems = mi.build_registers(rows, {"addr": 0, "name": 1})
    assert len(regs) == 1
    assert problems[0][1] == "impAddrRange" and problems[0][0] == 3


def test_a_row_without_a_name_gets_its_address_as_the_name():
    rows = [["Адрес", "Имя"], ["16", ""]]
    regs, _ = mi.build_registers(rows, {"addr": 0, "name": 1})
    assert regs[0]["name"] == "0x0010"


def test_missing_required_columns_refuse_the_import():
    with pytest.raises(mi.ImportError_):
        mi.build_registers(_rows(), {"name": 1})        # no address column


def test_a_sheet_with_no_usable_row_explains_itself():
    rows = [["Адрес", "Имя"], ["—", "нет"], ["", ""]]
    with pytest.raises(mi.ImportError_) as err:
        mi.build_registers(rows, {"addr": 0, "name": 1})
    assert str(err.value).strip()


def test_headerless_sheets_import_every_row():
    rows = [["16", "Температура"], ["18", "Давление"]]
    regs, problems = mi.build_registers(rows, {"addr": 0, "name": 1},
                                        has_header=False)
    assert len(regs) == 2 and problems == []


def test_length_is_clamped_like_everywhere_else():
    rows = [["A", "N", "L"], ["1", "x", "-5"], ["2", "y", "9999999"]]
    regs, _ = mi.build_registers(rows, {"addr": 0, "name": 1, "length": 2})
    assert regs[0]["length"] == 1 and regs[1]["length"] <= 0xFFFF


def test_short_rows_do_not_raise():
    """A ragged sheet may leave later columns missing entirely."""
    rows = [["Адрес", "Имя", "Тип"], ["16"], ["18", "Имя2"]]
    regs, _ = mi.build_registers(rows, {"addr": 0, "name": 1, "type": 2})
    assert [r["addr"] for r in regs] == [16, 18]


def test_problem_keys_are_all_translatable():
    from app import i18n
    for key in ("impBadAddr", "impAddrRange", "impDuplicateAddr"):
        assert key in i18n.STRINGS["ru"] and key in i18n.STRINGS["en"]


def test_field_and_mode_labels_are_translatable():
    from app import i18n
    for _key, label, _req in mi.FIELDS:
        assert label in i18n.STRINGS["ru"] and label in i18n.STRINGS["en"]
    for label in mi.ADDR_MODE_LABELS.values():
        assert label in i18n.STRINGS["ru"] and label in i18n.STRINGS["en"]


# ═══════════════ the dialog, driven for real ═══════════════
def _dialog(tmp_path, text, encoding="utf-8"):
    from app.app_context import AppContext
    from app.settings_manager import DEFAULT_SETTINGS
    from gui.import_dialog import ImportMapDialog
    p = tmp_path / "vendor.csv"
    p.write_bytes(text.encode(encoding))
    return ImportMapDialog(AppContext(dict(DEFAULT_SETTINGS)), str(p))


VENDOR_CSV = ("Адрес;Наименование;Тип;Доступ;Ед. изм.;Масштаб\n"
              "16;Температура;FLOAT;R;°C;0,1\n"
              "18;Давление;uint16;RW;бар;1\n"
              "не адрес;Мусор;;;;\n"
              "20;Ток;int32;чтение;А;0,01\n")


def test_dialog_guesses_everything_from_a_cp1251_vendor_sheet(tmp_path):
    """The whole point of the feature: open a real vendor CSV and have the
    mapping already right."""
    d = _dialog(tmp_path, VENDOR_CSV, encoding="cp1251")
    assert d.chk_header.isChecked()
    assert d.current_mapping() == {"addr": 0, "name": 1, "type": 2,
                                   "rw": 3, "unit": 4, "scale": 5}
    assert [r["addr"] for r in d.registers] == [16, 18, 20]
    assert [r["type"] for r in d.registers] == ["FLOAT", "UINT16", "LONG"]
    assert d.registers[0]["name"] == "Температура"


def test_dialog_reports_the_bad_row_with_its_file_line(tmp_path):
    d = _dialog(tmp_path, VENDOR_CSV, encoding="cp1251")
    assert "4" in d.lbl_problems.text(), d.lbl_problems.text()
    assert "{" not in d.lbl_problems.text(), "an unfilled placeholder leaked"


def test_changing_the_address_mode_repreviews(tmp_path):
    d = _dialog(tmp_path, VENDOR_CSV, encoding="cp1251")
    before = [r["addr"] for r in d.registers]
    d.combo_addr.setCurrentIndex(list(mi.ADDR_MODES).index("4x"))
    assert [r["addr"] for r in d.registers] != before


def test_unassigning_the_address_column_disables_import(tmp_path):
    d = _dialog(tmp_path, VENDOR_CSV, encoding="cp1251")
    assert d.btn_import.isEnabled()
    d._pickers[0].setCurrentIndex(0)          # "— ignore —"
    assert not d.btn_import.isEnabled()
    assert d.registers == []


def test_toggling_the_header_checkbox_changes_the_row_count(tmp_path):
    d = _dialog(tmp_path, VENDOR_CSV, encoding="cp1251")
    with_header = len(d.registers)
    d.chk_header.setChecked(False)
    # The header row now counts as data, and its address cell is unparsable —
    # so it becomes a reported problem rather than a silent loss.
    assert len(d.registers) == with_header
    assert any("Адрес" in p or "адрес" in p.lower()
               for p in [d.lbl_problems.text()])


def test_a_field_assigned_twice_keeps_the_first_column(tmp_path):
    d = _dialog(tmp_path, VENDOR_CSV, encoding="cp1251")
    name_idx = d._pickers[1].findData("name")
    d._pickers[2].setCurrentIndex(name_idx)   # column 2 also claims "name"
    assert d.current_mapping()["name"] == 1


def test_dialog_survives_a_file_it_cannot_read(tmp_path, monkeypatch):
    """A broken file must leave a usable dialog, not a traceback."""
    from gui import dialogs
    monkeypatch.setattr(dialogs, "themed_message", lambda *a, **k: 0)
    d = _dialog(tmp_path, "\n\n\n")
    assert d.registers == [] and not d.btn_import.isEnabled()
