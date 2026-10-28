"""Response times are measured with a fine clock. On Windows time.monotonic()
ticks every 15.6 ms, so a device answering in 3 ms showed as 0 or 16 ms in
the line statistics and in «Проверить связь»."""
import time

from core.modbus_client import Response


def _slow_answer(*_a, **_k):
    """A device that answers in ~3 ms — between two monotonic ticks."""
    t = time.perf_counter()
    while time.perf_counter() - t < 0.003:
        pass
    return Response(outcome="ok", registers=[0])


def test_line_statistics_see_a_3_ms_answer():
    from core.modbus_core import ModbusCore
    core = ModbusCore()
    for _ in range(20):
        core._counted(_slow_answer)
    snap = core.stats.snapshot()
    assert 2.5 <= snap["rt_min"] and snap["rt_max"] < 12.0
    assert 2.5 <= snap["rt_avg"] < 8.0


def test_the_link_test_sees_a_3_ms_answer():
    from core import linktest

    class Client:
        read_holding_registers = staticmethod(_slow_answer)

    times = [linktest._ask(Client(), "holding", 0, 1)[1] for _ in range(20)]
    assert min(times) >= 2.5 and max(times) < 12.0
