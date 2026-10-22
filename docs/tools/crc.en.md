---
seo_title: Modbus RTU CRC calculator online and frame decoder
description: Online CRC16 Modbus RTU calculator — type a frame in hex to get its checksum, the ready packet and a decoding — device address, function, register address, count, data, exception code.
---

# CRC calculator and frame decoder

Type a Modbus RTU frame in hex — **without the CRC** to compute the
checksum, or **with it** to check it. The decoding appears below: device
address, function, address, count, data.

<div class="mbt" markdown>
<label for="mbt-crc-in">Frame (hex)</label>
<input id="mbt-crc-in" class="mbt-input" type="text" value="01 03 00 00 00 02" spellcheck="false" autocomplete="off">
<div id="mbt-crc-out" class="mbt-out"></div>
</div>

Spaces, commas and `0x` are all fine; every byte is two digits. Everything
is computed in your browser, nothing is sent anywhere.

## How the Modbus CRC is computed

CRC-16/MODBUS: polynomial `0xA001` (`0x8005` reflected), initial value
`0xFFFF`, no final XOR. The two CRC bytes go at the end of the frame **low
byte first**: for `01 03 00 00 00 02` the CRC is `0x0BC4`, and the frame
carries the bytes `C4 0B`.

```python
def crc16_modbus(data: bytes) -> int:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc

frame = bytes.fromhex("010300000002")
crc = crc16_modbus(frame)
packet = frame + bytes([crc & 0xFF, crc >> 8])   # 01 03 00 00 00 02 C4 0B
```

A device silently drops a frame with a bad CRC — so one wrong byte looks
like "the device does not answer". The frame structure is in
[What is Modbus RTU](../modbus/index.md), function and exception codes in
[Functions and errors](../modbus/functions.md).

## In the app

In ModbusReader you never compute a CRC by hand: the
[console](../guide/console.md) appends it to any frame, the transaction log
decodes every frame, and the [sniffer](../guide/sniffer.md) flags frames with
a bad CRC.

Other tools: [FLOAT and INT32 converter](converter.md) ·
[addresses 40001 ↔ 0x0000](address.md).
