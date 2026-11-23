---
seo_title: Modbus CRC16 — calculation algorithm, polynomial 0xA001, code in C, Python and JavaScript
description: How the Modbus RTU CRC-16 is calculated — polynomial 0x8005 (0xA001), initial value 0xFFFF, byte order in the frame. A step-by-step example, tested code in C (bitwise and table-driven), Python and JavaScript, and checking a received frame.
---

# Modbus CRC-16

Every [Modbus RTU](rtu.md) frame ends with two **CRC** bytes — a checksum
of all the bytes before them. The receiver computes it again and compares:
a mismatch means noise corrupted the frame, and it is silently dropped.
Compute the CRC of a ready frame with the
[online calculator](../tools/crc.md); this page is about how it works and
how to compute it in your own program.

| Parameter | Value |
|---|---|
| Name | CRC-16/MODBUS |
| Polynomial | 0x8005 (x¹⁶ + x¹⁵ + x² + 1); reflected — **0xA001** |
| Initial value | **0xFFFF** |
| Reflect input and output | yes (bits are processed lowest first) |
| Final XOR | none (0x0000) |
| Order in the frame | **low byte first** |
| Check value | CRC of the string `123456789` = `0x4B37` |

!!! note "Not just any CRC-16"
    There are dozens of CRC-16 variants with the same polynomial but a
    different initial value or bit order: CRC-16/ARC starts at 0x0000,
    CRC-16/CCITT uses the polynomial 0x1021. Only CRC-16/MODBUS matches
    Modbus — check against the value `0x4B37`.

## Algorithm { #algorithm }

1. CRC register = `0xFFFF`.
2. For every byte of the frame (except the CRC bytes themselves):
    1. CRC = CRC XOR byte (the byte goes into the low 8 bits).
    2. Eight times: if the lowest bit of CRC is 1 — shift CRC right by 1
       and XOR with `0xA001`; otherwise just shift right by 1.
3. The result is a 16-bit number. The **low** byte goes into the frame
   first, then the high byte.

### Step by step { #example }

The request frame `01 03 00 00 00 02`. The first byte `0x01`:

```text
CRC = FFFF XOR 0001 = FFFE
step  low bit  action                CRC
 1       0     shift                 7FFF
 2       1     shift, XOR A001       9FFE
 3       0     shift                 4FFF
 4       1     shift, XOR A001       87FE
 5       0     shift                 43FF
 6       1     shift, XOR A001       81FE
 7       0     shift                 40FF
 8       1     shift, XOR A001       807E
```

The other five bytes go the same way; at the end CRC = `0x0BC4`. It goes
into the frame low byte first — `C4 0B`:

```text
01 03 00 00 00 02 C4 0B
```

## Code { #code }

Every example below has been tested: the frame `01 03 00 00 00 02` gives
`C4 0B`, the string `123456789` gives `0x4B37`.

=== "C"

    ```c
    #include <stdint.h>
    #include <stddef.h>

    uint16_t modbus_crc16(const uint8_t *data, size_t len)
    {
        uint16_t crc = 0xFFFF;
        for (size_t i = 0; i < len; i++) {
            crc ^= data[i];
            for (int bit = 0; bit < 8; bit++) {
                if (crc & 0x0001)
                    crc = (crc >> 1) ^ 0xA001;
                else
                    crc >>= 1;
            }
        }
        return crc;
    }

    /* append the CRC to a frame (low byte first);
       the buffer needs room for 2 more bytes */
    size_t add_crc(uint8_t *frame, size_t len)
    {
        uint16_t crc = modbus_crc16(frame, len);
        frame[len]     = crc & 0xFF;
        frame[len + 1] = crc >> 8;
        return len + 2;
    }
    ```

