---
seo_title: Python macro examples for Modbus — tests, calibration, measurements
description: Ready-made ModbusReader macros — a setpoint sweep that waits for stabilisation, checking registers against a reference, readings into an Excel table, waiting for an event with a timeout, finding device registers without documentation, value statistics.
---

# Macro examples

The macros below are written for the **demo project** (a temperature
controller) — register names come from it. For your device, put your own
names in. Command reference: [Macros](../guide/macros.md).

!!! note "Raw values"
    `read()` returns the value without the map's scaling. In the demo
    project "Heater power" has a scale of 0.1, so below it is multiplied by
    0.1 by hand.

## Readings into a table

Every 5 seconds — a row with every register of the map. After an hour — a
720-row table you can save to Excel.

```python
for i in range(720):
    row = {"#": i, "time": timestamp()}
    row.update(read_all())          # every map register: {name: value}
    record(row)
    wait(5)
```

For long recordings without a macro there is the [logger](../guide/logger.md):
it writes CSV straight to disk.

## Setpoint sweep with stabilisation

Set a setpoint, wait until the temperature is within tolerance, record how
long it took. If it does not get there within 10 minutes — note it and move
on.

```python
SETPOINTS = [20, 25, 30, 35]
TOLERANCE = 0.5          # °C
LIMIT = 600              # s per setpoint

for sp in SETPOINTS:
    write("Temperature setpoint", sp)
    t0 = now()
    reached = False
    while now() - t0 < LIMIT:
        t = read("Temperature")
        if abs(t - sp) <= TOLERANCE:
            reached = True
            break
        wait(2)
    record({"setpoint": sp,
            "temperature": round(t, 2),
            "reached": "yes" if reached else "no",
            "time, s": round(now() - t0)})
    log("setpoint", sp, "done" if reached else "not reached in", LIMIT, "s")
```

## Checking against a reference

Check that the device settings match the reference — after replacing a
device or updating its firmware, for example.

```python
EXPECTED = {
    "Temperature setpoint": 25.0,
    "Mode": 1,
    "Alarm delay": 30,
}

bad = 0
for name, want in EXPECTED.items():
    got = read(name)
    ok = abs(got - want) < 0.01
    bad += 0 if ok else 1
    record({"register": name, "reference": want, "device": got,
            "result": "OK" if ok else "MISMATCH"})
log("mismatches:", bad)
```

## Waiting for an event with a timeout

Turn the heater on and time how long until a discrete input fires (in the
demo — "Door open"). The example shows how to wait for a condition without
hanging forever.

```python
def wait_for(name, value, timeout, step=0.1):
    """Wait until the register equals value. Return the time, or None."""
    t0 = now()
    while now() - t0 < timeout:
        if read(name) == value:
            return now() - t0
        wait(step)
    return None

write("Heater", 1)
dt = wait_for("Door open", 1, timeout=30)
write("Heater", 0)
if dt is None:
    log("the event did not happen within 30 s")
else:
    record({"event": "Door open", "after, s": round(dt, 2)})
```

## Value statistics

A hundred samples — min, max, average and spread. Useful for judging sensor
noise.

```python
values = []
for i in range(100):
    values.append(read("Sensor current"))
    wait(0.2)

avg = sum(values) / len(values)
record({"samples": len(values), "min": min(values), "max": max(values),
        "average": round(avg, 3), "spread": max(values) - min(values)})
```

## Power in engineering units

The map's scale is not applied in a macro — applying it yourself is easy.

```python
for i in range(60):
    raw = read("Heater power")       # 573
    record({"time": timestamp(), "power, %": round(raw * 0.1, 1)})
    wait(1)
```

## Finding registers without documentation

Read addresses 0…99 in a row as `UINT16` and record every one that answered.
These addresses are not in the map, so the type is given explicitly. No
answer or an exception — the address is skipped.

```python
for addr in range(100):
    try:
        v = read(addr, "UINT16")
    except RuntimeError:
        continue
    record({"address": hex(addr), "value": v, "hex": hex(v)})
log("done")
```

Input registers work the same with the prefix: `read("IR " + str(addr), "UINT16")`.
For a quick overview there is also the [scanner](../guide/scanner.md) in
Registers mode.

## Retry on a link glitch

A wrapper that retries a read a few times before giving up — for long tests
on a noisy line.

```python
def read_retry(name, tries=3):
    for k in range(tries):
        try:
            return read(name)
        except RuntimeError:
            log("no answer", name, "attempt", k + 1)
            wait(0.5)
    return None

for i in range(10):
    record({"#": i, "temperature": read_retry("Temperature")})
    wait(1)
```

## A recipe: a sequence of writes

Write several registers step by step with pauses — a start-up sequence, for
instance.

```python
STEPS = [
    ("Mode", 0, 1),                   # stop, wait 1 s
    ("Temperature setpoint", 25, 0.5),
    ("Fan", 1, 0.5),
    ("Mode", 1, 0),                   # run
]
for name, value, pause in STEPS:
    write(name, value)
    log("written", name, "=", value)
    wait(pause)
```
