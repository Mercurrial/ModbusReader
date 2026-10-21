---
seo_title: Troubleshooting — Modbus device not responding, wrong values, errors
description: Common Modbus RTU problems in ModbusReader and their fixes — no answer (timeout), CRC errors, exception 02, strange FLOAT values, negative numbers, port busy, no COM port, SmartScreen, a write not acknowledged.
---

# Troubleshooting

## No answer (timeout) { #timeout }

The log says "Timeout", the **No answer** counter in the statistics grows.

1. Is it the right **port**? The COM number changes when the adapter goes
   into another USB socket.
2. Do **baud rate, parity, stop bits** and the **device address** match the
   device settings?
3. Swap the **A and B** wires.
4. Is there a **common ground** (GND)?
5. Don't know the address or baud rate — the [scanner](guide/scanner.md).

The full checklist: [Debugging a line](examples/line-debugging.md).

## CRC errors

An answer arrived but was corrupted. Causes: no common ground or terminator,
noise, wrong parity, a second master on the line. See
[Debugging a line](examples/line-debugging.md#unreliable).

## Exception 02 — illegal data address

The device is on the line but has no such register:

- the address is **off by one** — the datasheet counts from 1 or uses 40001;
- the register is in **another table** — input instead of holding;
- a 32-bit value **runs past the last** register of the device.

See [Tables and addresses](modbus/addressing.md).

## A FLOAT shows −775.2, 1e-38 or huge numbers

Wrong **byte order**. **Settings → Connection → Codecs → FLOAT** — try ABCD,
CDAB, DCBA (the default is BADC). Details:
[Byte order](modbus/data-types.md#byte-order).

## A counter turned negative after 32767

The register's type is `SHORT` (signed) and should be `UINT16`. For 32 bits —
`UINT32` instead of `LONG`. Change the type in the [map editor](guide/map-editor.md).

## A value is 10 or 100 times too big

The device sends it as a fixed-point integer: 2412 instead of 24.12 V. Set a
**scale** of 0.01 in **Engineering units…** — see
[Scaling](modbus/data-types.md#scaling).

## "???" in the table

The register type cannot become a number (service types such as `ARR`,
`DATE_TIME`), or the word is not a valid value of the type — a `BCD16` digit
above 9, for example. Check the type in the map.

## "Write not acknowledged"

- The register is read-only — an input register or a discrete input, or the
  device does not allow writing it.
- The value is out of range — the device answered with exception 03.
- The device accepts 32-bit values only through function 16 — ModbusReader
  writes them one word at a time with function 06. Send the write from the
  [console](guide/console.md) as a function 16 frame.
- Not connected — a write is neither sent nor queued: connect and repeat.

## "Port is busy"

A port has exactly one owner. While polling runs, the sniffer and the
emulator cannot use the same port — and the other way round. Disconnect
(++f5++) or use a second adapter. Another program (a SCADA, a terminal) may be
holding the port too — close it.

## No COM port in the list

- Windows: **Device Manager → Ports (COM & LPT)**. No port, or an
  exclamation mark — install the adapter driver (FTDI, CP210x, CH340).
- Linux: your user must be in the `dialout` group
  ([Install](install.md#linux)).
- macOS: use the `/dev/cu.…` device.
- You can type the port into the settings by hand.

## Values do not update

- Did you press **Connect**? Green dots next to registers mean values are
  arriving.
- Polling stopped after the link was lost — connect again or turn on **Keep
  polling on connection loss**.
- Port settings changed while polling — reconnect.

## Windows: "Windows protected your PC"

The app is not signed with a paid certificate. **More info → Run anyway**.
See [Install](install.md#smartscreen).

## macOS: "the app is damaged"

```bash
xattr -dr com.apple.quarantine /Applications/ModbusReader.app
```

## Linux: an error about the xcb platform

Install `libxcb-cursor0` (Debian, Ubuntu) or `xcb-util-cursor` (Fedora,
Arch).

## The app crashed or behaves oddly

Error tracebacks go to `modbusreader_errors.log` — next to the settings
(`%APPDATA%\ModbusReader`, or next to the portable exe). Attach it to a bug
report in [Issues](https://github.com/Mercurrial/ModbusReader/issues). The
console build, `ModbusReader_debug.exe`, shows more detail.

## Didn't find your answer

Ask in [Discussions](https://github.com/Mercurrial/ModbusReader/discussions):
give the device and adapter models and the link settings, and attach the
transaction log (**Save log…**).
