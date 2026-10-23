---
seo_title: What is Modbus RTU — frame, address, function code, CRC
description: The Modbus RTU protocol in plain words — master and slave devices, the frame (address, function code, data, CRC16), 3.5-character silence, the broadcast address, differences from Modbus TCP. With a real frame decoded.
---

# What is Modbus RTU

**Modbus** is a protocol for exchanging data between a controller or a PC
and devices: sensors, controllers, variable-frequency drives, meters. It
dates from 1979 and is still the most widespread protocol in industrial
automation: simple, open and supported by almost every vendor.

**Modbus RTU** is the variant for serial lines (usually RS-485): data travels
in binary, and every frame is protected by a CRC16 checksum. This is what
ModbusReader works with.

## Master and slaves

A line has one **master** (client) and up to 247 **slave** devices (servers).
Only the master speaks: it sends a request to one particular device, and
only that device answers. Devices never start an exchange themselves.

- In normal mode ModbusReader is the **master**: it polls a device using the
  register map.
- As the [emulator](../guide/slave.md) it is a **slave**: it answers another
  master as a device would.
- As the [sniffer](../guide/sniffer.md) it is neither: it only listens.

## Device data — registers

Everything a device shows and accepts lives in four tables:

| Table | Holds | Access | Example |
|---|---|---|---|
| Coils (0x) | Bits | read and write | Turn the fan on |
| Discrete inputs (1x) | Bits | read only | Door open |
| Input registers (3x) | 16-bit words | read only | Measured current |
| Holding registers (4x) | 16-bit words | read and write | Temperature setpoint |

Every register is 16 bits. Bigger numbers (32-bit integers, FLOAT) take two
or four neighbouring registers. More in [Tables and addresses](addressing.md)
and [Data types and byte order](data-types.md).

## The Modbus RTU frame

Every request and answer is one frame:

| Device address | Function code | Data | CRC16 |
|:---:|:---:|:---:|:---:|
| 1 byte | 1 byte | 0–252 bytes | 2 bytes |

- **Address** — 1…247; 0 is broadcast (writes only, devices don't answer).
- **Function code** — what to do: read holding registers (03), write one
  register (06) and so on. The list is in [Functions and errors](functions.md).
- **CRC16** — the checksum, low byte first. A device silently drops a frame
  with a bad CRC. Compute the CRC of any frame with the
  [CRC calculator](../tools/crc.md).

Frames are separated by **at least 3.5 characters of silence** on the line —
that is how a receiver knows a frame has ended. At 9600 baud that is about
4 ms; above 19200 baud the standard fixes it at 1.75 ms.

### Example: reading two registers

The master asks device 1 to read 2 holding registers starting at address 0:

```text
01 03 00 00 00 02 C4 0B
|  |  +-+-+ +-+-+ +-+-+
|  |    |     |     +-- CRC16
|  |    |     +-------- register count: 2
|  |    +-------------- start address: 0x0000
|  +------------------- function 03: read holding registers
+---------------------- device address: 1
```

The device answers:

```text
01 03 04 41 C4 CC CD 3B 67
|  |  |  +----+----+ +-+-+
|  |  |       |        +-- CRC16
|  |  |       +----------- 4 data bytes: 0x41C4, 0xCCCD
|  |  +------------------- byte count: 4
|  +---------------------- function 03
+------------------------- device address: 1
```

The two registers `41C4 CCCD` are the FLOAT **24.6** in ABCD order. If a
device cannot carry out a request it answers with an **exception**: the
function code with its top bit set (`0x83`) and an error code — for example,
`01 83 02 C0 F1` means "illegal data address".

In ModbusReader this decoding is visible in the transaction log at the
bottom of the window, and any frame can be sent by hand from the
[console](../guide/console.md) — the app computes the CRC.

## RTU, ASCII and TCP

| | Modbus RTU | Modbus ASCII | Modbus TCP |
|---|---|---|---|
| Medium | RS-485, RS-232 | RS-485, RS-232 | Ethernet |
| Encoding | binary | text (hex characters) | binary |
| Check | CRC16 | LRC | none (TCP does it) |
| Device address | in every frame | in every frame | Unit ID in the MBAP header |

All three share the same functions and registers — only the "wrapping"
differs. ModbusReader works with **Modbus RTU** over a serial port. How
Modbus TCP works — port 502, the MBAP header, the Unit ID — is in
[Modbus TCP](tcp.md); polling RS-485 devices over a network is in
[RTU over TCP and converters](rtu-over-tcp.md).

## Next

- [Tables and addresses](addressing.md) — why register 40001 is address 0.
- [Data types and byte order](data-types.md) — FLOAT, LONG and "swapped"
  words.
- [Function and exception codes](functions.md) — 03, 06, 16 and what
  exception 02 means.
