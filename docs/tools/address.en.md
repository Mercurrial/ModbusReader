---
seo_title: Modbus address converter 40001 ↔ 0x0000 online — holding, input, coils
description: Online Modbus register address converter — Modicon 40001, 30001, 10001 notation to the zero-based protocol address and back, hex and decimal, one-based number, read and write functions for every table.
---

# Addresses 40001 ↔ 0x0000

Type an address the way the device datasheet writes it — `40001`, `30010`,
`0x0010`, `10h` or `16`. A five-digit address from 10001 up, or a six-digit
one, is read as Modicon notation by itself. Anything else — `16`, `0x10`,
`10h` — is the zero-based protocol address; pick its table.

<div class="mbt" markdown>
<label for="mbt-addr-in">Address</label>
<div class="mbt-row">
<input id="mbt-addr-in" class="mbt-input" type="text" value="40001" spellcheck="false" autocomplete="off">
<select id="mbt-addr-table" class="mbt-input mbt-narrow">
<option value="holding" selected>Holding (4x)</option>
<option value="input">Input (3x)</option>
<option value="coil">Coils (0x)</option>
<option value="discrete">Discrete (1x)</option>
</select>
</div>
<div id="mbt-addr-out" class="mbt-out"></div>
</div>

## Why 40001 is address 0

In the Modbus frame itself the address is **zero-based** and carries no
table: the function code picks the table. Modicon notation adds the table as
the first digit and counts registers **from one**:

| Written | Table | Address in the frame |
|---|---|---|
| `00001` | coils | 0 |
| `10001` | discrete inputs | 0 |
| `30001` | input registers | 0 |
| `40001` | holding registers | 0 |
| `40100` | holding registers | 99 |
| `400001` | holding registers (six-digit form) | 0 |

Hence the most common mistake — **off by one**: the device answers, but with
the wrong value. More in [Tables and addresses](../modbus/addressing.md).

## In the app

ModbusReader shows addresses zero-based in hex with a table prefix: `0x0000`
— holding, `IR 0x0000` — input, `CO 0x0000` — coil, `DI 0x0000` — discrete
input. [Importing a map from Excel](../guide/map-editor.md#import) has an
explicit address format choice (zero-based, one-based or 4x).

Other tools: [CRC calculator](crc.md) · [FLOAT and INT32 converter](converter.md).
