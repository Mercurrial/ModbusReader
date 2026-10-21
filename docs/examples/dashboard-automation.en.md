---
seo_title: No-code automation on the dashboard — timer, gate, button
description: A step-by-step automation example in ModbusReader — turn a fan on when it overheats and off when it cools down using a timer, gates and buttons on the dashboard, with no macros and no code.
---

# Dashboard automation

The task: **turn the fan on when the temperature is above 30 °C and off when
it drops below 28 °C** — without a line of code. The example is built on the
demo project; wires and widgets are described in [Dashboard](../guide/dashboard.md).

```text
                 +--------------+     +-----------------+
            +--->| Gate: t > 30 |---->| Button: Fan = 1 |
+--------+  |    +--------------+     +-----------------+
| Timer  |--+
| 1000 ms|  |    +--------------+     +-----------------+
+--------+  +--->| Gate: t < 28 |---->| Button: Fan = 0 |
                 +--------------+     +-----------------+
```

Once a second the timer sends a pulse into both gates. The upper one lets it
through only when it is hot — and its button turns the fan on. The lower one
only when it has cooled down — and the second button turns it off. Between 28
and 30 °C nothing happens: that is hysteresis, so the fan does not chatter
around the threshold.

## Steps

1. Open the **Dashboard** (++ctrl+6++) and press **Edit** (++ctrl+e++).
2. **Add widget → Timer.** Interval — `1000` ms. **Autostart** can stay
   off: a click starts the timer.
3. **Add widget → Gate.** Register — "Temperature", condition `>`, compare
   with `30`.
4. Another **Gate**: "Temperature", `<`, `28`.
5. **Add widget → Button.** Register — "Fan" (a coil), write value `1`.
   Title — "Fan: on".
6. Another **Button**: "Fan", value `0`, title "Fan: off".
7. **Wires:** drag from the timer's right dot to the left dot of each gate,
   and from each gate's right dot to its button.
8. Press **Done**, connect (++f5++) and click the timer — it starts. Pulses
   are visible: wires light up, widgets flash; a closed gate flashes too but
   lets nothing further.

Save the project (++ctrl+s++) — the dashboard and its wires are saved in it.

## Things to know

- **Nothing is written to the device in edit mode** — timers stop and
  buttons are inert.
- **A gate with no data is closed.** If the link drops and the temperature
  is unknown, the gate lets no pulse through — the chain will not write
  blindly.
- The timer writes on **every** tick while the condition holds: in the
  example the fan gets "turn on" once a second. Most devices are fine with
  that; if yours dislikes frequent writes — lengthen the interval.

## Variations

- **A manual start sequence:** Button "Start" → Button "Mode = 1" → Button
  "Fan = 1". One press, several writes down the chain.
- **One slider, two registers:** Slider → a Button bound to another register.
  The slider's value travels down the wire and the button writes it to its
  own register.
- **Emergency off:** Timer → Gate "Door open = 1" → Button "Heater = 0".

When the logic grows beyond "if — then", move on to [macros](macros.md):
loops, variables and a results table.

!!! warning "Not for safety systems"
    Dashboard automation works only while the app is open and the link is
    up. It is a commissioning and testing tool, not a replacement for a PLC
    or safety interlocks.
