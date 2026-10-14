"""Modbus tables (v2.1): holding / input registers / coils / discrete inputs.

A register's identity is its KEY ``area << 16 | addr`` — holding keeps
``key == addr``, so every map written before 2.1 means exactly what it did.
These tests pin the four tables end to end: map file → editor → import →
master (FC 01/02/03/04/05) → emulator (FC 01/02/04/05/15) → UI.
"""
import copy

import pytest
from PyQt6.QtCore import Qt

import datatypes as dt
import formats
import mapimport as mi
import profile_manager as pm
import slave_core as sc
import snapshots as sn
import sniffer_core
from app_context import AppContext
from settings_manager import DEFAULT_SETTINGS


def _ctx(**over):
    s = copy.deepcopy(DEFAULT_SETTINGS)
    s.update(over)
    return AppContext(s)


@pytest.fixture(autouse=True)
def default_orders():
    dt.configure_orders({})
    yield
    dt.configure_orders({})


MIXED = [
    {"addr": 0, "name": "Setpoint", "type": "SHORT", "rw": "RW"},
    {"addr": 0, "name": "Temp", "type": "SHORT", "area": "input", "rw": "R"},
    {"addr": 0, "name": "Pump", "type": "BOOL", "area": "coil", "rw": "RW"},
    {"addr": 1, "name": "Fan", "type": "BOOL", "area": "coil", "rw": "RW"},
    {"addr": 0, "name": "Door", "type": "BOOL", "area": "discrete", "rw": "R"},
]


# ═══════════════ keys ═══════════════
def test_holding_keys_are_plain_addresses():
    assert dt.reg_key({"addr": 0x10}) == 0x10
    assert dt.reg_key({"addr": "0x10"}) == 0x10
    assert dt.key_label(0x10) == "0x0010"
    assert dt.reg_id(0x10) == "0x0010"          # trend / dashboard ids unchanged


@pytest.mark.parametrize("area,label", [
    ("input", "IR 0x0010"), ("coil", "CO 0x0010"), ("discrete", "DI 0x0010")])
def test_every_table_has_its_own_key_and_label(area, label):
    key = dt.reg_key({"addr": 0x10, "area": area})
    assert key != 0x10
    assert dt.key_label(key) == label
    assert dt.parse_key(label) == key
    assert dt.parse_key(label.lower()) == key
    assert dt.id_label(dt.reg_id(key)) == label
    assert dt.split_key(key) == (dt.AREAS[area], 0x10)


def test_parse_key_rejects_junk():
    for junk in ("", "XX 0x10", "CO", "CO 0x10000", "a b c", "zz"):
        assert dt.parse_key(junk) is None


def test_only_coils_and_holding_are_writable():
    assert dt.is_writable({"addr": 0, "rw": "RW"})
    assert dt.is_writable({"addr": 0, "rw": "RW", "area": "coil"})
    assert not dt.is_writable({"addr": 0, "rw": "RW", "area": "input"})
    assert not dt.is_writable({"addr": 0, "rw": "RW", "area": "discrete"})


def test_bool_type():
    assert dt.encode("BOOL", "1") == [1]
    assert dt.encode("BOOL", "0") == [0]
    assert dt.read_to_str("BOOL", [1]) == "1"
    assert dt.addr_span({"type": "BOOL"}) == 1


# ═══════════════ map file ═══════════════
def test_holding_maps_are_written_without_an_area_key():
    reg = formats.normalize_register({"addr": 1, "name": "A", "type": "SHORT",
                                      "area": "holding"})
    assert "area" not in reg


def test_a_bit_table_forces_bool_and_a_read_only_table_forces_r():
    coil = formats.normalize_register({"addr": 1, "name": "C", "type": "FLOAT",
                                       "length": 2, "area": "coil"})
    assert (coil["area"], coil["type"], coil["length"]) == ("coil", "BOOL", 1)
    ir = formats.normalize_register({"addr": 1, "name": "I", "type": "FLOAT",
                                     "rw": "RW", "area": "input"})
    assert (ir["type"], ir["rw"]) == ("FLOAT", "R")
    di = formats.normalize_register({"addr": 1, "name": "D", "rw": "RW",
                                     "area": "discrete"})
    assert (di["type"], di["rw"]) == ("BOOL", "R")


