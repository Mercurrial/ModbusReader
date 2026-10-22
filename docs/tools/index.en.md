---
seo_title: Online Modbus tools — CRC calculator, FLOAT converter, 40001 addresses
description: Free online tools for Modbus RTU — CRC16 calculator with a frame decoder, FLOAT/INT32 to registers converter in every byte order, 40001 ↔ 0x0000 address converter. They run in your browser.
---

# Online tools

Three helpers for commissioning engineers — they run right in your
browser, with nothing to install and no data sent anywhere.

<div class="grid cards" markdown>

-   :material-shield-check:{ .lg .middle } [**CRC calculator and frame decoder**](crc.md)

    ---

    CRC16 Modbus for any frame, checking a ready packet, and a decoding:
    device address, function, registers, exception.

-   :material-swap-horizontal:{ .lg .middle } [**FLOAT and INT32 converter**](converter.md)

    ---

    Value → registers and registers → value in every byte order: ABCD, CDAB,
    BADC, DCBA. FLOAT, DOUBLE, INT16…INT64.

-   :material-map-marker:{ .lg .middle } [**Addresses 40001 ↔ 0x0000**](address.md)

    ---

    Modicon notation, zero-based protocol address, one-based number, hex and
    decimal, read and write functions.

</div>

ModbusReader does all of this itself: it computes CRCs, lays values out over
registers and shows addresses in a readable form. The tools help when the app
is not at hand — or to find out why another program shows an odd value.
