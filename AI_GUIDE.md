# AI guide: maps, dashboards and macros

For an AI (or a person) who has to produce ModbusReader content quickly:
a **register map from a device description** (a PDF, a datasheet, a table),
a **dashboard**, or a **macro**. Everything here is what the code accepts
today; the code wins if they ever disagree (`core/formats.py`,
`core/datatypes.py`, `core/dash_model.py`, `core/macro_engine.py`).

Always finish with the check — it reads the file the way the app does:

```
python tools/check_project.py Projects/<name>/<name>.mbproj
```

Working examples to copy from: `tools/make_demo_project.py` (a full
project generator — map, scaled value, enum, every area, a dashboard).

---

## 1. The project file

A project is one JSON file, `*.mbproj`: connection + register map +
dashboards. Write it with the library, not by hand-assembling the envelope:

```python
import sys; sys.path.insert(0, r"<repo>")
from core import formats
from app.settings_manager import DEFAULT_SETTINGS

settings = dict(DEFAULT_SETTINGS, transport="serial", port="COM7",
                baudrate="115200", parity="None (N)", stopbits="1", slave_id=32)
formats.dump_project(path, "Plant name", settings, REGISTERS,
                     dashboards=[{"name": "Пульт", "widgets": W, "links": L}])
formats.load_project(path)          # reads back: raises if something is off
```

Where it goes: `Projects/<name>/<name>.mbproj` (the Projects folder sits
beside the installed program; from the sources it is
`Documents/ModbusReader`). The app keeps the project's macros in
`Projects/<name>/macros/` and the result tables in `Projects/<name>/results/`.

Connection keys (`formats.PROJECT_CONNECTION_KEYS`) and their values:

| Key | Values |
|---|---|
| `transport` | `"serial"`, `"tcp"` (Modbus TCP), `"rtu_tcp"` (RTU over TCP) |
| `port` | `"COM7"` (serial) |
| `baudrate` | string: `"9600"` … `"230400"` |
| `parity` | `"None (N)"`, `"Even (E)"`, `"Odd (O)"` |
| `stopbits` | `"1"`, `"2"` |
| `slave_id` | int 1–247 (TCP unit id 0–255). Documents often give it in hex: `0x20` → `32` |
| `host`, `tcp_port` | TCP only: `"192.168.0.10"`, `502` |
| `poll_rate`, `timeout`, `interframe_delay` | ms (defaults 500, 1000, 50) |
| `order_short` | `"AB"`, `"BA"` |
| `order_long`, `order_float` | `"ABCD"`, `"BADC"`, `"CDAB"`, `"DCBA"` (defaults `ABCD`, `BADC`) |

---

## 2. A register map from a description

One register = one dict. Only `addr`, `name`, `type`, `rw` are required.

```python
{"addr": 3, "type": "UINT16", "rw": "RW", "unit": "°C", "default": "270",
 "name": "Температура нагрева", "name_en": "HeatTemp",
 "comment": "100–500 °C; не ниже температуры предв. нагрева"}
```

| Field | Meaning |
|---|---|
| `addr` | Address **on the wire**, 0-based, 0…65535 |
| `area` | Modbus table: omit for holding (FC 03/06/16); `"input"` (FC 04), `"coil"` (FC 01/05), `"discrete"` (FC 02). Coil/discrete force `type: "BOOL"`; input/discrete force `rw: "R"` |
| `type` | See the type table below |
| `rw` | `"R"`, `"W"`, `"RW"` |
| `name` | Name in the UI language (Russian here). **Unique, case-insensitive** — macros find registers by it |
| `name_en` | English name; put the document's own identifier here (`preHeatTemp`) — a macro may use it too |
| `unit` | `"°C"`, `"с"`, `"%"`… |
| `scale`, `offset` | Engineering value = raw × scale + offset. «°C × 10» → `scale: 0.1` |
| `enum` | `{"0": "Стоп", "1": "Пуск"}` — raw value → label (keys are strings) |
| `default` | Factory value, as a string |
| `comment` | Range, meaning of bits, conditions — whatever the operator needs |
| `length` | Only for variable types (`STRING`, `ARR`…): number of addresses |

Types (`core/datatypes.py`, the span is in 16-bit addresses):

