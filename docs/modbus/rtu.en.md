---
seo_title: Modbus RTU — frame format, CRC16, 3.5-character silence, examples
description: Modbus RTU explained — the frame (address, function code, data, CRC16), the 1.5 and 3.5-character timing, 8E1 and 8N1 serial settings, the broadcast address and exceptions. With real request and response frames decoded.
---

# Modbus RTU

**Modbus RTU** is the serial-line variant of the [Modbus protocol](index.md),
usually over RS-485. Data travels in binary, and every frame is protected by
a CRC16 checksum. It is the most common kind of Modbus: energy meters,
sensors, controllers and variable-frequency drives all talk it.

## Master and slaves

A line has one **master** (in the current terminology, the client) and up to
247 **slave** devices (servers). Only the master speaks: it sends a request
to one particular device, and only that device answers. Devices never start
an exchange themselves.

| Address | Meaning |
|:---:|---|
| 0 | Broadcast: every device takes the request, none answers |
| 1…247 | Device addresses |
| 248…255 | Reserved |

Broadcast only makes sense for writes (setting the clock on every device,
say) — nothing can be read that way, since nobody answers.

## The Modbus RTU frame { #frame }

Every request and answer is one frame:

| Device address | Function code | Data | CRC16 |
|:---:|:---:|:---:|:---:|
| 1 byte | 1 byte | 0–252 bytes | 2 bytes |

- **Address** — who the request is for; in the answer the device puts its
  own address.
- **Function code** — what to do: read holding registers (03), write one
  register (06) and so on. The list is in [Functions and errors](functions/index.md).
- **Data** — the first register's address, the count, the values; what is
  there depends on the function.
- **CRC16** — the checksum of all the bytes before it, **low byte first**. A
  device silently drops a frame with a bad CRC. Compute the CRC of any frame
  with the [CRC calculator](../tools/crc.md).

A whole frame is at most **256 bytes**. That is where the per-request limits
come from: at most 125 registers in one read and 123 in one write.

The function code plus data (no address, no CRC) is called the **PDU** — it
is the same in RTU, ASCII and TCP. The whole frame with address and CRC is
the **ADU**.

## Timing: 1.5 and 3.5 characters { #timing }

An RTU frame has no start or end byte — silence on the line marks its edges:

- **Between frames — at least 3.5 characters** (t3.5). This silence tells a
  receiver the frame is over.
- **Inside a frame — at most 1.5 characters** (t1.5) between bytes. A longer
  gap makes the frame invalid.

A character on the line is 11 bits: start, 8 data bits, parity (or a second
stop bit) and stop. Hence the times:

| Baud rate | Character | t1.5 | t3.5 |
|---:|---:|---:|---:|
| 2400 | 4.58 ms | 6.88 ms | 16.04 ms |
| 4800 | 2.29 ms | 3.44 ms | 8.02 ms |
| 9600 | 1.15 ms | 1.72 ms | 4.01 ms |
| 19200 | 0.57 ms | 0.86 ms | 2.01 ms |
| above 19200 | — | 0.75 ms | 1.75 ms |

Above 19200 baud the standard fixes the gaps instead of scaling them with
the speed — otherwise a simple microcontroller could not time them.

!!! tip "Timing and a PC"
    USB adapters and the operating system hand received bytes to a program
    in batches and with a delay, so a master on a PC cannot time t1.5 to the
    millisecond. PC programs usually find the end of an answer from its
    length — known from its first bytes — and from a silence well beyond
    3.5 characters. ModbusReader does both, so a slow device that pauses
    inside its answer does not confuse it.

## Serial settings { #serial }

For the master and a device to understand each other, these must match:

- **Baud rate** — most often 9600 or 19200; the standard requires every
  device to support both, with 19200 as the default.
- **Character format** — 8 data bits, parity and stop bits. The standard's
  default is **8E1** (even parity, 1 stop bit); without parity it is **8N2**.
  In practice many devices ship with **8N1**, and most masters cope.
- **Device address** — unique on the line.

If any of them differs the device stays silent — to the master that is a
[timeout](../troubleshooting.md#timeout). The [scanner](../guide/scanner.md)
finds an unknown device's address; for the baud rate, see
[if the baud rate is unknown](../guide/scanner.md#unknown-baud).

## Example: reading two registers { #example }

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

The two registers `41C4 CCCD` are the FLOAT **24.6** in ABCD order (see
[Data types and byte order](data-types.md)).

### Writing one register

Write 100 (`0x0064`) to register 1 of device 1 — function 06:

```text
01 06 00 01 00 64 D9 E1
```

The device answers with an exact copy of the request — that is the
confirmation of the write.

### An error answer

If a device cannot carry out a request it answers with an **exception**: the
function code with its top bit set (`0x03` → `0x83`) and an error code:

```text
01 83 02 C0 F1
|  |  |  +-+-+
|  |  |    +-- CRC16
|  |  +------- exception 02: illegal data address
|  +---------- 0x83 = function 03 + error flag
+------------- device address: 1
```

All exception codes and what to do about them are in
[Functions and errors](functions/index.md#exceptions).

## RTU, ASCII and TCP

| | Modbus RTU | Modbus ASCII | Modbus TCP |
|---|---|---|---|
| Medium | RS-485, RS-232 | RS-485, RS-232 | Ethernet |
| Encoding | binary | text (hex characters) | binary |
| Frame edges | 3.5-character silence | `:` and CR LF | length in the header |
| Check | CRC16 | LRC | none (TCP does it) |
| Device address | in every frame | in every frame | Unit ID in the MBAP header |

All three share the same functions and registers — only the "wrapping"
differs. How Modbus TCP works — port 502, the MBAP header, the Unit ID — is
in [Modbus TCP](tcp.md); polling RS-485 devices over a network is in
[RTU over TCP and converters](rtu-over-tcp.md).

## In ModbusReader

ModbusReader is a Modbus RTU master over any COM port or USB-RS-485
adapter, and over [Modbus TCP](tcp.md) too. Every frame, decoded field by
field, is in the transaction log at the bottom of the window; any frame can
be sent by hand from the [console](../guide/console.md) — the app computes
the CRC. As the [emulator](../guide/slave.md) the app becomes a slave
device itself, and the [sniffer](../guide/sniffer.md) listens to someone
else's traffic without taking part.

## Next

- [Tables and addresses](addressing.md) — why register 40001 is address 0.
- [Data types and byte order](data-types.md) — FLOAT, LONG and "swapped"
  words.
- [Function and exception codes](functions/index.md) — 03, 06, 16 and what
  exception 02 means.
- [The Modbus protocol](index.md) — an overview of the whole protocol.
