---
seo_title: Участие в проекте и поддержка ModbusReader
description: Как помочь ModbusReader — сообщить об ошибке, предложить улучшение, поделиться картой регистров прибора, задать вопрос, поддержать разработку, собрать программу из исходников.
---

# Участие и поддержка

ModbusReader бесплатен и останется бесплатным. Помочь проекту можно
по-разному — и не только деньгами.

## Вопросы

Как подключить прибор, что значит сообщение, как сделать нужную проверку —
спрашивайте в [Discussions](https://github.com/Mercurrial/ModbusReader/discussions).
Ответы остаются там и помогают следующим.

## Ошибки и предложения

[Issues](https://github.com/Mercurrial/ModbusReader/issues/new/choose) — для
ошибок и идей. Хорошее сообщение об ошибке:

- версия программы (**Настройки → О программе**) и система;
- что делали, что ожидали и что получилось;
- журнал обмена (**«Сохранить журнал…»**) и файл `modbusreader_errors.log`,
  если программа упала.

Уязвимости — не в открытые Issues, а по правилам
[SECURITY.md](https://github.com/Mercurrial/ModbusReader/blob/main/SECURITY.md).

## Карты регистров приборов

Сделали карту для своего прибора? Поделитесь через шаблон **«Карта регистров
прибора»** в [Issues](https://github.com/Mercurrial/ModbusReader/issues/new/choose) —
приложите `.json` карты и модель прибора. Так у следующего наладчика карта
будет готова с первой минуты.

## Звезда и рассказ

⭐ на [GitHub](https://github.com/Mercurrial/ModbusReader) помогает другим найти
программу. Если она пригодилась — расскажите коллегам или на форуме по
АСУ ТП.

## Поддержать разработку

Если программа экономит вам время — можно поддержать разработку:
**[dalink.to/mercurrial](https://dalink.to/mercurrial)**.

## Разработка

Код — на [GitHub](https://github.com/Mercurrial/ModbusReader), Python 3.10+ и
PyQt6.

```bash
git clone https://github.com/Mercurrial/ModbusReader.git
cd ModbusReader
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt -r requirements-dev.txt
.venv\Scripts\python -m pytest
.venv\Scripts\python main.py
```

Около 900 тестов работают без экрана. Устройство кода — в
[ARCHITECTURE.md](https://github.com/Mercurrial/ModbusReader/blob/main/ARCHITECTURE.md),
история изменений — в
[CHANGELOG.md](https://github.com/Mercurrial/ModbusReader/blob/main/CHANGELOG.md).

Этот сайт тоже в репозитории — Markdown в папке `docs/`. Нашли ошибку на
странице — нажмите ✏️ вверху страницы и предложите правку.

## Лицензия

[GNU GPL v3](https://github.com/Mercurrial/ModbusReader/blob/main/LICENSE) или
более поздняя: программу можно использовать, в том числе в работе,
изучать, изменять и распространять. Изменённые версии, которые вы
распространяете, тоже должны быть открыты под GPL. Программа
предоставляется без каких-либо гарантий.
