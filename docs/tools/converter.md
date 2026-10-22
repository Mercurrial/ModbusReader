---
seo_title: Конвертер Modbus FLOAT и INT32 в регистры — ABCD, CDAB, BADC, DCBA
description: Онлайн-конвертер значений Modbus — FLOAT, DOUBLE, INT32, UINT32, INT16, INT64 в 16-битные регистры и обратно во всех порядках байт — ABCD (big-endian), CDAB (word swap), BADC (byte swap), DCBA (little-endian).
---

# Конвертер FLOAT и INT32 ↔ регистры

Прибор передаёт 32-битные и 64-битные значения несколькими 16-битными
регистрами, и порядок байт у производителей разный. Конвертер показывает
значение **во всех четырёх порядках сразу** — так легко понять, как
раскладывает байты ваш прибор.

<div class="mbt" markdown>
<label for="mbt-val-type">Тип</label>
<select id="mbt-val-type" class="mbt-input">
<option value="FLOAT" selected>FLOAT (32 бита, IEEE-754)</option>
<option value="INT32">INT32 / LONG (со знаком)</option>
<option value="UINT32">UINT32 / DWORD (без знака)</option>
<option value="INT16">INT16 / SHORT (со знаком)</option>
<option value="UINT16">UINT16 / WORD (без знака)</option>
<option value="DOUBLE">DOUBLE (64 бита, IEEE-754)</option>
<option value="INT64">INT64 (со знаком)</option>
<option value="UINT64">UINT64 (без знака)</option>
</select>

<label for="mbt-val-in">Значение → регистры</label>
<input id="mbt-val-in" class="mbt-input" type="text" value="24.6" spellcheck="false" autocomplete="off">
<div id="mbt-val-out" class="mbt-out"></div>

<label for="mbt-reg-in">Регистры → значение</label>
<div class="mbt-row">
<input id="mbt-reg-in" class="mbt-input" type="text" value="41C4 CCCD" spellcheck="false" autocomplete="off">
<select id="mbt-reg-fmt" class="mbt-input mbt-narrow">
<option value="hex" selected>hex</option>
<option value="dec">dec</option>
</select>
</div>
<div id="mbt-reg-out" class="mbt-out"></div>
</div>

Регистры вводите в том порядке, в каком они пришли от прибора: сначала
регистр с меньшим адресом.

## Что значат ABCD, CDAB, BADC, DCBA

Буквы — байты значения от старшего (**A**) к младшему (**D**); порядок букв —
как они идут по линии. Число FLOAT **24.6** = `0x41C4CCCD`:

| Порядок | Регистры | Другие названия |
|---|---|---|
| **ABCD** | `41C4 CCCD` | big-endian, «стандартный» |
| **CDAB** | `CCCD 41C4` | word swap — переставлены слова (часто у ПЛК) |
| **BADC** | `C441 CDCC` | byte swap — переставлены байты в словах |
| **DCBA** | `CDCC C441` | little-endian |

Если значение в SCADA или программе «странное» — огромное, крошечное или
отрицательное, — вставьте сырые регистры во вторую строку: правильный
порядок даст правдоподобное число. Подробнее — в разделе
[Типы данных и порядок байт](../modbus/data-types.md).

## В программе

ModbusReader переводит регистры в значения сам: тип задаётся в карте
регистров, порядок байт — в **Настройки → Подключение → Кодеки**, отдельно
для 16-битных, целых 32/64-битных и FLOAT/DOUBLE. Этот конвертер считает
ровно так же, как программа.

Другие инструменты: [калькулятор CRC](crc.md) ·
[адреса 40001 ↔ 0x0000](address.md).
