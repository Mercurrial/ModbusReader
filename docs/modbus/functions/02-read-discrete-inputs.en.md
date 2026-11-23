---
seo_title: Modbus function code 02 (0x02) Read Discrete Inputs — format and example
description: Modbus function 02 reads discrete inputs (the 1x table of read-only bits). Request and response format, bit packing, an example frame with CRC decoded, coils vs discrete inputs, exceptions.
---

# Function 02 — Read Discrete Inputs

**Function 02** (0x02, Read Discrete Inputs) reads the state of one or more
**discrete inputs** — the read-only bits of the 1x table. They are what a
device "sees" outside: a limit switch, a door sensor, a dry contact, an
alarm signal. A discrete input cannot be written — the outside world sets
it.

| Property | Value |
|---|---|
| Code | 2 (0x02) |
| Table | Discrete inputs (1x) |
| Action | Read |
| Per request | 1…2000 bits |
| Broadcast (address 0) | No |

## Request { #request }

The format is that of [function 01](01-read-coils.md):

| Field | Bytes | Value |
|---|:---:|---|
| Device address | 1 | 1…247 |
| Function code | 1 | `02` |
| First input address | 2 | 0x0000…0xFFFF |
| Input count | 2 | 1…2000 |
| CRC16 | 2 | low byte first |

Read twenty-two inputs from device 1 starting at address 196 (0x00C4; 10197
in Modicon notation):

```text
01 02 00 C4 00 16 B8 39
|  |  +-+-+ +-+-+ +-+-+
|  |    |     |     +-- CRC16
|  |    |     +-------- count: 22
|  |    +-------------- first input address: 196
|  +------------------- function 02
+---------------------- device address: 1
```

## Response { #response }

```text
01 02 03 AC DB 35 22 88
|  |  |  +--+--+  +-+-+
|  |  |     |       +-- CRC16
|  |  |     +---------- bits of inputs 196...217
|  |  +---------------- 3 bytes (22 bits -> 3 bytes)
|  +------------------- function 02
+---------------------- device address: 1
```

The bits are packed as in [function 01](01-read-coils.md#bit-packing): the
first input is the lowest bit of the first byte. Byte `0xAC` = `1010 1100`
gives inputs 196…203 right to left: 0, 0, 1, 1, 0, 1, 0, 1. The last byte
`0x35` = `0011 0101` carries the six remaining inputs (212…217): 1, 0, 1, 0,
1, 1; the two high bits are zero padding.

## Errors { #exceptions }

| Answer | Exception | When |
|---|:---:|---|
| `01 82 01 81 60` | 01 | The device has no discrete inputs |
| `01 82 02 C1 61` | 02 | No input at that address, or the block runs past the end |
| — | 03 | Count 0 or above 2000 |
| — | 04 | The device failed to read its inputs |

## Coils or discrete inputs? { #coils-or-inputs }

| | Coils (function 01) | Discrete inputs (function 02) |
|---|---|---|
| What | Outputs, commands, flags | Inputs, outside states |
| Writable | Yes (05, 15) | No |
| Modicon notation | 0xxxx | 1xxxx |

As with registers, vendors follow this in different ways: some devices
offer inputs only as discrete inputs, others expose the same bits as coils
too, others as bits of a holding register. Check the manual: **1xxxx**,
**FC02**, **Discrete Input** all mean function 02.

## In ModbusReader { #modbusreader }

Map rows with the **1x Discrete** table are read with function 02; type
`BOOL`, read-only. Function 02 frames show in the transaction log and the
[sniffer](../../guide/sniffer.md); the [emulator](../../guide/slave.md)
answers 02 from its own inputs.

## See also { #see-also }

- [Function 01 — Read Coils](01-read-coils.md)
- [Tables and addresses](../addressing.md) — 10001 and zero-based
  addresses.
- [All Modbus functions](index.md) · [CRC calculator and frame decoder](../../tools/crc.md)
