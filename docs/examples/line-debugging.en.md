---
seo_title: Debugging an RS-485 line — timeouts, CRC errors, Modbus exceptions
description: How to find the cause of Modbus RTU link problems — line statistics, the transaction log, scanner and sniffer in ModbusReader; typical cases — the device is silent, answers are corrupted, the link drops under load.
---

# Debugging an RS-485 line

A link that works "now and then" is the nastiest problem on site.
ModbusReader gives three tools to get to the bottom of it: the **line
statistics**, the **transaction log** and the **sniffer**.

## Step 1. Look at the statistics

Connect, let polling run for a minute or two, then click the statistics in the
bottom-right corner.

| Picture | What it means | Where to look |
|---|---|---|
| 0 answers out of N | The device does not hear or does not answer | [Step 2](#silent) |
| 90–99 % answered, some timeouts | The link works but is unreliable | [Step 3](#unreliable) |
| Many CRC errors | Answers arrive corrupted | [Step 3](#unreliable) |
| Exceptions | The link is fine, the requests are the problem | [Step 4](#exceptions) |
| Response time grows | The device is overloaded or slow | Raise the inter-frame delay |

Counters reset on every connect and with **Reset** — reset them after every
change to see its effect.

## Step 2. The device is silent { #silent }

Check in order — simplest first:

1. **Port.** Is it the right COM port? The adapter may have a new number in
   another USB socket.
2. **Device address** in the status bar (`ID: 1`).
3. **Baud rate, parity, stop bits** — as in the device. Unknown — the
   [scanner](../guide/scanner.md#unknown-baud).
4. **A/B polarity.** Swap the wires — harmless, and it helps more often than
   you'd think.
5. **Device power**, and whether Modbus is enabled at all (some devices
   enable the interface in a menu).
6. **Register table.** If the map holds even one register the device knows,
   an answer will come. Check from the [console](../guide/console.md) with
   the simplest request: `01 03 00 00 00 01` — read one register at address
   0. An exception in reply is already a success: the device is on the line.

## Step 3. The link works, with glitches { #unreliable }

**CRC errors** — an answer arrived but was corrupted:

- no **common ground (GND)** between the adapter and the device;
- a long line without 120 Ω **terminators** at the ends;
- the cable is not twisted pair, or runs next to power cables and
  variable-frequency drives;
- **wrong parity**, or a baud rate close to but not the right one;
- a **second master** on the line (a SCADA polling the same devices, say) —
  frames collide. Check with the sniffer.

**Timeouts every so often:**

- the device cannot keep up: raise the **inter-frame delay** (100–200 ms) and
  the **response timeout**;
- a weak signal on a long line: lower the baud rate (115200 → 19200, say);
- a cheap adapter without automatic direction control.

## Step 4. Exceptions { #exceptions }

The device is on the line and refuses particular requests. Click the green
dot next to a register — the log then shows that register's frames — and
check the [exception table](../modbus/functions.md#exceptions):

- **02** — no such address: off-by-one, the wrong table (FC 03 instead of
  04), a FLOAT running past the device's last register;
- **01** — the device does not support the function: the register is in
  another table;
- **03** — an illegal value on write: a setpoint out of range.

## Step 5. Listen to the line with the sniffer

If someone else's master (a SCADA, a controller) works on the line, wire a
**second adapter** in parallel and open the [sniffer](../guide/sniffer.md):

- requests but no answers — the device does not hear, or the address is wrong;
- answers with **BAD CRC** — noise on the line, not a master bug;
- two different masters taking turns — a conflict, frames will collide;
- exceptions — the master asks for something the device does not have.

The sniffer transmits nothing, so attaching it to a working line is safe.

## If nothing helped

Save the transaction log (**Save log…**), take a screenshot of the
statistics and ask in
[Discussions](https://github.com/Mercurrial/ModbusReader/discussions) — with
the device and adapter models and the link settings.
