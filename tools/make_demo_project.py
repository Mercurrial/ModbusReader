# tools/make_demo_project.py
"""Write examples/demo.mbproj — a made-up temperature controller.

A public checkout has no real device map (those stay private), so this is
what a newcomer opens first and what tools/ui_snapshots.py photographs. It
touches every area and the common types, a scaled value and an enum:

    python tools/make_demo_project.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import formats  # noqa: E402
from settings_manager import DEFAULT_SETTINGS  # noqa: E402

REGISTERS = [
    # holding registers (4x)
    {"addr": 0, "type": "FLOAT", "rw": "R", "unit": "°C",
     "name": "Температура", "name_en": "Temperature"},
    {"addr": 2, "type": "FLOAT", "rw": "RW", "unit": "°C",
     "name": "Уставка температуры", "name_en": "Temperature setpoint"},
    {"addr": 4, "type": "UINT16", "rw": "RW",
     "name": "Режим", "name_en": "Mode",
     "enum": {"0": "Стоп", "1": "Работа", "2": "Авария"}},
    {"addr": 5, "type": "UINT16", "rw": "R", "unit": "%", "scale": 0.1,
     "name": "Мощность нагревателя", "name_en": "Heater power"},
    {"addr": 6, "type": "UINT32", "rw": "R", "unit": "ч",
     "name": "Наработка", "name_en": "Operating hours"},
    {"addr": 8, "type": "BITS16", "rw": "R",
     "name": "Слово состояния", "name_en": "Status word"},
    {"addr": 9, "type": "UINT16", "rw": "R",
     "name": "Код ошибки", "name_en": "Error code"},
    {"addr": 10, "type": "UINT16", "rw": "RW", "unit": "с", "default": "30",
     "name": "Задержка аварии", "name_en": "Alarm delay"},
    # input registers (3x)
    {"addr": 0, "area": "input", "type": "UINT16", "rw": "R", "unit": "В",
     "scale": 0.01, "name": "Напряжение питания", "name_en": "Supply voltage"},
    {"addr": 1, "area": "input", "type": "SHORT", "rw": "R", "unit": "мА",
     "name": "Ток датчика", "name_en": "Sensor current"},
    # coils (0x) and discrete inputs (1x)
    {"addr": 0, "area": "coil", "type": "BOOL", "rw": "RW",
     "name": "Нагреватель", "name_en": "Heater"},
    {"addr": 1, "area": "coil", "type": "BOOL", "rw": "RW",
     "name": "Вентилятор", "name_en": "Fan"},
    {"addr": 0, "area": "discrete", "type": "BOOL", "rw": "R",
     "name": "Дверь открыта", "name_en": "Door open"},
]


def main():
    import datatypes
    for r in REGISTERS:                    # what the map editor writes
        r.setdefault("length", datatypes.addr_span(r))
    settings = dict(DEFAULT_SETTINGS)
    settings.update({"port": "COM1", "baudrate": "115200", "slave_id": 1})
    path = os.path.join(ROOT, "examples", "demo.mbproj")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    formats.dump_project(path, "Демо-термоконтроллер", settings, REGISTERS)
    print("written:", path)


if __name__ == "__main__":
    main()
