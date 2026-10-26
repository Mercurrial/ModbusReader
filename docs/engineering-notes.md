# Engineering notes

Implementation notes per release: what was built, and above all *why* the
non-obvious parts are the way they are. The current design is described in
[ARCHITECTURE.md](../ARCHITECTURE.md); user-facing changes are in
[CHANGELOG.md](../CHANGELOG.md). Module paths below follow the current layout
(`app/`, `core/`, `gui/`); before 26.10.0 every module sat in the repository
root, `gui_*` modules carried that prefix and the map editor was
`profile_editor`.

## Registry migration (2026-07)

`core/datatypes.py` was extracted as the single source of truth and all consumers were
moved off their private `if/elif` chains:
- `modbus_core`: `should_poll` poll filter; `is_scalar/read_count/decode/encode/
  read_to_str` in read/write paths; 6 codecs re-exported for back-compat.
- `map_editor`: imports `FIXED_TYPE_LEN/VARIABLE_TYPES/ALL_TYPES/TYPE_HINTS`;
  `type_size = datatypes.addr_span`.
- `macro_engine`: `_SCALAR_TYPES = datatypes.SCALAR_KEYS`.
- `main_window`: 3 `_NON_POLL_TYPES` sites → `datatypes.is_area(...)`.
- `memory_viewer`: `words_per_element = datatypes.read_count(dtype)`.
Verified: codec parity vs old pack/unpack, read_count, area filter, dropdown
order, macro scalar filter, full app instantiation — all headless.

## 1.0 – 1.1 (2026-07): design passes

### Settings wiring

Previously 14 settings keys were dead. Now: `poll_rate` → pause
between poll cycles (registers read back-to-back, next cycle ≥ poll_interval;
queues drain every tick), `timeout` → client response timeout, all applied on
(re)connect; `interframe_delay` → pauses between write words / array chunks /
queue ops; `log_max`/`log_autoscroll`/`log_verbosity` → LogPanel (live via
`apply_settings()`; «min» drops TX/RX from the record); `load_last` gates the
startup profile load; `mono_values` + `highlight_changes` (change-flash) →
RegisterTable; `trend_grid` → pyqtgraph grids (cards + expand dialog).
Removed: `autosave`, legacy `rx_timeout`/`tx_timeout`, `row_density`.

### Summary of the 2026-07 work

 data-type registry (`core/datatypes.py`); settings schema registry
(`app/settings_schema.py`); commands registry (`app/commands.py`); transport registry
(`core/transports.py`, serial + TCP — TCP not surfaced in UI yet); AppContext
(`app/app_context.py`) — adopted by main_window + app-specific children; themes registry
(`theme_manager.THEMES`); `StateDotDelegate` reads theme tokens; dashboard column
registry (`register_table.COLUMNS`; editor schema intentionally separate); log-panel
extraction (`log.LogPanel`); register-grid MVC extraction (`register_table.
RegisterTable`, emits intent signals; main_window 1339→867); i18n label cleanup
(map_editor + toolbar labels → `STRINGS`; fixed an `untitledProfile` ru bug);
settings-schema i18n migration (tuples → `STRINGS` keys, golden-parity proved);
COM-port auto-detect (editable combo via `Field.options_fn`); profile validation
(overlaps/dup-names — editor badge + load-time log warnings); permanent pytest
suite (`tests/`, 97 tests); opaque in-cell editor fix (gui/styles.py — typed text no
longer overlays the old cell text); raw-frame console (`gui/console.py` — auto-CRC
command row + editable packet row, ↑/↓ history, `core.raw_queue`).

### Design pass (2026-07)
 resizable dashboard columns (Interactive);
themed QScrollBar (was native white/dotted — styled `::add-page`/`::sub-page`/
`corner`); faster theme switch (`setUpdatesEnabled` batch + single `setHtml` log
rebuild, no double pass); unified SVG icon set (emoji/dingbats → `gui/icons.py`, incl.
settings sidebar); restyled memory viewer; **live WYSIWYG drag-reorder** in the
profile editor (grip-drag, model reorders under the cursor, Esc cancels, one
undo/drag).

### Design pass v2 (2026-07-16) — corrections + polish

- **Drag regression fixed:** live repopulate on each move destroyed the cell
  widgets and dropped the *implicit* mouse-grab → the drag froze after one step.
  `ReorderableTable` now `viewport().grabMouse()` on drag start (survives the
  churn), releases on commit/cancel. Regressioned with a real mouse-path test.
