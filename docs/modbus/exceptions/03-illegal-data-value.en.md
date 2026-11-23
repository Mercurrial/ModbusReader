---
seo_title: Modbus exception 03 Illegal Data Value — causes and how to fix it
description: Modbus exception code 03 (Illegal Data Value) means the device rejected a value or count in the request. Causes — a setpoint out of range, more than 125 registers, a wrong byte count, not FF00 in function 05, scaling — and how to check.
---

# Exception 03 — Illegal Data Value

**Exception 03** (Illegal Data Value) means the device understood the
function and the address, but **a value in the request does not suit it**.
By the specification this is first of all an error in the request's
**structure** — a wrong count or length; in practice many devices also
answer 03 to a setpoint outside its allowed range.

```text
01 86 03 02 61
|  |  |
|  |  +-- exception 03: Illegal Data Value
|  +----- 0x86 = error answer to function 06
+-------- device 1
```

## Causes { #causes }

### Count out of range { #count }

| Function | Allowed count |
|---|---|
| [01](../functions/01-read-coils.md), [02](../functions/02-read-discrete-inputs.md) — reading bits | 1…2000 |
| [03](../functions/03-read-holding-registers.md), [04](../functions/04-read-input-registers.md) — reading registers | 1…125 |
| [15](../functions/15-write-multiple-coils.md) — writing bits | 1…1968 |
| [16](../functions/16-write-multiple-registers.md) — writing registers | 1…123 |

A request for 0 registers or 126 gets exception 03. Many devices limit the
count further (16, 32, 64 registers at once) and answer 03 to anything
more.

### Byte count does not match the count { #byte-count }

Functions 15 and 16 carry a "byte count" field, and it must match the
count: exactly 2 × the register count for 16, the bit count / 8 rounded up
for 15. A common mistake in hand-built frames.

### Not FF 00 in function 05 { #coil-value }

[Function 05](../functions/05-write-single-coil.md) takes only `FF 00` (on)
and `00 00` (off). `00 01` gets exception 03.

### A setpoint out of range { #range }

The device allows a setpoint of 0…100 °C and 150 is written — many devices
answer 03. Check the manual for the **minimum, maximum and scaling**: if
the register holds tenths, 25.0 °C is 250, and writing 2500 means 250.0 °C,
out of range.

### Wrong type or format { #format }

- A negative number into an unsigned register.
- A FLOAT written in the wrong byte order: the device sees a huge or
  "not-a-number" value and refuses.
- An enumeration value that is not on the list (mode 7 when 0…3 are
  allowed).

### Writing not allowed in the current mode { #mode }

Some parameters can only be changed in a certain state — motor parameters
of a variable-frequency drive only while it is stopped, for instance. Some
devices answer 03 then, others 04 or 01.

## What to do { #fix }

1. Compare the count with the limits above and with the device manual.
2. Read the register's current value — it hints at the scaling and format.
3. Write a value that is surely allowed (the current one, say) — if that
   works, the problem is the range.
4. For a FLOAT, check the byte order:
   [Data types and byte order](../data-types.md).

## In ModbusReader { #modbusreader }

A value in the **New value** column is entered in engineering units — the
app applies the scaling and writes the raw number, so the "250 instead of
25.0" mistake does not happen as long as the scaling in the
[map](../../guide/map-editor.md) is right. If the device answers 03, the log
says **"Write not acknowledged"** with the register's address. The
[emulator](../../guide/slave.md) answers 03 to a wrong count or length — a
handy way to see how your master copes.

## See also { #see-also }

- [Exception 02 — Illegal Data Address](02-illegal-data-address.md)
- [Function 06 — Write Single Register](../functions/06-write-single-register.md)
  · [Function 16 — Write Multiple Registers](../functions/16-write-multiple-registers.md)
- [All exception codes](index.md)
