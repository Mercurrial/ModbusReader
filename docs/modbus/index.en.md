---
seo_title: Modbus protocol explained — how it works, RTU vs TCP, registers, function codes
description: The Modbus protocol explained in full — how the request/response exchange works, registers and addresses, function and exception codes, Modbus RTU, ASCII and TCP, RS-485, limits, Modbus vs Profibus and CANopen, and a FAQ.
---

# The Modbus protocol

**Modbus** is an open protocol for exchanging data between a controller or a
PC and industrial devices: sensors, energy meters, temperature controllers,
variable-frequency drives, I/O modules. Modicon created it in 1979 for its
programmable controllers; today it is the most widespread protocol in
industrial automation and building monitoring — simple, free and supported
by almost every vendor.

| Property | Modbus |
|---|---|
| Type | Application-layer request/response protocol |
| Created | 1979, Modicon (now Schneider Electric) |
| Maintained by | Modbus Organization, since 2004 |
| Main variants | [Modbus RTU](rtu.md), Modbus ASCII, [Modbus TCP](tcp.md) |
| Media | RS-485, RS-232, Ethernet |
| Addresses per line | 247 (RTU and ASCII) |
| TCP port | 502; 802 for Modbus/TCP Security |
| Licence | Open, royalty-free |

## How the exchange works { #how-it-works }

Modbus is a **request/response** protocol. One side — the **client**
(historically the **master**) — sends a request; the other — the **server**
(the **slave**) — carries it out and answers. A server never starts an
exchange: if it has news, the client has to ask. So working with Modbus
means **polling**: the master reads the values it needs, round and round.

```text
  Master (PC, PLC, SCADA)
     |  request: "device 5, read registers 0-9"
     v
  ----+-----------+-----------+-----------+----  RS-485 line
      |           |           |           |
   device 1    device 2    device 5    device 7
                              |
     ^  answer: "here are 10 registers" (only device 5 answers)
```

- On a serial line (RS-485) there is **one master** and up to 247 slaves.
  Each request goes to one device by its address 1…247, and only that device
  answers. Address 0 is broadcast: every device takes it, none answers.
- On a network (Modbus TCP) there can be several clients, each with its own
  TCP connection to the device.

In 2020 the Modbus Organization replaced "master/slave" with "client/server"
in its documents. Manuals and device menus still use both — they mean the
same thing.

## Data: four tables { #data-model }

Modbus presents everything a device shows and accepts as four tables:

| Table | Holds | Access | Notation | Example |
|---|---|---|:---:|---|
| Coils | bits | read and write | 0x | Start the pump |
| Discrete inputs | bits | read only | 1x | Door open |
| Input registers | 16-bit words | read only | 3x | Measured current |
| Holding registers | 16-bit words | read and write | 4x | Temperature setpoint |

Each table has up to 65,536 entries with addresses 0…65535. A **register**
is a 16-bit word, and the protocol knows no other data type: vendors spread
FLOATs, 32- and 64-bit integers and strings over several neighbouring
registers — each in their own way. Hence the usual commissioning puzzles:

- **Addresses.** The manual says "register 40001", the frame carries
  address 0. Why, and how to convert — [Tables and addresses](addressing.md).
- **Byte order.** The same FLOAT goes into registers as ABCD, CDAB, BADC or
  DCBA depending on the device — [Data types and byte order](data-types.md).
