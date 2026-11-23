---
seo_title: Modbus function code 06 (0x06) Write Single Register — format and example
description: Modbus function 06 writes one holding register. Request and echo response, an example frame with CRC, writing negative and 32-bit values, EEPROM wear, exceptions 02 and 03.
---

# Function 06 — Write Single Register

**Function 06** (0x06, Write Single Register) writes one 16-bit value to one
**holding register** (the 4x table). This is how setpoints, settings and
operating modes are changed — anything a device keeps in a single word.

| Property | Value |
|---|---|
| Code | 6 (0x06) |
| Table | Holding registers (4x) |
| Action | Write one register |
| Value | 0x0000…0xFFFF |
| Broadcast (address 0) | Yes, without an answer |

## Request { #request }

| Field | Bytes | Value |
|---|:---:|---|
| Device address | 1 | 0…247 |
| Function code | 1 | `06` |
| Register address | 2 | 0x0000…0xFFFF |
| Value | 2 | high byte first |
| CRC16 | 2 | low byte first |

Write 3 to register 1 of device 1:

```text
01 06 00 01 00 03 98 0B
|  |  +-+-+ +-+-+ +-+-+
|  |    |     |     +-- CRC16
|  |    |     +-------- value: 3
|  |    +-------------- register address: 1
|  +------------------- function 06
+---------------------- device address: 1
```

## Response { #response }

The device answers with an **exact copy of the request** — the confirmation
of the write:

```text
01 06 00 01 00 03 98 0B
```

If the answer differs from the request or never comes, the write cannot be
taken as done: read the register back with
[function 03](03-read-holding-registers.md).

## Errors { #exceptions }

| Answer | Exception | When |
|---|:---:|---|
| `01 86 01 83 A0` | 01 | The device does not support function 06 (some only take [16](16-write-multiple-registers.md)) |
| `01 86 02 C3 A1` | 02 | No register at that address, or it is read-only |
| `01 86 03 02 61` | 03 | The value is outside the setpoint's range |
| — | 04 | The device failed to store the value |

## What number to write { #value }

The value is 16 bits; what they mean is up to the device:

- **Negative numbers** (INT16) are written in two's complement: −1 →
  `FF FF`, −10 → `FF F6`.
- **Scaling.** If the manual says "setpoint, ×0.1 °C", 25.0 °C is 250
  (`00 FA`), not 25.
- **32-bit values** (FLOAT, INT32) take two registers. With function 06 they
  are written in two requests — one word, then the other. In between the
  device holds half of the new number and half of the old; if it applies
  values at once, that may briefly produce garbage. Writing both registers
  in one [function 16](16-write-multiple-registers.md) request is safer.

## In practice { #notes }

- **EEPROM wears out.** Many devices keep setpoints in non-volatile memory
  rated for 100,000 – 1,000,000 writes. Writing every second in a loop eats
  that in days or months. Write only when the value changes; some devices
  offer separate "not saved" registers for frequent changes.
- **Password and write enable.** Some devices accept settings only after a
  password or unlock code is written to a service register — otherwise the
  answer is exception 02 or 03.
- **Broadcast** sets one setpoint on every device at once, but none of them
  confirms it.

## In ModbusReader { #modbusreader }

The value of a register with `RW` or `W` access is entered in the **New
value** column in engineering units: the app applies the scaling and sends
a function 06 frame. Multi-register values (FLOAT, LONG) are written word
by word with function 06; if the device needs function 16, send the frame
from the [console](../../guide/console.md). The
[emulator](../../guide/slave.md) takes 06 and changes its own register, and
the [sniffer](../../guide/sniffer.md) shows other masters' writes.

## See also { #see-also }

- [Function 16 — Write Multiple Registers](16-write-multiple-registers.md) —
  several registers in one request.
- [Function 03 — Read Holding Registers](03-read-holding-registers.md) —
  checking what was written.
- [Data types and byte order](../data-types.md) · [All Modbus functions](index.md)
