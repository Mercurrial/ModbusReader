# ARCHITECTURE — ModbusRegReader

> Internal engineering map. Audience: whoever (human or Claude) edits this code next.
> Goal of the codebase: grow from a Modbus register reader into a general
> instrument that "умеет всё". The architecture exists to make **adding features
> a one-descriptor edit**, not a cross-file surgery.

---

## 0. Hard constraints (do not violate)

1. **NO .exe builds without an explicit user request.** Standing order, verbatim:
   *"Больше не надо собирать в exe без моей конкретной просьбы."*
   All verification is **headless**.
2. **Verify headless** with the project venv:
   ```bash
   QT_QPA_PLATFORM=offscreen PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe <script>
   ```
3. **Device byte-order DEFAULTS are sacred.** Codecs live in `byteorder.py`
   (permutations) + `datatypes.configure_orders()` (per-type choice from
   settings: `order_short`/`order_long`/`order_float`). The DEFAULTS —
   SHORT="AB", LONG="ABCD" (no swap), FLOAT="BADC" (bytes swapped within each
   word) — are the user's proven device protocol and are guarded bit-for-bit by
   `tests/test_byteorder.py` (legacy implementation inlined as golden). Never
   change the defaults; users pick other orders in Settings → Подключение →
   Кодеки.
4. **Area types are never polled.** `MEMORY_AREA`, `UNUSED_AREA`, legacy `AREA`
   are excluded from cyclic polling. This is enforced centrally — keep it that way.
5. UI text is bilingual RU/EN. RU is primary (the user writes RU).

---

## 1. The architectural style — Descriptor + Registry

Chosen style for the whole project (the thing we are converging on):

> **Each extensible domain is declared as DATA — a frozen dataclass *descriptor* —
> inside one central *registry* dict. The rest of the app talks to the domain only
> through a thin module-level helper API. Adding a feature = adding one descriptor.
> Nothing else changes.**

