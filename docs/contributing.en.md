---
seo_title: Contributing to and supporting ModbusReader
description: How to help ModbusReader — report a bug, suggest an improvement, share a device register map, ask a question, support development, build the app from source.
---

# Contributing and support

ModbusReader is free and will stay free. There are many ways to help — and
not only with money.

## Questions

How to connect a device, what a message means, how to do a certain test —
ask in [Discussions](https://github.com/Mercurrial/ModbusReader/discussions).
The answers stay there and help the next person.

## Bugs and ideas

[Issues](https://github.com/Mercurrial/ModbusReader/issues/new/choose) are for
bugs and ideas. A good bug report has:

- the app version (**Settings → About**) and the system;
- what you did, what you expected and what happened;
- the transaction log (**Save log…**) and `modbusreader_errors.log` if the app
  crashed.

Vulnerabilities go not to public Issues but by the rules in
[SECURITY.md](https://github.com/Mercurrial/ModbusReader/blob/main/SECURITY.md).

## Device register maps

Made a map for your device? Share it with the **device register map**
template in [Issues](https://github.com/Mercurrial/ModbusReader/issues/new/choose) —
attach the map's `.json` and the device model. Then the next engineer has the
map ready from the first minute.

## A star and a word

A ⭐ on [GitHub](https://github.com/Mercurrial/ModbusReader) helps others find
the app. If it helped you, tell your colleagues or an automation forum.

## Support development

If the app saves you time, you can support its development:
**[dalink.to/mercurrial](https://dalink.to/mercurrial)**.

## Development

The code is on [GitHub](https://github.com/Mercurrial/ModbusReader), Python
3.10+ and PyQt6.

```bash
git clone https://github.com/Mercurrial/ModbusReader.git
cd ModbusReader
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt -r requirements-dev.txt
.venv\Scripts\python -m pytest
.venv\Scripts\python main.py
```

About 900 tests run without a screen. The code layout is in
[ARCHITECTURE.md](https://github.com/Mercurrial/ModbusReader/blob/main/ARCHITECTURE.md),
the history in
[CHANGELOG.md](https://github.com/Mercurrial/ModbusReader/blob/main/CHANGELOG.md).

This site lives in the repository too — Markdown in the `docs/` folder. Spot
a mistake on a page — press ✏️ at the top of the page and suggest a fix.

## Licence

[GNU GPL v3](https://github.com/Mercurrial/ModbusReader/blob/main/LICENSE) or
later: you may use the app, including at work, study, change and distribute
it. Changed versions you distribute must be open under the GPL too. The app
comes with no warranty of any kind.
