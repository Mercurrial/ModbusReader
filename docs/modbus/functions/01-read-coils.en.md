---
seo_title: Modbus function code 01 (0x01) Read Coils — format and bit packing
description: Modbus function 01 reads coils (the 0x table of read/write bits). Request and response format, how bits are packed into bytes, an example frame with CRC decoded, the 2000-bit limit, exceptions.
---

# Function 01 — Read Coils

**Function 01** (0x01, Read Coils) reads the state of one or more **coils**
— the bits of the 0x table, which can be both read and written. The name
comes from relay logic (a relay coil); today it is anything that switches
on and off: relays and digital outputs, "start" and "stop" commands, mode
flags.

| Property | Value |
|---|---|
| Code | 1 (0x01) |
| Table | Coils (0x) |
| Action | Read |
| Per request | 1…2000 bits |
| Broadcast (address 0) | No |

## Request { #request }

| Field | Bytes | Value |
|---|:---:|---|
| Device address | 1 | 1…247 |
| Function code | 1 | `01` |
| First bit address | 2 | 0x0000…0xFFFF |
| Bit count | 2 | 1…2000 (0x0001…0x07D0) |
| CRC16 | 2 | low byte first |

Read nineteen coils from device 1 starting at address 19 (0x0013):

```text
01 01 00 13 00 13 8C 02
|  |  +-+-+ +-+-+ +-+-+
|  |    |     |     +-- CRC16
|  |    |     +-------- count: 19
|  |    +-------------- first bit address: 19
|  +------------------- function 01
+---------------------- device address: 1
```

## Response { #response }

| Field | Bytes | Value |
|---|:---:|---|
| Device address | 1 | |
| Function code | 1 | `01` |
| Byte count | 1 | bit count / 8, rounded up |
| Bits | N | 8 bits per byte |
| CRC16 | 2 | |

```text
01 01 03 CD 6B 05 42 82
|  |  |  +--+--+  +-+-+
|  |  |     |       +-- CRC16
|  |  |     +---------- 3 bytes of bits
|  |  +---------------- byte count: 3 (19 bits -> 3 bytes)
|  +------------------- function 01
+---------------------- device address: 1
```

### How the bits are packed { #bit-packing }

The first requested bit is the **lowest** bit of the first data byte, and so
on. Read a byte right to left:

```text
byte 0xCD = 1 1 0 0 1 1 0 1
            | | | | | | | +-- address 19 = 1
            | | | | | | +---- address 20 = 0
            | | | | | +------ address 21 = 1
            | | | | +-------- address 22 = 1
            | | | +---------- address 23 = 0
            | | +------------ address 24 = 0
            | +-------------- address 25 = 1
            +---------------- address 26 = 1
```

The second byte `0x6B` holds addresses 27…34, the third `0x05`
(`0000 0101`) addresses 35…37: 1, 0, 1. The device pads the unused high
bits of the last byte with zeros.

## Errors { #exceptions }

| Answer | Exception | When |
|---|:---:|---|
| `01 81 01 81 90` | 01 | The device has no coils or does not support function 01 |
| `01 81 02 C1 91` | 02 | No bit at that address, or the block runs past the end |
| — | 03 | Count 0 or above 2000 |
| — | 04 | The device failed to read the state |

## In practice { #notes }

- **Coils are not register bits.** Many devices keep flags not as coils
  but as bits inside a holding register (a "status word"). Those are read
  with function [03](03-read-holding-registers.md) and picked out with a
  mask.
- **00001 addresses.** Modicon notation writes coils as 00001…09999 (or
  000001…); the frame carries the zero-based address: 00001 → 0.
- **Blocks are cheaper.** A request for 100 bits takes almost as long on the
  line as a request for one — if the bits are consecutive, read them
  together.

## In ModbusReader { #modbusreader }

Map rows with the **0x Coil** table are read with function 01; their type is
always `BOOL`. A bit is written in the **New value** column
([how](../../guide/register-map.md)) — `1`/`0`, `on`/`off`; the write goes
out as [function 05](05-write-single-coil.md). Function 01 frames show in
the transaction log and the [sniffer](../../guide/sniffer.md); the
[emulator](../../guide/slave.md) answers 01 from its own coils.

## See also { #see-also }

- [Function 02 — Read Discrete Inputs](02-read-discrete-inputs.md) —
  read-only bits.
- [Function 05 — Write Single Coil](05-write-single-coil.md) and
  [function 15 — Write Multiple Coils](15-write-multiple-coils.md) — writing
  bits.
- [All Modbus functions](index.md) · [Tables and addresses](../addressing.md)
