---
seo_title: Quick start — your first connection to a Modbus RTU device
description: Five steps from install to live values — the demo project, a register map, link settings, connecting, reading and writing registers in ModbusReader.
---

# Quick start

Five steps from the first launch to live values from a device.

## 1. Look at the demo project

On first launch the **demo project** opens straight away — a made-up
temperature controller with a 13-register map and a ready-made dashboard —
along with a short tour of the interface. Reopen the tour any time with
**Help** or ++f1++: on every page it explains that page.

![The main window with the demo project: register table, trends and the traffic log](images/en/main.png)

On the left is the page rail: **Monitor** at the top (the register map and
the dashboard), **Tools** below. Top right are the link settings and
**Connect**. At the bottom are the transaction log and the raw-frame line.

To get back to the demo project, use **Demo project** on the empty map
screen: the app puts its own copy into `Documents\ModbusReader`.

## 2. Open or create a register map

The map describes the device registers: addresses, names, data types,
units. Without it the app has nothing to poll. Options:

- **Open project** (++ctrl+o++) — an `.mbproj` file holding the map, the
  link settings and the dashboards together.
- **Open map** (++ctrl+shift+o++) — a standalone `.json` with just the
  register list.
- **Import from a spreadsheet** — CSV or Excel from the device datasheet.
  See the [map from a datasheet](examples/datasheet-import.md) example.
- **Create map** — by hand in the [map editor](guide/map-editor.md).

## 3. Set the link parameters

Click the link chip in the header (`COM1 · 115200 · 8N1 · ID 1`) — it opens
**Settings → Connection**:

- **Port** — the adapter's COM port (`/dev/ttyUSB0` on Linux,
  `/dev/cu.usbserial-…` on macOS);
- **Baud rate**, **Parity**, **Stop bits** — as configured in the device.

Press **Save**. The **device address** (Slave ID, 1–247) is set at the
bottom of the window, in the status bar: click `ID: 1`, type the address and
press ++enter++ — it applies at once, even while polling.

Every parameter must match the device, otherwise it simply does not
answer. If you don't know the device settings, find it with the
[scanner](guide/scanner.md). Adapters and wiring are covered in
[Connect a device](connect.md).

## 4. Connect

Press **Connect** or ++f5++. The app opens the port and starts polling every
register of the map in a loop (the period is **Settings → Connection → Poll
period**, 500 ms by default).

- A green dot next to a register — a value has arrived since connecting.
- Bottom right — line statistics: sent, received, errors, response time.
  Click for details.
- At the bottom — the transaction log: every frame in hex, decoded.

If no values appear, open the log and see [Troubleshooting](troubleshooting.md):
timeouts, CRC errors and exceptions are covered there.

## 5. Read and write

- **Write:** click the **New value** cell of an RW register, type a number
  and press ++enter++ (or ++f2++ on the selected row).
- **Chart:** right-click a row → **Add to live chart**.
- **Watch:** right-click → **Add to watch**; the window is ++f6++.
- **Display:** right-click → **View as** — decimal, hexadecimal or binary.

Save everything as one file — **Save project** (++ctrl+s++). Next time the
app opens it by itself.

## No device at hand

To bring the demo map to life without hardware, run a second copy of
ModbusReader as the [slave emulator](guide/slave.md) on a pair of virtual
COM ports (for example, [com0com](https://com0com.sourceforge.net/)).
Step by step: [Testing a SCADA with the emulator](examples/test-scada.md).

## Next

- [Modbus basics](modbus/index.md) — if 40001 addresses, byte order and
  function codes still sound mysterious.
- [User guide](guide/index.md) — every page of the app in order.
- [Examples](examples/index.md) — ready-made macros and scenarios.
