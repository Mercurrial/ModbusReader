---
seo_title: ModbusReader projects and files — .mbproj, .json maps, dashboards
description: What a ModbusReader project (.mbproj) holds — link settings, the register map, dashboards; how it differs from a standalone .json map; which other files the app writes.
---

# Projects and files

## The `.mbproj` project

A **project** is one file per site or device. It holds:

- the **link settings** — port, baud rate, parity, stop bits, device address,
  poll period, timeout, delays and byte order;
- the **register map**;
- **every dashboard** with its widgets and wires;
- the window layout — which page was open, log height, trend panel width.

Open a project and the app is ready for that device: just press
**Connect**.

| Action | Keys |
|---|---|
| New project | ++ctrl+n++ |
| Open project | ++ctrl+o++ |
| Save project | ++ctrl+s++ |

The project menu opens when you click its name in the window header: it also
has **Save project as…**, **Recent projects**, and opening or creating a
standalone map. **New project** closes the current map and dashboards but
keeps the link settings.

On start-up the app reopens the project or map you worked with last time
(**Settings → General → Startup**). The installer associates `.mbproj` with
the app, so a project opens on double-click.

## The `.json` map

A **register map** is a standalone file with just the register list — no
link settings, no dashboards. It is the thing to share: one map per device
model, as many projects using it as there are sites. The format is in
[Map editor](map-editor.md#file-format).

| Action | Keys |
|---|---|
| New map | ++ctrl+shift+n++ |
| Open map | ++ctrl+shift+o++ |

If you open a map file as a project, the app notices and opens it as a map.

## Other files

| File | From | Contents |
|---|---|---|
| `.mbdash` | [Dashboard](dashboard.md) → Save dashboard to file… | One dashboard — to move it to another project |
| `.mbsnap` | [Snapshots](snapshots.md) → Save… | Every register value at snapshot time |
| `.csv` | [Logger](logger.md) | Logged values: a row per instant, a column per register |
| `.csv`, `.xlsx` | [Macros](macros.md) → CSV / XLSX | A macro's results table |
| `.py` | [Macros](macros.md) → Save | The macro text |
| `.txt` | Transaction log → Save log… | The transaction log |

Every ModbusReader format is text (JSON or CSV): readable, diffable and fine
to keep in version control.
