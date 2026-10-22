---
seo_title: Modbus data types and byte order — FLOAT, LONG, ABCD, CDAB, BADC
description: How Modbus devices store FLOAT, INT32, UINT32, INT64, DOUBLE, BCD and strings in 16-bit registers, what ABCD, BADC, CDAB and DCBA byte orders (word swap, byte swap) mean, how to find the right one when values look wrong, and how scaling and enumerations work.
---

# Data types and byte order

A Modbus register is 16 bits, nothing more. The protocol does not know what
is inside: a signed number, an unsigned one, half a FLOAT or two characters
of a string. Only the device documentation knows — and the register map, in
which you set the **type**.

## Types in ModbusReader

| Type | Registers | What it is | Range / example |
|---|:---:|---|---|
| `BOOL` | 1 | A 0/1 bit: coil, discrete input or flag | 0, 1 |
| `SHORT` | 1 | Signed 16-bit integer (INT16) | −32768…32767 |
| `UINT16` | 1 | Unsigned 16-bit integer (WORD) | 0…65535 |
| `BITS16` | 1 | 16 flags, shown in binary | `0b0000 0000 0010 0101` |
| `BCD16` | 1 | 4 decimal digits in BCD | `0x1234` → 1234 |
| `LONG` | 2 | Signed 32-bit integer (INT32, DINT) | ±2,147,483,647 |
| `UINT32` | 2 | Unsigned 32-bit integer (DWORD, UDINT) | 0…4,294,967,295 |
| `BCD32` | 2 | 8 decimal digits in BCD | `0x12345678` → 12345678 |
| `FLOAT` | 2 | IEEE-754 floating point (REAL) | 24.6 |
| `INT64` | 4 | Signed 64-bit integer (LINT) | energy counters |
| `DOUBLE` | 4 | IEEE-754 double precision (LREAL) | 3.141592653589793 |
| `STRING` | N | Text: 2 characters per register, length in the SIZE column | serial number |

The other types in the editor list (`BYTE`, `LONG1`, `FLOAT1`, `FLOAT2`,
`ARR`, `STR_LEN`, `DATE_TIME` and the service areas `UNUSED_AREA`,
`MEMORY_AREA`) exist for compatibility with particular device maps and are
not polled as numbers — the table shows them as `???` or as a memory area
you can open with a double-click.

!!! tip "Sign matters"
    If a counter jumps from 32767 to −32768, its type is `SHORT` and it
    should be `UINT16`. The same for 32 bits: `LONG` ↔ `UINT32`.

**Strings** take two bytes per register, the high byte being the first
character; the encoding is Windows-1251, so Cyrillic reads correctly. A string
ends at the first zero byte; on write the rest of the field is zero-filled.

## Byte order { #byte-order }

A 32-bit value takes two registers, and the Modbus standard does not say in
which order to put them. Every vendor decided for itself. Name the bytes of
the number with letters: **A** — most significant … **D** — least. Then the
FLOAT **24.6** = `0x41C4CCCD` (A=`41`, B=`C4`, C=`CC`, D=`CD`) can arrive in four
ways:

| Order | Register 1 | Register 2 | Also called |
|---|---|---|---|
| **ABCD** | `41C4` | `CCCD` | Big-endian, "standard" |
| **BADC** | `C441` | `CDCC` | Byte swap — bytes swapped inside each word |
| **CDAB** | `CCCD` | `41C4` | Word swap — words swapped (common on PLCs) |
| **DCBA** | `CDCC` | `C441` | Little-endian, fully reversed |

Pick the wrong order and you get not an error but **a different number**.
The same two registers `41C4 CCCD` read as BADC give −775.2, as CDAB
−107,613,728, as DCBA −429,426,720. A wrong order almost always produces a
huge, tiny or negative number where none should be.

16-bit values have two variants: **AB** (standard) and **BA** (bytes
swapped).

### Where to set it

**Settings → Connection → Codecs — byte order**, separately for three
families:

| Setting | Applies to | Default |
|---|---|---|
| SHORT (16 bit) | SHORT, UINT16, BITS16, BCD16, STRING | AB |
| LONG (32 bit) | LONG, UINT32, BCD32, INT64 | ABCD |
| FLOAT (32 bit, IEEE-754) | FLOAT, DOUBLE | **BADC** |

The order is shared by the whole map and saved in the project together with
the link settings.

!!! note "Why FLOAT defaults to BADC"
    That is the protocol of the devices the app was first written for. If
    your device sends FLOAT in the standard ABCD order, change the setting
    once and save the project.

### Finding the right order

1. Find a register whose value you know: a setpoint, the supply voltage,
   room temperature.
2. Switch the FLOAT (or LONG) order in the settings and save — the value in
   the table updates on the next poll.
3. The right order gives a plausible number; the other three give garbage.

Faster: paste the raw registers into the [online converter](../tools/converter.md)
— it shows the value in all four orders at once.

The raw register words are visible in the transaction log at the bottom of
the window: click the green dot next to a register to see that register's
frames in the log.

## 64-bit values

`INT64` and `DOUBLE` take four registers and follow the same settings:
`INT64` the LONG order, `DOUBLE` the FLOAT order. ABCD — eight bytes from
most to least significant, BADC — bytes swapped in every word, CDAB — words
in reverse order, DCBA — fully reversed.

## Scale and offset { #scaling }

Many devices send fractional values as integers: 573 instead of 57.3 %, 2412
instead of 24.12 V. Each register in the map can have **engineering units**
(in the editor — **Engineering units…**):

```text
displayed = raw × scale + offset
```

For example, a scale of `0.1` turns 573 into **57.3**, and a scale of `0.01`
with the unit "V" turns 2412 into **24.12 V**. Scaling applies in the table,
trends, dashboard, logger and snapshots. When you write from the table or the
dashboard, the app converts back: you type 25.5 — the raw value goes to the
device.

!!! warning "Macros work with raw values"
    `read()` in a macro returns the number as the device sent it (573, not
    57.3), and `write()` writes it without conversion. Apply the scale in the
    macro yourself: `read("Heater power") * 0.1`.

## Enumerations

Mode and state registers can have value labels — one per line:

```text
0 = Stop
1 = Run
2 = Fault
```

Then the table shows **Run** instead of `1`, and the dashboard **Select**
widget offers the list of modes.

Next: [Function and exception codes](functions.md).
