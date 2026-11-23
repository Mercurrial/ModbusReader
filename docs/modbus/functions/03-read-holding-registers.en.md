---
seo_title: Modbus function code 03 (0x03) Read Holding Registers — request and response format
description: Modbus function 03 reads holding registers (4x). Request and response byte by byte, an example frame with CRC, the 125-register limit, exceptions 01, 02 and 03, and common mistakes when reading.
---

# Function 03 — Read Holding Registers

**Function 03** (0x03, Read Holding Registers) reads one or more consecutive
**holding registers** — the 16-bit words of the 4x table. It is the most
used Modbus function: devices keep setpoints and settings in holding
registers, and many keep their measurements there too.

| Property | Value |
|---|---|
| Code | 3 (0x03) |
| Table | Holding registers (4x) |
| Action | Read |
| Per request | 1…125 registers |
| Broadcast (address 0) | No — nobody answers a read |

## Request { #request }

| Field | Bytes | Value |
|---|:---:|---|
| Device address | 1 | 1…247 |
| Function code | 1 | `03` |
| Start address | 2 | 0x0000…0xFFFF, high byte first |
| Register count | 2 | 1…125 (0x0001…0x007D) |
| CRC16 | 2 | low byte first |

Read three registers from device 1 starting at address 0x006B (107; 40108
in Modicon notation):

```text
01 03 00 6B 00 03 74 17
|  |  +-+-+ +-+-+ +-+-+
|  |    |     |     +-- CRC16
|  |    |     +-------- count: 3
|  |    +-------------- start address: 0x006B
|  +------------------- function 03
+---------------------- device address: 1
```

## Response { #response }

| Field | Bytes | Value |
|---|:---:|---|
| Device address | 1 | as in the request |
| Function code | 1 | `03` |
| Byte count | 1 | 2 × register count |
| Register values | 2 × N | each register high byte first |
| CRC16 | 2 | |

```text
01 03 06 02 2B 00 00 00 64 05 7A
|  |  |  +-+-+ +-+-+ +-+-+ +-+-+
|  |  |    |     |     |     +-- CRC16
|  |  |    |     |     +-------- register 0x006D = 0x0064 = 100
|  |  |    |     +-------------- register 0x006C = 0x0000 = 0
|  |  |    +-------------------- register 0x006B = 0x022B = 555
|  |  +------------------------- 6 data bytes
|  +---------------------------- function 03
+------------------------------- device address: 1
```

Each register is an unsigned 16-bit number. Whether it is really a signed
integer, half of a FLOAT or a value scaled by 0.1 the protocol does not
say — the device's register map does. How to build 32-bit values from two
registers — [Data types and byte order](../data-types.md).

## Errors { #exceptions }

| Answer | Exception | When |
|---|:---:|---|
| `01 83 01 80 F0` | 01 | The device does not support function 03 (devices that keep everything in input registers) |
| `01 83 02 C0 F1` | 02 | No register at that address — or `start + count` runs past the end |
| `01 83 03 01 31` | 03 | Count 0 or above 125 |
| `01 83 04 40 F3` | 04 | The device failed to read the value |

The function code in an error answer is `0x83`: the top bit means
"exception". Every code in detail — [Exceptions](index.md#exceptions).

## In practice { #notes }

- **Off by one.** The most common cause of exception 02: the manual says
  "register 40108", the request needs 107 (0x006B). See
  [Tables and addresses](../addressing.md).
- **Wrong table.** If 03 gets exception 02 at an address from the manual,
  it may be an input register, read with
  [function 04](04-read-input-registers.md).
- **Holes in the map.** Many devices refuse (exception 02) if the requested
  block contains even one register that does not exist. Read such maps in
  several requests over continuous stretches.
- **Fewer than 125.** Some devices do not give 125 registers at once — the
  limit is in their manual (16, 32, 64 are common).
- **Half a value.** If a FLOAT sits in registers 100–101, reading only 101
  gives garbage, and some devices answer with an exception.

## In ModbusReader { #modbusreader }

Registers with the **4x Holding** table in the
[register map](../../guide/map-editor.md) are read with function 03 — each
with its own request, round and round. The request and answer, decoded, are
in the transaction log; a function 03 frame of your own can be sent from the
[console](../../guide/console.md). As the [emulator](../../guide/slave.md)
ModbusReader answers 03 itself, and the [sniffer](../../guide/sniffer.md)
decodes other masters' requests and answers.

## See also { #see-also }

- [Function 04 — Read Input Registers](04-read-input-registers.md) — the
  same for input registers.
- [Function 06 — Write Single Register](06-write-single-register.md) and
  [function 16 — Write Multiple Registers](16-write-multiple-registers.md) —
  writing holding registers.
- [All Modbus functions](index.md) · [CRC calculator and frame decoder](../../tools/crc.md)
