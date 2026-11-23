---
seo_title: Modbus function code 15 (0x0F) Write Multiple Coils — format and example
description: Modbus function 15 (0x0F) writes several coils in one request. Request and response format, bit packing, an example frame with CRC decoded, the 1968-bit limit, exceptions.
---

# Function 15 — Write Multiple Coils

**Function 15** (0x0F, Write Multiple Coils) writes several consecutive
**coils** — bits of the 0x table — in one request. Handy when a group of
outputs has to switch together: all relays of a module, a set of mode
flags.

| Property | Value |
|---|---|
| Code | 15 (0x0F) |
| Table | Coils (0x) |
| Action | Write several bits |
| Per request | 1…1968 bits |
| Broadcast (address 0) | Yes, without an answer |

## Request { #request }

| Field | Bytes | Value |
|---|:---:|---|
| Device address | 1 | 0…247 |
| Function code | 1 | `0F` |
| First bit address | 2 | 0x0000…0xFFFF |
| Bit count | 2 | 1…1968 (0x0001…0x07B0) |
| Byte count | 1 | bit count / 8, rounded up |
| Bits | N | 8 per byte, first bit lowest |
| CRC16 | 2 | low byte first |

Write ten coils of device 1 starting at address 19:

```text
01 0F 00 13 00 0A 02 CD 01 72 CB
|  |  +-+-+ +-+-+ |  +-+-+ +-+-+
|  |    |     |   |    |     +-- CRC16
|  |    |     |   |    +-------- bits: CD 01
|  |    |     |   +------------- 2 data bytes
|  |    |     +----------------- count: 10
|  |    +----------------------- first bit address: 19
|  +---------------------------- function 15 (0x0F)
+------------------------------- device address: 1
```

The bits are packed as in [function 01](01-read-coils.md#bit-packing):
`0xCD` = `1100 1101` sets addresses 19…26 right to left — 1, 0, 1, 1, 0, 0,
1, 1; `0x01` = `0000 0001` sets addresses 27 and 28 — 1 and 0, and its top
six bits are unused and must be zero.

## Response { #response }

The device returns the address and count — not the bits:

```text
01 0F 00 13 00 0A 24 09
|  |  +-+-+ +-+-+ +-+-+
|  |    |     |     +-- CRC16
|  |    |     +-------- bits written: 10
|  |    +-------------- from address: 19
|  +------------------- function 15
+---------------------- device address: 1
```

## Errors { #exceptions }

| Answer | Exception | When |
|---|:---:|---|
| `01 8F 01 85 F0` | 01 | The device does not support function 15 — write bits one by one with [function 05](05-write-single-coil.md) |
| `01 8F 02 C5 F1` | 02 | The block runs past the existing coils |
| `01 8F 03 04 31` | 03 | Count 0 or above 1968, or the byte count does not match the count |
| — | 04 | The device failed to write the bits |

## In practice { #notes }

- **Every bit of the block is written.** A bit in the middle cannot be
  "skipped" — its value in the frame is written too. To change one bit
  without touching its neighbours, use [function 05](05-write-single-coil.md)
  or read the block with function 01 first.
- **The byte count** must match the bit count: 10 bits — 2 bytes, 16 bits —
  2 bytes, 17 bits — 3 bytes. Getting it wrong is a common cause of
  exception 03 in hand-built frames.
- **Together.** A device usually applies all bits of one request together
  — this matters for groups of outputs that must switch at the same moment.

## In ModbusReader { #modbusreader }

When polling, the app writes coils one at a time with function 05. A
function 15 frame for a group of bits can be sent from the
[console](../../guide/console.md) — it adds the CRC. The
[emulator](../../guide/slave.md) takes function 15, and the
[sniffer](../../guide/sniffer.md) decodes it in other masters' traffic.

## See also { #see-also }

- [Function 05 — Write Single Coil](05-write-single-coil.md)
- [Function 01 — Read Coils](01-read-coils.md)
- [All Modbus functions](index.md) · [CRC calculator and frame decoder](../../tools/crc.md)
