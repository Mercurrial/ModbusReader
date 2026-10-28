---
seo_title: ModbusReader — free Modbus RTU and Modbus TCP tool for Windows, Linux and macOS
description: Free, open-source tool to commission and monitor Modbus RTU (RS-485) and Modbus TCP devices — register map, live trends, dashboard, bus scanner, sniffer, Python macros and a Modbus slave simulator. Guides, examples and protocol basics.
hide:
  - navigation
  - toc
---

<div class="mr-hero" markdown>

# A free Modbus RTU and TCP tool

<p class="mr-lead">ModbusReader commissions, polls and monitors Modbus RTU (RS-485)
and Modbus TCP devices: a register map with names and units, live trends, a
dashboard, a scanner, a sniffer, macros and a device emulator (slave).</p>

[:material-download: Download for Windows](https://github.com/Mercurrial/ModbusReader/releases/latest/download/ModbusReader-Setup.exe){ #mr-download .md-button .md-button--primary data-linux-href="https://github.com/Mercurrial/ModbusReader/releases/latest/download/ModbusReader-x86_64.AppImage" data-linux-label="Download for Linux" data-mac-href="https://github.com/Mercurrial/ModbusReader/releases/latest/download/ModbusReader-macOS-arm64.zip" data-mac-label="Download for macOS" data-mobile-href="install/" data-mobile-label="How to install on a computer" }
[:material-rocket-launch: Quick start](quickstart.md){ .md-button }
[:fontawesome-brands-github: GitHub](https://github.com/Mercurrial/ModbusReader){ .md-button }

<p class="mr-note">Other systems: <a href="https://github.com/Mercurrial/ModbusReader/releases/latest/download/ModbusReader-Setup.exe">Windows 10/11</a> · <a href="https://github.com/Mercurrial/ModbusReader/releases/latest/download/ModbusReader-x86_64.AppImage">Linux (AppImage)</a> · <a href="https://github.com/Mercurrial/ModbusReader/releases/latest/download/ModbusReader-macOS-arm64.zip">macOS (Apple Silicon)</a> · <a href="install/">how to install</a><br>
free · open source (GPL-3.0) · English and Russian UI</p>

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

    A USB-to-RS-485 adapter and A/B wiring — or a device on the network over Modbus TCP.

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
    from BOOL to DOUBLE plus strings. Write right in the table.

    [:octicons-arrow-right-24: Register map](guide/register-map.md)

-   **Modbus RTU and Modbus TCP**

    ---

    RS-485 through a USB adapter, PLCs and meters on the network, RS-485 ↔
    Ethernet converters ("RTU over TCP"). "Test link" tells what is wrong.

    [:octicons-arrow-right-24: Connecting](connect.md)

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

    Find the devices on a line and on the network, send raw frames with automatic CRC, log for
    hours to CSV and compare "before vs after".

    [:octicons-arrow-right-24: All tools](guide/index.md)

-   **Examples**

    ---

    Ready-made macros and scenarios: testing a SCADA, importing a map from
    a datasheet, dashboard automation, debugging a line.

    [:octicons-arrow-right-24: Examples](examples/index.md)

</div>

## Online tools

<div class="grid cards" markdown>

-   :material-shield-check:{ .lg .middle } [**CRC calculator**](tools/crc.md)

    CRC16 Modbus and a decoding of any frame.

-   :material-swap-horizontal:{ .lg .middle } [**FLOAT ↔ registers**](tools/converter.md)

    Values in every byte order: ABCD, CDAB, BADC, DCBA.

-   :material-map-marker:{ .lg .middle } [**Addresses 40001 ↔ 0x0000**](tools/address.md)

    Modicon notation and the zero-based protocol address.

</div>

## Why ModbusReader

- **Free with no limits** — no trial period, no register or runtime limit.
  The code is open under GPL-3.0.
- **Master, slave simulator and sniffer in one app** — jobs that usually
  take several different tools.
- **A register map like the device datasheet** — names, units and
  enumerations instead of bare addresses; import from Excel and CSV.
- **English and Russian UI**, dark and light themes, accent colours, the menu
  on the left, right or top. Updates install in the background — switching to
  a new version takes a couple of seconds.

The current version is **{{ app_version }}**. Release notes are in the
[CHANGELOG](https://github.com/Mercurrial/ModbusReader/blob/main/CHANGELOG.md).
Questions go to [Discussions](https://github.com/Mercurrial/ModbusReader/discussions),
bugs to [Issues](https://github.com/Mercurrial/ModbusReader/issues).

## FAQ

??? question "Is it really free?"
    Yes. No trial period, no limit on registers or runtime, no sign-up and no
    ads. The code is open under GPL-3.0 — you may use the app at work too.

??? question "How does ModbusReader differ from Modbus Poll and Modbus Slave?"
    Master, device emulator and sniffer in one free app; a register map
    holding names, units and enumerations; a dashboard and Python macros.
    What it lacks is Modbus ASCII and UDP. A detailed comparison:
    [a free Modbus Poll alternative](compare.md).

??? question "Does it support Modbus TCP?"
    Yes, since version 26.10.3: connecting to PLCs, meters and gateways over
    [Modbus TCP](modbus/tcp.md), to RS-485 ↔ Ethernet converters in
    [RTU over TCP](modbus/rtu-over-tcp.md) mode, a TCP emulator and a search
    for devices on the network. How to connect:
    [Connecting over the network](connect.md#tcp).

??? question "Which adapter do I need?"
    Any USB-to-RS-485 adapter the system sees as a COM port: FTDI, CP210x or
    CH340 based. See [Connect a device](connect.md).

??? question "Can I try it without a device?"
    Yes. The demo project opens on first launch with a made-up device of its
    own: press **Connect** — the values come alive, and writing the
    setpoint, mode, heater or fan acts on it ([more](quickstart.md#no-device)).
    Your own map can be tried with the [emulator](guide/slave.md) over Modbus
    TCP on `127.0.0.1` — one computer is enough.

??? question "Which systems does it run on?"
    Windows 10 (1809+) and 11 — installer and portable build; Linux —
    AppImage (Ubuntu 22.04+ and the like); macOS 12+ on Apple Silicon.
    See [Install](install.md).

??? question "Why does a FLOAT show a huge or negative number?"
    Wrong byte order: vendors lay out 32-bit values differently. Check the
    registers in the [converter](tools/converter.md) and pick the order in
    **Settings → Connection → Codecs**. See
    [Data types and byte order](modbus/data-types.md).

??? question "Where do I get a device register map?"
    From the device datasheet or manual — the register table imports from
    Excel or CSV in a couple of minutes. See
    [A map from a datasheet](examples/datasheet-import.md).
