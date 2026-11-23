---
seo_title: Modbus function code 04 (0x04) Read Input Registers — format and example
description: Modbus function 04 reads input registers (3x), where devices keep their measurements. Request and response format, an example frame with CRC, how it differs from function 03, the 125-register limit, exceptions.
---

# Function 04 — Read Input Registers

**Function 04** (0x04, Read Input Registers) reads one or more consecutive
**input registers** — the 16-bit words of the 3x table. They are read-only:
devices usually put what they measure there — temperature, current,
voltage, flow. No function can write an input register.

| Property | Value |
|---|---|
| Code | 4 (0x04) |
| Table | Input registers (3x) |
| Action | Read |
| Per request | 1…125 registers |
| Broadcast (address 0) | No |

## Request { #request }

The format is that of [function 03](03-read-holding-registers.md) — only
the function code differs:

| Field | Bytes | Value |
|---|:---:|---|
| Device address | 1 | 1…247 |
| Function code | 1 | `04` |
| Start address | 2 | 0x0000…0xFFFF |
| Register count | 2 | 1…125 |
| CRC16 | 2 | low byte first |

Read one input register at address 8 (30009 in Modicon notation) from
device 1:

```text
01 04 00 08 00 01 B0 08
|  |  +-+-+ +-+-+ +-+-+
|  |    |     |     +-- CRC16
|  |    |     +-------- count: 1
|  |    +-------------- start address: 0x0008
|  +------------------- function 04
+---------------------- device address: 1
```

## Response { #response }

```text
01 04 02 00 0A 39 37
|  |  |  +-+-+ +-+-+
|  |  |    |     +-- CRC16
|  |  |    +-------- register 0x0008 = 0x000A = 10
|  |  +------------- 2 data bytes
|  +---------------- function 04
+------------------- device address: 1
```

The byte count is twice the register count; each register high byte first.
Turning words into a FLOAT or a 32-bit integer —
[Data types and byte order](../data-types.md).

## Errors { #exceptions }

| Answer | Exception | When |
|---|:---:|---|
| `01 84 01 82 C0` | 01 | The device does not support function 04 — all its data is in holding registers |
| `01 84 02 C2 C1` | 02 | No input register at that address, or the block runs past the end |
| — | 03 | Count 0 or above 125 |
| — | 04 | The device could not get the value (a failed sensor, say) |

## 03 or 04? { #03-or-04 }

The protocol separates "what the device measures" (input, read-only) from
"what can be set" (holding, read and write). Vendors follow it in different
ways:

- **Strictly:** measurements in input (function 04), setpoints in holding
  (03). Many energy meters and I/O modules work this way.
- **Everything in holding:** measurements and settings alike are read with
  function 03, and the device does not support 04 (exception 01).
- **The same data in both tables:** some devices give identical data to 03
  and 04.

The manual gives the hint: an address like **3xxxx** or a note
**FC04 / Input Register** means function 04; **4xxxx**, **FC03**,
**Holding** mean function 03. Without a manual — try both: the device
answers one with data and the other with an exception.

## In ModbusReader { #modbusreader }

Registers with the **3x Input** table in the
[register map](../../guide/map-editor.md) are read with function 04, and the
app does not let you write them — their access is always "R". When a map
is imported from Excel or CSV, 3xxxx addresses land in this table by
themselves. Function 04 frames show in the transaction log and the
[sniffer](../../guide/sniffer.md), can be sent from the
[console](../../guide/console.md), and the [emulator](../../guide/slave.md)
answers 04 from its own input registers.

## See also { #see-also }

- [Function 03 — Read Holding Registers](03-read-holding-registers.md)
- [Tables and addresses](../addressing.md) — 30001, 40001 and zero-based
  addresses.
- [All Modbus functions](index.md) · [CRC calculator and frame decoder](../../tools/crc.md)