| Type | Span | Use for |
|---|---|---|
| `UINT16` / `SHORT` | 1 | unsigned 0…65535 / signed −32768…32767 |
| `BITS16` | 1 | a status/error word — 16 flags (shown bit by bit) |
| `BCD16` | 1 | 4 BCD digits |
| `BOOL` | 1 | coils and discrete inputs |
| `UINT32` / `LONG` | 2 | 32-bit, **high word first** |
| `LONG1` | 2 | 32-bit, **low word first** |
| `FLOAT` | 2 | IEEE-754 single; byte order from `order_float` |
| `FLOAT1`, `FLOAT2` | 2 | single with other byte orders |
| `BCD32` | 2 | 8 BCD digits |
| `INT64`, `DOUBLE` | 4 | 64-bit integer / IEEE-754 double |
| `STRING` | `length` | 2 characters per address |

Reading a document — what to look for:

1. **Function codes / tables.** "Read Input Registers (04)", "3x", `30001`
   → `area: "input"`. "Holding (03)", "4x", `40001` → holding. `0x`/`1x`
   → coils / discrete inputs.
2. **Address base.** `40001`-style numbers are 1-based and carry the table:
   `40001` → holding `addr 0`, `30010` → input `addr 9`. Hex addresses
   (`0x0003`) are usually already on the wire. If unsure, the doc's own
   request examples (`01 03 00 03 00 01 …`) show the wire address.
3. **Size and order.** A 32-bit value over two registers: which word comes
   first decides `UINT32`/`LONG` (high first) vs `LONG1` (low first); a
   float's byte order goes to the project's `order_float`.
4. **Scaling.** "value × 10", "0.1 °C resolution" → `scale: 0.1`, `unit`.
5. **Codes.** Status/mode values → `enum`. Bitfields → `BITS16` with the bit
   meanings in `comment` (one `enum` cannot describe bits).
6. **Access.** Read-only parameters → `rw: "R"` even in the holding table;
   commands → `"RW"` (or `"W"` if reading back is meaningless).
7. **Limits, defaults, conditions** ("not below X, else exception 03") →
   `comment` and `default`. Reserved registers: include them only if they are
   documented; mark them "резерв".
8. Two registers must never overlap (`FLOAT` at 0 takes 0 and 1); names must
   be unique. The checker reports both.

---

## 3. A dashboard

A project holds a list of boards: `{"name": str, "widgets": [...], "links": [...]}`.

Every widget:

```python
{"uid": "u001", "kind": "gauge", "title": "CH1", "x": 12, "y": 48, "w": 280, "h": 210,
 "reg_id": "0x10000", "reg_type": "UINT16", "name": "Температура CH1",
 "unit": "°C", "vmin": 0, "vmax": 600, "ahi": 520}
```

* `uid` — unique within the board (any short string).
* `reg_id` — the register's **key** in hex: `"0x%04X" % (area_code << 16 | addr)`,
  area codes holding 0, input 1, coil 2, discrete 3. So holding 7 → `"0x0007"`,
  input 4 → `"0x10004"`, coil 3 → `"0x20003"`. In Python:
  `datatypes.reg_id(datatypes.reg_key(reg))`.
* `reg_type`, `name` — copies of the register's type and name.
* `x, y, w, h` — logical pixels (zoom 100 %).
* Dashboards work in **engineering units**: `scale`/`offset` are applied to
  what is shown and undone on writes, so `vmin`/`vmax`/thresholds/values are
  in °C, not in raw counts.

Kinds (`core/dash_model.py`) and their own keys:

| Kind | Binds | Keys | Notes |
|---|---|---|---|
| `value` | any | `unit`, `alo`, `ahi` | big number + mini trend; `alo`/`ahi` alarm limits or `null` |
| `led` | any | `thr`, `invert` | lit when value > `thr` |
| `bar` | any | `vmin`, `vmax`, `alo`, `ahi` | |
| `gauge` | any | `vmin`, `vmax`, `alo`, `ahi`, `unit` | |
| `bits` | `BITS16` | — | 16 bits of a status word |
| `chart` | any | `vmin`, `vmax` | trend on the board |
| `button` | writable | `value_on` | writes `value_on` when pressed |
| `toggle` | writable | `value_on`, `value_off` | |
| `input` | writable | — | operator types a value, Enter writes it |
| `slider` | writable | `vmin`, `vmax`, `step`, `live` | `live: true` writes while dragging |
| `select` | writable | `options: [[value, label], …]` | values are raw enum keys; copy them from the register's `enum` |
| `timer` | — | `interval` (ms ≥ 50), `autostart` | pulses its wires |
| `gate` | any | `cond` (`gt ge lt le eq ne`), `cmp` | passes a pulse only if the condition holds; unknown value → blocks |
| `label` | — | `title` is the text | section headings |

