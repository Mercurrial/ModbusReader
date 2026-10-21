---
seo_title: Register map — reading and writing Modbus registers
description: The main page of ModbusReader — the register table with live values, writing values, dec/hex/bin view, search, the transaction log, RS-485 line statistics and memory area inspection.
---

# Register map

The main page of the app (++ctrl+1++): every register of the device in one
table. While polling runs, values update on every cycle.

![Register map: address, name, type, access, value and new value](../images/en/main.png)

## Columns

| Column | Shows |
|---|---|
| ● | State dot: green — a value has arrived since connecting |
| Address | Zero-based address in hex with a table prefix: `0x000A`, `IR 0x0001`, `CO 0x0000`, `DI 0x0000` — see [Tables and addresses](../modbus/addressing.md) |
| Name | The map name; in the English UI the English name, if set |
| Data type | `FLOAT`, `UINT16`, `BOOL`… — see [Data types](../modbus/data-types.md) |
| Access | `R` — read only, `RW` — read and write, `W` — write only |
| Value | The current value with scaling, unit and enum label |
| New value | The field for writing to the device |

Hide columns you don't need in **Settings → Table**. Row height, zebra
striping, monospace values and the flash on change live there too.

## Writing a value

1. Click the **New value** cell of an RW register (or select the row and
   press ++f2++).
2. Type the value and press ++enter++. ++tab++ / ++shift+tab++ move to the
   next / previous row of the column.

The value is entered in **engineering units** — if the register has a
scale, the app converts it to raw. Coils accept `1`/`0`, `on`/`off`,
`true`/`false`, `yes`/`no`. For a register with an enumeration — the number.

The result goes to the log: **Write OK** or **Write not acknowledged** with
the address of the word the device refused. Without a connection a write
is neither sent nor queued: the log says it was not sent.

Right-click a row → **Write value…** does the same in a separate dialog.

## Register menu

Right-click a row:

- **Add to live chart** / **Remove from chart** — a live [trend](trends.md)
  on the right (up to 8 at once).
- **Add to watch** — into the [watch window](trends.md#watch) (++f6++).
- **View as** — decimal, hexadecimal or binary. Not offered for registers
  with scaling, an enum, or strings: an engineering value has no "hex view".
- **Copy value**, **Copy address**.
- **Write value…** — for writable registers.

## Search

++ctrl+f++ — the **Search register…** field above the table. It filters by
name and address; the "13 of 13" counter next to it shows how many rows are
visible.

## Transaction log

At the bottom of the window — every exchanged frame in hex, decoded:

```text
[12:00:01.316] [TX] → [01 03 00 00 00 02 C4 0B]  FC03 · read 2 reg from 0x0000
[12:00:01.330] [RX] ← [01 03 04 41 C4 CC CD 3B 67]  data: [41C4 CCCD]
```

- The **All / TX / RX / Errors** tabs filter the log, **Find in log**
  searches its text.
- The log can be saved to `.txt` or cleared.
- **Clicking a register's state dot** turns on a detailed log for that
  register (a ring appears around the dot) — handy when you need to see the
  raw words of one FLOAT to find its byte order.
- Verbosity, panel height and entry limit — **Settings → Log**.

Under the log is the raw-frame line. More about it in [Console](console.md).

## Line statistics

The bottom-right corner shows **TX / RX / ERR** counters and the average
response time. Click for details:

| Counter | Meaning |
|---|---|
| Requests sent / Answers received | The answer rate is the main measure of link quality |
| No answer (timeout) | Wiring, slave ID, baud rate |
| CRC errors | The answer was corrupted: noise, no terminator, wrong parity |
| Modbus exceptions | The device refused: address or function not supported |
| Response time | Last, average, min and max |

Counters reset on every connect and with **Reset**. What to do about them —
see [Troubleshooting](../troubleshooting.md).

## Memory areas

A register of type `MEMORY_AREA` is not one value but a large array (an
oscillogram buffer or the device event log, for example). It is not polled
cyclically; a **double-click** opens the array viewer: number of channels,
layout (**Interleaved** Ch1, Ch2, Ch3… or **Blocked**), type and byte order.
**Request data** reads the array in chunks of 125 registers.

## Edit map

**Edit map** above the table (or ++ctrl+2++) opens the
[map editor](map-editor.md).
