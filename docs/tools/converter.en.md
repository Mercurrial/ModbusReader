---
seo_title: Modbus FLOAT and INT32 to registers converter — ABCD, CDAB, BADC, DCBA
description: Online Modbus value converter — FLOAT, DOUBLE, INT32, UINT32, INT16, INT64 to 16-bit registers and back in every byte order — ABCD (big-endian), CDAB (word swap), BADC (byte swap), DCBA (little-endian).
---

# FLOAT and INT32 ↔ registers converter

Devices send 32- and 64-bit values as several 16-bit registers, and vendors
order the bytes differently. The converter shows a value **in all four
orders at once** — an easy way to see how your device lays out its bytes.

<div class="mbt" markdown>
<label for="mbt-val-type">Type</label>
<select id="mbt-val-type" class="mbt-input">
<option value="FLOAT" selected>FLOAT (32-bit IEEE-754)</option>
<option value="INT32">INT32 / LONG (signed)</option>
<option value="UINT32">UINT32 / DWORD (unsigned)</option>
<option value="INT16">INT16 / SHORT (signed)</option>
<option value="UINT16">UINT16 / WORD (unsigned)</option>
<option value="DOUBLE">DOUBLE (64-bit IEEE-754)</option>
<option value="INT64">INT64 (signed)</option>
<option value="UINT64">UINT64 (unsigned)</option>
</select>

<label for="mbt-val-in">Value → registers</label>
<input id="mbt-val-in" class="mbt-input" type="text" value="24.6" spellcheck="false" autocomplete="off">
<div id="mbt-val-out" class="mbt-out"></div>

<label for="mbt-reg-in">Registers → value</label>
<div class="mbt-row">
<input id="mbt-reg-in" class="mbt-input" type="text" value="41C4 CCCD" spellcheck="false" autocomplete="off">
<select id="mbt-reg-fmt" class="mbt-input mbt-narrow">
<option value="hex" selected>hex</option>
<option value="dec">dec</option>
</select>
</div>
<div id="mbt-reg-out" class="mbt-out"></div>
</div>

Enter the registers in the order they came from the device: the lower
address first.

## What ABCD, CDAB, BADC and DCBA mean

The letters are the value's bytes from most (**A**) to least (**D**)
significant; their order is the order on the wire. The FLOAT **24.6** =
`0x41C4CCCD`:

| Order | Registers | Also called |
|---|---|---|
| **ABCD** | `41C4 CCCD` | big-endian, "standard" |
| **CDAB** | `CCCD 41C4` | word swap (common on PLCs) |
| **BADC** | `C441 CDCC` | byte swap |
| **DCBA** | `CDCC C441` | little-endian |

If a value in a SCADA or program looks "odd" — huge, tiny or negative —
paste the raw registers into the second line: the right order gives a
plausible number. More in [Data types and byte order](../modbus/data-types.md).

## In the app

ModbusReader turns registers into values itself: the type is set in the
register map, the byte order in **Settings → Connection → Codecs**,
separately for 16-bit, 32/64-bit integers and FLOAT/DOUBLE. This converter
computes exactly what the app does.

Other tools: [CRC calculator](crc.md) · [addresses 40001 ↔ 0x0000](address.md).
