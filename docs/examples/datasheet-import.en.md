---
seo_title: A register map from a device datasheet — import from Excel and CSV
description: Step by step — turning the Modbus register table of a device datasheet (PDF, Excel) into a ModbusReader map — preparing the table, picking the 40001 / zero-based / one-based address format, mapping columns, checking on the device.
---

# A map from a datasheet

Almost every Modbus device datasheet has a register table. There is no need
to retype it into the app — get the table into Excel or CSV and
[import it](../guide/map-editor.md#import).

## 1. Get the table

- If the vendor ships the map as Excel or CSV — use it.
- If there is only a PDF — select the table in a PDF viewer and paste it into
  Excel, or open the PDF in Word / LibreOffice and copy the table from there.
- Remove merged cells, section headings in the middle of the table and
  footnotes — every row must be one register.

An example of what you should end up with (save it as `meter.csv`):

```text
Address,Name,Type,Access,Unit,Scale
40001,Phase A voltage,UINT16,R,V,0.1
40002,Phase A current,UINT16,R,A,0.01
40003,Active power,INT32,R,W,1
40005,Frequency,UINT16,R,Hz,0.01
40010,Device address,UINT16,RW,,1
40011,Baud rate,UINT16,RW,,1
30001,Board temperature,INT16,R,°C,0.1
```

Columns can be named anything and come in any order — you map them during
the import. Only the address column is required.

## 2. Import

1. **Edit map** (++ctrl+2++) → **Import from a spreadsheet…** → pick the
   file.
2. Check the columns were recognised: "Address" → *Address*, "Name" →
   *Name*, "Type" → *Type*, "Scale" → *Scale*. Columns you don't need —
   *ignore*.
3. **Address format** — the key decision:

    | The datasheet says | Choose |
    |---|---|
    | `40001`, `40002`, `30001` | **4x / 3x (40001 = register 0)** |
    | `1`, `2`, `3` and calls it a "register number" | **One-based (1 = register 0)** |
    | `0`, `0x0000`, `0000h` | **As written (zero-based)** |

    In the example above it is 4x: `40001` becomes holding register 0 and
    `30001` becomes input register 0. If you forget to pick 4x, the app warns
    you: too many addresses above 30000.
4. Look at the summary at the bottom: how many registers will be imported and
   whether there are issues — unparsable addresses, duplicates.
5. **Replace the current map** → **Import**.

The app understands datasheet type names by itself: `INT16` → `SHORT`,
`UINT16` / `WORD` → `UINT16`, `INT32` / `DINT` → `LONG`, `UINT32` / `DWORD` →
`UINT32`, `REAL` / `FLOAT32` → `FLOAT` and so on. If a type is not
recognised it becomes `SHORT` — fix it in the editor.

## 3. Finish in the editor

- Check the **size** of 32-bit registers: an `INT32` at 40003 takes 40003
  and 40004, the next register is 40005. The bottom of the editor shows
  **address overlaps** — there should be none.
- Add **enumerations** for mode registers: **Engineering units…** →
  `0 = Stop`, `1 = Run`.
- Add Russian names too if the map will be used with the Russian UI.

## 4. Check on the device

1. Connect (++f5++) and find a register whose value you know: the device
   address, the baud rate, mains voltage ≈ 230 V.
2. If it shows someone else's value, the addresses are off by one. Look at
   the neighbouring rows: if the right value is next door, re-import with
   another address format.
3. If 32-bit values are huge or negative — wrong [byte
   order](../modbus/data-types.md#byte-order).
4. If the device answers a whole block with exception 02 — these may be input
   registers rather than holding (or the other way round): change the
   **TABLE**.

Save the map (++ctrl+s++) or the whole project — and the map is ready for
this device model for good. Share it with others through
[Issues](https://github.com/Mercurrial/ModbusReader/issues) — there is a
"device register map" template.
