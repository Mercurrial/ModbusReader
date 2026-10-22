---
seo_title: Перевод адресов Modbus 40001 ↔ 0x0000 онлайн — holding, input, coils
description: Онлайн-перевод адресов регистров Modbus — нотация Modicon 40001, 30001, 10001 в адрес протокола с нуля и обратно, hex и dec, номер с единицы, функции чтения и записи для каждой таблицы.
---

# Адреса 40001 ↔ 0x0000

Введите адрес так, как он написан в паспорте прибора, — `40001`, `30010`,
`0x0010`, `10h` или `16`. Пятизначный адрес от 10001 и шестизначный
программа поймёт как нотацию Modicon сама. Остальное — `16`, `0x10`, `10h` —
считается адресом протокола с нуля; для него выберите таблицу.

<div class="mbt" markdown>
<label for="mbt-addr-in">Адрес</label>
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

## Почему 40001 — это адрес 0

В самом кадре Modbus адрес считается **с нуля** и не содержит таблицы:
таблицу задаёт код функции. Нотация Modicon дописывает таблицу первой
цифрой и считает регистры **с единицы**:

| Запись | Таблица | Адрес в кадре |
|---|---|---|
| `00001` | coils | 0 |
| `10001` | discrete inputs | 0 |
| `30001` | input registers | 0 |
| `40001` | holding registers | 0 |
| `40100` | holding registers | 99 |
| `400001` | holding registers (шестизначная запись) | 0 |

Отсюда самая частая ошибка — **сдвиг на единицу**: прибор отвечает, но не тем
значением. Подробно — в разделе [Области и адреса](../modbus/addressing.md).

## В программе

ModbusReader показывает адреса с нуля в hex с приставкой таблицы:
`0x0000` — holding, `IR 0x0000` — input, `CO 0x0000` — coil, `DI 0x0000` —
discrete input. При [импорте карты из Excel](../guide/map-editor.md#import)
формат адреса (с нуля, с единицы или 4x) выбирается явно.

Другие инструменты: [калькулятор CRC](crc.md) ·
[конвертер FLOAT и INT32](converter.md).