"Writable" = `rw` contains `W` and the area is holding or coil.
Minimum sizes: most kinds 120×70; `label` 120×40; `bits`/`chart` 180×90/110;
`slider`/`select` height ≥ 95; `input` height ≥ 90.

Wires (`links`): `{"from": uid, "to": uid}`, from a widget with an output to
one with an input — timers, controls and gates. A pulse makes the target do
its action: a control writes its value (from an `input`/`slider`/`select` the
pulse carries that widget's value), a timer starts/stops, a gate passes the
pulse on or stops it. Example: timer (1000 ms) → gate (Температура > 30) →
button «Вентилятор: 1».

Layout that reads well in a 1280-px window: content width 1156 starting at
`x = 12`; four columns of 280 with 12-px gaps (`x = 12, 304, 596, 888`) or two
of 572 (`x = 12, 596`); a full-width `label` (h 40) above each group; 8-px
vertical gaps. Typical heights: value 100–110, gauge 210, chart 180,
controls 100–115. Group by meaning (measurement / control / parameters /
service), one board per job. Put controls next to what they control, and
never more than one control per register on a board unless they do different
things (Пуск/Стоп buttons on one register are fine).

---

## 4. A macro

A macro is ordinary Python run in a worker thread with a small API. **No
`import`, no `__dunder__` names, no file or network access** — it reads and
writes the device and fills a results table; the operator exports the table
(CSV / XLSX) into `Projects/<name>/results/`.

| Call | Does |
|---|---|
| `read(key)` / `read(key, "FLOAT")` | read one register |
| `write(key, value)` / `write(key, value, "UINT16")` | write one register |
| `reg(key)` | handle: `r.read()`, `r.write(v)`, `r.value` |
| `read_all()` | `{name: value}` for the whole map |
| `wait(s)` / `sleep(s)` | pause (fractions fine); Stop interrupts it |
| `record(col=value, …)` or `record({...})` | add a row to the results table; columns appear in first-seen order |
| `log(...)` / `print(...)` | a line in the macro log |
| `now()` | seconds as float (for timing) |
| `timestamp()` | `"YYYY-MM-DD HH:MM:SS"` |
| builtins | `abs min max round sum len range enumerate zip map filter sorted int float str bool list dict tuple set divmod pow any all isinstance …` |

`key` is a register name (Russian or `name_en`, any case), a holding address
(`10`, `0x0A`, `"0x0A"`), or another table: `"IR 0x01"`, `"CO 5"`, `"DI 3"`.
An address that is not in the map needs its type.

**Values are raw**: no `scale`, `offset` or `enum`. Apply the scale yourself
(`read("Температура CH2") * 0.1`).

Each `read` is one Modbus exchange queued behind the app's own polling, so
budget time per read (≈5–15 ms at 115200 baud, a timeout when the device is
silent). For fast sampling, keep the map's polling light or set a longer
`poll_rate`.

Patterns:

```python
# Sample at a fixed period without drift (here 50 ms) until Stop.
period = 0.05
t0 = now()
n = 0
while True:
    record(t=round(now() - t0, 3), CH2=read("Температура CH2") * 0.1)
    n += 1
    wait(max(0, t0 + n * period - now()))
```

```python
# Step a setpoint and log the response.
for sp in range(100, 301, 50):
    write("Уставка", sp)
    t0 = now()
    while now() - t0 < 30:
        record(time=timestamp(), setpoint=sp, temp=read("Температура"))
        wait(1)
```

```python
# Wait for a condition, with a timeout.
write("Нагрев", 1)
t0 = now()
while read("Состояние") != 5:
    if now() - t0 > 120:
        log("не дождались завершения"); break
    wait(0.5)
write("Нагрев", 0)
```

Save macros as `Projects/<name>/macros/<what>.py`; the macro page opens and
saves there (Ctrl+S in the editor). `tools/check_project.py` parses them and
checks every register name they use.

---

## 5. Checklist

- [ ] Addresses are wire addresses (0-based), each in the right `area`.
- [ ] 32-bit and float word/byte order matches the document.
- [ ] Scaled values have `scale` and `unit`; codes have `enum`; status words are `BITS16`.
- [ ] Names unique; `name_en` holds the document's identifier.
- [ ] Every bound widget's `reg_id` is computed from `area` + `addr`; controls only on writable registers.
- [ ] Ranges (`vmin`/`vmax`, thresholds) in engineering units.
- [ ] Macros scale raw values themselves and use names that exist.
- [ ] `python tools/check_project.py <file>` prints OK.
