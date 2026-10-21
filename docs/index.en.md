---
seo_title: ModbusReader — free Modbus RTU tool for Windows, Linux and macOS
description: Free, open-source tool to commission and monitor Modbus RTU (RS-485) devices — register map, live trends, dashboard, bus scanner, sniffer, Python macros and a Modbus slave simulator. Guides, examples and protocol basics.
hide:
  - navigation
  - toc
---

<div class="mr-hero" markdown>

# A free Modbus RTU tool

<p class="mr-lead">ModbusReader commissions, polls and monitors Modbus RTU devices
over RS-485: a register map with names and units, live trends, a dashboard,
a bus scanner, a sniffer, macros and a device emulator (slave).</p>

[:material-download: Download for Windows](https://github.com/Mercurrial/ModbusReader/releases/latest/download/ModbusReader-Setup.exe){ .md-button .md-button--primary }
[:material-rocket-launch: Quick start](quickstart.md){ .md-button }
[:fontawesome-brands-github: GitHub](https://github.com/Mercurrial/ModbusReader){ .md-button }

<p class="mr-note">Windows 10 / 11 · Linux · macOS · free · open source (GPL-3.0) ·
English and Russian UI</p>

<div class="mr-shot" markdown>
![ModbusReader main window: Modbus register map, live trends and a decoded traffic log](images/en/main.png)
</div>

</div>

## Getting started

<div class="grid cards" markdown>

-   :material-download-circle:{ .lg .middle } **Install**

    ---

    Installer and portable build for Windows, an AppImage for Linux, an
    app for macOS.

    [:octicons-arrow-right-24: Install](install.md)

-   :material-rocket-launch:{ .lg .middle } **Quick start**

    ---

    The demo project, your first register map and first connection — in
    five minutes.

    [:octicons-arrow-right-24: Start](quickstart.md)

-   :material-cable-data:{ .lg .middle } **Connect a device**

    ---

    USB-to-RS-485 adapter, A/B wiring, termination, baud rate and parity.

    [:octicons-arrow-right-24: Connect](connect.md)

-   :material-school:{ .lg .middle } **Modbus basics**

    ---

    The RTU frame, addresses 40001 vs 0x0000, FLOAT byte order, function
    and exception codes.

    [:octicons-arrow-right-24: Learn](modbus/index.md)

</div>

## What it does

<div class="grid cards" markdown>

-   **Register map**

    ---

    Every register of the device in one table — names, units, scaling,
    enumerations. Holding, input, coils and discrete inputs; 11 numeric types
    from BOOL to DOUBLE plus strings. Double-click to write.

    [:octicons-arrow-right-24: Register map](guide/register-map.md)

-   **Trends and watch**

    ---

    Any register on a live chart in one click; a floating watch window
    that stays on top of everything.

    [:octicons-arrow-right-24: Trends](guide/trends.md)

-   **Dashboard**

    ---

    14 widget kinds and wires between them: an operator panel and simple
    automation with no code.

    [:octicons-arrow-right-24: Dashboard](guide/dashboard.md)

-   **Modbus slave simulator**

    ---

    The app answers a master as a device would — test a SCADA, HMI or PLC
    without the real hardware.

    [:octicons-arrow-right-24: Slave emulator](guide/slave.md)

-   **RS-485 sniffer**

    ---

    Listens to someone else's traffic through a second adapter without
    sending a byte: requests, answers, exceptions, CRC errors.

    [:octicons-arrow-right-24: Sniffer](guide/sniffer.md)

-   **Python macros**

    ---

    Scripts read and write registers by name, wait for conditions and
    build a results table you can save as CSV or Excel.

    [:octicons-arrow-right-24: Macros](guide/macros.md)

-   **Scanner, console, logger, snapshots**

    ---

    Find the devices on a line, send raw frames with automatic CRC, log for
    hours to CSV and compare "before vs after".

    [:octicons-arrow-right-24: All tools](guide/index.md)

-   **Examples**

    ---

    Ready-made macros and scenarios: testing a SCADA, importing a map from
    a datasheet, dashboard automation, debugging a line.

    [:octicons-arrow-right-24: Examples](examples/index.md)

</div>

## Why ModbusReader

- **Free with no limits** — no trial period, no register or runtime limit.
  The code is open under GPL-3.0.
- **Master, slave simulator and sniffer in one app** — jobs that usually
  take several different tools.
- **A register map like the device datasheet** — names, units and
  enumerations instead of bare addresses; import from Excel and CSV.
- **English and Russian UI**, dark and light themes, updates installed only
  when you say so.

The current version is **{{ app_version }}**. Release notes are in the
[CHANGELOG](https://github.com/Mercurrial/ModbusReader/blob/main/CHANGELOG.md).
Questions go to [Discussions](https://github.com/Mercurrial/ModbusReader/discussions),
bugs to [Issues](https://github.com/Mercurrial/ModbusReader/issues).
