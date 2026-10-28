---
seo_title: Modbus TCP — port 502, the MBAP header, Unit ID and how it differs from Modbus RTU
description: Modbus TCP in plain words — port 502, the MBAP header (transaction ID, length, Unit ID), what the Unit ID is for and which one to use, how TCP differs from RTU, a real packet decoded and the usual connection errors.
---

# Modbus TCP

**Modbus TCP** is the same Modbus over Ethernet: registers, functions and
exception codes are those of [Modbus RTU](index.md); only the "wrapping"
changes. PLCs, meters, drives with a network card and RS-485 ↔ Ethernet
gateways support it.

!!! note "Modbus TCP in ModbusReader"
    Click the link settings in the window header and pick **Modbus TCP**: IP
    address, port and unit ID — [Connecting over the network](../connect.md#tcp).
    The TCP emulator and finding devices on the network are described there too.

## Port 502

A Modbus TCP device is a **server**: it listens on a TCP port and waits for
connections. The standard port is **502**. The master (client) connects to
the device's IP address and that port and sends requests over the open
connection.

- The port can be changed in the device settings — then the master needs the
  same one.
- The secure variant, **Modbus/TCP Security** (TLS), uses port **802**.
- On Linux and macOS programs without admin rights cannot listen on ports
  below 1024, so simulators often use **1502**.

## The frame: MBAP header + PDU

Unlike RTU, a Modbus TCP frame has **no CRC** (TCP takes care of integrity)
and **no pauses** between frames: the 7-byte **MBAP** header gives the
length.

| Field | Bytes | Meaning |
|---|:---:|---|
| Transaction ID | 2 | Request number; the answer comes back with the same number |
| Protocol ID | 2 | Always `00 00` — Modbus |
| Length | 2 | How many bytes follow: Unit ID + PDU |
| Unit ID | 1 | Device address behind a gateway (see below) |
| PDU | up to 253 | Function code and data — as in RTU |

### Example: reading two registers

Request — read 2 holding registers from address 0, Unit ID 1:

```text
00 01  00 00  00 06  01  03 00 00 00 02
|      |      |      |   +-- PDU: function 03, address 0x0000, count 2
|      |      |      +------ Unit ID: 1
|      |      +------------- length: 6 bytes follow
|      +-------------------- Protocol ID: 0 (Modbus)
+--------------------------- Transaction ID: 1
```

Answer:

```text
00 01  00 00  00 07  01  03 04 41 C4 CC CD
                         +-- function 03, 4 bytes: 0x41C4 0xCCCD (FLOAT 24.6)
```

The same request in Modbus RTU is `01 03 00 00 00 02 C4 0B`: instead of MBAP,
the device address goes first and a CRC goes last. Decode any frame, RTU or
TCP, with the [online tool](../tools/crc.md).

## Unit ID: which one to use

The **Unit ID** is a one-byte field Modbus TCP inherited from the RTU device
address. A device on the network is found by its IP address anyway, so:

- **A device with its own Ethernet** (PLC, meter) usually ignores the Unit
  ID. The specification recommends **255** (`0xFF`), but many devices answer
  only to **1** or to their Modbus address — check the manual.
- **A Modbus TCP ↔ RTU gateway** passes the Unit ID on as the **device
  address on the RS-485 line** behind it: Unit ID 5 is the device with
  address 5.
- If the device is silent with the right IP and port — try Unit ID 1, 255
  and 0.

## How TCP differs from RTU

| | Modbus RTU | Modbus TCP |
|---|---|---|
| Medium | RS-485 / RS-232, twisted pair | Ethernet, Wi-Fi, any IP network |
| Device address | 1–247 in every frame | IP address (+ Unit ID) |
| Frame boundary | 3.5-character silence | length in the MBAP header |
| Error check | CRC16 | TCP checksums |
| Masters on the line | one | several clients at once |
| Requests | strictly one at a time | several in flight, by transaction ID |
| Distance | up to ~1200 m on RS-485 | any — through networks and routers |
| Speed | 9600–115200 baud | 10/100 Mbit/s, the device is the limit |

Registers, [addressing](addressing.md), [data types and byte
order](data-types.md) and [exception codes](functions.md) are exactly the
same over TCP: a device's register map does not depend on how you connect to
it.

## If it does not connect { #not-connecting }

| What you see | Cause |
|---|---|
| **Connection refused** | The IP is right but the port is closed: another port number, or Modbus TCP is disabled in the device |
| **Connect timeout** | Wrong IP, the device is in another subnet, a firewall is in the way |
| Connected, **no answer** | Wrong Unit ID; behind a gateway — wrong RS-485 baud rate or parity |
| An **exception** in the answer | The link is fine; wrong register address or function — see [exception codes](functions.md) |
| An answer that is "not Modbus" | Another protocol on that port — e.g. a converter in [RTU over TCP](rtu-over-tcp.md) mode |

Many devices accept only **one or two connections**: if a SCADA is already
connected, a second master may be refused.

Next: [RTU over TCP and RS-485 ↔ Ethernet converters](rtu-over-tcp.md).
