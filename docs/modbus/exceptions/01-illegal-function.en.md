---
seo_title: Modbus exception 01 Illegal Function — the device does not support the function
description: Modbus exception code 01 (Illegal Function) means the device does not support the requested function code. Common causes — 03 instead of 04, writing with 16 instead of 06 or the other way round, a function unavailable in the current state — and what to do.
---

# Exception 01 — Illegal Function

**Exception 01** (Illegal Function) means the device took the frame but
**does not support that function code** — or cannot carry it out right
now, in its current state.

```text
01 83 01 80 F0
|  |  |
|  |  +-- exception 01: Illegal Function
|  +----- 0x83 = error answer to function 03
+-------- device 1
```

## Common causes { #causes }

### Reading with the wrong function { #read }

The device keeps all its data in one table and supports only one read
function:

- everything in **input registers** →
  [03](../functions/03-read-holding-registers.md) gets 01, read with
  [04](../functions/04-read-input-registers.md);
- everything in **holding registers** → 04 gets 01, read with 03;
- no **coils** or **discrete inputs** → 01 or 02 gets exception 01.

**Check:** see in the manual which function reads the register ("FC03",
"FC04", 3xxxx or 4xxxx addresses), or simply try the other one.

### Writing with the wrong function { #write }

- The device takes only [06](../functions/06-write-single-register.md), and
  the request uses [16](../functions/16-write-multiple-registers.md) —
  common with simple sensors and older controllers.
- The device takes only 16 (controllers and devices with 32-bit setpoints),
  and the request uses 06.
- Writing bits: only [05](../functions/05-write-single-coil.md) or only
  [15](../functions/15-write-multiple-coils.md).

### The function exists, but not for this register { #per-register }

Some devices answer 01 when the function is supported in general but not
for the requested area — writing a read-only register, for instance.
Strictly by the specification that is a case for exception 02, but vendors
read it differently.

### The wrong state { #state }

The specification allows 01 also when the function is supported but the
device is in a state where it cannot be carried out — not configured yet,
or waiting for another command.

### Rare and diagnostic functions { #rare }

Functions 07, 08, 11, 17, 20–24 and 43 are far from universal; many devices
answer 01 to anything but the main 01–06, 15 and 16.

## What to do { #fix }

1. Find the table of supported functions in the device manual — usually at
   the start of its Modbus section.
2. Without one, try the alternative: 03 ↔ 04, 06 ↔ 16, 05 ↔ 15.
3. If the device sits behind a gateway, make sure the 01 comes from the
   device and not the gateway (gateways may limit functions too).

## In ModbusReader { #modbusreader }

The read function in ModbusReader follows the map row's **table**: 4x
Holding — 03, 3x Input — 04, 0x Coil — 01, 1x Discrete — 02. If the device
answers exception 01, change the row's table in the
[map editor](../../guide/map-editor.md). Writes use functions 05 and 06; if
the device only takes 16 or 15, send the frame from the
[console](../../guide/console.md). The [emulator](../../guide/slave.md)
itself answers exception 01 to anything but 01–06, 15 and 16.

## See also { #see-also }

- [Modbus functions](../functions/index.md) — every function code.
- [Exception 02 — Illegal Data Address](02-illegal-data-address.md)
- [All exception codes](index.md)
