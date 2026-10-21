---
seo_title: Testing a SCADA without the device — Modbus RTU slave emulator and virtual COM ports
description: Step by step — how to debug a SCADA, HMI, PLC or your own Modbus RTU master without the real device, with the ModbusReader emulator and a pair of virtual COM ports from com0com (Windows) or socat (Linux).
---

# Testing a SCADA with the emulator

The task: test a master — a SCADA, an operator panel, a controller or your
own program — when there is no device. ModbusReader as the
[emulator](../guide/slave.md) answers the master as a device would, from the
register map.

## What you need

- **The device register map** — from its datasheet ([import from
  Excel](datasheet-import.md)), or the demo project to try things out.
- **A link between the master and the emulator:**
    - the master is on **another PC** or is a controller — two USB-to-RS-485
      adapters wired A–A, B–B, GND–GND;
    - the master is on **this same PC** — a pair of virtual COM ports:
      whatever is written into one comes out of the other.

## Virtual COM ports

=== "Windows — com0com"

    1. Install [com0com](https://com0com.sourceforge.net/) — a free driver
       for pairs of virtual ports.
    2. In its **Setup** utility create a pair and give the ports familiar
       names, e.g. `COM10` ↔ `COM11` (tick "use Ports class" so programs see
       them).
    3. Check that `COM10` and `COM11` show up in **Device Manager**.

=== "Linux — socat"

    ```bash
    socat -d -d pty,raw,echo=0,link=/tmp/ttyV0 pty,raw,echo=0,link=/tmp/ttyV1
    ```

    While this runs, `/tmp/ttyV0` and `/tmp/ttyV1` are a linked pair. Type
    the port name into ModbusReader by hand.

## Steps

1. **Emulator.** Open the device map in ModbusReader, go to **Slave
   emulator** (++ctrl+9++), pick port `COM11`, device address `1` and press
   **Start**. Baud rate and parity come from **Settings → Connection**, say
   115200 8N1.
2. **Values.** Double-click values in the emulator table to set plausible
   ones: temperature, mode, state. Remember these are raw values — without
   the map's scaling.
3. **Master.** In the SCADA (or another master) set port `COM10`, the same
   baud rate and parity and device address `1`. Start polling.
4. **Watch the traffic.** The emulator log shows every request of the
   master, and the **Reads / Writes / Last** columns show which registers it
   touches. If the SCADA reads an address that is not in the map, the log
   shows exception 02 — a reason to check the [addressing](../modbus/addressing.md)
   in the SCADA project (off-by-one is the usual suspect).
5. **Writes.** Change a setpoint from the SCADA — the value in the emulator
   table changes. Change a value in the emulator — the SCADA should see it.

### The master is a second copy of ModbusReader

To bring the demo project to life without a device, the master can be
ModbusReader itself: start a second copy, open the same project, pick port
`COM10` and press **Connect**. The two copies share one settings file; it is
easier if the second one is the [portable build](../install.md#windows) from a
separate folder: it keeps its own settings.

## What else to check

- **Master timeouts:** set an answer **delay** of 500–1500 ms in the emulator
  and see how the master copes with a slow device.
- **A vanishing device:** stop the emulator — the master should show a lost
  link and restore it after a restart.
- **Byte order:** set a FLOAT to 24.6 and check the SCADA shows 24.6, not
  −775.2 — otherwise the SCADA uses another [byte
  order](../modbus/data-types.md#byte-order).
- **Broadcast commands:** the emulator accepts a write to address 0 without
  answering, like a real device.
