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


def _w(kind, reg_id, title, x, y, w, h, **extra):
    """One dashboard widget, bound to *reg_id* (datatypes.reg_id)."""
    cfg = {"kind": kind, "reg_id": reg_id, "title": title, "name": title,
           "x": x, "y": y, "w": w, "h": h}
    cfg.update(extra)
    return cfg


# A ready-made control panel, 3 rows on a grid that fits the dashboard page
# of a 1440-px window: columns 290 · 570 (or 290 + 127 + 121) · 260.
DASHBOARD = [
    _w("gauge", "0x0000", "Температура", 12, 12, 290, 230,
       unit="°C", vmin=0, vmax=60, ahi=45, reg_type="FLOAT"),
    _w("chart", "0x0000", "Температура", 318, 12, 570, 230,
       unit="°C", vmin=15, vmax=35, reg_type="FLOAT"),
    _w("value", "0x0002", "Уставка", 904, 12, 260, 107,
       unit="°C", reg_type="FLOAT"),
    _w("value", "0x0005", "Мощность нагревателя", 904, 135, 260, 107,
       unit="%", reg_type="UINT16"),
    _w("bar", "0x10000", "Напряжение питания", 12, 258, 290, 130,
       unit="В", vmin=0, vmax=30, reg_type="UINT16"),
    _w("bits", "0x0008", "Слово состояния", 318, 258, 290, 130,
       reg_type="BITS16"),
    _w("led", "0x20000", "Нагреватель", 624, 258, 127, 130,
       thr=0.5, invert=False, reg_type="BOOL"),
    _w("led", "0x30000", "Дверь", 767, 258, 121, 130,
       thr=0.5, invert=False, reg_type="BOOL"),
    _w("value", "0x10001", "Ток датчика", 904, 258, 260, 130,
       unit="мА", reg_type="SHORT"),
    _w("select", "0x0004", "Режим", 12, 404, 290, 115, reg_type="UINT16",
       options=[[0, "Стоп"], [1, "Работа"], [2, "Авария"]]),
    _w("slider", "0x0002", "Уставка", 318, 404, 570, 115,
       unit="°C", vmin=15, vmax=40, step=0.5, live=False, reg_type="FLOAT"),
    _w("toggle", "0x20001", "Вентилятор", 904, 404, 260, 115,
       value_on=1, value_off=0, reg_type="BOOL"),
]
for _i, _cfg in enumerate(DASHBOARD, 1):       # stable ids: a diff stays small
    _cfg["uid"] = f"demo{_i:02d}"


def main():
    import datatypes
    for r in REGISTERS:                    # what the map editor writes
        r.setdefault("length", datatypes.addr_span(r))
    settings = dict(DEFAULT_SETTINGS)
    settings.update({"port": "COM1", "baudrate": "115200", "slave_id": 1})
    path = os.path.join(ROOT, "examples", "demo.mbproj")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    formats.dump_project(path, "Демо-термоконтроллер", settings, REGISTERS,
                         dashboards=[{"name": "Пульт", "widgets": DASHBOARD,
                                      "links": []}])
    print("written:", path)


if __name__ == "__main__":
    main()
