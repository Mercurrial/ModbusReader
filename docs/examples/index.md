---
seo_title: Примеры — макросы и сценарии работы с Modbus RTU
description: Готовые примеры для ModbusReader — макросы на Python для проверок и калибровки, проверка SCADA эмулятором Modbus Slave, импорт карты регистров из паспорта прибора, автоматика на дашборде, отладка линии RS-485 сниффером.
---

# Примеры

Все примеры можно повторить на **демо-проекте** — без прибора, с
эмулятором на виртуальном COM-порту (см. [Проверка SCADA эмулятором](test-scada.md)).

<div class="grid cards" markdown>

-   :material-language-python:{ .lg .middle } [**Примеры макросов**](macros.md)

    ---

    Перебор уставок с ожиданием стабилизации, сверка с эталоном, замеры в
    таблицу, ожидание события с таймаутом, поиск регистров без
    документации.

-   :material-monitor-dashboard:{ .lg .middle } [**Проверка SCADA эмулятором**](test-scada.md)

    ---

    ModbusReader притворяется прибором: отладка SCADA, панели или ПЛК без
    железа, в том числе на одном компьютере через com0com.

-   :material-file-excel:{ .lg .middle } [**Карта из паспорта прибора**](datasheet-import.md)

    ---

    Таблица регистров из PDF или Excel → карта ModbusReader за пару минут,
    без перепечатки и сдвига адресов на единицу.

-   :material-transit-connection-variant:{ .lg .middle } [**Автоматика на дашборде**](dashboard-automation.md)

    ---

    Таймер → условие → кнопка: включить вентилятор при перегреве без
    единой строчки кода.

-   :material-sine-wave:{ .lg .middle } [**Отладка линии RS-485**](line-debugging.md)

    ---

    Таймауты, ошибки CRC, исключения: как найти причину по статистике,
    журналу и снифферу.

</div>

Есть свой удачный сценарий или макрос? Поделитесь в
[Discussions](https://github.com/Mercurrial/ModbusReader/discussions) — лучшие
попадут сюда.