- **Scaling.** 23.5 °C often travels as the integer 235 with a factor of
  0.1 — [scale and offset](data-types.md#scaling).

What lives in which register of a given device is its **register map** — a
table in the vendor's manual. Without it you can read a device, but not
know what the numbers mean.

## Function codes { #functions }

What to do with the data is set by the **function code** — the second byte
of a frame. The most used:

| Code | Function | What it does |
|:---:|---|---|
| 01 | [Read Coils](functions/01-read-coils.md) | Reads bits (coils) |
| 02 | [Read Discrete Inputs](functions/02-read-discrete-inputs.md) | Reads discrete inputs |
| 03 | [Read Holding Registers](functions/03-read-holding-registers.md) | Reads holding registers — the most common function |
| 04 | [Read Input Registers](functions/04-read-input-registers.md) | Reads input registers |
| 05 | [Write Single Coil](functions/05-write-single-coil.md) | Turns one bit on or off |
| 06 | [Write Single Register](functions/06-write-single-register.md) | Writes one register |
| 15 (0F) | [Write Multiple Coils](functions/15-write-multiple-coils.md) | Writes several bits |
| 16 (10) | [Write Multiple Registers](functions/16-write-multiple-registers.md) | Writes several registers |
| 23 (17) | Read/Write Multiple Registers | Writes and reads in one request |
| 43/14 (2B/0E) | Read Device Identification | Vendor, model, firmware version |

Codes 65–72 and 100–110 are left to vendors for their own functions. The
full reference with request formats is in
[Function and exception codes](functions/index.md).

**How much at once.** One request reads up to 125 registers or 2000 bits and
writes up to 123 registers or 1968 bits. More takes several requests.

## Errors: exceptions { #exceptions }

If a device understood a request but cannot carry it out, it answers with an
**exception**: the function code with its top bit set (03 → 0x83) and an
error code. If it did not understand the request at all (another address, a
bad checksum), it **stays silent**, and the master gets a timeout.

| Code | Name | What it usually means |
|:---:|---|---|
| 01 | Illegal Function | The device does not support this function |
| 02 | Illegal Data Address | No register at that address (or the block runs past the end) |
| 03 | Illegal Data Value | A value or count the device does not accept |
| 04 | Server Device Failure | An internal error in the device |
| 05 | Acknowledge | Accepted, takes long — ask again later |
| 06 | Server Device Busy | The device is busy — retry later |
| 08 | Memory Parity Error | A memory error reading a file record |
| 0A | Gateway Path Unavailable | The gateway cannot reach the network behind it |
| 0B | Gateway Target Device Failed to Respond | The device behind the gateway did not answer |

What to check for each — [Exceptions](functions/index.md#exceptions) and
[Troubleshooting](../troubleshooting.md).

## Modbus variants { #variants }

All variants share the functions and registers — what differs is the
"wrapping": how a frame travels, how the device is addressed and how
integrity is checked.

| Variant | Medium | Frame | Check | Where you meet it |
|---|---|---|---|---|
| [Modbus RTU](rtu.md) | RS-485, RS-232 | binary, edges by silence | CRC16 | The vast majority of devices |
| Modbus ASCII | RS-485, RS-232 | text: `:` … CR LF | LRC | Older devices, modem links |
| [Modbus TCP](tcp.md) | Ethernet | MBAP header + PDU | by TCP | PLCs, gateways, networked devices |
| [RTU over TCP](rtu-over-tcp.md) | Ethernet | a whole RTU frame inside TCP | CRC16 | RS-485 ↔ Ethernet converters |
| Modbus UDP | Ethernet | like TCP, over UDP | none | Rare, outside the official specification |
| Modbus/TCP Security | Ethernet | Modbus TCP inside TLS | TLS | New systems with security requirements |
| Modbus Plus | own bus | proprietary, token passing | — | Legacy Modicon systems |

There are vendor extensions too — **Enron Modbus**, for example, with 32-bit
registers for gas flow computers. They are only partly compatible with
plain Modbus.

### PDU and ADU { #pdu-adu }

The specification splits a frame in two:

- **PDU** (Protocol Data Unit) — the function code and data. The same in
  every variant, at most 253 bytes.
- **ADU** (Application Data Unit) — the PDU plus addressing and checking,
  specific to each variant.

```text
Modbus RTU:  [addr 1 B][  PDU: function + data  ][CRC 2 B]   up to 256 bytes
Modbus TCP:  [MBAP 7 B][  PDU: function + data  ]            up to 260 bytes
```

That is why an RTU ↔ TCP gateway does not look into the data: it takes one
wrapping off and puts the other on.

## Physical layer: RS-485 and Ethernet { #physical }

Modbus is a protocol, not an interface: it says *what* is sent, while the
wires and signal levels belong to the physical interface.

- **RS-485** — the main medium of Modbus RTU. Two lines A and B (a twisted
  pair), half duplex, up to 1200 m at speeds up to ~100 kbit/s, up to 32
  standard unit loads per segment without a repeater. 120 Ω terminators at
  both ends of the line, devices daisy-chained, no long stubs or stars. How
  to connect a PC — [Connecting to a device](../connect.md).
- **RS-232** — point to point, one device per port, up to ~15 m. Found on
  older devices and modems.
- **Ethernet** — for Modbus TCP: an ordinary network, an IP address, port 502.

**Serial settings** must match on the master and every device on the line:
baud rate (usually 9600 or 19200), parity and stop bits (8E1 by the
standard, 8N1 very often in practice). Details in
[Modbus RTU](rtu.md#serial).

## What an exchange looks like { #example }

The master reads two holding registers starting at address 0 from device 1
— function 03:

```text
Request:  01 03 00 00 00 02 C4 0B
Answer:   01 03 04 41 C4 CC CD 3B 67
```

The answer carries 4 data bytes — registers `41C4` and `CCCD`, which
together are the FLOAT 24.6. Byte by byte in [Modbus RTU](rtu.md#example);
decode any frame of your own [online](../tools/crc.md).

## Limits { #limits }

Modbus's simplicity is both its strength and its weakness:

- **Polling only.** A device does not report an event — the master learns
  of it on its next read. The more devices and registers, the less often
  each is polled.
- **No data types or descriptions.** The protocol carries 16-bit words; what
  they mean is only in the device's documentation.
- **No security.** Classic Modbus neither checks who sent a command nor
  encrypts anything. Protection comes from network isolation or
  Modbus/TCP Security.
- **One master per RS-485 line.** Two masters on one line get in each
  other's way.
- **Small packets.** Up to 125 registers per request.

## Modbus vs other protocols { #comparison }

| | Modbus | Profibus DP | CANopen | BACnet | OPC UA |
|---|---|---|---|---|---|
| Where | Everywhere, from meters to PLCs | Factory automation (Siemens) | Machines, drives, vehicles | Building automation | Between systems and to the cloud |
| Medium | RS-485, Ethernet | RS-485 | CAN | RS-485 (MS/TP), Ethernet | Ethernet |
| Data model | Registers and bits | Cyclic blocks described by GSD | Object dictionary | Objects with properties | Typed information model |
| Complexity | Minimal | High | Medium | Medium | High |
| Standard | Open specification, modbus.org | IEC 61158, PI | CiA 301, EN 50325-4 | ASHRAE 135, ISO 16484-5 | IEC 62541 |

Modbus is chosen when mixed devices have to be linked simply and cheaply:
nearly everything speaks it, and commissioning takes a laptop and a USB
adapter. Often Modbus works at the bottom — the device level — and the data
travels on to SCADA or OPC UA through a gateway.

## Where it is used { #usage }

- **Energy metering:** electricity, heat and flow meters.
- **Drives:** variable-frequency drives and soft starters.
- **Controllers and sensors:** temperature, pressure, humidity, level.
- **I/O modules** — digital and analogue signals for PLCs.
- **Solar:** inverters, charge controllers, battery BMS.
- **Buildings:** ventilation, boiler rooms, heating substations, monitoring.
- **Home automation and IoT:** MQTT gateways, Home Assistant, Wiren Board
  controllers.

## Getting started with Modbus { #getting-started }

1. **Find the Modbus section of the device manual**: the default address,
   baud rate, parity and the register map.
2. **Connect:** to RS-485 through a USB-RS-485 adapter (A to A, B to B), to a
   networked device by its IP address. Details —
   [Connecting to a device](../connect.md).
3. **Read one register** from the map, say with function 03. An answer means
   the link works; a timeout — check the wiring and serial settings.
4. **Make sense of the values:** addresses, byte order, scaling.
5. **Describe every register you need** — and poll them in a loop.

## In ModbusReader { #modbusreader }

[ModbusReader](../index.md) is a free program that makes these steps
visible: a register map with names, units and scaling, live trends, an
address [scanner](../guide/scanner.md), a [console](../guide/console.md)
for hand-made frames, a [sniffer](../guide/sniffer.md) for other people's
traffic and a [device emulator](../guide/slave.md). It speaks Modbus RTU and
Modbus TCP, on Windows, Linux and macOS.

[:material-download: Download ModbusReader](../install.md){ .md-button .md-button--primary }
[:material-rocket-launch: Quick start](../quickstart.md){ .md-button }

## FAQ { #faq }

??? question "Is Modbus an interface or a protocol?"
    A protocol. It defines which bytes are sent and what they mean. The
    interface is RS-485, RS-232 or Ethernet: wires, signal levels,
    connectors. "A device with an RS-485 interface and the Modbus RTU
    protocol" names both.

??? question "What is the difference between Modbus RTU and Modbus TCP?"
    The data and functions are the same. RTU runs over a serial line
    (RS-485), the device address is in every frame and CRC16 checks
    integrity. TCP runs over Ethernet: instead of a CRC there is the MBAP
    header with the Unit ID, and TCP itself guarantees delivery. More in
    [Modbus TCP](tcp.md).

??? question "How many devices can one line take?"
    There are 247 addresses. But a standard RS-485 transmitter drives 32
    unit loads; devices with 1/4 or 1/8 unit-load receivers allow 128 or
    256 per segment. Beyond that — a repeater. In practice polling time
    limits it too: the more devices, the less often each is read.

??? question "How fast is Modbus?"
    Modbus RTU usually runs at 9600 or 19200 baud; many devices support
    38400–115200. Polling one register at 9600 baud takes at least 20 ms:
    the request, the silence, the device's reaction time and the answer.
    Modbus TCP is limited by how fast the device answers, not by the network.

??? question "Why is register 40001 read at address 0?"
    "40001" is Modicon notation: the 4 stands for the holding-register table
    and numbering starts at one. The frame carries the zero-based address
    without the prefix. More in [Tables and addresses](addressing.md).

??? question "Do I need a licence to use Modbus?"
    No. The specifications are published free on modbus.org, and there are
    no royalties for using the protocol.

??? question "What does exception 02 mean?"
    The device got the request, but has no register at that address — or the
    requested block runs past the end of its registers. Most often the
    address is off by one or taken from the 3x table instead of 4x. More in
    [Exceptions](functions/index.md#exceptions).

## Reference sections { #reference }

- [Modbus RTU](rtu.md) — the frame, timing, CRC16, serial settings.
- [Modbus TCP](tcp.md) — port 502, the MBAP header, the Unit ID.
- [RTU over TCP and converters](rtu-over-tcp.md) — RS-485 devices over a
  network.
- [Tables and addresses](addressing.md) — 40001, 0x0000 and the off-by-one.
- [Data types and byte order](data-types.md) — FLOAT, LONG, ABCD and CDAB.
- [Function and exception codes](functions/index.md) — every function and
  exception code.
- [Troubleshooting](../troubleshooting.md) — timeouts, CRC errors, odd values.
- [Online tools](../tools/index.md) — CRC calculator, FLOAT converter,
  address conversion.