def test_unknown_area_falls_back_to_holding():
    reg = formats.normalize_register({"addr": 1, "name": "A", "area": "bogus"})
    assert "area" not in reg


def test_tables_do_not_overlap_each_other():
    assert pm.find_overlaps(MIXED) == []
    clash = [{"addr": 0, "name": "A", "type": "BOOL", "area": "coil"},
             {"addr": 0, "name": "B", "type": "BOOL", "area": "coil"}]
    assert pm.find_overlaps(clash)
    assert "CO 0x0000" in pm.find_overlaps(clash)[0]


def test_a_new_table_starts_a_new_chain():
    regs = [{"addr": 0, "name": "A", "type": "LONG"},
            {"addr": 2, "name": "B", "type": "BOOL", "area": "coil"}]
    assert pm.chained_flags(regs) == [False, False]


# ═══════════════ editor ═══════════════
@pytest.fixture()
def editor():
    from profile_editor import ProfileEditorDialog
    regs = [{"addr": 0, "name": "A", "type": "SHORT"},
            {"addr": 1, "name": "B", "type": "LONG"},
            {"addr": 3, "name": "C", "type": "SHORT"}]
    ed = ProfileEditorDialog(None, regs, _ctx())
    yield ed
    ed.is_modified = False
    ed.close()


def test_editor_has_an_area_column(editor):
    from profile_editor import COL_AREA
    cb = editor.table.cellWidget(0, COL_AREA)
    assert [cb.itemData(i) for i in range(cb.count())] == list(dt.AREAS)
    assert cb.currentData() == "holding"


def test_moving_a_row_to_coils(editor):
    from profile_editor import COL_AREA, COL_TYPE, COL_ACC
    editor._on_area_changed(1, "coil")
    reg = editor.profile_data[1]
    assert (reg["area"], reg["type"], reg["length"]) == ("coil", "BOOL", 1)
    assert [r["addr"] for r in editor.profile_data] == [0, 1, 3]   # C stays put
    assert not editor.table.cellWidget(1, COL_TYPE).isEnabled()
    assert editor.table.cellWidget(1, COL_ACC).isEnabled()
    assert editor.table.cellWidget(1, COL_AREA).currentData() == "coil"
    out = editor._export_list()
    assert out[1]["area"] == "coil" and "area" not in out[0]


def test_read_only_tables_lock_access(editor):
    from profile_editor import COL_ACC
    editor._on_area_changed(0, "input")
    assert editor.profile_data[0]["rw"] == "R"
    assert not editor.table.cellWidget(0, COL_ACC).isEnabled()
    editor._on_area_changed(0, "holding")
    reg = editor.profile_data[0]
    assert "area" not in reg and reg["rw"] == "RW"


def test_a_new_row_continues_the_last_table(editor):
    editor._on_area_changed(2, "coil")
    editor._add_row()
    new = editor.profile_data[-1]
    assert new["area"] == "coil" and new["type"] == "BOOL"
    assert new["addr"] == 4


# ═══════════════ import ═══════════════
def test_import_reads_an_area_column():
    rows = [["Адрес", "Имя", "Область"],
            ["1", "Насос", "Coil"], ["1", "Уставка", "holding"],
            ["1", "Темп.", "IR"], ["1", "Дверь", "дискретный вход"]]
    regs, problems = mi.build_registers(rows, {"addr": 0, "name": 1, "area": 2})
    assert [dt.key_label(dt.reg_key(r)) for r in regs] == [
        "CO 0x0001", "0x0001", "IR 0x0001", "DI 0x0001"]
    assert not [p for p in problems if p[1] == "impDuplicateAddr"]
    assert regs[0]["type"] == "BOOL" and regs[3]["rw"] == "R"


def test_the_area_column_is_recognised_by_its_header():
    assert mi.guess_mapping(["Address", "Name", "Register type"]).get("area") == 2


