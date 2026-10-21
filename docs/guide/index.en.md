---
seo_title: ModbusReader user guide
description: Every page and tool of ModbusReader in order — register map, editor and import, projects, trends, dashboard, console, scanner, sniffer, logger, snapshots, slave emulator, macros and settings.
---

# User guide

The ModbusReader window is laid out like this:

- **Left** — the page rail. **Monitor** at the top: the register map and the
  dashboard. **Tools** below. A green dot next to an item means the tool is
  working in the background (for example, the logger is recording). The rail
  collapses to icons.
- **Top** — the project and the current page, the link settings and
  **Connect** (++f5++).
- **Bottom** — the transaction log, the raw-frame line and the status bar:
  device address, counters, line statistics.

++f1++ (the **Help** button) on any page starts a short tour of that very
page.

## Monitor

<div class="grid cards" markdown>

-   [**Register map**](register-map.md) ++ctrl+1++

    The table of every device register with live values; writing, display
    mode, line statistics.

-   [**Dashboard**](dashboard.md) ++ctrl+6++

    Your own panel of 14 widget kinds, wires between them for automation.

</div>

## Map and project

<div class="grid cards" markdown>

-   [**Map editor and import**](map-editor.md) ++ctrl+2++

    Creating a map, importing from CSV and Excel, scaling and
    enumerations.

-   [**Projects and files**](projects.md)

    What an `.mbproj` holds and how it differs from a `.json` map.

-   [**Trends and watch**](trends.md) ++f6++

    Live register charts and the floating watch window.

</div>

## Tools

<div class="grid cards" markdown>

-   [**Console**](console.md) ++ctrl+3++

    The transaction log full screen and sending raw frames.

-   [**Scanner**](scanner.md) ++ctrl+4++

    Find the devices on a line and the live registers of a device.

-   [**Sniffer**](sniffer.md) ++ctrl+5++

    Passive listening to someone else's traffic.

-   [**Snapshots**](snapshots.md) ++ctrl+7++

    "What changed?" — compare every value with a remembered set.

-   [**Logger**](logger.md) ++ctrl+8++

    Hours-long logging of values to CSV.

-   [**Slave emulator**](slave.md) ++ctrl+9++

    The app answers a master as a device.

-   [**Macros**](macros.md) ++ctrl+m++

    Python scripts for automated checks.

-   [**Settings**](settings.md) ++ctrl+comma++

    Connection, appearance, table, graphs, log, hotkeys.

</div>
