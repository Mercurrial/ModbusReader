---
seo_title: Modbus bus scanner — find devices and registers on an RS-485 line
description: How to find Modbus RTU devices on a line when the address is unknown, and which registers a device answers — the ModbusReader scanner, Devices and Registers modes, what "Alive (exception)" means, how to find the baud rate.
---

# Scanner

The **Scanner** (++ctrl+4++) answers two questions: *who is on the line* and
*which addresses a device answers*. It works through the open connection —
press **Connect** (++f5++) first. Map polling carries on during the scan.

![Scanner: found devices with their response times](../images/en/scanner.png)

## Modes

**Devices** — sweeps the device addresses (Slave ID) in the range 1…247.
Each one is sent a read of one holding register at address 0. A device counts
as found if it answered:

- **Responds** — returned data;
- **Alive (exception)** — answered with a Modbus error. That is a **hit**
  too: the device is on the line and decoded the request, it just has no
  register 0. Read it at the addresses from its documentation.

**Registers** — sweeps holding register addresses on **one** device (its
address is set alongside). Every address that answered is listed with its
raw value — a way to find a device's live registers with no documentation.

Every hit shows its response time in milliseconds. At the end — a summary:
"Found 5 of 32 · 6.4 s". The scan runs in the background; press the button
again to stop it.

## Scan speed

A silent address costs a full **response timeout** (**Settings → Connection
→ Response timeout**, 1000 ms by default). Sweeping all 247 addresses with a
1 s timeout takes about four minutes. To speed it up:

- narrow the range if you roughly know the address;
- lower the timeout to 200–300 ms — most devices answer within 10–50 ms.
  Remember to set it back for normal work.

## If the baud rate is unknown { #unknown-baud }

The scanner searches at one baud rate and parity — the ones in the settings.
If the device parameters are unknown, go through them in turn: start with
**9600 8N1**, **19200 8N1**, **9600 8E1**, **19200 8E1**, then 38400 and
115200 — reconnect for each (++f5++ twice) and run a device scan over a
narrow range (say 1…10). Most devices ship with address 1.

CRC errors in the line statistics while you search mean the baud rate is
close but wrong, or the parity is wrong.
