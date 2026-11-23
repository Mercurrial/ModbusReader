---
seo_title: Modbus function code 05 (0x05) Write Single Coil — FF00 and 0000 explained
description: Modbus function 05 writes one coil (bit). Why "on" is FF 00 and "off" is 00 00, the request and its echo response, an example frame with CRC, exceptions and common mistakes.
---

# Function 05 — Write Single Coil

**Function 05** (0x05, Write Single Coil) turns one **coil** — a bit of the
0x table — on or off. This is how commands are given: switch a relay, start
a pump, reset an alarm, put a device into manual mode.

| Property | Value |
|---|---|
| Code | 5 (0x05) |
| Table | Coils (0x) |
| Action | Write one bit |
| Values | `FF 00` — on, `00 00` — off |
| Broadcast (address 0) | Yes, without an answer |

## Request { #request }

| Field | Bytes | Value |
|---|:---:|---|
| Device address | 1 | 0…247 |
| Function code | 1 | `05` |
| Bit address | 2 | 0x0000…0xFFFF |
| Value | 2 | `FF 00` or `00 00` |
| CRC16 | 2 | low byte first |

Turn on coil 172 (0x00AC) of device 1:

```text
01 05 00 AC FF 00 4C 1B
|  |  +-+-+ +-+-+ +-+-+
|  |    |     |     +-- CRC16
|  |    |     +-------- FF 00 = on
|  |    +-------------- bit address: 172
|  +------------------- function 05
+---------------------- device address: 1
```

Turn the same bit off:

```text
01 05 00 AC 00 00 0D EB
```

!!! warning "Only FF 00 and 00 00"
    The value is not "1" or "0" but exactly `FF 00` or `00 00`. Anything
    else (`00 01`, `01 00`) the device must reject with
    [exception 03](index.md#exceptions). A common mistake in hand-built
    frames.

## Response { #response }

The device answers with an **exact copy of the request**:

```text
01 05 00 AC FF 00 4C 1B
```

The echo means the command was accepted. It is sent after the bit has
changed; but if the bit drives something physical (a relay, a contactor),
the echo does not prove the mechanism has already moved — check its state if
that matters.

## Errors { #exceptions }

| Answer | Exception | When |
|---|:---:|---|
| `01 85 01 83 50` | 01 | The device does not support writing coils |
| `01 85 02 C3 51` | 02 | No bit at that address |
| `01 85 03 02 91` | 03 | The value is neither `FF 00` nor `00 00` |
| — | 04 | The device failed to carry out the command |

## In practice { #notes }

- **Pulse commands.** Many devices reset "command" coils themselves once
  done: write 1 — the device resets the alarm and returns the bit to 0.
  Reading the bit right after the write may already show 0 — that is normal.
- **Broadcast.** A request to address 0 is carried out by every device on
  the line, and none answers — the result can only be checked by reading.
- **Several bits** in one request — [function 15](15-write-multiple-coils.md).
- **A bit inside a register.** If a flag is a bit of a holding register
  rather than a coil, function 05 does not reach it — write the register
  ([06](06-write-single-register.md)) or use mask write (function 22).

## In ModbusReader { #modbusreader }

A bit from a map row with the **0x Coil** table is written with function
05: enter `1`/`0` or `on`/`off` in the **New value** column. If the device
answers with an exception or not at all, the log says **"Write not
acknowledged"** — causes in [Troubleshooting](../../troubleshooting.md). A
function 05 frame to any address can be sent from the
[console](../../guide/console.md), and the [emulator](../../guide/slave.md)
takes 05 and changes its own bit.

## See also { #see-also }

- [Function 01 — Read Coils](01-read-coils.md) — reading bits.
- [Function 15 — Write Multiple Coils](15-write-multiple-coils.md) — writing
  several bits.
- [All Modbus functions](index.md) · [CRC calculator and frame decoder](../../tools/crc.md)
