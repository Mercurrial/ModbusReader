---
seo_title: Modbus function codes and exception codes — 01, 02, 03, 04, 06, 16
description: Modbus function reference — reading coils, discrete inputs, holding and input registers, writing one or many registers. Exception codes 01–0B — what "illegal function", "illegal data address" and "device busy" mean and what to check.
---

# Function and exception codes

## Function codes

The function code in the second byte of a frame tells the device what to do.

| Code | Hex | Function | Table |
|:---:|:---:|---|---|
| 1 | `01` | Read Coils | Coils |
| 2 | `02` | Read Discrete Inputs | Discrete inputs |
| 3 | `03` | Read Holding Registers | Holding |
| 4 | `04` | Read Input Registers | Input |
| 5 | `05` | Write Single Coil | Coils |
| 6 | `06` | Write Single Register | Holding |
| 15 | `0F` | Write Multiple Coils | Coils |
| 16 | `10` | Write Multiple Registers | Holding |
| 8 | `08` | Diagnostics | — |
| 22 | `16` | Mask Write Register | Holding |
| 23 | `17` | Read/Write Multiple Registers | Holding |

Function 05 writes `FF 00` to turn a coil on and `00 00` to turn it off.

### Which functions ModbusReader uses

| Mode | Functions |
|---|---|
| Polling (master) | read — 01, 02, 03, 04; write — 05 (coils) and 06 (registers) |
| [Emulator](../guide/slave.md) | answers 01, 02, 03, 04, 05, 06, 15, 16; anything else gets exception 01 |
| [Sniffer](../guide/sniffer.md) | decodes 01–06, 08, 15, 16, 22, 23; shows the rest as bytes |
| [Console](../guide/console.md) | any frame you type |

!!! note "Writing 32-bit values"
    The master writes FLOAT, LONG and other multi-register values **one
    word at a time with function 06**, one after another with a pause in
    between. Most devices accept this. If your device only accepts such
    values as a whole with function 16, send the frame from the
    [console](../guide/console.md), for example:
    `01 10 00 02 00 02 04 41 C8 00 00` — write FLOAT 25.0 to registers
    0x0002–0x0003 of device 1 (the console adds the CRC).

## Exceptions { #exceptions }

If a device received a frame with a valid CRC but cannot carry out the
request, it answers with an **exception**: the function code with its top
bit set (`03` → `83`, `06` → `86`) and a one-byte error code.

```text
01 83 02 C0 F1    device 1, function 03, exception 02 — illegal data address
```

| Code | Name | Meaning | What to check |
|:---:|---|---|---|
| `01` | Illegal Function | The device does not support this function | The register's table: maybe FC 04 instead of FC 03 |
| `02` | Illegal Data Address | No such address (or the range runs past the end) | Off-by-one, hex/dec, the table, FLOAT/string length |
| `03` | Illegal Data Value | Bad value or count | Setpoint range, data type, writing a read-only register |
| `04` | Slave Device Failure | Internal device error | Device state, documentation |
| `05` | Acknowledge | Accepted, takes a long time | Repeat later |
| `06` | Slave Device Busy | The device is busy | Raise the inter-frame delay |
| `08` | Memory Parity Error | Device memory error | Device documentation |
| `0A` | Gateway Path Unavailable | The gateway found no path | Gateway settings |
| `0B` | Gateway Target Failed to Respond | The device behind the gateway is silent | Address and link behind the gateway |

An exception is good news: **the link works**, the device hears you and
answers. The problem is the request, not the wires. No answer at all is a
[timeout](../troubleshooting.md#timeout).

### Where ModbusReader shows exceptions

- In the transaction log — an error line with the decoded frame.
- In the line statistics (bottom right) — the **Modbus exceptions** counter.
- In the [scanner](../guide/scanner.md) a device that answered with an
  exception is marked **Alive (exception)**: it is on the line, it just did
  not serve register 0.
- In the [sniffer](../guide/sniffer.md) exception frames are highlighted.

## No answer and CRC errors

Not every problem is an exception:

| What you see | Cause |
|---|---|
| **Timeout** — no answer | Wrong port, baud rate, parity or device address; A/B swapped; device off |
| **CRC error** — answer corrupted | Noise, no common ground or terminator, wrong parity, two masters on the line |
| **Exception** — device refused | The address, function or value does not fit |

Every case is covered in [Troubleshooting](../troubleshooting.md).
