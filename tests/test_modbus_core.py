"""ModbusCore: poll filter, crash-proof frame logging, honest write outcome."""
import struct

from core.modbus_core import ModbusCore


class _OkRes:
    def isError(self):
        return False


class _ErrRes:
    def isError(self):
        return True


class _Client:
    def __init__(self, results):
        self._results = list(results)

    def write_register(self, address, value, **kw):
        return self._results.pop(0)


def _collect(core):
    msgs = []
    core.log_msg.connect(lambda lv, m: msgs.append((lv, m)))
    return msgs


def test_update_profile_filters_areas():
    core = ModbusCore()
    core.update_profile([
        {"addr": 1, "type": "SHORT"},
        {"addr": 2, "type": "MEMORY_AREA"},
        {"addr": 3, "type": "FLOAT"},
        {"addr": 4, "type": "UNUSED_AREA"},
    ])
    assert [r["addr"] for r in core.poll_list] == [1, 3]


def test_frame_logging_never_raises_on_out_of_spec():
    core = ModbusCore()
    msgs = _collect(core)
    core.slave_id = 300                       # > 1 byte
    core._log_tx_read(0x1FFFF, 1)             # addr > 2 bytes
    core._log_rx_read([0x12345, 7])
    core._log_tx_write(0x1FFFF, 99999)
    core._log_rx_write(0x1FFFF, 99999)
    assert len(msgs) == 4                     # logged, no struct.error


def test_frame_logging_byte_parity_normal_case():
    core = ModbusCore()
    msgs = _collect(core)
    core.slave_id = 10
    core._log_tx_read(0x0010, 2)
    pdu = struct.pack(">BBHH", 10, 0x03, 0x0010, 2)
    expected = " ".join(f"{b:02X}" for b in pdu + core._crc16(pdu))
    assert expected in msgs[0][1]


def test_write_reports_error_when_unacknowledged():
    core = ModbusCore()
    core.client = _Client([_ErrRes()])
    msgs = _collect(core)
    core._execute_write(0x10, "SHORT", "5")
    assert not any(lv == "SYS" and "успешна" in m for lv, m in msgs)
    assert any(lv == "ERR" and "не подтверждена" in m for lv, m in msgs)


def test_write_reports_success_when_all_acked():
    core = ModbusCore()
    core.client = _Client([_OkRes(), _OkRes()])
    msgs = _collect(core)
    core._execute_write(0x10, "FLOAT", "3.25")     # 2 words
    assert any(lv == "SYS" and "успешна" in m for lv, m in msgs)
    assert not any(lv == "ERR" for lv, m in msgs)


def test_write_partial_failure_names_failed_word():
    core = ModbusCore()
    core.client = _Client([_OkRes(), _ErrRes()])
    msgs = _collect(core)
    core._execute_write(0x10, "LONG", "100000")
    err = [m for lv, m in msgs if lv == "ERR"]
    assert err and "0x0011" in err[0]


def test_execute_read_contains_exceptions():
    core = ModbusCore()
    core.client = None                         # read raises inside
    assert core._execute_read(0x10, "SHORT") is None   # contained, not raised


def test_setup_connection_wires_poll_settings():
    core = ModbusCore()
    core.setup_connection({"poll_rate": 2000, "timeout": 3000,
                           "interframe_delay": 100}, 10)
    assert core.poll_interval == 2.0
    assert core.timeout == 3.0
    assert core.interframe == 0.1


def test_setup_connection_clamps_and_tolerates_garbage():
    core = ModbusCore()
    core.setup_connection({"poll_rate": 999999, "timeout": 1,
                           "interframe_delay": "junk"}, 10)
    assert core.poll_interval == 5.0           # clamped high
    assert core.timeout == 0.1                 # clamped low
    assert core.interframe == 0.05             # garbage -> default


def test_setup_connection_defaults():
    core = ModbusCore()
    core.setup_connection({}, 10)
    assert core.poll_interval == 0.5
    assert core.timeout == 1.0
    assert core.interframe == 0.05