def test_4x_blocks_name_their_tables():
    rows = [["addr"], ["40001"], ["30001"], ["10003"], ["5"]]
    regs, _ = mi.build_registers(rows, {"addr": 0}, addr_mode="4x")
    assert [dt.key_label(dt.reg_key(r)) for r in regs] == [
        "0x0000", "IR 0x0000", "DI 0x0002", "0x0004"]


# ═══════════════ master + emulator loop ═══════════════
class _Res:
    def __init__(self, registers=None, bits=None, err=False):
        self.registers = list(registers or [])
        self.bits = list(bits or [])
        self._err = err

    def isError(self):
        return self._err


class _LoopClient:
    """A pymodbus-shaped client whose every call is answered by the
    emulator's pure responder — real frames, both directions."""

    def __init__(self, store, sid=10):
        self.st, self.sid, self.calls = store, sid, []

    def _ask(self, fc, a, b):
        self.calls.append(fc)
        return sc.build_response(sc.with_crc(bytes(
            (self.sid, fc, a >> 8, a & 0xFF, b >> 8, b & 0xFF))), self.st, self.sid)

    def _words(self, fc, address, count):
        r = self._ask(fc, address, count)
        if r["exception"]:
            return _Res(err=True)
        resp = r["response"]
        return _Res([int.from_bytes(resp[3 + 2 * i:5 + 2 * i], "big")
                     for i in range(count)])

    def _bits(self, fc, address, count):
        r = self._ask(fc, address, count)
        if r["exception"]:
            return _Res(err=True)
        data = r["response"][3:-2]
        bits = [bool((data[i // 8] >> (i % 8)) & 1) for i in range(len(data) * 8)]
        return _Res(bits=bits)                     # padded, like pymodbus

    def read_holding_registers(self, address, count, **kw):
        return self._words(3, address, count)

    def read_input_registers(self, address, count, **kw):
        return self._words(4, address, count)

    def read_coils(self, address, count, **kw):
        return self._bits(1, address, count)

    def read_discrete_inputs(self, address, count, **kw):
        return self._bits(2, address, count)

    def write_coil(self, address, value, **kw):
        r = self._ask(5, address, 0xFF00 if value else 0)
        return _Res(err=bool(r["exception"]))

    def write_register(self, address, value, **kw):
        r = self._ask(6, address, value)
        return _Res(err=bool(r["exception"]))


@pytest.fixture()
def loop():
    from modbus_core import ModbusCore
    st = sc.SlaveStore.from_registers(MIXED)
    for reg, v in zip(MIXED, ("42", "215", "1", "0", "1")):
        st.set_value(reg, v)
    core = ModbusCore()
    core.client = _LoopClient(st)
    core.update_profile(MIXED)
    got = {}
    core.data_updated.connect(lambda k, v: got.__setitem__(k, v))
    return core, st, got


def test_the_master_reads_every_table_with_its_own_function(loop):
    core, st, got = loop
    for reg in MIXED:
        assert core._execute_read(dt.reg_key(reg), reg["type"]) is True
    assert core.client.calls == [3, 4, 1, 1, 2]
    assert got == {0: "42", dt.parse_key("IR 0"): "215",
                   dt.parse_key("CO 0"): "1", dt.parse_key("CO 1"): "0",
                   dt.parse_key("DI 0"): "1"}


def test_the_master_switches_a_coil_with_fc05(loop):
    core, st, _ = loop
    fan = dt.parse_key("CO 1")
    assert core._execute_write(fan, "BOOL", "1") is True
    assert core.client.calls == [5]
    assert st.read(fan, 1) == [1]
    assert st.read(0, 1) == [42]                    # holding 1 untouched


def test_the_master_refuses_to_write_a_read_only_table(loop):
    core, st, _ = loop
    logs = []
    core.log_msg.connect(lambda lvl, m: logs.append(m))
    assert core._execute_write(dt.parse_key("IR 0"), "SHORT", "1") is False
    assert core._execute_write(dt.parse_key("DI 0"), "BOOL", "0") is False
    assert core.client.calls == []                  # nothing went on the wire
    assert any("IR 0x0000" in m for m in logs)


def test_the_macro_api_reads_by_table_label(loop):
    core, st, _ = loop
    from macro_engine import MacroRunner
    r = MacroRunner("", core, MIXED)
    info = r._lookup("CO 0x0001")
    assert info["addr"] == dt.parse_key("CO 1") and info["name"] == "Fan"
    assert r._lookup("Temp")["addr"] == dt.parse_key("IR 0")
    assert r._lookup(0)["name"] == "Setpoint"       # an int is a holding address


# ═══════════════ emulator protocol ═══════════════
def _req(*b):
    return sc.with_crc(bytes(b))


def _coil_store(n=10):
    regs = [{"addr": i, "name": f"C{i}", "type": "BOOL", "area": "coil"}
            for i in range(n)]
    return sc.SlaveStore.from_registers(regs)


def test_fc01_packs_bits_lsb_first():
    st = _coil_store()
    for i in (0, 2, 9):
        st.write(dt.parse_key(f"CO {i}"), [1])
    r = sc.build_response(_req(10, 1, 0, 0, 0, 10), st, 10)
    assert r["response"] == sc.with_crc(bytes([10, 1, 2, 0b00000101, 0b00000010]))


def test_fc05_takes_only_ff00_or_0000():
    st = _coil_store()
    r = sc.build_response(_req(10, 5, 0, 3, 0x12, 0x34), st, 10)
    assert r["exception"] == sc.ILLEGAL_VALUE
    req = _req(10, 5, 0, 3, 0xFF, 0)
    r = sc.build_response(req, st, 10)
    assert r["response"] == req and st.read(dt.parse_key("CO 3"), 1) == [1]


def test_fc15_writes_many_coils():
    st = _coil_store()
    r = sc.build_response(_req(10, 0x0F, 0, 0, 0, 10, 2, 0b10000001, 0b11), st, 10)
    assert r["response"] == sc.with_crc(bytes([10, 0x0F, 0, 0, 0, 10]))
    assert st.read(dt.parse_key("CO 0"), 10) == [1, 0, 0, 0, 0, 0, 0, 1, 1, 1]
    bad = sc.build_response(_req(10, 0x0F, 0, 0, 0, 10, 1, 0xFF), st, 10)
    assert bad["exception"] == sc.ILLEGAL_VALUE      # byte count must match


def test_fc04_serves_input_registers_or_falls_back_to_holding():
    only_holding = sc.SlaveStore.from_registers([{"addr": 0, "name": "H"}])
    only_holding.write(0, [7])
    r = sc.build_response(_req(10, 4, 0, 0, 0, 1), only_holding, 10)
    assert r["response"] == sc.with_crc(bytes([10, 4, 2, 0, 7]))
    st = sc.SlaveStore.from_registers(MIXED)
    st.write(0, [1])
    st.write(dt.parse_key("IR 0"), [2])
    r = sc.build_response(_req(10, 4, 0, 0, 0, 1), st, 10)
    assert r["response"] == sc.with_crc(bytes([10, 4, 2, 0, 2]))


def test_fc06_cannot_reach_a_coil():
    st = sc.SlaveStore.from_registers(
        [{"addr": 0, "name": "C", "type": "BOOL", "area": "coil"}])
    r = sc.build_response(_req(10, 6, 0, 0, 0, 1), st, 10)
    assert r["exception"] == sc.ILLEGAL_ADDRESS


def test_a_read_cannot_spill_into_the_next_table():
    st = sc.SlaveStore.from_registers(
        [{"addr": 0xFFFF, "name": "H"}, {"addr": 0, "name": "I", "area": "input"}])
    r = sc.build_response(_req(10, 3, 0xFF, 0xFF, 0, 2), st, 10)
    assert r["exception"] == sc.ILLEGAL_ADDRESS


# ═══════════════ UI ═══════════════
def test_the_table_shows_every_table_on_its_own_row():
    from gui_table import RegisterTable, COL_ADDR, COL_CURRENT, COL_NEW
    t = RegisterTable(_ctx())
    t.populate(MIXED)
    assert [t.item(r, COL_ADDR).text() for r in range(5)] == [
        "0x0000", "IR 0x0000", "CO 0x0000", "CO 0x0001", "DI 0x0000"]
    t.update_value(dt.parse_key("CO 1"), "1")
    assert t.item(3, COL_CURRENT).text() == "1"
    assert t.item(0, COL_CURRENT).text() != "1"
    editable = Qt.ItemFlag.ItemIsEditable
    assert t.item(2, COL_NEW).flags() & editable                    # coil: RW
    assert not t.item(1, COL_NEW).flags() & editable                # input
    sent = []
    t.write_requested.connect(lambda *a: sent.append(a))
    t.set_connected(True)
    t.item(2, COL_NEW).setText("1")
    t._on_cell_changed(2, COL_NEW)
    assert sent == [(dt.parse_key("CO 0"), "BOOL", "1")]
    t.deleteLater()


def test_snapshots_tell_tables_apart():
    a = sn.make(MIXED, {0: "42", dt.parse_key("CO 0"): "1"}, "a")
    b = sn.make(MIXED, {0: "42", dt.parse_key("CO 0"): "0"}, "b")
    rows = {sn_row["key"]: sn_row for sn_row in sn.compare(a, b)}
    assert rows[0]["state"] == sn.SAME
    assert rows[dt.parse_key("CO 0")]["state"] == sn.CHANGED
    assert sn.load(a)["registers"][2]["area"] == "coil"


def test_logger_columns_carry_the_table():
    import datalog
    cols = datalog.columns_for(MIXED)
    assert [c[0] for c in cols][:3] == [0, dt.parse_key("IR 0"), dt.parse_key("CO 0")]
    assert cols[2][1].startswith("CO 0x0000 Pump")


def test_the_sniffer_decodes_bit_functions():
    resp = sniffer_core.decode_frame(sc.with_crc(bytes([10, 1, 1, 0b101])))
    assert resp["kind"] == "response" and resp["describe"].startswith("bits 101")
    sw = sniffer_core.decode_frame(sc.with_crc(bytes([10, 5, 0, 3, 0xFF, 0])))
    assert sw["describe"] == "coil 0x0003 = ON"


def test_pymodbus_itself_understands_the_emulator():
    """Requests built by pymodbus' own framer, answers decoded by it: the
    emulator speaks standard Modbus, not just to our own test double."""
    from pymodbus.framer import FramerRTU
    from pymodbus.pdu import DecodePDU
    from pymodbus.pdu.bit_message import (ReadCoilsRequest, ReadDiscreteInputsRequest,
                                          WriteSingleCoilRequest,
                                          WriteMultipleCoilsRequest)
    from pymodbus.pdu.register_message import ReadInputRegistersRequest
    regs = ([{"addr": i, "name": f"C{i}", "type": "BOOL", "area": "coil"}
             for i in range(10)]
            + [{"addr": 5, "name": "I", "area": "input"},
               {"addr": 0, "name": "D", "area": "discrete"}])
    st = sc.SlaveStore.from_registers(regs)
    st.write(dt.parse_key("CO 2"), [1])
    st.write(dt.parse_key("IR 5"), [1234])
    st.write(dt.parse_key("DI 0"), [1])
    framer = FramerRTU(DecodePDU(False))

    def ask(req):
        resp = sc.build_response(framer.buildFrame(req), st, 10)["response"]
        return framer.handleFrame(resp, 10, 0)[1]

    assert ask(ReadCoilsRequest(address=0, count=10, dev_id=10)).bits[:10] == \
        [False, False, True] + [False] * 7
    assert ask(ReadDiscreteInputsRequest(address=0, count=1, dev_id=10)).bits[0] is True
    assert ask(ReadInputRegistersRequest(address=5, count=1, dev_id=10)).registers == [1234]
    ask(WriteSingleCoilRequest(address=7, bits=[True], dev_id=10))
    assert st.read(dt.parse_key("CO 7"), 1) == [1]
    r = ask(WriteMultipleCoilsRequest(address=0, bits=[True] * 3 + [False] * 7, dev_id=10))
    assert (r.address, r.count) == (0, 10)
    assert st.read(dt.parse_key("CO 0"), 10) == [1, 1, 1] + [0] * 7
