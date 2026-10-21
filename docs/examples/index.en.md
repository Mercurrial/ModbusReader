---
seo_title: Examples — macros and Modbus RTU scenarios
description: Ready-made ModbusReader examples — Python macros for tests and calibration, testing a SCADA with a Modbus slave emulator, importing a register map from a datasheet, dashboard automation, debugging an RS-485 line with the sniffer.
---

# Examples

Every example can be tried on the **demo project** — no device needed, with
the emulator on a virtual COM port (see [Testing a SCADA with the
emulator](test-scada.md)).

<div class="grid cards" markdown>

-   :material-language-python:{ .lg .middle } [**Macro examples**](macros.md)

    ---

    A setpoint sweep waiting for stabilisation, checking against a reference,
    readings into a table, waiting for an event with a timeout, finding
    registers without documentation.

-   :material-monitor-dashboard:{ .lg .middle } [**Testing a SCADA with the emulator**](test-scada.md)

    ---

    ModbusReader pretends to be the device: debug a SCADA, HMI or PLC with no
    hardware, even on one PC with com0com.

-   :material-file-excel:{ .lg .middle } [**A map from a datasheet**](datasheet-import.md)

    ---

    A register table from a PDF or Excel → a ModbusReader map in a couple of
    minutes, no retyping, no off-by-one.

-   :material-transit-connection-variant:{ .lg .middle } [**Dashboard automation**](dashboard-automation.md)

    ---

    Timer → gate → button: turn the fan on when it overheats, without a line
    of code.

-   :material-sine-wave:{ .lg .middle } [**Debugging an RS-485 line**](line-debugging.md)

    ---

    Timeouts, CRC errors, exceptions: finding the cause with the statistics,
    the log and the sniffer.

</div>

Have a good scenario or macro of your own? Share it in
[Discussions](https://github.com/Mercurrial/ModbusReader/discussions) — the
best ones end up here.
