---
seo_title: ModbusReader — бесплатная программа для Modbus RTU и RS-485
description: Бесплатная программа для наладки и опроса приборов по Modbus RTU (RS-485) — карта регистров, графики, дашборд, сканер, сниффер, макросы на Python и эмулятор Modbus Slave. Гайды, примеры и основы протокола.
hide:
  - navigation
  - toc
---

<div class="mr-hero" markdown>

# Бесплатная программа для Modbus RTU

<p class="mr-lead">ModbusReader — наладка, опрос и мониторинг приборов по Modbus RTU
через RS-485: карта регистров с именами и единицами, графики в реальном времени,
дашборд, сканер, сниффер, макросы и эмулятор прибора (Slave).</p>

[:material-download: Скачать для Windows](https://github.com/Mercurrial/ModbusReader/releases/latest/download/ModbusReader-Setup.exe){ #mr-download .md-button .md-button--primary data-linux-href="https://github.com/Mercurrial/ModbusReader/releases/latest/download/ModbusReader-x86_64.AppImage" data-linux-label="Скачать для Linux" data-mac-href="https://github.com/Mercurrial/ModbusReader/releases/latest/download/ModbusReader-macOS-arm64.zip" data-mac-label="Скачать для macOS" data-mobile-href="install/" data-mobile-label="Как установить на компьютер" }
[:material-rocket-launch: Быстрый старт](quickstart.md){ .md-button }
[:fontawesome-brands-github: GitHub](https://github.com/Mercurrial/ModbusReader){ .md-button }

<p class="mr-note">Другие системы: <a href="https://github.com/Mercurrial/ModbusReader/releases/latest/download/ModbusReader-Setup.exe">Windows 10/11</a> · <a href="https://github.com/Mercurrial/ModbusReader/releases/latest/download/ModbusReader-x86_64.AppImage">Linux (AppImage)</a> · <a href="https://github.com/Mercurrial/ModbusReader/releases/latest/download/ModbusReader-macOS-arm64.zip">macOS (Apple Silicon)</a> · <a href="install/">как установить</a><br>
бесплатно · открытый код (GPL-3.0) · русский и английский интерфейс</p>

<div class="mr-shot" markdown>
![Главное окно ModbusReader: карта регистров Modbus, живые графики и журнал обмена с разбором кадров](images/main.png)
</div>

</div>

## С чего начать

<div class="grid cards" markdown>

-   :material-download-circle:{ .lg .middle } **Установка**

    ---

    Установщик и портативная версия для Windows, AppImage для Linux,
    сборка для macOS.

    [:octicons-arrow-right-24: Установить](install.md)

-   :material-rocket-launch:{ .lg .middle } **Быстрый старт**

    ---

    Демо-проект, первая карта регистров и первое подключение — за пять минут.

    [:octicons-arrow-right-24: Начать](quickstart.md)

-   :material-cable-data:{ .lg .middle } **Подключение к прибору**

    ---

    Адаптер USB-RS-485, проводка A/B, терминатор, скорость и чётность.

    [:octicons-arrow-right-24: Подключить](connect.md)

-   :material-school:{ .lg .middle } **Основы Modbus**

    ---

    Кадр RTU, адреса 40001 и 0x0000, порядок байт FLOAT, коды функций и ошибок.

    [:octicons-arrow-right-24: Разобраться](modbus/index.md)

</div>

## Что умеет программа

<div class="grid cards" markdown>

-   **Карта регистров**

    ---

    Все регистры прибора в одной таблице — имена, единицы, масштаб,
    перечисления. Holding, input, coils и discrete inputs; 11 числовых типов
    от BOOL до DOUBLE и строки. Запись — двойным щелчком.

    [:octicons-arrow-right-24: Карта регистров](guide/register-map.md)

-   **Графики и наблюдение**

    ---

    Любой регистр — на живой график одним щелчком; плавающее окно
    наблюдения поверх всех окон.

    [:octicons-arrow-right-24: Графики](guide/trends.md)

-   **Дашборд**

    ---

    14 видов виджетов и провода между ними: пульт оператора и простая
    автоматика без программирования.

    [:octicons-arrow-right-24: Дашборд](guide/dashboard.md)

-   **Эмулятор Modbus Slave**

    ---

    Программа отвечает мастеру как прибор — проверяйте SCADA, панель или
    ПЛК без реального железа.

    [:octicons-arrow-right-24: Эмулятор](guide/slave.md)

-   **Сниффер RS-485**

    ---

    Слушает чужой обмен вторым адаптером, ничего не передавая:
    запросы, ответы, исключения, сбои CRC.

    [:octicons-arrow-right-24: Сниффер](guide/sniffer.md)

-   **Макросы на Python**

    ---

    Скрипты читают и пишут регистры по именам, ждут условий и собирают
    таблицу результатов в CSV или Excel.

    [:octicons-arrow-right-24: Макросы](guide/macros.md)

-   **Сканер, консоль, логгер, снимки**

    ---

    Поиск приборов на линии, отправка сырых кадров с автоматическим CRC,
    многочасовая запись в CSV и сравнение «было — стало».

    [:octicons-arrow-right-24: Все инструменты](guide/index.md)

-   **Примеры**

    ---

    Готовые макросы и сценарии: проверка SCADA, импорт карты из паспорта
    прибора, автоматика на дашборде, отладка линии.

    [:octicons-arrow-right-24: Примеры](examples/index.md)

</div>

## Онлайн-инструменты

<div class="grid cards" markdown>

-   :material-shield-check:{ .lg .middle } [**Калькулятор CRC**](tools/crc.md)

    CRC16 Modbus и расшифровка любого кадра.

-   :material-swap-horizontal:{ .lg .middle } [**FLOAT ↔ регистры**](tools/converter.md)

    Значения во всех порядках байт: ABCD, CDAB, BADC, DCBA.

-   :material-map-marker:{ .lg .middle } [**Адреса 40001 ↔ 0x0000**](tools/address.md)

    Нотация Modicon и адрес протокола с нуля.

</div>

## Почему ModbusReader

- **Бесплатно и без ограничений** — нет пробного периода, лимита регистров или
  времени работы. Код открыт под GPL-3.0.
- **Мастер, эмулятор и сниффер в одной программе** — то, для чего обычно
  ставят несколько разных утилит.
- **Карта регистров как в паспорте прибора** — имена, единицы и перечисления
  вместо голых адресов; импорт из Excel и CSV.
- **Русский и английский интерфейс**, тёмная и светлая темы, автообновление
  с вашего подтверждения.

Текущая версия — **{{ app_version }}**. История изменений —
в [CHANGELOG](https://github.com/Mercurrial/ModbusReader/blob/main/CHANGELOG.md).
Вопросы — в [Discussions](https://github.com/Mercurrial/ModbusReader/discussions),
ошибки — в [Issues](https://github.com/Mercurrial/ModbusReader/issues).

## Частые вопросы

??? question "Это действительно бесплатно?"
    Да. Нет пробного периода, ограничений по числу регистров или времени
    работы, регистрации и рекламы. Код открыт под GPL-3.0 — программу можно
    использовать и в работе.

??? question "Чем ModbusReader отличается от Modbus Poll и Modbus Slave?"
    Мастер, эмулятор прибора и сниффер собраны в одной бесплатной программе;
    карта регистров хранит имена, единицы и перечисления; есть дашборд и
    макросы на Python. Чего нет — Modbus TCP и ASCII. Подробное сравнение —
    [бесплатная альтернатива Modbus Poll](compare.md).

??? question "Поддерживается ли Modbus TCP?"
    Пока нет: ModbusReader работает с **Modbus RTU** по последовательному
    порту — RS-485 или RS-232 через USB-адаптер.

??? question "Какой адаптер нужен?"
    Любой USB-RS-485 адаптер, который система видит как COM-порт: на
    микросхемах FTDI, CP210x или CH340. См. [Подключение к прибору](connect.md).

??? question "Можно ли попробовать без прибора?"
    Да. При первом запуске открывается демо-проект, а вторая копия
    программы в режиме [эмулятора](guide/slave.md) на паре виртуальных
    COM-портов «оживит» его. См. [Проверка SCADA эмулятором](examples/test-scada.md).

??? question "На каких системах работает?"
    Windows 10 (1809+) и 11 — установщик и портативная версия; Linux —
    AppImage (Ubuntu 22.04+ и аналоги); macOS 12+ на Apple Silicon.
    См. [Установка](install.md).

??? question "Почему FLOAT показывает огромное или отрицательное число?"
    Не тот порядок байт: производители раскладывают 32-битные значения
    по-разному. Проверьте регистры в [конвертере](tools/converter.md) и
    выберите порядок в **Настройки → Подключение → Кодеки**. См.
    [Типы данных и порядок байт](modbus/data-types.md).

??? question "Где взять карту регистров прибора?"
    В паспорте или руководстве прибора — таблица регистров импортируется из
    Excel или CSV за пару минут. См. [Карта из паспорта прибора](examples/datasheet-import.md).
