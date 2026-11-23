---
seo_title: Modbus exception 02 Illegal Data Address — causes and how to fix it
description: Modbus exception code 02 (Illegal Data Address) means the device has no register at that address. The common causes — off by one, 40001 instead of 0, hex vs decimal, the wrong table, a block past the end — and how to check each.
---

# Exception 02 — Illegal Data Address

**Exception 02** (Illegal Data Address) means the device got the request
and understood the function, but **has no register or bit at that
address** — or the requested block `start address + count` runs past the
ones that exist.

It is the most common Modbus error when commissioning a new device. The
good news: the link works — the device hears you and answers.

```text
01 83 02 C0 F1
|  |  |
|  |  +-- exception 02: Illegal Data Address
|  +----- 0x83 = error answer to function 03
+-------- device 1
```

## Causes — most common first { #causes }

### 1. Off by one { #off-by-one }

Manuals often number registers from one: "register 1", "40001", while the
frame counts from zero. Register "40001" is address **0**, "40100" is
address **99**.

**Check:** subtract 1 from the address. If the manual gives zero-based
addresses (often in hex: `0x0000`), do not subtract anything.

### 2. The 4xxxx notation taken whole { #notation }

"40108" is not address 40108 but "holding register No. 108". The 4 names
the table and is not part of the address. The request carries 107.

**Check:** drop the 4/3/1/0 prefix and subtract one. The
[online tool](../../tools/address.md) converts addresses; details in
[Tables and addresses](../addressing.md).

### 3. Hex read as decimal { #hex }

Address `0x0100` is 256, not 100. Manuals that give hex addresses without
the `0x` prefix ("register 1000h", or just "1000" in a "Hex" column) are a
frequent source of this error.

### 4. The wrong table { #table }

The register exists, but in another table: a measurement sits in input
registers (read with function [04](../functions/04-read-input-registers.md))
while the request uses function
[03](../functions/03-read-holding-registers.md) — or the other way round. On
many devices the 3x and 4x tables are separate, and the same number means
different data in each.

### 5. The block runs past the end or across a hole { #block }

"Read 10 registers from address 95" on a device with 100 registers (0…99)
reaches the non-existent 100–104 — and the whole request gets exception 02,
although the first five registers exist. Many devices refuse the same way
if an unused address sits in the middle of the block.

**Check:** read one register — the first one. If it answers, shrink the
block or split it into continuous stretches.

### 6. A multi-register value not read from its start { #partial }

A FLOAT or INT32 in registers 100–101: some devices give it only whole,
starting at 100. A request from address 101 or with count 1 gets exception
02.

### 7. A read-only register { #read-only }

Writing with function 06 or 16 to a register that can only be read gets
exception 02 on some devices (03 or 01 on others).

### 8. A register locked by a password or a mode { #locked }

Service registers are often available only after a password is written or
in a certain mode (a stopped drive, say). Until then the device answers as
if they did not exist.

## Finding the right address { #find }

1. Read **one** register whose address is certain from the manual (the
   serial number or firmware version, say).
2. If it works, compare with your map: how far off are the addresses?
3. If not, try the same address ±1 and the other function (03 ↔ 04).
4. Without a manual, scan the addresses automatically: a register scanner
   shows which addresses the device answers.

## In ModbusReader { #modbusreader }

Exception 02 shows in the transaction log with the request's address, and
the register gets an error state in the table. The **Registers** mode of
the [scanner](../../guide/scanner.md) walks through addresses and shows
which ones the device gives — that is how a device's real map is found
without a manual. When a [map is imported](../../guide/map-editor.md) from
Excel or CSV, the app asks for the address format (4xxxx, one-based or
zero-based) — which removes the off-by-one.

## See also { #see-also }

- [Tables and addresses](../addressing.md) — 40001, 0x0000 and zero-based
  numbering.
- [Address conversion 40001 ↔ 0x0000](../../tools/address.md) — online.
- [Exception 01 — Illegal Function](01-illegal-function.md) ·
  [Exception 03 — Illegal Data Value](03-illegal-data-value.md)
- [All exception codes](index.md)
