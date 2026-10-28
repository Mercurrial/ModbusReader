---
seo_title: Modbus RTU over TCP and RS-485 ↔ Ethernet converters (USR-TCP232, Moxa)
description: What Modbus RTU over TCP is, how a converter's transparent mode differs from a Modbus TCP ↔ RTU gateway, how to set up USR-TCP232 and Moxa NPort/MGate, and how to tell which mode a converter is in.
---

# RTU over TCP and converters

To poll an RS-485 device over a network, an **RS-485 ↔ Ethernet converter**
(also called a serial device server or gateway) goes between it and the
computer. It can work in two modes, and the mode decides how you connect to
it.

!!! note "In ModbusReader"
    Click the link settings in the window header and pick **RTU over TCP**:
    the converter's IP address and port, the device address on the line —
    [Connecting over the network](../connect.md#tcp). Not sure which mode the
    converter is in? Press **Test link**: the app tries both and tells you.

## Two converter modes

| | Transparent mode | Modbus TCP ↔ RTU gateway |
|---|---|---|
| What goes over the network | **RTU frames** as they are — with address and CRC | **Modbus TCP frames** with the MBAP header |
| Also called | "RTU over TCP", transparent, TCP Server | Modbus gateway, "Modbus TCP to RTU" |
| What the converter does | moves bytes between the port and TCP | converts MBAP ↔ RTU, computes the CRC |
| Device address | inside the RTU frame | the Unit ID in the MBAP header |
| The master must support | "RTU over TCP" | plain Modbus TCP |
| Port | anything in its settings (often 23, 4001, 8899…) | usually 502 |

**Transparent mode** ("RTU over TCP") is like a long extension cord for
RS-485: the master sends over TCP exactly the bytes that would go into a COM
port, CRC included. Handy when the gateway knows nothing about Modbus or full
compatibility matters, but the master has to support RTU over TCP.

**A Modbus TCP ↔ RTU gateway** turns an RS-485 device into an ordinary Modbus
TCP device: any Modbus TCP master works. The Unit ID in the request becomes
the device address on the RS-485 line.

## How to tell which mode a converter is in

Connect and send a request both ways:

- an answer to a **Modbus TCP** request (`00 01 00 00 00 06 01 03 00 00 00 02`)
  — it is a gateway;
- an answer to a bare **RTU frame** (`01 03 00 00 00 02 C4 0B`) — transparent
  mode. It usually stays silent on a Modbus TCP request: the converter sends
  the MBAP header down the line as it is, and the device does not understand
  it;
- no answer either way — check the baud rate and parity in the converter's
  settings and the device address.

Decode the answer with the [online tool](../tools/crc.md): it recognises both
RTU and Modbus TCP frames.

## Setting up a converter

Whatever the brand, the same things are configured:

1. **Network address** of the converter — in the same subnet as the
   computer.
2. **Work mode** — TCP Server (the computer connects to the converter), and
   the protocol: transparent or Modbus TCP.
3. **Port** — the one you will enter in the master.
4. **Serial port parameters** — baud rate, parity, stop bits — **as in the
   device**. The master does not set them: they do not travel over the
   network.
5. **Timeouts**: the device's response time and the packing (frame)
   interval — the defaults usually do; raise the timeout for slow devices.

### USR-TCP232-410S

Out of the box the converter is at **192.168.0.7**, works as a **TCP
Server** on port **23** and accepts up to 8 clients — that is transparent
mode, "RTU over TCP". To make it a Modbus TCP ↔ RTU gateway, turn on the
**ModbusTCP** conversion in its settings; the port is usually changed to 502
for it. Details are in the [vendor's
manual](https://www.pusr.com/download/M4/USR-TCP232-410S_User_Manual_V1.0.0.pdf).

### Moxa NPort and MGate

**NPort** units are serial device servers: in **TCP Server** mode they work
transparently (data port 4001 by default) — that is "RTU over TCP". **MGate**
units are Modbus gateways: an RS-485 device behind one looks like an ordinary
Modbus TCP device, with the Unit ID as its line address.

## Common problems

- **Connected, the device is silent** — the converter's baud rate or parity
  does not match, wrong device address (Unit ID), A and B swapped on the
  RS-485 side.
- **Every other answer missing** — a short timeout in the converter or the
  master; several masters through one transparent channel get in each
  other's way.
- **The connection drops** — the converter's client limit is exceeded, or it
  closes idle connections; the master must reconnect.

The Modbus TCP protocol in detail is in [Modbus TCP](tcp.md), connecting to
RS-485 in [Connect a device](../connect.md).
