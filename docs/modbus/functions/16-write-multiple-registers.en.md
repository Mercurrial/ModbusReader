---
seo_title: Modbus function code 16 (0x10) Write Multiple Registers — format, FLOAT example
description: Modbus function 16 (0x10) writes several holding registers in one request. Request and response format, an example frame with CRC, writing FLOAT and 32-bit values, the 123-register limit, exceptions.
---

# Function 16 — Write Multiple Registers

**Function 16** (0x10, Write Multiple Registers) writes several consecutive
**holding registers** in one request. It is the main way to write a value
that takes more than one register — a FLOAT, a 32- or 64-bit integer, a
string — and to write a group of setpoints at once.

| Property | Value |
|---|---|
| Code | 16 (0x10) |
| Table | Holding registers (4x) |
| Action | Write several registers |
| Per request | 1…123 registers |
| Broadcast (address 0) | Yes, without an answer |

## Request { #request }

| Field | Bytes | Value |
|---|:---:|---|
| Device address | 1 | 0…247 |
| Function code | 1 | `10` |
| Start address | 2 | 0x0000…0xFFFF |
| Register count | 2 | 1…123 (0x0001…0x007B) |
| Byte count | 1 | 2 × register count |
| Values | 2 × N | each register high byte first |
| CRC16 | 2 | low byte first |

Write 10 and 258 to registers 1 and 2 of device 1:

```text
01 10 00 01 00 02 04 00 0A 01 02 92 30
|  |  +-+-+ +-+-+ |  +-+-+ +-+-+ +-+-+
|  |    |     |   |    |     |     +-- CRC16
|  |    |     |   |    |     +-------- register 2 = 0x0102 = 258
|  |    |     |   |    +-------------- register 1 = 0x000A = 10
|  |    |     |   +------------------- 4 data bytes
|  |    |     +----------------------- count: 2
|  |    +----------------------------- start address: 1
|  +---------------------------------- function 16 (0x10)
+------------------------------------- device address: 1
```

## Response { #response }

The device returns the start address and the number of registers written:

```text
01 10 00 01 00 02 10 08
|  |  +-+-+ +-+-+ +-+-+
|  |    |     |     +-- CRC16
|  |    |     +-------- registers written: 2
|  |    +-------------- from address: 1
|  +------------------- function 16
+---------------------- device address: 1
```

## Writing a FLOAT { #float }

25.0 in IEEE 754 is `41 C8 00 00`. Write it to registers 2–3 of device 1 in
ABCD order:

```text
01 10 00 02 00 02 04 41 C8 00 00 E7 B4
```

If the device keeps FLOATs in another word or byte order, the data bytes are
rearranged: CDAB — `00 00 41 C8`, BADC — `C8 41 00 00`, DCBA —
`00 00 C8 41`. Which order your device uses and how to find out —
[Data types and byte order](../data-types.md); split any number into
registers with the [FLOAT converter](../../tools/converter.md).

## Errors { #exceptions }

| Answer | Exception | When |
|---|:---:|---|
| `01 90 01 8D C0` | 01 | The device does not support function 16 — write registers one by one with [function 06](06-write-single-register.md) |
| `01 90 02 CD C1` | 02 | The block runs past the registers or touches a read-only one |
| `01 90 03 0C 01` | 03 | Count 0 or above 123, byte count not 2 × count, or a value out of range |
| — | 04 | The device failed to store the values |

## 16 or 06? { #16-or-06 }

| | Function 06 | Function 16 |
|---|---|---|
| Registers per request | 1 | 1…123 |
| Answer | a copy of the request | address and count |
| 32-bit value | two requests, half a number in between | one request |
| Support | almost everywhere | almost everywhere, but not always |

Some devices take only one of the two: old and simple ones only 06, some
controllers and devices with 32-bit setpoints only 16 (answering 06 with
exception 01 or 02). If a write fails with one function — try the other.
Function 16 also works for a single register: count 1, byte count 2.

## In ModbusReader { #modbusreader }

When polling, the app writes with function 06 — multi-register values word
by word. If the device needs function 16, build the frame in the
[console](../../guide/console.md), such as the FLOAT write above — the
console adds the CRC. The [emulator](../../guide/slave.md) takes function 16,
and the [sniffer](../../guide/sniffer.md) decodes it: you see which values
another master wrote.

## See also { #see-also }

- [Function 06 — Write Single Register](06-write-single-register.md)
- [Function 03 — Read Holding Registers](03-read-holding-registers.md)
- [FLOAT and INT32 converter](../../tools/converter.md) · [All Modbus functions](index.md)