=== "C, table-driven"

    ```c
    #include <stdint.h>
    #include <stddef.h>

    static uint16_t table[256];

    void modbus_crc16_init(void)          /* call once at start-up */
    {
        for (int n = 0; n < 256; n++) {
            uint16_t crc = (uint16_t)n;
            for (int bit = 0; bit < 8; bit++)
                crc = (crc & 1) ? (crc >> 1) ^ 0xA001 : crc >> 1;
            table[n] = crc;
        }
    }

    uint16_t modbus_crc16_fast(const uint8_t *data, size_t len)
    {
        uint16_t crc = 0xFFFF;
        while (len--)
            crc = (crc >> 8) ^ table[(crc ^ *data++) & 0xFF];
        return crc;
    }
    ```

    The table-driven version is several times faster: one table lookup
    instead of eight shifts per byte. On a microcontroller the table can
    live in flash as a constant — it starts `0x0000, 0xC0C1, 0xC181,
    0x0140…` and ends with `0x4040`.

=== "Python"

    ```python
    def modbus_crc16(data: bytes) -> int:
        crc = 0xFFFF
        for byte in data:
            crc ^= byte
            for _ in range(8):
                if crc & 1:
                    crc = (crc >> 1) ^ 0xA001
                else:
                    crc >>= 1
        return crc


    def with_crc(frame: bytes) -> bytes:
        """The frame with its CRC appended, low byte first."""
        return frame + modbus_crc16(frame).to_bytes(2, "little")


    print(with_crc(bytes.fromhex("01 03 00 00 00 02")).hex(" ").upper())
    # 01 03 00 00 00 02 C4 0B
    ```

=== "JavaScript"

    ```javascript
    function modbusCrc16(bytes) {
      let crc = 0xFFFF;
      for (const b of bytes) {
        crc ^= b;
        for (let i = 0; i < 8; i++) {
          crc = (crc & 1) ? (crc >>> 1) ^ 0xA001 : crc >>> 1;
        }
      }
      return crc;
    }

    function withCrc(bytes) {
      const crc = modbusCrc16(bytes);
      return [...bytes, crc & 0xFF, crc >>> 8];   // low byte first
    }

    withCrc([0x01, 0x03, 0x00, 0x00, 0x00, 0x02]);
    // [1, 3, 0, 0, 0, 2, 196, 11]  ->  01 03 00 00 00 02 C4 0B
    ```

## Checking a received frame { #check }

A handy property: the CRC computed over the **whole** frame including its
two CRC bytes comes out `0x0000`. So the check is one line:

```python
def crc_ok(frame: bytes) -> bool:
    return len(frame) >= 4 and modbus_crc16(frame) == 0
```

The 4-byte minimum is address, function and CRC; anything shorter is
corrupt anyway.

## Common mistakes { #mistakes }

| Symptom | Cause |
|---|---|
| The CRC is "almost right" — bytes swapped | The high byte was written first. Modbus RTU wants the low byte first |
| The device stays silent though "the frame is right" | The CRC was computed over the characters of a hex string ("01 03 …" as text), not over bytes |
| The CRC matches no calculator | Initial value 0x0000 instead of 0xFFFF (that is CRC-16/ARC) |
| Only some frames fail | A signed type: `char` instead of `uint8_t` in C, negative bytes in Java/C# |
| A Modbus TCP device answers with an error | [Modbus TCP](tcp.md) has no CRC — TCP takes care of integrity. Only [RTU over TCP](rtu-over-tcp.md) carries one |

[Modbus ASCII](index.md#variants) uses an LRC instead of a CRC — a
one-byte sum computed differently.

## Why a CRC and not a byte sum { #why }

A plain sum misses swapped bytes and many double errors. CRC-16 is
guaranteed to catch any single or double bit error, any odd number of
errors and any burst of up to 16 consecutive bits — which is what noise on
an RS-485 line usually looks like. The chance of missing a random
corruption is about 1 in 65,536.

## In ModbusReader { #modbusreader }

ModbusReader computes and checks the CRC itself: in the
[console](../guide/console.md) type a frame without the checksum — the app
adds it before sending. Answers with a bad CRC go to the **CRC errors**
counter of the [line statistics](../guide/register-map.md), and the
[sniffer](../guide/sniffer.md) marks them in other masters' traffic —
frequent CRC errors point at noise, bad wiring or wrong parity (see
[Troubleshooting](../troubleshooting.md)).

## See also { #see-also }

- [CRC calculator and frame decoder](../tools/crc.md) — online, in the
  browser.
- [Modbus RTU](rtu.md) — where the CRC sits in a frame.
- [The Modbus protocol](index.md) · [Function and exception codes](functions/index.md)
