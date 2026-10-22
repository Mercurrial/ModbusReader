---
seo_title: Modbus register addresses — 40001, 0x0000 and the off-by-one
description: Why holding register 40001 is address 0, how coils, discrete inputs, input and holding registers differ, how to read addresses from a device datasheet (4x, zero-based, one-based, hex) and how ModbusReader shows them.
---

# Tables and addresses

The most common reason for "the device answers but the values are wrong" is
an **address off by one**, or looking for a register in the wrong table.
Let's settle it once and for all.

## Four tables

A Modbus device has four **independent** address spaces. Coil 0, discrete
input 0, input register 0 and holding register 0 are four different things,
and each is read by its own function:

| Table | In ModbusReader | Size | Read | Write |
|---|---|---|---|---|
| Coils | `CO 0x0000`, "0x Coil" | 1 bit | FC 01 | FC 05 |
| Discrete inputs | `DI 0x0000`, "1x Discrete" | 1 bit | FC 02 | — |
| Input registers | `IR 0x0000`, "3x Input" | 16 bits | FC 04 | — |
| Holding registers | `0x0000`, "4x Holding" | 16 bits | FC 03 | FC 06 / FC 16 |

If a device answers a register with exception 02 "illegal address", check
whether it lives in another table: measurements are often served as input
registers (FC 04) rather than holding (FC 03).

## On the wire the address is zero-based

In the frame itself the address is a 16-bit number from 0 to 65535
(`0x0000…0xFFFF`). The first register of each table is address **0**. But
device documentation writes the same register in three different ways:

| Written in the datasheet | Meaning | Address on the wire |
|---|---|---|
| `0`, `0x0000`, `0000h` | protocol address, zero-based | 0 |
| `1`, "register 1" | register number, one-based | 0 |
| `40001` | holding register 1 in Modicon notation (4x) | 0 |
| `30001` | input register 1 (3x) | 0 |
| `10001` | discrete input 1 (1x) | 0 |
| `00001` | coil 1 (0x) | 0 |

The **4x/3x/1x/0x** notation comes from Modicon controllers: the first digit
names the table, the rest is the register number **counted from one**. So
`40001` is the holding register at address 0, and `40010` is at address 9.
A six-digit form also exists: `400001` = `40001`.

!!! warning "Off by one"
    If the datasheet says "register 100" and the device returns someone
    else's value at address 100, the numbering is probably one-based and you
    need address 99. Easy to check: read the neighbouring addresses and look
    for a value you know (a serial number, a setpoint you set yourself).

Convert an address from one form to another — [addresses 40001 ↔ 0x0000](../tools/address.md).

### Decimal or hexadecimal

`0x0010`, `10h`, `$10` and `16` are the same address. If the datasheet table
contains letters A–F, the addresses are hex even without a prefix.

## How ModbusReader handles it

- The table shows addresses **zero-based in hex**, with a table prefix:
  `0x000A` — holding register 10, `IR 0x0001` — input register 1,
  `CO 0x0000` — coil 0, `DI 0x0000` — discrete input 0.
- In the [map editor](../guide/map-editor.md) the table is chosen in the
  **TABLE** column; an address can be typed as `0x10`, `10h` or `16`.
- [Importing from CSV/Excel](../guide/map-editor.md#import) has an explicit
  address format choice: **As written (zero-based)**, **One-based (1 =
  register 0)** or **4x / 3x (40001 = register 0)**. If many addresses in the
  file are above 30000 the app hints that it looks like the 4x convention. In
  4x mode the table comes from the first digit: 3xxxx — input, 1xxxx —
  discrete input.
- In [macros](../guide/macros.md) a register is named by its map name or by
  address: `read(0x0A)`, `read("IR 0x01")`, `read("CO 5")`, `read("DI 3")`.

## How much one request can read

One FC 03/04 request reads up to **125 registers**, FC 01/02 up to 2000
bits. A string field in the map reads at most 125 registers (250
characters).

Next: [Data types and byte order](data-types.md).