Why: the old code had the same knowledge (e.g. "how big is a FLOAT", "is this
type pollable") copy-pasted as private `if/elif` chains in every file. Each new
type meant editing 5 files and forgetting one. The registry makes the knowledge
live in exactly one place.

**`datatypes.py` is the reference implementation of this style** (joined by
`settings_schema.py`, `commands.py` and `transports.py`). When building the next
registry (themes, columns), copy its shape: `@dataclass(frozen=True)`
descriptor → ordered registry → thin helpers → derived views computed once at
import.

---

## 2. Runtime / threading model

```
main.py
  └─ QApplication, loads app_settings.json, applies stylesheet
  └─ ModernScadaApp (gui_main.py)  ← the main window (~1400 lines; shrinking)
        ├─ AppContext (app_context.py)           — shared services: settings,
        │                                          core, translator, theme
        ├─ NavRail (gui_rail.py)                 — every page, left edge
        ├─ MainToolBar (gui_toolbar.py)          — header: project / page,
        │                                          link chip, Connect
        ├─ RegisterTable (gui_table.py)          — the dashboard grid (MVC view)
        ├─ TrendsManager (gui_trends.py)         — live charts
        ├─ LogPanel (gui_log.py)                 — transaction log
        ├─ MainStatusBar (gui_statusbar.py)
        ├─ pages (content_stack): map, dashboard, console, scanner, sniffer,
        │   snapshots, logger, macros (MacroWindow, embedded), slave
        └─ embedded overlays: SettingsDialog, ProfileEditorDialog
```

**Application context (`app_context.py`):** `AppContext` owns the cross-cutting
services the whole UI shares — the `settings` dict, the `ModbusCore` worker, the
active translator (`lang` / `t`), and theme/accent (`theme_tokens()` /
`stylesheet()`). It's the lever for dissolving the gui_main god object: children
take **one** context instead of reaching into the window. The window's
`settings` / `modbus_core` / `lang` / `t` are now read-through *properties* onto
the context (single owner, no churn at the ~130 existing call sites); language
and settings-apply route through `ctx.set_lang()` / `ctx.update()`. The
app-specific children take the context: `MacroWindow`, `TrendsManager`,
`MemoryViewerDialog`, `ProfileEditorDialog`, `LogPanel`, `RegisterTable`. Two stay on explicit params **by
design**: `SettingsDialog` (already a decoupled dict-taker that works on a
`.copy()`) and `OnboardingGuide` (a reusable leaf widget — coupling it to the app
context would kill its reuse). It holds a QThread but defines no Qt signals — UI
refresh stays the window's job.

**Threading rule:** the serial port has exactly one owner — the `ModbusCore`
thread. Everyone else communicates via queues + Qt signals, never by touching the
client directly.

`ModbusCore` (modbus_core.py) drains five inputs each loop, by priority:
1. `op_queue`     — **synchronous** macro ops (highest priority); see `request_op()`
2. `raw_queue`    — raw console frames (sent verbatim past the framer via
   `client.socket`; response read until 50 ms of line silence or timeout)
3. `write_queue`  — async writes from the table
4. `array_read_queue` — one-shot memory-area reads (for MemoryViewer)
5. `poll_list`    — cyclic polling of scalar registers (cycle cadence = poll_rate)

`ModbusCore` signals (Qt, cross-thread safe):
- `status_changed(bool connected, str msg)` — `msg` may be "" (a failed
  open is reported through `log_msg("ERR", …)` instead)
- `data_updated(int addr, str display_value)` — table cell update
- `log_msg(str level, str message)`
- `array_read_finished(int addr, list words)`

Macro threads (`MacroRunner` in macro_engine.py) **never** touch serial. They call
`core.request_op("read"/"write", ...)`, which enqueues onto `op_queue` and blocks
on a per-op result `queue.Queue(maxsize=1)`. So serial access is always serialized
through the one core thread.

Connection-loss policy (configurable in settings):
- `retry_count` failed polls in a row ⇒ "connection lost".
- `auto_reconnect == False` (default): stop, require pressing Connect again.
- `auto_reconnect == True`: keep silently retrying every `reconnect_interval` s.
- pymodbus client is built with `retries=1` so the retry count we show is honest.

---

## 3. File-by-file map

| File | LOC | Responsibility | Key symbols |
|---|---|---|---|
| `main.py` | 63 | Entry point. Reads settings, sets HiDPI, applies stylesheet, shows window. Global excepthook. | `main()` |
| **`datatypes.py`** | ~500 | **Registry of Modbus register data types — single source of truth.** Codecs, decode/encode/format, span, poll/area flags; the four Modbus tables (`AREAS`) and the register key. | `DataType`, `TYPES`, `decode/encode/read_count/is_area/should_poll/is_scalar/addr_span/read_to_str`, `AREAS`, `reg_key/split_key/key_label/parse_key/apply_area` |
| `modbus_core.py` | 383 | The worker thread. Builds its pymodbus client via the `transports` registry (transport-agnostic). Poll loop + write/array/sync-op queues. | `ModbusCore(QThread)`, `request_op()` |
| **`transports.py`** | 97 | **Transport registry** — `Transport` descriptors + `TRANSPORTS` (serial/TCP). Each owns client construction + a link-description string; ModbusCore names no concrete pymodbus class. | `Transport`, `TRANSPORTS`, `BY_ID`, `get()` |
| `macro_engine.py` | 263 | Runs a user Python macro in a worker thread with a restricted-builtins namespace + domain API (`reg/read/write/wait/record/log/...`). | `MacroRunner(QThread)`, `_Register` |
| **`app_context.py`** | 85 | **Shared-services context** — owns settings + Modbus core + translator + theme; derives `theme_tokens()`/`stylesheet()`; `set_lang()`/`update()`/`save()`. The lever for dissolving the god object. | `AppContext` |
| `gui_main.py` | 867 | Main window / coordinator. Builds the layout, wires signals, routes the table's intent signals to core/trends/status/memory-viewer, owns overlays + settings apply. Sources shared services from `AppContext`; dispatches toolbar commands via `commands`. | `ModernScadaApp`, `_dispatch_command`, `_command_handler_map`, `_on_write_requested`, `_on_inspect_requested` |
| `gui_log.py` | ~250 | Transaction log: ONE `LogStore` (entries + cap + verbosity) rendered by any number of `LogView`s (filter tabs + themed view). `LogPanel` = bottom strip (view + raw console + toggle); the Консоль view is a second `LogView` on the same store. | `LogStore`, `LogView`, `LogPanel`, `render_entry` |
| `gui_console.py` | 186 | Raw-frame console strip: command row (live CRC16 in gray) + editable resulting-packet row + ↑/↓ history. Emits `send_requested(bytes)`; window routes to `core.queue_raw()`. | `RawConsole`, `parse_hex`, `crc16` |
| **`gui_table.py`** | ~540 | **Register-grid view (MVC).** Column registry (`COLUMNS`), state-dot delegate, populate, value formatting + view-modes, interaction, **full-width fill + width-stealing resize** (`_reflow_columns`/`_FLEX_COLS`/`_MINW`). References only ctx/`datatypes`; emits intent signals (write/verbose/value/inspect/trend) the window routes. | `RegisterTable`, `Column`/`COLUMNS`, `StateDotDelegate`, `COL_*`, `format_value`, `mono_font` |
| `profile_editor.py` | 1013 | Register-map editor dialog. Add/reorder/type rows, open/save JSON profile. Takes an `AppContext`. | `ProfileEditorDialog`, `ReorderableTable`, `normalize_registers()` |
| `profile_manager.py` | ~110 | Load a profile JSON + non-blocking validation (overlaps, duplicate names) + the editor's **address-chain model** (`chained_flags`/`rechain`/`is_contiguous`): registers packed right after their predecessor move with it, a register after a gap keeps its address. | `load_profile_data`, `find_overlaps`, `find_duplicate_names`, `chained_flags`, `rechain` |
| `settings_manager.py` | ~185 | `DEFAULT_SETTINGS` dict + **crash-safe** load/save of `app_settings.json`: absolute (CWD-independent) path, atomic write (temp+fsync+`os.replace`) with rolling `.bak`, recovery from `.bak`, corrupt file preserved as `.corrupt`. | `DEFAULT_SETTINGS`, `load_settings`, `save_settings`, `SETTINGS_FILE` |
| **`settings_schema.py`** | 301 | **Settings UI registry** — `Field`/`Section`/`Page` descriptors + `PAGES`; text = `i18n.STRINGS` keys resolved by `tr()` (literals pass through); dynamic combos via `options_fn` (COM-port auto-detect) + `editable`. | `Field`, `Section`, `Page`, `PAGES`, `tr`, `iter_fields`, `_com_ports` |
| `gui_settings.py` | ~430 | Settings dialog UI — **schema-driven**, no per-setting code; lazy-built tabs. | `SettingsDialog`, `get_new_settings()`, `_make_control` |
| **`theme_manager.py`** | 170 | **Theme/accent registry.** `THEMES` dict of color-token palettes (dark/light) + `ACCENT_PALETTES` overrides; `get_theme()` is a copy-returning lookup. | `THEMES`, `get_theme()`, `ACCENT_PALETTES`, `DEFAULT_THEME` |
| `styles.py` | 806 | Builds the QSS stylesheet from theme tokens + font + accent. | `get_stylesheet()` |
| `i18n.py` | 246 | **Translation registry.** `STRINGS` dict, `get_translator(lang)` → `t(key)`. | `STRINGS`, `get_translator`, `SUPPORTED_LANGUAGES` |
| **`commands.py`** | ~140 | **Command registry** — `Command` descriptors + `COMMANDS` (id, label key, icon, shortcut, placement, rail group). Drives the rail, the header buttons, shortcuts and tooltips. | `Command`, `COMMANDS`, `BY_ID`, `VIEWS`, `RAIL_FOOTER`, `GROUPS`, `BUTTONS`, `SHORTCUTS` |
| `gui_rail.py` | ~240 | Left navigation rail: every page in two groups (monitor / tools), settings + help at the bottom, collapsible, busy dots. | `NavRail`, `command_triggered`, `set_active_view`, `set_busy`, `set_collapsed` |
| `gui_toolbar.py` | ~290 | Header bar: project crumb + page title, link chip, Connect (the primary action), watch / language / theme / layout. | `MainToolBar`, `command_triggered`, `link_clicked`, `set_link_text` |
| `gui_trends.py` | 894 | Live trend cards + fullscreen chart dialog (pyqtgraph). `TrendsManager` takes an `AppContext`. | `TrendsManager`, `TrendCard`, `ChartExpandDialog` |
| `gui_macros.py` | ~790 | Macro page: code editor + run/stop + results table + export + help. Takes an `AppContext`; `embedded=True` since 2.2 (a page, not a window). | `MacroWindow`, `CodeEditor` |
| `gui_widgets.py` | ~360 | Reusable design widgets, incl. empty states. | `Segmented`, `ToggleSwitch`, `LabeledSlider`, `SwatchPicker`, `EmptyState`, `EmptyOverlay` |
| `gui_statusbar.py` | 189 | Status bar: connection dot + editable slave-id. | `MainStatusBar`, `_SlaveIdEditor` |
| `gui_onboarding.py` | 267 | First-run coach-mark guide overlay. | `OnboardingGuide` |
| `memory_viewer.py` | ~330 | Dialog to read a memory area as a 2D grid; multi-endian array parser; themed controls (wide combos, chevron arrows). Takes an `AppContext`. | `MemoryViewerDialog` |
| `icons.py` | ~135 | SVG icon helper (recolored to theme). `pixmap`/`icon` for widgets; `icon_url()` caches a themed PNG for QSS `image:` (combo/spin chevrons — Qt can't do CSS border-triangles). | `pixmap`, `icon`, `icon_url` |
| `dialogs.py` | ~55 | `themed_message()` — QMessageBox with an `icons.py` glyph in a semantic colour instead of the native icon; inherits the app QSS. Used for the confirm dialogs. | `themed_message` |
| `linestats.py` | ~150 | Line statistics: thread-safe counters + response times, outcome classification, the pymodbus RTU-framer CRC probe. | `LineStats`, `classify`, `install_crc_probe` |
| `gui_watch.py` | ~420 | Watch window: floating list of picked registers (value, min/max, age, write). | `WatchWindow` |
| `slave_core.py` | ~380 | Slave / device emulator: pure `build_response`, `SlaveStore`, `SlaveServer` thread. | `build_response`, `SlaveStore`, `SlaveServer` |
| `gui_slave.py` | ~470 | Slave view: port/ID/delay, served map with editable values + access counts, exchange log. | `SlaveView` |
| `tools/make_icon.py` | ~110 | Generates `assets/app.png` + `assets/app.ico`. | — |
| `bundle_project.py` | 89 | Dev utility (concatenates sources). Not part of the app. | — |

---

## 4. Registries & extension points that EXIST today

### 4.1 Data types — `datatypes.py`  ✅ (the template)

`DataType` fields: `key, label, hint, fixed_span (None=variable), is_area,
decode, encode, fmt`. `is_scalar` ⇔ has both decode and encode.

**Add a register type** → add ONE entry to `TYPES`:
```python
_dt("UINT16", fixed_span=1, hint="Unsigned 16-bit → 1 address",
    decode=lambda regs: regs[0] & 0xFFFF,
    encode=lambda v: [int(v) & 0xFFFF],
    fmt=str),
```
That alone makes it: pollable, readable/writable by the dashboard, available in
the profile-editor dropdown, usable by macros, correctly sized in address-span
maths. **No other file changes.** Verify with the §7 smoke test.

Derived views (recomputed at import, don't hand-edit): `ALL_TYPES`,
`FIXED_TYPE_LEN`, `VARIABLE_TYPES`, `TYPE_HINTS`, `SCALAR_KEYS`, `_AREA_KEYS`.

Consumers (all migrated to the registry — see §6 history):
`modbus_core` (poll filter, read/decode/encode), `profile_editor` (dropdown +
span), `macro_engine` (scalar filter), `gui_main` (`is_area` at 3 sites),
`memory_viewer` (`read_count`).

### 4.1a Icons — `icons.py`

One SVG stroke set (`_PATHS`), recolored to the theme via `currentColor`. **Use
these — never emoji/Unicode dingbats** (they render in inconsistent, off-style
ways). `icons.icon(name, color, size)` → `QIcon`; `icons.pixmap(...)` → `QPixmap`
(for `QLabel.setPixmap`, e.g. a section-title glyph). Settings-sidebar page icons
come from `Page.glyph` (an icon *name*, not a char). For QSS sub-controls that
need `image:` (combo/spin arrows) use `icons.icon_url(name, color, size)` — it
caches a themed PNG and returns `url(...)`. **Qt QSS can't draw a CSS
border-triangle (it fills a box), so always use an image for arrows.**

### 4.2 Themes / accents — `theme_manager.py`  ✅

`get_theme(name, accent)` returns a flat dict of color tokens consumed by
`styles.get_stylesheet()` and the widgets. Accents live in `ACCENT_PALETTES`.
- **Add an accent** → one entry in `ACCENT_PALETTES` (`accent`/`tint`/`soft`).
- **Add a full theme** → one entry in the `THEMES` registry (keyed by lowercase
  name; `DEFAULT_THEME = "dark"`). `get_theme` is a lookup — no branching — and
  returns a **deep copy** so callers/the accent overlay can't corrupt the
  registry. Token *keys* must match across themes (the stylesheet reads the same
  names regardless of theme).

### 4.3 Translations — `i18n.py`

`STRINGS[key]` → `{"ru": ..., "en": ...}`. `get_translator(lang)` returns `t(key)`
(falls back to English, then the key). The two language maps are kept symmetric.
- **Add a string** → one entry in each language map in `STRINGS`.
- UI **labels** (buttons, headers, menu items, dialog titles) are in `STRINGS`.
  The `("…" if lang=="ru" else "…")` pattern remains only where it's the right
  tool: the bilingual **helpers** that resolve it (`gui_settings.L`,
  `gui_onboarding.L`, `settings_schema.tr`), long-form **onboarding-guide prose**
  (contextual narrative, kept near its use site), and register **data defaults**.

### 4.4 Settings — `settings_manager.py` + `settings_schema.py`  ✅

Two layers:
- `settings_manager.DEFAULT_SETTINGS` — the persisted schema + defaults.
  `load_settings()` merges saved JSON over defaults (adding a key is back-compat).
- `settings_schema.PAGES` — the **UI schema registry** (Descriptor + Registry).
  `Field` / `Section` / `Page` frozen dataclasses declare what each setting's
  control is, how it's grouped, and its value transforms. `gui_settings.py`
  renders itself by walking `PAGES` and contains **no per-setting code**.

**Add a setting** (now a two-line change, no UI code):
1. add `key: default` to `DEFAULT_SETTINGS`;
2. add ONE `Field(...)` to the relevant `Section` in `settings_schema.PAGES`.

`Field` kinds: `toggle | segmented | slider | swatch | text | combo`. Hooks:
`to_widget` (settings→control seed), `from_widget` (control→settings), `derive`
(one value writes extra keys — e.g. `font_choice` also sets `font_family`).
Bilingual labels are `(ru, en)` tuples resolved by `tr()`. Informational pages
(Shortcuts/About) set `Page.static = "_static_…"` → a custom dialog method.

### 4.5 Commands / shortcuts — `commands.py`  ✅

`Command` fields: `cmd_id, label_key, icon, shortcut, place, register, group`.
`place ∈ {view, rail, button, icon, hidden}` — `view` = a page in the left rail
(in rail section `group` ∈ `GROUPS`: monitor / tools), `rail` = the rail footer
(settings, help), `button` = header-bar action (watch, connect); `register=False`
makes a shortcut a display-only alias.

The old triangle (toolbar `action_*` signals + a `SHORTCUTS` dict for tooltips +
a separate `_setup_shortcuts` list for bindings) collapsed into one registry plus
one handler map:
- the toolbar builds its action buttons by walking `commands.BUTTONS`, and emits a
  single `command_triggered(cmd_id)` for every click;
- `gui_main._command_handler_map()` binds `cmd_id → method` **once** (most live on
  the window; `theme` is owned by the toolbar);
- `gui_main._dispatch_command()` is the one slot both clicks **and** shortcuts go
  through; `_setup_shortcuts()` registers a `QShortcut` per `commands.SHORTCUTS`
  entry, routing to the same dispatch;
- tooltips ("label (shortcut)") derive from the descriptor's `label_key` +
  `shortcut`.

**Add a page** → ONE `Command(..., place="view", group=...)` + its widget in
`_view_pages()`. **Add a header action** → ONE `Command(..., place="button")` +
one `cmd_id: self._handler` line in `_command_handler_map()`. Entry, global
shortcut and tooltip all follow.

Derived views (recomputed at import): `BY_ID`, `BUTTONS` (the rendered action
buttons), `SHORTCUTS` (commands whose shortcut is registered globally).

Parameterized / non-command events keep dedicated signals: rail
`brand_clicked` / `collapsed_changed`; header `link_clicked`, `theme_changed`,
`lang_changed`, `graphs_toggled`, `log_toggled`.

### 4.6 Transports — `transports.py`  ✅

`Transport` fields: `transport_id, label, create, describe`. `create(settings,
timeout)` builds the (not-yet-connected) pymodbus client; `describe(settings)`
returns the link string for status messages (e.g. `"COM1 (115200)"`).

`ModbusCore` is transport-agnostic — it imports `transports`, never a concrete
pymodbus class. `setup_connection` picks the descriptor (`transports.get(
settings["transport"])`) and snapshots `settings`; `_make_client()` delegates to
`self.transport.create(...)` and `_describe()` to `.describe(...)`. The read/write
PDU API (`read_holding_registers` / `write_register` in `_safe_read` /
`_safe_write_single`) is already transport-neutral, so nothing else changed.

**Add a transport** → add ONE `Transport(...)` to `TRANSPORTS` (a `create` +
`describe` pair). Nothing in ModbusCore changes.

Selection is the `transport` setting (`"serial"` default | `"tcp"`). **TCP is
implemented but intentionally not surfaced in the Settings UI** — the product is
serial-first (the connection dialog shows only Serial / RTU; see backlog history
"remove TCP everywhere"). Set `"transport": "tcp"` (+ `host`/`tcp_port`) in
app_settings.json to use it; surfacing it later = a selector `Field` in
`settings_schema.py`, no core change. Caveat: verbose frame logging assumes RTU
framing (slave + PDU + CRC16); over TCP the logged bytes are RTU-style while the
decoded data stays correct.

Derived views: `BY_ID`, `DEFAULT_ID` (`"serial"`); `get(id)` falls back to serial.

---

## 5. Data shapes

**Register dict** (one row of a profile; profile = `list[dict]` JSON):
```python
{"addr": int|hexstr, "name": str, "type": str,   # type ∈ datatypes.ALL_TYPES
 "rw": "R"|"RW", "length": int}                    # length only for variable types
```

**Table columns** (`gui_table.py`): the 7 dashboard columns (`COL_STATE..COL_NEW`,
0..6) are declared once in the `COLUMNS` registry (`Column(index, header_key,
show_key, resize)`), which `RegisterTable` uses to drive header text + visibility
from one place. Data columns use `resize="interactive"` (user-resizable; auto-fit
once per `populate()` via `_autofit_columns`) — NOT ResizeToContents/Stretch,
which would lock the borders. `profile_editor` keeps its own wider, structurally-different
schema (drag handle, RU+EN names, size/unit/default/comment); the two tables
overlap only on addr/type/access, so a single *shared* registry would be forced
— intentionally not merged.

**Macro namespace** (`macro_engine._make_globals`): `reg, read, write, read_all,
wait/sleep, record, log/print, now, timestamp` + restricted builtins
(`_SAFE_BUILTIN_NAMES`). No `import`, `open`, `eval`, `exec` — guard-rail, not a
hardened sandbox (single-operator tool).

---

## 6. History — what the registry migration already did

`datatypes.py` was extracted as the single source of truth and all consumers were
moved off their private `if/elif` chains:
- `modbus_core`: `should_poll` poll filter; `is_scalar/read_count/decode/encode/
  read_to_str` in read/write paths; 6 codecs re-exported for back-compat.
- `profile_editor`: imports `FIXED_TYPE_LEN/VARIABLE_TYPES/ALL_TYPES/TYPE_HINTS`;
  `type_size = datatypes.addr_span`.
- `macro_engine`: `_SCALAR_TYPES = datatypes.SCALAR_KEYS`.
- `gui_main`: 3 `_NON_POLL_TYPES` sites → `datatypes.is_area(...)`.
- `memory_viewer`: `words_per_element = datatypes.read_count(dtype)`.
Verified: codec parity vs old pack/unpack, read_count, area filter, dropdown
order, macro scalar filter, full app instantiation — all headless.

---

## 7. How to verify (headless, no .exe)

**The permanent test suite** lives in `tests/` (pytest; 769 tests). Run after
ANY change:
```bash
.venv/Scripts/python.exe -m pytest
```
Coverage: codecs (round-trip/sign/range), transports (serial parity vs manual
construction), settings (corrupt/merge, schema-key↔DEFAULT_SETTINGS drift
guard, i18n symmetry, **atomic-write + `.bak` recovery + corrupt-preserve**),
profile domain (normalize tolerance, overlap/dup-name validation), macro engine
(lookup variants, sandbox builtins), ModbusCore (poll filter, masked frame
logging + byte parity, honest write outcome), RegisterTable (populate/update/
view-modes/intent signals, **full-width fill + width-stealing resize**), editor
drag-reorder (**real mouse-path grip drag** + model handlers), LogPanel
(escape/filters/cap), full-app integration (build, theme/lang, overlays,
profile load). `tests/conftest.py` forces offscreen Qt and blocks all writes
to the real `app_settings.json`.

**Quick smoke** (no pytest needed):
```bash
QT_QPA_PLATFORM=offscreen PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -c "
from PyQt6.QtWidgets import QApplication; app=QApplication([])
import gui_main; w=gui_main.ModernScadaApp(); w.close(); print('ok')"
```

---

## 8. Backlog — remaining hardcode / future registry phases

The registry/architecture backlog is **clear** — every planned phase is done
(see below). The gui_main god-object dissolution is complete (1426→867, thin
coordinator).

**Settings are fully wired** (was: 14 dead keys). Now: `poll_rate` → pause
between poll cycles (registers read back-to-back, next cycle ≥ poll_interval;
queues drain every tick), `timeout` → client response timeout, all applied on
(re)connect; `interframe_delay` → pauses between write words / array chunks /
queue ops; `log_max`/`log_autoscroll`/`log_verbosity` → LogPanel (live via
`apply_settings()`; «min» drops TX/RX from the record); `load_last` gates the
startup profile load; `mono_values` + `highlight_changes` (change-flash) →
RegisterTable; `trend_grid` → pyqtgraph grids (cards + expand dialog).
Removed: `autosave` (per user), legacy `rx_timeout`/`tx_timeout`, `row_density`.

Optional polish: further gui_main splitting (profile-loading, overlay
management); onboarding-guide prose into `STRINGS`; surfacing the TCP transport
in the UI (**explicitly deferred by the user**); a "sim" transport descriptor
for hardware-free demo/testing (user is weighing it).

**Done:** data-type registry (`datatypes.py`); settings schema registry
(`settings_schema.py`); commands registry (`commands.py`); transport registry
(`transports.py`, serial + TCP — TCP not surfaced in UI yet); AppContext
(`app_context.py`) — adopted by gui_main + app-specific children; themes registry
(`theme_manager.THEMES`); `StateDotDelegate` reads theme tokens; dashboard column
registry (`gui_table.COLUMNS`; editor schema intentionally separate); log-panel
extraction (`gui_log.LogPanel`); register-grid MVC extraction (`gui_table.
RegisterTable`, emits intent signals; gui_main 1339→867); i18n label cleanup
(profile_editor + toolbar labels → `STRINGS`; fixed an `untitledProfile` ru bug);
settings-schema i18n migration (tuples → `STRINGS` keys, golden-parity proved);
COM-port auto-detect (editable combo via `Field.options_fn`); profile validation
(overlaps/dup-names — editor badge + load-time log warnings); permanent pytest
suite (`tests/`, 97 tests); opaque in-cell editor fix (styles.py — typed text no
longer overlays the old cell text); raw-frame console (`gui_console.py` — auto-CRC
command row + editable packet row, ↑/↓ history, `core.raw_queue`).

**Design pass (2026-07):** resizable dashboard columns (Interactive);
themed QScrollBar (was native white/dotted — styled `::add-page`/`::sub-page`/
`corner`); faster theme switch (`setUpdatesEnabled` batch + single `setHtml` log
rebuild, no double pass); unified SVG icon set (emoji/dingbats → `icons.py`, incl.
settings sidebar); restyled memory viewer; **live WYSIWYG drag-reorder** in the
profile editor (grip-drag, model reorders under the cursor, Esc cancels, one
undo/drag).

**Design pass v2 (2026-07-16) — corrections + polish:**
- **Drag regression fixed:** live repopulate on each move destroyed the cell
  widgets and dropped the *implicit* mouse-grab → the drag froze after one step.
  `ReorderableTable` now `viewport().grabMouse()` on drag start (survives the
  churn), releases on commit/cancel. Regressioned with a real mouse-path test.
- **Combo/spin arrows are real images, not CSS triangles.** Qt QSS renders a
  border-triangle as a filled box (the "rectangle arrow" bug). `icons.icon_url()`
  caches a themed chevron PNG per (name,color,size); `styles.py` uses
  `image: url(...)` for `QComboBox::down-arrow` and the spin arrows. **Rule: for
  Qt arrows use an image, never border-triangles.**
- **Dashboard table fills the viewport + width-stealing resize.** Content columns
  size to content; `CURRENT`/`NEW` (`_FLEX_COLS`) split the remainder equally;
  `RegisterTable._reflow_columns(exclude)` keeps total == viewport width — dragging
  one border makes the value columns yield/absorb, and once they hit `_MINW` the
  overflow is taken from the dragged column so **no horizontal scrollbar appears**.
  Header text centered. (`sectionResized`/`resizeEvent`→reflow; `_adjusting` guard.)
- **Themed message boxes** (`dialogs.themed_message`): native icon/chrome replaced
  by an `icons.py` glyph in a semantic colour + `QMessageBox` QSS. Migrated the
  editor/settings/macros confirmations.
- **Settings persistence hardened** (the "settings reset themselves" bug):
  `settings_manager.SETTINGS_FILE` is now an **absolute path** (was CWD-relative);
  `save_settings` writes **atomically** (temp+fsync+`os.replace`) keeping a `.bak`;
  `load_settings` recovers from `.bak` and preserves a corrupt file as `.corrupt`;
  `main.py` reads via `load_settings()` (no direct relative open). Font selector
  (`settings_schema` `font_choice` + `font_size`) already existed — kept.

**Polish pass v3 (2026-07-17) — v1.1.0:**
- **Version** now lives in `version.py` (`APP_VERSION`) — toolbar brand + About
  read it. Bump it with every meaningful batch (standing user instruction).
- **Card dialogs** (`dialogs._CardDialog`): frameless rounded card in the
  onboarding-guide style (no native title bar). ALL native
  QMessageBox.critical/warning/information calls migrated to
  `themed_message`/`themed_info` — zero native chrome anywhere.
- **Nav switcher** (superseded by the 2.2 rail): `commands.py` gained `place="view"` commands
  (`view_table`/`view_map`/`view_console`/`view_slave`, Ctrl+1..4) and a derived
  `VIEWS` tuple. The toolbar renders the cluster; the active view (or open
  settings/editor overlay) carries `[active="true"]` (QSS accent underline).
  `gui_views.py`: `ConsoleView` (full-screen exchange terminal fed by
  `gui_main._log` + its own `RawConsole`) and `SlaveStubView` (placeholder —
  slave mode itself is deferred by user instruction). `gui_main._switch_view`
  routes; overlays reject() first so unsaved-changes prompts still gate
  navigation. The Connect button flips label + green icon + `[connected="true"]`
  QSS when polling. The redundant "Настройки" sub-header inside the settings
  overlay was removed (nav highlight replaces it).
- **Drag-reorder v3 (grab anywhere, no lag)**: rows drag from ANY item cell
  (combos/spins keep their own mouse); during the drag only
  `verticalHeader().moveSection()` moves (view-level, zero widget churn — the
  per-crossing repopulate was the lag), a translucent ghost pixmap of the row
  follows the cursor (closed-hand cursor, edge auto-scroll). Data is permuted
  ONCE on release from `visual_order()`; Esc just resets the visual order.
- **Font picker with live preview** (`settings_schema` kind="font"): plain
  QComboBox listing `QFontDatabase.families()` with per-item FontRole (each
  family rendered in its own face); saved-but-uninstalled family stays
  selectable; legacy "inter"/"ibm"/"system" tokens round-trip unchanged.
  A `stFontPreview` sample under the picker tracks family AND the size slider.
- **Search box**: magnifier is an `icons.py` pixmap (recolored on restyle);
  the dead "DEC" suffix label was removed. NEW: Ctrl+F (hidden command) jumps
  to the Table view and focuses the search input.
- Shortcuts page (Settings) now matches reality: views Ctrl+1..4, Esc, F5,
  Ctrl+,/N/O/M/T, F1, Ctrl+F, F2, Tab/Shift+Tab.

**Polish pass v4 (2026-07-17) — v1.1.1:**
- **Nav slimmed:** the top bar keeps ONLY real views — Карта регистров
  (renamed from Таблица) | Консоль | Slave. The Профиль dropdown moved out of
  the top bar into the **map head bar** (`gui_main.btn_profile`, `#mhProfile`
  QSS) next to search: Создать новый / Открыть существующий / Недавние (menu
  reads `recent_profiles` straight from settings — toolbar `set_recent`
  plumbing deleted). `view_map` became a hidden command (Ctrl+2 still opens the
  editor); the editor overlay keeps the MAP nav button highlighted.
- **Session restore:** `_save_window_geometry` now also persists `last_view`,
  `open_trends` ({id,name,unit,win} per card) and the real log-panel height;
  `_restore_session_state` reopens trend cards (skipping registers absent from
  the restored profile), the log height and the active view. Keys in
  DEFAULT_SETTINGS: `open_trends`, `last_view`.
- **Drag eye-candy:** dashed **landing slot** drawn over the dragged row's
  current position + displaced rows **glide** to their new spot
  (QVariantAnimation 140 ms OutCubic, snapshot labels, ≤8 concurrent, overlays
  hidden during grabs). Still zero model churn during the drag.
- **Font picker v2:** type-to-search (editable combo + MatchContains
  completer); items added via one addItems() and per-item FontRole assigned in
  deferred 60-item chunks (Appearance tab no longer lags on open). **Font apply
  sped up**: `_on_settings_accepted` closes the overlay and defers the actual
  apply one event-loop pass (`_finish_settings_apply`) so the app-wide
  setStyleSheet never repolishes the 300-item font combo. (Do NOT force
  DeferredDelete inside the dialog's own signal — use-after-free.)
- **Cosmetics:** lang RU/EN segment is a fixed-height pill (was a full-height
  gray rectangle) with accent active state; QSlider restyled (accent fill +
  ring handle) — fixes the ugly light-theme sliders; the editor "Добавить
  регистр" label lost its duplicated textual "+".

**Polish pass v5 (2026-07-17, третья волна) — v1.1.2:**
- Settings overlay lost its header bar entirely (Esc = overlay shortcut in
  gui_main; F1 = the settings guide via `_show_help` delegation).
- **One segmented style everywhere**: `gui_widgets.Segmented` is a fixed-height
  (30 px) pill matching the toolbar RU/EN switch; active segment = accent.
  (The tall-gray-rectangle bug was the missing fixed height, same as langSeg.)
- **ConsoleView v2**: no header; the same filter tab bar as the bottom terminal
  (objectNames `logTabBar`/`logTab`, so one QSS rules both) with Все/TX/RX/Err
  filtering; active tab got a stronger highlight (tint + bold + underline).
- **Terminal height/collapse**: `v_splitter` stretch factors (0→1, 1→0) so the
  log keeps its PIXEL height on window resize (this was the wrong-remembered
  height); `splitterMoved` records the height and syncs the layout-menu state
  when dragged to zero (reopening now takes ONE click); a **status-bar chip**
  («Журнал ▴/▾», `MainStatusBar.btn_log` + `log_toggle_clicked`) is the big
  obvious toggle.
- **Portability**: `requirements.txt` added (Python 3.10+ floor — `X | None`
  unions); `settings_manager._settings_dir()` falls back to
  `%APPDATA%/ModbusReader` (with one-time migration) when the app dir is
  read-only; `README.md` covers setup on a fresh machine + Linux notes
  (`dialout` group). No hardcoded absolute paths (grep-verified). Perf
  baseline (offscreen): window build ~210 ms, populate 200 rows ~21 ms,
  200 value updates ~3 ms, theme switch ~410 ms.

**v1.2.0 (2026-07-17): configurable byte-order codecs.**
`byteorder.py` — pure permutation codecs for 16/32-bit values (orders
AB/BA and ABCD/BADC/CDAB/DCBA; all involutions, one permutation for both
encode and decode). `datatypes.py` pack/unpack functions are now thin wrappers
reading a module-level `_ORDERS` config; `configure_orders(settings)` is called
by AppContext on startup and on every settings update, so the editor, macros
and the poll loop all follow the user's choice live. Settings UI: new
"Кодеки — порядок байт" section on the Connection page (3 segmented pills).
Parity guarantee: the original implementation is inlined verbatim in
`tests/test_byteorder.py` as the golden reference; defaults are asserted equal
to it bit-for-bit, plus known wire vectors and round-trips for every order.
An existing `app_settings.json` without the new keys resolves to the exact
historical behavior (verified against the real user file).

**v1.3.0 (2026-07-17): scanner, sniffer, dashboard + smart nav.**
- **Smart toolbar**: which views show as labelled tabs = `settings
  ["pinned_views"]` (view_table always pinned); the rest live in the ⋯
  overflow menu (`gui_toolbar.btn_more`, icon "dots") which also hosts
  «Настроить вкладки» (checkable pin toggles → `pins_changed` → persisted).
  When the active view is unpinned, ⋯ carries the [active] highlight.
- **ScannerView** (`gui_scanner.py` + `scanner_engine.ScannerWorker`, Ctrl+4):
  device scan (slave-ID range ping) and register scan (address range on one
  ID). Built on a new core op kind **"probe"** (`ModbusCore._probe`) that
  classifies alive / exception(=alive) / silent; `request_op(...)` and
  `_safe_read/_read_value` gained a per-op `slave=` override (scans of a
  FOREIGN slave never emit data_updated into the main table). The port stays
  owned by the core thread — the worker only enqueues sync ops.
- **SnifferView** (`gui_sniffer.py` + `sniffer_core.py`, Ctrl+5): passive RTU
  tap. Pure, tested pieces: `crc16` (0xA001), `decode_frame` (FC 03/04/06/10 +
  exceptions, request/response heuristics); `SnifferWorker` owns its OWN
  serial port, splits the stream on t3.5 silence (min 1.75 ms) and never
  transmits. One-port-one-owner enforced in the view: refuses the master's
  port while polling.
- **DashboardView** (`gui_dash.py`, Ctrl+6): mini-HMI. Widget kinds value /
  led / bar / gauge (270° dial), custom-painted with live theme tokens; cards
  bound by reg_id, fed from the same `value_sampled` stream as trends;
  persisted in `settings["dash_widgets"]`; add-dialog in the frameless-card
  style. Slave stub moved to Ctrl+7.

**v1.4.0 (2026-07-17): dashboard v2 — the full mini-HMI.**
`gui_dash.py` rewritten around MANUAL card layout (no QGridLayout) so
re-ordering animates: cards drag from anywhere (ghost pixmap + dashed slot,
live re-flow at 160 ms OutCubic — the profile-editor pattern), order persists.
`WidgetDialog` adds AND edits (double-click / context menu; fields follow the
kind: min/max for bar/gauge, threshold+invert toggle for LED, optional lo/hi
alarms for the rest); context menu also duplicates. Pure helpers `alarm_state`
/ `led_on` drive recoloring: alarm = error border + red value/fill/arc; a
2-second watchdog dims cards with no fresh sample for 5 s (honest "no data");
value cards draw a 60-sample sparkline. Card kinds: value / led / bar /
gauge (270° dial with min/max scale labels). Everything still binds by
reg_id to the value_sampled feed and persists in settings["dash_widgets"].

**v1.5.0 (2026-07-18): profile v2 (scaling/enum) + dashboard v3 (free layout,
wired automation).**
- **Versioned formats** — `formats.py`: a small envelope (`format`, `version`)
  plus a **migration registry** per document. `migrate_profile` detects the
  on-disk shape (bare array = v0, `{"registers":[…]}` = v1, envelope = v2) and
  runs the chain up to the current version, so **files written by any past
  build open forever**. `profile_manager.load_profile_data` and the editor both
  route through it. Adding a format change = ONE migration + a version bump;
  never edit an old migration. A project track (`migrate_project`, .mbproj)
  exists with the embedded profile migrated on its own track.
- **Engineering units** — `scaling.py` (pure): `displayed = raw*scale + offset`
  plus an enum map (`{"0":"Стоп"}`) as *register* properties. The table shows
  engineering values/labels and converts back to RAW on write; the dashboard
  uses the same helpers. Identity defaults mean old profiles are untouched.
  Edited via the row context menu → «Инженерные единицы…»
  (`gui_scaling_dialog.py`).
- **Dashboard v3** — `dash_model.py` (pure: kind registry, snapping math,
  automation graph) + `gui_dash.py` (paint/interaction) + `gui_dash_dialog.py`.
  * **Two modes**: Run (widgets live) / Edit (arrange). **No device write can
    happen in edit mode** — timers are stopped and controls are inert.
  * **Free placement** with PowerPoint-style alignment: edges/centers snap to
    neighbours and the canvas centre, guides are drawn, Alt disables snapping,
    everything else lands on a 4 px grid. Cards resize from the corner.
  * **Wired automation**:each widget has one in/out port; drag from the right dot
    to a left dot to link. `Graph.propagate` is breadth-first with a visited
    set + depth guard, so timer → button → timer can't hang the UI.
  * New kinds: **button** (writes a value), **input** (type + Enter),
    **toggle** (two values), **timer** (periodic pulse), **label**.
  * Legacy v2 cards (no x/y) are laid out via `flow_positions` so an existing
    dashboard looks unchanged.
  * Perf: canvas repaint is clipped to the exposed rect; wire hit-testing does
    a bounding-box reject first (2250 ms → 170 ms per 500 picks).

**v1.6.0 (2026-07-18): dashboard v4 + multiple dashboards + .mbproj / .mbdash.**
- **Add-widget crash fixed** — the dialog returned `x/y/w/h = None` for a NEW
  widget and `int(None)` raised *inside* the click handler, so nothing
  appeared. The dialog now omits absent geometry and `_make_card` treats
  falsy geometry as missing. Guarded by a test that drives the real
  dialog → add path (the old tests called `_make_card` directly and missed it).
- **Kind picker = tiles** (`KindTile`, a QToolButton with
  `ToolButtonTextUnderIcon`) grouped by `dash_model.KIND_GROUPS`, replacing a
  long combo with in-list headers. Each kind carries its `icon` in the registry.
- **Colour bug** — plain `QWidget` row containers inherited the global
  `QWidget { background: bg_1 }` and painted lighter blocks inside the bg_2
  dialog card. All containers are now `#dlgRow` → transparent.
- **Zoom & pan** — `zoom_by`/`zoom_reset` (Ctrl+wheel around the cursor,
  Ctrl+± / Ctrl+0), middle-button drag pans. Cards are placed at
  `logical × zoom`; **cfg keeps LOGICAL geometry**, so persistence, snapping
  and nudging are zoom-independent (`_persist` must never read `card.x()`).
- **Hotkeys** — Ctrl+E toggle edit, Del delete widget/wire, Ctrl+D duplicate,
  arrows nudge (Shift ×10), Esc clears selection.
- **Wire UX** — crosshair cursor over the out-port and while wiring, every
  legal target's input port glows (hover = outline + bigger dot), the live
  wire is marching-ants dashed and **snaps to the hovered port**; dropping
  flashes the target. Fixed a real bug: `_on_wire_finished` cleared
  `_wire_src` before `_target_at()` used it, so **no wire could ever be
  created by mouse** — caught by the new mouse-path test.
- **Multiple dashboards** — settings hold `dashboards: [{name, widgets,
  links}]` + `dash_index`; the pre-1.6 flat `dash_widgets`/`dash_links` are
  migrated on load (and kept in sync for safety). Toolbar: a dashboard combo +
  ⋯ menu (new / rename / duplicate / delete / export / import).
- **File formats** — `.mbdash` (one dashboard, own version + migration track)
  and **`.mbproj`** (connection + register profile + ALL dashboards + layout).
  `make_project` takes a dashboard LIST; `migrate_project` accepts the legacy
  flat `dashboard:` key. `gui_main._save_project` / `_open_project` /
  `apply_project` wire it to the head-bar Профиль menu; opening a project
  restores settings, map and dashboards but never auto-connects the port.
- Perf (40 cards / 30 wires): repaint 14 ms (grid is a cached tile), zoom step
  0.23 ms, drag handler 0.19 ms/event, board switch 4 ms, value update 5 µs.

**v1.7.0 (2026-08-12): dashboard v5/v6 — five new block kinds, pulse
visualisation, whole-app sweep.**
- **Drag fix** — `move_started` now carries the in-card press point; the view
  keeps THAT point under the cursor (`raw = (local - grab) / zoom`). Before, a
  drag teleported the card so the cursor sat at its top centre. Pinned by
  `test_drag_keeps_the_grabbed_point_under_the_cursor` + a zoom-aware twin;
  the test helper drives FIXED GLOBAL positions because the card moves under
  the cursor and local coordinates would compound.
- **Navigation** — wheel zooms without Ctrl, right/middle drag pans (a right
  click that moved <6 px is still the context menu), and the canvas is
  centre-aligned in its scroll area so zooming feels centred, not top-left.
- **Five new kinds** (14 total). Each is ONE `WidgetKind` entry plus a paint
  branch; `WidgetKind.group` now drives the picker sections, so
  `KIND_GROUPS` / `DISPLAY_KINDS` / `CONTROL_KINDS` / `LOGIC_KINDS` are all
  derived — a new kind cannot be missing from the picker.
  * **bits** — a 16-bit status word as 16 cells, MSB left. Read-only.
  * **chart** — a real mini-trend (240-sample window, area fill, min/max
    labels) vs the value card's 60-sample sparkline.
  * **slider** — drag a setpoint, write on RELEASE (opt-in `live` writes
    while dragging); `step` quantises the value.
  * **select** — named values from the register's enum, snapshotted into the
    cfg at edit time so labels survive without the profile loaded.
  * **gate** — a condition node (`dm.gate_pass`, pure): passes the pulse only
    while the watched register satisfies `cond`/`cmp`. **Fails closed** — an
    unreadable value never passes, or a disconnected device would keep firing
    writes. Implemented via `Graph.propagate(..., blocked=…)`: a blocked node
    still activates (so it flashes) but the chain stops there.
- **Pulse visualisation** — after a propagation the traversed links glow and
  send a dot along the curve for `PULSE_TRAVEL`; a blocked branch stays dark,
  which is how you read where the automation actually went.
- **Painting polish** — shallow card gradient, radial-gradient LED lamp, gauge
  tick marks, gradient bar with alarm-threshold ticks, an explicit stale dot in
  the corner, and `flash()` lights up on the SAME frame (it used to wait for
  the animation's first `valueChanged` and drop the first frame).
- **Picker layout** — 5 tiles/row in a `QGridLayout` (a single row clipped
  once the display group grew); a test asserts no tile elides or overflows and
  the dialog stays ≤740 px in both languages.
- **Perf** — `update_value` now uses a lazily built `reg_id → [card]` index
  (invalidated on create/destroy/edit): a 300-register poll cycle against a
  40-card board went 9 ms → 0.28 ms. Per-kind repaint worst case: chart
  1.8 ms, bits 0.9 ms, everything else <0.5 ms.
- **Sweep** — every deferred call now goes through `qt_utils.later` (the
  guarded `singleShot`); unused imports removed app-wide; verified no object
  growth over repeated settings open/close and board switching.

**v1.8.0 (2026-08-13): interaction fixes, appearance system, scanner/sniffer
hardening.**
- **Dashboard interaction** — three real bugs, all reproduced first:
  * *Phantom drag.* The press before a double-click armed a move; the modal
    edit dialog swallowed the release, so afterwards the card followed the
    cursor with no button held. Compounded by Qt's default
    `mouseDoubleClickEvent`, which **forwards to `mousePressEvent`** and
    re-armed the very gesture we cancelled — the handler must not call
    `super()`. A move event with no button down now cancels any gesture,
    which closes the whole "lost release" class (dialogs, menus, focus loss).
  * *Teleport.* Removed the `QPoint(w*z/2, 18)` fallback grab point: with no
    recorded grab, nothing moves at all.
  * *Dead pan.* `pan_by` moves the scrollbars, but the canvas was exactly the
    size of its viewport → zero range → nothing happened; and a right-drag
    started over a card never reached the canvas. The canvas is now a SHEET
    (1600×1000 logical, always ≥ viewport + margin) and cards forward
    middle/right drags to it via `pan_press/pan_move/pan_release`.
- **Zoom scales content, not just the box** — `paintEvent` applies
  `p.scale(z, z)` once and every painter works in LOGICAL pixels (`pw`/`ph`,
  `prect()`); ports, handles, slider tracks and the input field's font scale
  with it, and mouse coordinates convert back via `to_logical`. Verified by
  rendering 1× upscaled against a real 2× render.
- **Card animations removed** — a `QVariantAnimation` per card could outlive
  its card and crash the process (access violation, not an exception). The
  view's single repaint timer now fades every card (`decay_pulse`) and stops
  itself when nothing is animating. This also killed a stream of
  `TypeError: missing argument '_self'` which had been *masking* the crash.
- **Widget dialog** — was 541…710 px depending on kind, which read as random
  padding. Fields live in a fixed-height host with uniform 48 px rows; the
  dialog is a constant 687 px in both languages. Control kinds now only offer
  **writable** registers (`rw` contains "W"), with an explicit empty state.
- **Appearance system** (`theme_manager.py`): three layers, all optional and
  all backwards-compatible.
  * `SCHEMES` — whole surface families (graphite/carbon/midnight/slate,
    paper/snow/sand). A scheme restates only the ramp; semantics and graph
    colours stay shared. `graphite`/`paper` are byte-identical to the old look.
  * `CONTRAST_LEVELS` — soft/normal/high pushes surfaces and text apart by a
    measured amount. Tests assert body text clears WCAG AA on every
    scheme × contrast combination.
  * 12 accents, each with a dark AND a light value; `accent_fg` is *derived*
    by comparing contrast ratios, so no accent can carry unreadable text
    (violet was at 3.4:1 with the old fixed threshold).
  * `set_active()` publishes the appearance so the ~20 call sites that only
    know a theme name still match the window.
- **Font safety** (`fonts.py`) — symbol families (Wingdings, the Segoe icon
  fonts) are filtered out of the picker using Qt's own writing-system
  metadata, the saved value is validated on load, a family without Cyrillic
  warns, and a Reset button restores a known-good face. Picking a dingbat font
  used to be unrecoverable: the settings page itself became unreadable.
- **Scanner/sniffer hardening** — the user cannot test these on hardware, so
  the logic is now pinned by 24 tests with a fake core and a fake serial port.
  Fixed: switching language **wiped the scan results** (`_on_mode_changed`
  cleared the table from `retranslate`) and replaced the summary with "ready".
  New `carve_frames()` splits merged captures on CRC boundaries — timing alone
  cannot separate back-to-back frames — and a read failure mid-capture is
  reported instead of killing the thread.
- **Translations, second pass** — the register table's whole context menu, the
  status bar, the log placeholder and the memory viewer were hardcoded
  English. A guard test now scans the arguments of Qt text setters and fails
  on any literal prose (verified against a deliberately reintroduced regress).
- Guides for the scanner, sniffer and dashboard; F1 resolves to the visible
  view, not just to overlays.

**v1.8.1: the appearance actually applies.**
The v1.8.0 scheme system was measurably invisible. Two separate causes, both
found by rendering the real window and diffing pixels rather than by reading
code:
1. **`main.py` built the global stylesheet before anything published the saved
   appearance.** `get_stylesheet` reads the scheme/contrast from
   `theme_manager`'s active state, which was still at its defaults at that
   point, and the window never regenerated the QSS afterwards. So the app
   started in the DEFAULT scheme while dialogs constructed later (after
   `AppContext.__init__` → `sync_appearance()`) used the SAVED one — hence the
   report "only the widget dialog's background changes". `main()` now calls
   `set_active()` before `get_stylesheet()`, pinned by
   `test_startup_publishes_the_saved_appearance`.
2. **The token deltas were too small to see.** Measured against the rendered
   window: carbon changed **0.0 %** of pixels, midnight 2.0 %, contrast
   soft→high 2.2 %. The dark ramps all sat within 3–16 RGB steps of each other
   and `text_1` did not move at all. Retuned: carbon is true black, midnight
   is unmistakably blue, slate is a genuinely lighter dark, and each scheme
   carries its OWN text ramp. Now 80 / 99 / 99 % of pixels change.
   `test_every_scheme_is_visibly_distinct_from_the_others` fails if any two
   ramps come back within 14 steps.
3. **Contrast now drives TEXT.** A dark background is already near-black, so
   darkening it further is imperceptible; "dull" lives in secondary text.
   `_INK_SHIFT` moves text_2/3/4 furthest and text_1 too. Secondary text goes
   from 7.8:1 to 14.8:1 between soft and high — the pixel-percentage metric
   understates this because text is only ~2 % of the screen, so the test
   asserts the WCAG ratio instead.
- **Live preview** — `SettingsDialog.appearance_changed` restyles the whole
  window while the dialog is open (debounced 90 ms, ~150 ms per apply) without
  touching saved settings; Cancel restores the saved look. Judging a scheme
  from a swatch in a settings row is not possible.

**v1.9.0: security, input robustness, coverage.**
Findings were *verified* against the running code before being fixed, and each
one is now pinned by a test.

- **Macro sandbox escape (real, exploitable).** Withheld builtins were not a
  boundary: a two-line script reached the interpreter via
  ``().__class__.__base__.__subclasses__()`` → ``catch_warnings`` →
  ``_module.__builtins__['__import__']('os')``. Verified working against this
  exact namespace. Fixed at the root with a **parse-time AST gate**
  (`macro_engine._reject_unsafe`): no `import`, no dunder names. The
  safe-builtins list deliberately contains no `getattr`/`vars`/`dir`/`globals`/
  `type`, so there is no route around it, and a rejected script never executes
  a statement (test asserts it cannot even reach the device).
  Still documented as a guard-rail, not a boundary.
- **Macros can be loaded from a .py file**, i.e. somebody else's code. The app
  now asks for confirmation once before running a script that came from disk;
  code typed in the editor is not nagged about.
- **A runaway macro could not be stopped.** Stop was only polled inside the
  domain API, so `while True: pass` ignored it and the thread outlived every
  attempt to quit. A line tracer (`MacroRunner._trace`, checked every 200
  lines, macro frames only) makes Stop work regardless of what the script does.
- **Settings backup pointed at the wrong file.** `_BACKUP_FILE` was a constant
  computed at IMPORT from `SETTINGS_FILE`; anything that repointed the settings
  path afterwards (a test, a second install, the %APPDATA% fallback) kept
  reading and OVERWRITING the backup of the original path. Now derived at call
  time. `conftest` keeps the real `save_settings` reachable as
  `real_save_settings` so this can be tested without risking the live file.
- **File-loader robustness** — 30 hostile inputs through the real loaders.
  Unhelpful exceptions became explicit messages (the UI prints `str(e)`):
  `KeyError: -1` for a negative version, `OverflowError` for `1e400` as an
  address, `UnicodeDecodeError` for a non-UTF-8 file. Addresses are clamped to
  16 bits and lengths to `0xFFFF` — an absurd `length` would otherwise have the
  poll loop ask the device for gigabytes. `migrate_project({})` used to yield a
  valid-looking EMPTY project, which reads as data loss; a project must now
  carry at least one project key.
- **The i18n guard missed dialogs.** It only inspected Qt text setters, so a
  screenful of hardcoded Russian in the profile-loading error dialogs went
  unnoticed. `themed_info`/`themed_message` are now covered too.
- **Coverage** — 397 tests (was 295). New: macro safety, file robustness,
  widgets/dialogs/icons/guides/trends. Modules still without direct tests:
  `gui_macros`, `memory_viewer`, `gui_statusbar`, `bundle_project`.
- **Perf** — verified linear (no quadratic paths) for `find_overlaps`,
  `find_duplicate_names`, `normalize_registers`; table populate 124 ms at 2000
  registers, 2000 value updates 16 ms.

**v1.10.0: import a register map from CSV / XLSX.**
`mapimport.py` (pure) + `gui_import_dialog.py` (rendering), reached from the
map editor's toolbar. Vendors ship spreadsheets, not JSON, so this is how a map
normally enters the app for the first time.
- **Guess, then let the user correct.** The header row is detected, columns are
  matched against RU+EN hints, and every column gets a field picker. The guess
  is a convenience; the mapping is the contract, and the preview re-renders on
  every change.
- **Encoding and delimiter are real problems.** Vendor CSVs are routinely
  cp1251 or carry a UTF-8 BOM; `;` is the norm where the decimal separator is a
  comma. Both are detected, with a frequency count behind `csv.Sniffer`.
- **The address convention is the dangerous part.** A datasheet may write
  `40001` (4x), `0x1F`, `1Fh`, `$10` or plain decimal. Reading a 4x sheet raw
  shifts the ENTIRE map by one — far worse than failing. So it is an explicit
  choice, never a silent guess; and because `40001` is itself a legal 16-bit
  address, raw mode is obeyed but a sheet that *looks* like 4x is flagged
  (`impMaybe4x`).
- **Header detection is deliberately strict**: ANY numeric cell means "data".
  A looser rule read `["16", "Температура", "FLOAT"]` as a header, which
  silently drops the first register. Erring the other way is visible and
  correctable.
- **One bad row never costs the import.** Rows that yield no address are
  reported with their FILE line number and skipped; duplicate addresses are
  reported but kept. Problems travel as `(line, i18n key, params)` so the pure
  module stays language-free.
- Types and access are normalised from free text (`uint16`/`word`/`DWORD`/
  `REAL`/`чтение`…) into registry keys, with a test asserting every alias
  targets a real `datatypes` entry.
- 89 tests; the dialog is driven for real against a cp1251 vendor sheet.

**v1.11.0: snapshot / compare (Ctrl+7).**
`snapshots.py` (pure) + `gui_snapshot.py` (view). Freeze every current value,
change something on the device, compare. The commissioning question "what did
that parameter actually change?" is unanswerable by eye across a hundred rows.
- **Comparison is where the subtlety is**, so it is the pure part:
  * A register present on only ONE side is `added`/`removed`, never `changed` —
    calling it a change would be a lie, and those rows are exactly what an
    operator needs to notice after editing a map.
  * Values compare NUMERICALLY when both sides parse as numbers ("5" == "5.0"),
    textually otherwise (enum labels, "—").
  * The float tolerance exists only to absorb round-trip noise
    ("0.30000000000000004" vs "0.3"). The first version used 1e-9 relative,
    which made 1e9 and 1e9+1 compare equal — hiding a whole unit of change on a
    large register. It is now 1e-12.
- `sn.make` stores unread registers as `None` rather than skipping them, so
  "never read" stays distinguishable from "gone from the map"; a row with no
  `addr` key at all is dropped instead of defaulting to a phantom register 0.
- Snapshots save/load as `.mbsnap` with the usual versioned envelope and
  readable refusals; the view filters by state and shows a numeric delta
  (blank on unchanged rows — a "+0" on every untouched row buries the real
  ones). The summary re-renders on a language switch, the failure mode already
  fixed twice elsewhere.
- Values come from `RegisterTable.current_values()`, i.e. the DISPLAYED text,
  so scaling and enum labels are already applied and a comparison speaks the
  same language as the screen.
- 55 tests; performance at 5000 registers: snapshot 7 ms, compare 53 ms.

**v1.12.0: data logger (Ctrl+8).**
`datalog.py` (writer) + `gui_logger.py` (view). Long unattended runs to CSV —
the one feature people actually go to Modbus Poll for.
Format decisions, chosen because they are painful to change once files exist:
- **Wide** (one column per register, one row per sample), not long. Polling is
  cyclic and synchronised, so every register genuinely has a value at the same
  instant and the file charts in Excel with no pivoting. The cost is an honest
  one: the column set is FIXED when the file opens, so adding a register means
  stopping and starting — stated in the UI hint rather than papered over.
- **UTF-8 with BOM.** Without it Excel on Windows decodes as cp1251 and every
  Cyrillic name is mojibake, which defeats the point of choosing CSV.
  `;` + decimal comma by default (RU locale), switchable.
- **Rotation by size** into `name_002.csv`. An overnight run at 200 ms is
  ~400 000 rows; Excel gives up past ~1M.
- **Buffered, flushed on a row/time budget**, always on close: flushing every
  sample would add latency to the poll path, and a crash costs a few seconds.
- **Never raises at the caller.** A full disk or a file locked by Excel sets
  `last_error`, stops the timer and shows why. `open()` can raise ValueError
  (embedded null) as well as OSError — both are caught.
- Sampling runs on the VIEW's own timer, not the poll callback: a row must be a
  coherent snapshot of every register, and writing per incoming value would
  produce one row per register with a single filled cell.
- A missing value is an empty cell, never a shifted row (a test pins that every
  row has identical width whatever the input).
- 31 tests. Throughput: 200 columns × 10 000 rows in 1.65 s (165 µs/row).

**v1.13.0: dashboard selection, project-first workflow, chrome cleanup.**

*Dashboard multi-select (`gui_dash.py`).* Selection became a LIST, not a uid.
`DashboardView._sel` is click order; the last entry is the "primary" (the anchor
of a drag). `sel_uid` survives as a property over it, so the older
single-widget call sites and their tests needed no edits. `_select()` is the
single writer that keeps the list, each card's highlight and the repaint in
step, and it drops uids with no card so a stale reference can never leave a
highlight nobody can clear.
- Rubber band lives on the canvas in canvas pixels; it INTERSECTS rather than
  contains, because requiring containment makes it impossible to band a row of
  widgets without also enclosing everything beneath them.
- Group move captures every member's origin at drag start and applies one
  shared delta. Applying per-frame deltas to live positions accumulates
  rounding and the group shears apart over a long drag. Only the primary snaps;
  `_others()` excludes the whole moving group, or a group snaps to itself and
  glues solid.
- The clipboard lives on the view, so a copy survives switching dashboards —
  which is the main reason to have copy. `_snapshot()` takes the widgets AND
  the wires **between** them; a wire with one end outside the set is DROPPED,
  because pasting it would silently wire a duplicate into the original's target
  (i.e. into live equipment). Both halves of that rule are pinned by tests.
- 29 tests, driving real QMouseEvent/QKeyEvent through the real widgets. Two
  deliberate mutations (skip the wire remap; let a click collapse the group)
  were each caught by exactly one test.

*Project-first (`gui_main.py`).* A project (`.mbproj`) is the workspace; the
register map is one part of it that also happens to be openable alone. The
head-bar menu now leads with New/Open/Save/Save-as project plus its own recents
list, then a separate captioned section for the bare `.json` map. The head-bar
button shows the OPEN PROJECT'S NAME — before this the window looked identical
inside and outside a project, which is most of why the two file kinds read as
unrelated mysteries. `_save_project` overwrites the file it came from; only a
never-written project asks where to go. New project keeps connection settings
(they describe the bench, not the project) and confirms before discarding a map.
19 tests, with an autouse fixture that turns any unexpected modal into a
failure instead of the mystery hang a modal causes under offscreen Qt.

*Appearance speed.* Measured, not guessed: `QApplication.setStyleSheet` is 93 %
of an appearance change and scales with WIDGET COUNT, not stylesheet size (a
46-char sheet on the same tree costs 280 ms against 436 ms for the full 24 KB).
Three fixes, each verified by counting `setStyleSheet` calls:
- `qt_utils.debounce()` — a coalescing timer. `later()` queues N runs for N
  clicks, so clicking through four schemes ran four full restyles back to back;
  that is what "3-5 seconds" was. Now one.
- Skip the restyle when the computed QSS equals the current one.
- Cancel/Esc closes the settings page BEFORE restoring the appearance, so the
  restyle walks 289 widgets instead of 761.
Also: `icons.pixmap()` memoises by (name, colour, size, dpr).

*Chrome.* The contrast control now moves TEXT and barely moves lines: on
carbon+high a "soft" separator had been pushed to `#4c4c4c`, brighter than the
text it separated. `_INK_SHIFT` line travel dropped from 0.22/0.46/0.40 to
0.06/0.16/0.30. On top of that the top bar, the map head bar and the log tab bar
lost their bottom rules (a tonal step already draws that edge — the rule was the
same boundary drawn twice), the toolbar's three vertical dividers and the RU/EN
pill's ring are gone, the table header/gutter/corner share one surface instead
of two, scrollbar handles rest on `line` and only brighten on hover, the
scanner's progress bar is hidden unless a scan is running, and the snapshot view
shows an empty state instead of a bare six-column grid.

**v1.14.0: band-select fix, menu language, logger as a monitor.**
- *Rubber band, all four directions.* It was measured from the previous rect's
  `topLeft()`, but after `normalized()` that is the geometric corner, not the
  anchor — so each frame the band covered only the last two cursor positions,
  and an up/left drag collapsed it. Now anchored in `_band_from`. The first
  test for this passed against the broken code because it used ONE big move;
  a real drag is many small ones, and `_drag_band()` in the test now does that.
  Down-right still worked before the fix, which is exactly what was reported.
- *Menu language.* Section captions are two-word signposts, not sentences in
  capitals: a caption in caps reads as a warning banner, and the explanation
  belongs in a tooltip where it costs nothing until wanted. Disabled menu items
  needed their own QSS — Qt was painting them from the disabled palette, which
  on a tinted accent came out salmon red, so headings looked like errors.
  Ctrl+N/O/S now belong to the PROJECT (the document); the bare register map
  takes Ctrl+Shift+N/O.
- *Logger is a monitor, not a form.* Four fields on an empty page said nothing
  about an eight-hour run. Before starting it lists the columns the file will
  have plus a rows/bytes-per-hour forecast — the column set freezes when the
  file opens, so this is the last moment to notice a missing register. While
  running it shows the rows as they land, newest first (scrolling to the bottom
  of 40 000 rows to find the current one is not monitoring), bounded to
  `PREVIEW_ROWS`. Status carries rows, size, elapsed, part and file. 25 tests.

**v2.0.0 (2026-10-13): full audit — the first final release.**
Every finding was reproduced on the running code first; each is pinned by
`tests/test_audit_v2.py` (712 tests in total). The user-facing summary is in
`CHANGELOG.md`; the engineering rules that came out of it:

- **One log, two views.** `gui_log.LogStore` is the only buffer; the bottom
  `LogPanel` and the full-screen `ConsoleView` are two `LogView`s on it (the
  old structural duplicate — two buffers with different cap/verbosity rules —
  is gone). The raw-console history lives in `settings["console_history"]`
  and is REPLACED, never mutated, so both consoles share it.
- **Parity goes through `transports.parity_code()`** — it accepts every
  stored spelling ("Even (E)", "Even", "E"). The old map only knew "Even", so
  the value the Settings page saves fell back to "N": every link was 8N1.
  The sniffer uses the same normaliser.
- **Editor addressing is a chain, not a renumbering** (`profile_manager.
  chained_flags`/`rechain`). Flags are taken BEFORE an edit; chained rows are
  re-packed after it, explicit rows (after a gap / out of order) keep their
  address, the first row is the anchor (no longer forced to 0). A drag
  re-packs only a fully contiguous map. The address cell is editable.
- **`gui_main._set_profile(regs, path)` is the one entry point** for "this is
  the map now": table, poll list, status bar, logger plan and
  `last_profile_path` all follow it. `last_profile_path` is set only while the
  map IS that file; a restart restores it, else the open project's map (only
  the map — connection/dashboards are already newer in the settings).
- **The core speaks the UI language** (`ModbusCore.t`, swapped by
  `AppContext.set_lang`); messages are `core*` i18n keys. A failed open logs
  ERR and emits `status_changed(False, "")`. On shutdown `_drain_queues()`
  answers waiting ops, DROPS queued writes (never sent on a later connect) and
  releases pending memory reads. `start()` resets `_abort`; `stop()` sets it.
- **`RegisterTable.current_values()` returns clean values** (engineering
  number or enum label, no unit, always decimal). `fresh_only=True` (the
  logger) skips registers not read since the link came up. `update_value`
  wraps its blockSignals in try/finally and never emits non-finite samples.
  The table has a `t` property — its context menu called `self.t` without one.
- **Status lines carry state, not emoji:** `qt_utils.set_state(label,
  "error")` + QSS `QLabel#mhCrumb[state="error"]`.
- **Ctrl+S belongs to the window** and is routed to the map editor while it is
  open (`_save_shortcut`) — two window-level shortcuts on one key are
  ambiguous in Qt and neither fires.
- **Shortcuts page is generated** from `commands.COMMANDS` (+ a small table of
  widget-local keys) — it had drifted three versions behind.
- **Settings defaults are deep-copied** by `load_settings()`; nothing may
  mutate a settings list in place that could still be a DEFAULT_SETTINGS one.
- `main.py` writes unhandled tracebacks to `modbusreader_errors.log` next to
  the settings; the packaged build has no console.
- Tests never touch the developer's real settings: `conftest` points
  `SETTINGS_FILE` at a temp dir for the whole session. The i18n guard also
  checks widget constructors (`QLabel("…")`) and dialog titles.

**v2.2.0 (2026-10-15): the window redesigned as a professional tool.**
Pinned by `tests/test_nav_views.py` (rail, header, macros page).

- **Frame**: `NavRail` (left, every page always visible, two groups: monitor =
  map + dashboard, tools = console … emulator; settings + help in the footer;
  collapsible to icons, `settings["rail_collapsed"]`; a green busy dot on a
  tool that works in the background, sampled by the 500 ms stats timer in
  `_refresh_activity`) + `MainToolBar` as a HEADER bar ("project ▾ / page",
  the link chip "COM3 · 115200 · 8N1 · ID 10" → settings, Connect as the one
  accent-filled primary button, then watch / RU|EN / theme / layout). The ⋯
  overflow and `pinned_views` are gone from the UI (the key stays in settings
  and projects for round-trips). `_set_nav(id)` keeps the rail highlight and
  the header title together; overlays pass their nav id ("view_map" lights
  the map page and titles the editor).
- **Macros are a page** (`MacroWindow(embedded=True)`, `view_macros`, Ctrl+M).
  A running macro survives page switches; `confirm_close()` / `shutdown()`
  carry the old close prompts to window close.
- **Project dropdown** moved from the map head bar to the header (it owns the
  map, the boards AND the link). The map head bar is now the page toolbar:
  search, count, "Edit map".
- **Empty states** (`gui_widgets.EmptyState`: tile + title + sentence +
  first action; `EmptyOverlay` lays it over a table/scroll viewport while it
  is empty, driven by the model's row signals) on the map (open project / open
  map / create map), scanner, sniffer, dashboard; snapshot / logger / emulator
  swapped their grey sentence for it (`setText` stays compatible).
- **Visual system**: chrome (rail, header, status bar) bg_1 with whisper
  `line_soft` edges, data bg_0; one button language (accent-filled primary,
  quiet ghost secondaries; hover = `_mix(accent, text_1, .16)`, no white
  flash); grid text hierarchy (`RegisterTable._recolor`: name/value text_1,
  address/type text_3, non-writable access text_4 — re-run on theme change);
  every data table left-aligned (centred cells in wide columns read as a
  toy); read-only rows leave "New value" EMPTY instead of a dash; a long name
  elides before the values leave the screen (`_reflow_columns` takes viewport
  overflow out of NAME); settings form capped at a 860 px column; the macro
  editor is finally monospace (the global font rule overrode `setFont`).
- **Trend card** (`gui_trends.TrendCard`, rebuilt): big current value
  (`#gValue`), delta over the window, min/max/avg in one line — all with ONE
  precision from `decimals_for(window)` and `fmt_value()` (thin-space
  thousands, exponent only < 1e-4 or ≥ 1e9; the expanded view uses the same);
  Y ticks at the window's real min/mid/max inside an 18 % pad (ticks at the
  exact range edges were clipped); gradient fill (`_gradient_brush`,
  ObjectBoundingMode) + dot with halo; y-only grid on cards
  (`_apply_grid(vertical=False)`); states waiting / live / stale (no sample
  for `STALE_AFTER` = 5 s, checked by a 1 s timer — value and line fade) /
  paused, shown through `[state]` QSS properties; grip appears on hover in
  the series-colour dot's slot; explicit expand button.
- **Polish rules** (`tests/test_polish_v22.py`): no native-chrome dialogs —
  text input is `dialogs.themed_input` (card style, returns the
  `(text, ok)` shape of Qt's getText); the focus ring is NEUTRAL
  (`focus_ring = text_4` in styles.py — an accent ring read as an error with
  red-family accents); `_park_focus()` gives focus to the page on every
  switch and at start-up (else Qt drops it into the first field); every
  user-visible unit and frame description comes from i18n (`unitMsSuffix`,
  `unitMbSuffix`, `unitMin`, `coreFrame*`, `gui_trends.win_label`,
  `gui_logger.human_size(n, lang)`); menus that open menus use
  `gui_widgets.DropButton` (a drawn chevron, never a "▾" glyph); the window
  title is "<document> — ModbusReader" (`_refresh_window_title`).
- **Build**: `tools/version_resource.py` gives both exes a Windows version
  resource generated from version.py; `tools/make_splash.py` →
  `assets/splash.png`, shown by PyInstaller's `Splash` target while the
  one-file exe unpacks and closed by `main._close_splash()` once the window is
  up. Both take effect on the next build.

**v2.1.0 (2026-10-13): new types, line statistics, watch window, icon,
slave mode, Modbus tables.** Pinned by `tests/test_v21_features.py` and
`tests/test_areas.py` (804 tests in total).

- **Modbus tables** (`datatypes.AREAS`): holding (FC 03/06/16), input
  registers (FC 04, read-only), coils (FC 01/05, bits) and discrete inputs
  (FC 02, read-only bits). A register's optional `"area"` field names its
  table; holding is the default and is NEVER written, so every older map and
  project is byte-identical and `PROFILE_VERSION` did not change (the
  "maintain forever" cost is one optional key). `datatypes.apply_area` is the
  one rule set: a bit table forces `BOOL` ×1, a read-only table forces `R`.
  **Identity is the KEY** `area.code << 16 | addr` (`reg_key`), so holding
  keeps `key == addr` and every existing reg_id / trend / dashboard binding /
  watch list / setting means what it did. Everything that used to key by
  address now keys by `reg_key`: the table (`_ROLE_KEY` on the address cell —
  never parse the label), the core's `data_updated`/`request_op`/writes, the
  watch window, dashboard binding (`reg_id(key)`), macros (`reg("CO 0x0005")`
  via `parse_key`), snapshots (`area` stored when not holding; `compare` keys
  by table), logger columns, overlaps/chains (per table). People read keys
  through `key_label` ("IR 0x0010", "CO 0x0010", "DI 0x0010"; holding has no
  prefix) and `id_label(reg_id)`. The core picks the pymodbus call per table
  (`_READERS`), unpacks bits into 0/1 words (`res.registers`), switches a coil
  with FC 05 and refuses writes to read-only tables before touching the wire.
  The emulator keys its store the same way: FC 01/02 pack bits LSB-first,
  FC 05 accepts only FF00/0000, FC 15 checks the byte count, FC 04 serves the
  input table — or the holding table when the map has no input registers
  (what many devices do, and what 2.1 previews did). A run may not spill into
  the next table (`covers`). Import: an "area" column (`parse_area` aliases:
  coil / CO / 0x / FC1 / катушка …) and, in 4x mode, the block names the
  table (3xxxx input, 1xxxx discrete; short forms stay holding). The sniffer
  decodes FC 01/02/05/15. Cross-checked against pymodbus' own framer.

- **Types** (`datatypes.py` + `byteorder.py`): UINT16, BITS16, BCD16, UINT32,
  BCD32, INT64, DOUBLE, STRING. The guarded historical codecs are untouched;
  the new ones are separate functions. 64-bit values use `_PERM64`, derived
  from the 32-bit order NAME (CDAB = the four words reversed). `DataType`
  gained `text` (STRING: `encode(value, words)` pads with NUL to the field)
  and `default_view` (BITS16 opens in "bin"). Numbers are parsed by
  `_int_arg` — never via float, so INT64 > 2**53 stays exact.
  `reg_read_count(reg)` = fixed span, or a text field's own length (≤ 125);
  the poll loop and `_read_value` use it. The core writes text NUL-padded to
  the register's span (looked up in `poll_list` by `_find_reg`).
- **Line statistics** (`linestats.py`): `LineStats` (thread-safe counters +
  response times), `classify(res)`, and `install_crc_probe(client, stats)`,
  which wraps the pymodbus RTU framer's `decode` and flags a COMPLETE frame
  with a bad CRC — pymodbus otherwise turns noise into a plain timeout. Every
  exchange goes through `ModbusCore._counted()`; raw console answers are judged
  by `sniffer_core.frame_crc_ok`. Reset per connection. The status bar shows
  `LineStatsChip` (sampled every 500 ms) and `LineStatsPopup`; the log's error
  count moved onto the «Журнал» chip.
- **Watch window** (`gui_watch.WatchWindow`, F6): a `Qt.Tool` window (above
  the main window; the pin adds WindowStaysOnTopHint). Fed by
  `RegisterTable.value_shown(addr, text, number)` — emitted only for watched
  addresses — so it shows EXACTLY the table text. Writes go back through
  `RegisterTable.request_write()` (same scaling/enum/not-connected rules).
  Sources: table context menu (`watch_toggle_requested`) and dashboard card
  menu (`DashboardView.watch_requested`). Persisted: `watch_list`,
  `watch_on_top`, `watch_geom`, `watch_visible`.
- **Icon**: `tools/make_icon.py` paints every size natively into
  `assets/app.png` + `assets/app.ico` (PNG-in-ICO). `icons.asset_path()` finds
  assets in source and in the PyInstaller bundle (`sys._MEIPASS`); the specs
  set `icon=` and ship `assets/` as data. The toolbar logo is the same image.
- **Slave mode** (`slave_core.py` + `gui_slave.SlaveView`, Ctrl+9) — built
  to the earlier design: `build_response(request, store, slave_id)` is PURE;
  `SlaveStore` holds words for every address the map covers (exception 02
  outside it), with a lock (server thread + GUI); `SlaveServer(QThread)` owns
  its port, frames by t3.5 silence + `carve_frames`, answers, emits
  `exchange(info)`. FC 03/04 from the same store, 06 echo, 16 ack;
  exceptions 01/02/03; bad CRC / other ID / broadcast read → silence;
  broadcast writes applied, not answered. One port, one owner: the slave
  view refuses the master's port, `_toggle_connection` refuses the
  emulator's (`serving_port()`). The served map is a snapshot
  (`reload_map`, kept values); a map change while running applies at the
  next start. The master↔slave codec parity is tested end to end through a
  loop client.