- **Combo/spin arrows are real images, not CSS triangles.** Qt QSS renders a
  border-triangle as a filled box (the "rectangle arrow" bug). `icons.icon_url()`
  caches a themed chevron PNG per (name,color,size); `gui/styles.py` uses
  `image: url(...)` for `QComboBox::down-arrow` and the spin arrows. **Rule: for
  Qt arrows use an image, never border-triangles.**
- **Dashboard table fills the viewport + width-stealing resize.** Content columns
  size to content; `CURRENT`/`NEW` (`_FLEX_COLS`) split the remainder equally;
  `RegisterTable._reflow_columns(exclude)` keeps total == viewport width — dragging
  one border makes the value columns yield/absorb, and once they hit `_MINW` the
  overflow is taken from the dragged column so **no horizontal scrollbar appears**.
  Header text centered. (`sectionResized`/`resizeEvent`→reflow; `_adjusting` guard.)
- **Themed message boxes** (`dialogs.themed_message`): native icon/chrome replaced
  by an `gui/icons.py` glyph in a semantic colour + `QMessageBox` QSS. Migrated the
  editor/settings/macros confirmations.
- **Settings persistence hardened** (the "settings reset themselves" bug):
  `settings_manager.SETTINGS_FILE` is now an **absolute path** (was CWD-relative);
  `save_settings` writes **atomically** (temp+fsync+`os.replace`) keeping a `.bak`;
  `load_settings` recovers from `.bak` and preserves a corrupt file as `.corrupt`;
  `main.py` reads via `load_settings()` (no direct relative open). Font selector
  (`settings_schema` `font_choice` + `font_size`) already existed — kept.

### Polish pass v3 (2026-07-17) — v1.1.0

- **Version** now lives in `app/version.py` (`APP_VERSION`) — toolbar brand + About
  read it.
- **Card dialogs** (`dialogs._CardDialog`): frameless rounded card in the
  onboarding-guide style (no native title bar). ALL native
  QMessageBox.critical/warning/information calls migrated to
  `themed_message`/`themed_info` — zero native chrome anywhere.
- **Nav switcher** (superseded by the 2.2 rail): `app/commands.py` gained `place="view"` commands
  (`view_table`/`view_map`/`view_console`/`view_slave`, Ctrl+1..4) and a derived
  `VIEWS` tuple. The toolbar renders the cluster; the active view (or open
  settings/editor overlay) carries `[active="true"]` (QSS accent underline).
  `gui/views.py`: `ConsoleView` (full-screen exchange terminal fed by
  `main_window._log` + its own `RawConsole`) and `SlaveStubView` (placeholder —
  slave mode itself came in 2.1). `main_window._switch_view`
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
- **Search box**: magnifier is an `gui/icons.py` pixmap (recolored on restyle);
  the dead "DEC" suffix label was removed. NEW: Ctrl+F (hidden command) jumps
  to the Table view and focuses the search input.
- Shortcuts page (Settings) now matches reality: views Ctrl+1..4, Esc, F5,
  Ctrl+,/N/O/M/T, F1, Ctrl+F, F2, Tab/Shift+Tab.

### Polish pass v4 (2026-07-17) — v1.1.1

- **Nav slimmed:** the top bar keeps ONLY real views — Карта регистров
  (renamed from Таблица) | Консоль | Slave. The Профиль dropdown moved out of
  the top bar into the **map head bar** (`main_window.btn_profile`, `#mhProfile`
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

### Polish pass v5 (2026-07-17, third wave) — v1.1.2

- Settings overlay lost its header bar entirely (Esc = overlay shortcut in
  main_window; F1 = the settings guide via `_show_help` delegation).
- **One segmented style everywhere**: `widgets.Segmented` is a fixed-height
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

## 1.2.0 (2026-07-17) — configurable byte-order codecs

`core/byteorder.py` — pure permutation codecs for 16/32-bit values (orders
AB/BA and ABCD/BADC/CDAB/DCBA; all involutions, one permutation for both
encode and decode). `core/datatypes.py` pack/unpack functions are now thin wrappers
reading a module-level `_ORDERS` config; `configure_orders(settings)` is called
by AppContext on startup and on every settings update, so the editor, macros
and the poll loop all follow the user's choice live. Settings UI: new
"Кодеки — порядок байт" section on the Connection page (3 segmented pills).
Parity guarantee: the original implementation is inlined verbatim in
`tests/test_byteorder.py` as the golden reference; defaults are asserted equal
to it bit-for-bit, plus known wire vectors and round-trips for every order.
An existing `app_settings.json` without the new keys resolves to the exact
historical behavior (verified against a real settings file).

## 1.3.0 (2026-07-17) — scanner, sniffer, dashboard + smart nav

- **Smart toolbar**: which views show as labelled tabs = `settings
  ["pinned_views"]` (view_table always pinned); the rest live in the ⋯
  overflow menu (`toolbar.btn_more`, icon "dots") which also hosts
  «Настроить вкладки» (checkable pin toggles → `pins_changed` → persisted).
  When the active view is unpinned, ⋯ carries the [active] highlight.
- **ScannerView** (`gui/scanner.py` + `scanner_engine.ScannerWorker`, Ctrl+4):
  device scan (slave-ID range ping) and register scan (address range on one
  ID). Built on a new core op kind **"probe"** (`ModbusCore._probe`) that
  classifies alive / exception(=alive) / silent; `request_op(...)` and
  `_safe_read/_read_value` gained a per-op `slave=` override (scans of a
  FOREIGN slave never emit data_updated into the main table). The port stays
  owned by the core thread — the worker only enqueues sync ops.
- **SnifferView** (`gui/sniffer.py` + `core/sniffer_core.py`, Ctrl+5): passive RTU
  tap. Pure, tested pieces: `crc16` (0xA001), `decode_frame` (FC 03/04/06/10 +
  exceptions, request/response heuristics); `SnifferWorker` owns its OWN
  serial port, splits the stream on t3.5 silence (min 1.75 ms) and never
  transmits. One-port-one-owner enforced in the view: refuses the master's
  port while polling.
- **DashboardView** (`gui/dashboard.py`, Ctrl+6): mini-HMI. Widget kinds value /
  led / bar / gauge (270° dial), custom-painted with live theme tokens; cards
  bound by reg_id, fed from the same `value_sampled` stream as trends;
  persisted in `settings["dash_widgets"]`; add-dialog in the frameless-card
  style. Slave stub moved to Ctrl+7.

## 1.4.0 (2026-07-17) — dashboard v2 — the full mini-HMI

`gui/dashboard.py` rewritten around MANUAL card layout (no QGridLayout) so
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

## 1.5.0 (2026-07-18) — profile v2 (scaling/enum) + dashboard v3 (free layout, wired automation)

- **Versioned formats** — `core/formats.py`: a small envelope (`format`, `version`)
  plus a **migration registry** per document. `migrate_profile` detects the
  on-disk shape (bare array = v0, `{"registers":[…]}` = v1, envelope = v2) and
  runs the chain up to the current version, so **files written by any past
  build open forever**. `profile_manager.load_profile_data` and the editor both
  route through it. Adding a format change = ONE migration + a version bump;
  never edit an old migration. A project track (`migrate_project`, .mbproj)
  exists with the embedded profile migrated on its own track.
- **Engineering units** — `core/scaling.py` (pure): `displayed = raw*scale + offset`
  plus an enum map (`{"0":"Стоп"}`) as *register* properties. The table shows
  engineering values/labels and converts back to RAW on write; the dashboard
  uses the same helpers. Identity defaults mean old profiles are untouched.
  Edited via the row context menu → «Инженерные единицы…»
  (`gui/scaling_dialog.py`).
- **Dashboard v3** — `core/dash_model.py` (pure: kind registry, snapping math,
  automation graph) + `gui/dashboard.py` (paint/interaction) + `gui/dashboard_dialog.py`.
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

## 1.6.0 (2026-07-18) — dashboard v4 + multiple dashboards + .mbproj / .mbdash

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
  flat `dashboard:` key. `main_window._save_project` / `_open_project` /
  `apply_project` wire it to the head-bar Профиль menu; opening a project
  restores settings, map and dashboards but never auto-connects the port.
- Perf (40 cards / 30 wires): repaint 14 ms (grid is a cached tile), zoom step
  0.23 ms, drag handler 0.19 ms/event, board switch 4 ms, value update 5 µs.

## 1.7.0 (2026-08-12) — dashboard v5/v6 — five new block kinds, pulse visualisation, whole-app sweep

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

## 1.8.0 (2026-08-13) — interaction fixes, appearance system, scanner/sniffer hardening

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
- **Appearance system** (`gui/theme_manager.py`): three layers, all optional and
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
- **Font safety** (`app/fonts.py`) — symbol families (Wingdings, the Segoe icon
  fonts) are filtered out of the picker using Qt's own writing-system
  metadata, the saved value is validated on load, a family without Cyrillic
  warns, and a Reset button restores a known-good face. Picking a dingbat font
  used to be unrecoverable: the settings page itself became unreadable.
- **Scanner/sniffer hardening** — there was no hardware to test these against, so
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

## 1.8.1 — the appearance actually applies

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

## 1.9.0 — security, input robustness, coverage

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
  `macros`, `memory_viewer`, `statusbar`, `bundle_project`.
- **Perf** — verified linear (no quadratic paths) for `find_overlaps`,
  `find_duplicate_names`, `normalize_registers`; table populate 124 ms at 2000
  registers, 2000 value updates 16 ms.

## 1.10.0 — import a register map from CSV / XLSX

`core/mapimport.py` (pure) + `gui/import_dialog.py` (rendering), reached from the
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

## 1.11.0 — snapshot / compare (Ctrl+7)

`core/snapshots.py` (pure) + `gui/snapshot_view.py` (view). Freeze every current value,
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

## 1.12.0 — data logger (Ctrl+8)

`core/datalog.py` (writer) + `gui/logger.py` (view). Long unattended runs to CSV —
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

## 1.13.0 — dashboard selection, project-first workflow, chrome cleanup

*Dashboard multi-select (`gui/dashboard.py`).* Selection became a LIST, not a uid.
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

*Project-first (`gui/main_window.py`).* A project (`.mbproj`) is the workspace; the
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

## 1.14.0 — band-select fix, menu language, logger as a monitor

- *Rubber band, all four directions.* It was measured from the previous rect's
  `topLeft()`, but after `normalized()` that is the geometric corner, not the
  anchor — so each frame the band covered only the last two cursor positions,
  and an up/left drag collapsed it. Now anchored in `_band_from`. The first
  test for this passed against the broken code because it used ONE big move;
  a real drag is many small ones, and `_drag_band()` in the test now does that.
  Down-right still worked before the fix, which is exactly the case that worked before.
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

## 2.0.0 (2026-10-13) — full audit — the first final release

Every finding was reproduced on the running code first; each is pinned by
`tests/test_audit_v2.py` (712 tests in total). The user-facing summary is in
`CHANGELOG.md`; the engineering rules that came out of it:

- **One log, two views.** `log.LogStore` is the only buffer; the bottom
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
- **`main_window._set_profile(regs, path)` is the one entry point** for "this is
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

## 2.1.0 (2026-10-13) — new types, line statistics, watch window, icon, slave mode, Modbus tables
 Pinned by `tests/test_v21_features.py` and
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

- **Types** (`core/datatypes.py` + `core/byteorder.py`): UINT16, BITS16, BCD16, UINT32,
  BCD32, INT64, DOUBLE, STRING. The guarded historical codecs are untouched;
  the new ones are separate functions. 64-bit values use `_PERM64`, derived
  from the 32-bit order NAME (CDAB = the four words reversed). `DataType`
  gained `text` (STRING: `encode(value, words)` pads with NUL to the field)
  and `default_view` (BITS16 opens in "bin"). Numbers are parsed by
  `_int_arg` — never via float, so INT64 > 2**53 stays exact.
  `reg_read_count(reg)` = fixed span, or a text field's own length (≤ 125);
  the poll loop and `_read_value` use it. The core writes text NUL-padded to
  the register's span (looked up in `poll_list` by `_find_reg`).
- **Line statistics** (`core/linestats.py`): `LineStats` (thread-safe counters +
  response times), `classify(res)`, and `install_crc_probe(client, stats)`,
  which wraps the pymodbus RTU framer's `decode` and flags a COMPLETE frame
  with a bad CRC — pymodbus otherwise turns noise into a plain timeout. Every
  exchange goes through `ModbusCore._counted()`; raw console answers are judged
  by `sniffer_core.frame_crc_ok`. Reset per connection. The status bar shows
  `LineStatsChip` (sampled every 500 ms) and `LineStatsPopup`; the log's error
  count moved onto the «Журнал» chip.
- **Watch window** (`watch.WatchWindow`, F6): a `Qt.Tool` window (above
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
- **Slave mode** (`core/slave_core.py` + `slave.SlaveView`, Ctrl+9) — built
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

## 2.2.0 (2026-10-15) — the window redesigned as a professional tool

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
- **Empty states** (`widgets.EmptyState`: tile + title + sentence +
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
- **Trend card** (`trends.TrendCard`, rebuilt): big current value
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
  (`focus_ring = text_4` in gui/styles.py — an accent ring read as an error with
  red-family accents); `_park_focus()` gives focus to the page on every
  switch and at start-up (else Qt drops it into the first field); every
  user-visible unit and frame description comes from i18n (`unitMsSuffix`,
  `unitMbSuffix`, `unitMin`, `coreFrame*`, `trends.win_label`,
  `logger.human_size(n, lang)`); menus that open menus use
  `widgets.DropButton` (a drawn chevron, never a "▾" glyph); the window
  title is "<document> — ModbusReader" (`_refresh_window_title`).
- **Build**: `tools/version_resource.py` gives both exes a Windows version
  resource generated from app/version.py; `tools/make_splash.py` →
  `assets/splash.png`, shown by PyInstaller's `Splash` target while the
  one-file exe unpacks and closed by `main._close_splash()` once the window is
  up. Both take effect on the next build.

## 26.10.0 (2026-10-16) — self-update, installer, open source, zoomed review

- **Versions are calendar versions from here on**, `YY.MM.N` (26.10.0 = the
  first release of October 2026, then 26.10.1, 26.11.0 …). The 2.x numbers
  meant nothing to a user and every release bumped the minor anyway; the date
  says how old a copy is. The number only grows (26 > 2), which is all
  `updater.is_newer` compares. One source: `app/version.py`;
  `tools/release.py` computes the next number and writes app/version.py, the
  CHANGELOG heading («## Не выпущено» → «## X — date») and README; tags are
  `vYY.MM.N`, annotated, on the release commit.
- **Commits** are one change each with a type prefix (`ui:`, `feat:`,
  `fix:`, `docs:`, `tools:`, `release:`) — no more one commit per release.
- **Demo project** (`examples/demo.mbproj`, generated by
  `tools/make_demo_project.py`, bundled by every spec): opened on the FIRST
  launch (`main.startup_document`: no settings file yet; a double-clicked
  file wins) and by «Демо-проект» on the empty map (`_open_demo`) — always as
  the user's copy in Documents/ModbusReader (`demo_copy_dir`, patched in
  tests), never the bundled file (a Save would write into the program
  folder and the next update would wipe it). Dashboard uids in it are fixed
  (`demo01…`); `_make_card` re-ids a duplicate uid (it used to orphan a card).
- **README pictures**: `tools/readme_shots.py` renders every screen at 2× from
  the demo project with a simulated device fed through `_on_data_updated`
  (never a private map; the log is cleared of local paths), rounds the
  corners, builds the hero banner, a themes collage (through
  `_finish_settings_apply`, the real Settings path) and the live trend as an
  APNG written by hand from Qt PNG chunks (no Pillow). Output: docs/images.
Pinned by `tests/test_polish_v23.py`; `tools/ui_snapshots.py OUT
[--settings dist/app_settings.json] [--theme] [--lang]` photographs every
page, menu, dialog and settings page headless for the next review.

- **Tables**: `widgets.RowNumberHeader` replaces the vertical header
  wherever row numbers show (map, memory viewer) — it paints the row's zebra
  colour under the number (parity counted over VISIBLE rows, as Qt does), and
  the QSS vertical section is transparent. Header text aligns with its cells
  (left over left, centred only over centred cells).
- **QLabel indent**: any QSS padding/border turns on Qt's automatic indent
  (half an "x") — global `QLabel { qproperty-indent: 0; }` so text starts at
  the padding edge. Layouts set ON a widget get the style's ~9 px default
  margins — zero them explicitly (bit the settings rows). QSS `margin` on a
  layout-managed QWidget does nothing — use `addSpacing`.
- **QTextEdit placeholder** is clipped to the empty document's height: keep
  placeholders to one short line.
- **Watch window** rebuilt as a frameless translucent Tool window with its own
  card, drag bar (`startSystemMove`), size grip and `WatchRowWidget` rows.
- **Editor**: name + counts on top, table tools below, Save/Apply/Close in a
  footer; JSON preview behind a toggle (`settings["editor_json"]`); the two
  name columns take the spare width until the user drags one. Drag snapshots
  are cleaned explicitly in `_end_drag` — `QAbstractAnimation.stop()` does not
  emit `finished`.
- **Esc** in overlays: QDialog handles it with focus inside; the main window's
  `keyPressEvent` rejects the overlay otherwise, and `changeEvent` puts focus
  back into the overlay on re-activation (Alt+Tab).
- **Self-update** (`core/updater.py` logic, `gui/update.py` UI; pinned by
  `tests/test_updater.py`). Feed: GitHub `releases/latest` of
  `version.UPDATE_REPO`, read ANONYMOUSLY (a private repo answers 404 =
  `not_found`). `install_kind()`: "source" (never checks by itself — the
  tests and a dev checkout stay offline), "installed" (`unins*.exe` beside
  the exe → the `ModbusReader-Setup-*` asset), "portable" (the asset with the
  running exe's name, else `ModbusReader.exe`). Every download must match the
  asset's GitHub `digest` (SHA-256), size and `MZ` header — no digest, no
  install; a verified earlier download is reused; old ones are deleted at
  start-up. Hand-over WITHOUT a script interpreter (a hidden PowerShell was
  refused intermittently by the dev machine's protection, and .cmd files are
  read in the OEM code page): portable — the new exe runs as
  `--finish-update --wait <pids> --target <old exe>` (main.py, before Qt):
  waits on the old process AND the one-file bootloader (`app_pids`), copies
  itself to `<old>.new`, `os.replace` with retries, starts it; failure starts
  the old exe. Installed — the installer runs with `/SILENT … /WAITPID=<pid>`;
  its `[Code] InitializeSetup` waits, `[Run]` (no skipifsilent) relaunches.
  Children get `updater.child_env()` (no `_MEI` paths,
  `PYINSTALLER_RESET_ENVIRONMENT=1`). `ModernScadaApp.quit_for_update()` asks
  everything a close would ask BEFORE starting the new copy and keeps the
  window if the start fails; after it, the close is not cancellable.
  Settings: `update_auto`, `update_skip` (a skipped version is not offered
  automatically), `update_last_check`.
- **Installer**: `ModbusReader_setup.spec` (one folder) +
  `installer/ModbusReader.iss` (UTF-8 WITH BOM — Russian messages), built by
  `tools/build_installer.py` (finds ISCC of Inno Setup 6/7). Per user
  (`PrivilegesRequired=lowest`, `{autopf}` = %LOCALAPPDATA%\Programs), fixed
  AppId, `[InstallDelete] {app}\_internal` so no stale modules survive an
  upgrade, `.mbproj` association under HKA, desktop icon task. An installed
  copy keeps settings in %APPDATA%\ModbusReader
  (`settings_manager.is_installed_dir`). `main._file_argument` opens a
  double-clicked .mbproj.
- **"The window opens minimized"** (reported 2026-10-20): `EmptyState`
  showed its body label (`_fit_body` → `setVisible(True)`) before the
  label's layout was attached to the widget. A parentless widget that is
  shown is a top-level window: five of them flashed for ~30 ms while the
  main window was built, each took the foreground and handed it back to the
  previous program, which kept it — the main window then opened behind it.
  Found by logging every top-level `Show` on the real platform (offscreen
  hides it: nothing there takes focus). Rule: attach a layout to its widget
  before filling it; `tests/test_startup.py` fails on any stray window
  during construction. Also: the restored rect is checked against the
  current screens (`qt_utils.fit_on_screens`) and the window raises and
  activates itself after `show()`.
- **Start-up card** (`gui/splash.py`): the old splash (a flat picture with
  square corners and an English "Starting…") looked like a placeholder. The
  card now follows the README banner — graphite, grid, the mark, the name,
  a real 8N1 frame (`0A 03 00 10`) on the line ending in the mark's green
  dot. Installed and source runs show it live (translucent window with a
  soft shadow, fade in/out, a stage line and a progress hairline:
  imports ≈ 60 %, building the window ≈ 40 %); it is not topmost and leaves
  `FINISH_DELAY_MS` after the window is shown, so no bare-desktop beat. The
  one-file exe keeps PyInstaller's splash for the unpacking seconds, now the
  same card rendered by `tools/make_splash.py`; its Tk window keys out
  magenta, so corner pixels are flattened to fully opaque or fully clear
  (no pink fringe). `main._bundle_splash_alive()` stops the live card from
  opening over it.
- **One release, one installer name** (2026-10-20, the user's call): the
  installer is `ModbusReader-Setup.exe` in every release (Inno
  `OutputBaseFilename`), so `releases/latest/download/ModbusReader-Setup.exe`
  is a permanent download link; the version lives in the file's properties.
  The repository keeps a single release: a new version `--clobber`-uploads
  the three files into it and THEN moves it to the new tag (`tools/release.py`
  prints the commands) — the reverse order would show the new number next
  to the old build for a moment, and a copy updating then would install the
  old build and be offered the update again. Local downloads still carry the
  version (`updater._download_name`), which `cleanup_downloads` relies on.
  Tags: the user first had the old ones deleted (2.x are gone; their
  CHANGELOG links point at commits), then settled the same day on ONE TAG
  PER VERSION, kept for good, with the single release moved from tag to tag.
  `tools/release.py` drops the «Готовится к выпуску» line under the released
  heading and prints no tag deletion. The updater reads the version from the
  release title first ("ModbusReader X"), the tag second.
- **Closing during an update check crashed** (found by the release smoke
  test, 2026-10-20): the check was a QThread owned by the controller;
  `shutdown()` waited 3 s, then the window's destruction destroyed the
  still-running thread and Qt aborted the process (exit 0xC0000409). Rare
  with the old 8 s first check, common once the check runs right after
  start-up on a laptop without internet (a dropped connection takes up to
  `TIMEOUT` per step). The check is now a daemon `threading.Thread`
  (`gui/update._check_worker`) reporting through a parentless `_CheckResult`
  QObject (queued to the GUI thread); `shutdown()` just disconnects it.
  Rule: never let a QThread that may block on the network be destroyed with
  its owner.

## Unreleased

- **Install mode** (2026-10-20, the user: "%LOCALAPPDATA%\Programs is a strange
  path"): `PrivilegesRequired=admin` + `PrivilegesRequiredOverridesAllowed=
  dialog` — Setup asks "for all users (recommended) / only for me"; the
  former goes to C:\Program Files with UAC, the latter stays per user.
  `UsePreviousPrivileges=yes` makes an update keep the mode without asking
  (checked in the local Inno help: it looks the AppId up in the registry).
  The app keeps starting the installer NON-elevated: Setup elevates itself,
  and only then can the `postinstall` [Run] entry restart the app as the
  original, non-admin user (Inno help, runasoriginaluser: no effect when
  Setup was started elevated). The update dialog adds `updAdminNote` when
  the program folder is not writable. Unattended installs must pass
  `/CURRENTUSER` or `/ALLUSERS` (silent + admin default = a UAC prompt).
- **«Обзор…» in Setup**: Inno's own folder dialog has no «New folder» and no
  context menu; `AppendDefaultDirName=no` would add a button but stop
  appending the program folder. `[Code]` replaces the button's OnClick with
  the Explorer folder picker (IFileDialog via `CreateComObject`, FOS_PICKFOLDERS),
  opened at the nearest existing parent, and appends `\ModbusReader` unless
  the chosen folder already has that name; falls back to `BrowseForFolder`
  with a New Folder button. Trap: `GetDisplayName`'s LPWSTR declared as
  `out String` crashes Pascal Script (access violation) — take it as a
  Cardinal and copy it with lstrcpynW, then CoTaskMemFree (32-bit Setup).
  Verified on a hidden desktop by driving the wizard with window messages
  (BM_CLICK is ignored by an inactive window; WM_COMMAND/BN_CLICKED to the
  parent with the button's HWND works) and capturing with PrintWindow.
- **Linux and macOS** (2026-10-20/21): `.github/workflows/tests.yml` runs
  the suite on ubuntu-latest for every push and on macos-latest (arm64) by
  hand or for a tag (10× minutes in a private repo), then renders every
  screen with `tools/ui_snapshots.py` into an artifact. The first run found
  four things, none OS-specific in the app's logic: (1) the CRC probe went
  silent with pymodbus 3.16 — `requirements.txt` allows `<4`, the builds use
  3.13, CI got 3.16 (decode now swallows a bad frame: used = all, payload
  empty; "no payload" works for both); (2) `finish_update` did not wait for
  the old copy outside Windows (now polls, reaping its own zombie children);
  (3) the "file still held" give-up is Windows-only; (4) a table layout test
  ran on a hidden widget, which gets no resize events. The screens then
  showed macOS rendering addresses in a proportional face — the mono lists
  only had JetBrains Mono / Consolas — now one list in `app/fonts.py`
  (`MONO_FAMILIES`, `MONO_CSS`, `mono_family()`). Everything else looks the
  same as on Windows.
- **Pinned libraries, updates on purpose** (2026-10-21, after pymodbus 3.16
  silently broke the CRC count): `requirements.txt` pins the exact runtime
  set the releases are built with (incl. PyQt6-Qt6, PyQt6-sip, colorama,
  et-xmlfile), `requirements-dev.txt` adds pytest and PyInstaller (its
  `_internal/` layout, splash and `PYINSTALLER_RESET_ENVIRONMENT` are relied
  on). Dependabot opens a weekly PR (minor+patch grouped, majors alone) and
  a monthly one for the Actions; CI tests it on Linux. `tests/
  test_library_contracts.py` names each assumption about library internals
  (device-address keyword device_id/slave/unit, `client.socket`, FramerRTU
  decode tuple + lookupPduClass/check_CRC, pyqtgraph API, list_ports) and
  fails if the tests do not run on the pins; `build_installer.py` exits on
  any drift (`pins()` + `environment_drift()`).
- **pymodbus replaced by the app's own client** (2026-10-21, the user's
  call: "no switch, remove pymodbus completely"). `core/modbus_client.py`:
  `_Client` (the request API — FC 01–06, 16 — and PDU parsing), `RtuMaster`
  (pyserial; t3.5 before a request, 1.75 ms above 19200 Bd; the answer's
  length from its header: exception 5, read 5 + byte count, write 8; noise
  before the answer skipped; adapter echo dropped — for FC 05/06, whose
  answer equals the request, learned from reads or by waiting one gap for a
  second copy; a started answer ends after `max(50 ms, 4·t3.5)` of silence
  (USB latency)), `TcpMaster` (MBAP, stale transaction ids skipped). Every
  `Response` carries `.outcome` (ok / exception / timeout / crc), so
  `linestats` lost its framer probe and `crc_flag`; `ModbusLinkError` is a
  dead link (counted as a timeout, reconnect logic unchanged). The core's
  "exception means the link is alive" check uses `linestats.classify`
  instead of pymodbus' `ModbusIOException`. Tests: `tests/
  test_modbus_client.py` drives both clients against `slave_core.
  build_response` through fake ports (echo, noise, bad CRC, pieces, silence,
  stale TCP answers, dead links) plus the core/statistics/scanner/raw-console
  paths; `test_library_contracts` guards that pymodbus never returns.
  Still to do: try it on real adapters (FTDI latency, cheap CH340 echo).
- **Code signing through SignPath Foundation** (2026-10-26, the user's
  call: free signing for open source, the certificate is issued to SignPath
  Foundation, which is then the publisher in the signature; the copyright
  stays with the author). SignPath signs only an artifact uploaded by a
  GitHub Actions run of this repository, so the Windows release files are
  now built by `.github/workflows/build.yml` (job `windows`), not locally.
  Two signing requests per build, each approved by hand on app.signpath.io:
  the programs first (the one-folder `ModbusReader.exe`, the launcher, the
  two portable exes — three files named ModbusReader.exe, hence one folder
  each in the zip, `installer/signpath/programs.xml`), because Inno Setup
  must pack them signed (Smart App Control and antivirus look at every
  exe, not only the download); then the installer
  (`installer/signpath/installer.xml`). `tools/build_installer.py --only
  programs|installer` splits the build for that. The uninstaller
  (`unins000.exe`, written by Setup at install time) stays unsigned: that
  would take Inno's `SignTool` calling SignPath in the middle of ISCC, and
  nothing downloads it. Third-party DLLs (Python, Qt) are not signed with
  the certificate. Everything is gated on the repository variable
  `SIGNPATH_ORGANIZATION_ID`: without it the job builds the same files
  unsigned, so releases come from CI already before SignPath accepts the
  project. A file without a valid signature fails the job (test-signing
  policy: present is enough). The job also runs the test suite on Windows
  (the launcher tests run only there) and installs the built Setup per
  user (`/VERYSILENT /CURRENTUSER /NOLAUNCH`), starts the launcher and
  checks after 20 s that the version folder's program runs and wrote no
  error log. The policy SignPath requires on the home page is
  `docs/code-signing.md`: roles, what is signed, how to verify, and the
  privacy statement — the update check is the only traffic the app starts
  by itself.
