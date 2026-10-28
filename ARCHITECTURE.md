# Architecture

This document describes how ModbusReader is built: the layout of the code, the
runtime model, the extension points, the file formats and the rules the code
relies on. It is meant for anyone changing the code. The reasoning behind
individual decisions, release by release, is in
[docs/engineering-notes.md](docs/engineering-notes.md); user-facing changes are
in [CHANGELOG.md](CHANGELOG.md).

## Contents

1. [Repository layout](#1-repository-layout)
2. [Design principles](#2-design-principles)
3. [Runtime model](#3-runtime-model)
4. [Modules](#4-modules)
5. [Extension points](#5-extension-points)
6. [Data and file formats](#6-data-and-file-formats)
7. [Updates and installation](#7-updates-and-installation)
8. [Rules and known pitfalls](#8-rules-and-known-pitfalls)
9. [Testing](#9-testing)
10. [Build and release](#10-build-and-release)
11. [Known limitations](#11-known-limitations)

---

## 1. Repository layout

```
main.py          entry point — the only module in the root
app/             application services: settings and their schema, the shared
                 context, commands, translations, version, fonts, paths
core/            everything that is not a widget: the Modbus link and its thread,
                 data types and byte orders, file formats, the scanner / sniffer /
                 slave / macro engines, the dashboard model, logging, snapshots,
                 map import, the updater
gui/             the window and everything on it: pages, dialogs, widgets, the
                 register table, dashboards, trends, themes, icons, stylesheet
tests/           pytest suite, runs headless
tools/           build, release, icon / splash / demo generators, screenshots
installer/       Inno Setup script for the per-user installer
examples/        the demo project shipped with every build
assets/          application icon and splash image
docs/            engineering notes and the README pictures
```

Imports are absolute from the repository root (`from core import datatypes`,
`from gui.register_table import RegisterTable`). Where code uses a module as an
object, the import keeps the module's established local name
(`from gui import main_window as gui_main`). Anything that refers to "a file
next to the program" goes through `app/paths.py`: `ROOT` is the source checkout
or the folder of the exe, `resource(...)` resolves a bundled file (inside the
PyInstaller bundle in a build).

## 2. Design principles

**Descriptor + Registry.** Every extensible domain is declared as data: a frozen
dataclass *descriptor* in one central *registry*, read through a thin helper API.
Adding a register type, a setting, a command, a transport, a dashboard widget
kind or a theme is one new descriptor; nothing else changes.
`core/datatypes.py` is the reference implementation — new registries copy its
shape (descriptor → ordered registry → helpers → derived views computed once at
import).

**One owner per serial port.** The master link belongs to the `ModbusCore`
thread; the sniffer and the slave emulator own *their* ports. Nothing else ever
touches a port directly: work is queued, results come back as Qt signals.

**Logic without widgets.** Everything in `core/` is free of widgets, and the
parts with real decision logic — byte orders, data types, frame decoding,
the slave's responses, snapshot comparison, map import, the dashboard graph,
file migrations, the updater — are plain functions that are tested directly.

**Shared services through one context.** `AppContext` (`app/app_context.py`)
owns the settings dict, the Modbus core, the translator and the active theme.
Pages and dialogs take the context instead of reaching into the main window.

**Everything visible is translatable and themed.** All UI text comes from
`app/i18n.py` (Russian and English); all colours come from theme tokens; all
glyphs come from `gui/icons.py`. Tests enforce the first and the last.

## 3. Runtime model

### Start-up

`main.py`:

1. If started with `--finish-update`, completes a portable self-update and exits
   without creating any window (see §7).
2. Notes whether this is the first launch (no settings file yet).
3. Creates the `QApplication`, loads the settings, publishes the saved
   appearance (`theme_manager.set_active`) and applies the stylesheet — in that
   order, or the first window would be styled with the default scheme.
4. Shows the start-up card (`gui/splash.py`) before the heavy imports and
   moves it through its stages while the window is built. The one-file exe
   shows the same card as a PyInstaller splash picture from the first instant
   (`assets/splash.png`, rendered by `tools/make_splash.py` with the same
   painter) and skips the live one. Either leaves once the window has painted.
5. Builds `ModernScadaApp` (`gui/main_window.py`), shows it, raises and
   activates it. No widget may be shown before it has a parent: a parentless
   widget becomes a window of its own, takes the foreground for a moment and
   hands it to the previous program — the main window then opens behind it
   (`tests/test_startup.py` guards this).
6. Opens a project passed on the command line (a double-clicked `.mbproj`) or,
   on the first launch, the demo project (`startup_document`).
7. On the first launch only: the «make it yours» card (`gui/welcome.py` —
   language, theme, accent, menu position, font; every pick applied to the
   live window like a saved Settings page), then the button tour
   (`gui/onboarding.py`).

### The main window

```
ModernScadaApp (gui/main_window.py)
 ├─ AppContext                     settings, ModbusCore, translator, theme
 ├─ NavRail (gui/rail.py)          every page, in two groups; help. Left, right
 │                                 or a bar on top (_place_rail); icons only;
 │                                 pages hidden from it (right-click menu)
 ├─ MainToolBar (gui/toolbar.py)   project / page, link chip, Connect; settings
 │                                 in the top-right corner
 ├─ ConnectionCard (gui/connection.py)  the link chip's popover: transport,
 │                                 COM / IP fields, «Проверить связь», recent links
 ├─ pages
 │   ├─ map: RegisterTable (gui/register_table.py) + TrendsManager + LogPanel
 │   ├─ dashboard, console, scanner, sniffer, snapshots, logger,
 │   └─ macros, slave emulator
 ├─ overlays: SettingsDialog, ProfileEditorDialog (the map editor)
 ├─ WatchWindow (gui/watch.py)     floating tool window
 ├─ MainStatusBar                  link state, line statistics, log toggle
 └─ UpdateController (gui/update.py)
```

The window is a coordinator: it routes the table's intent signals
(`write_requested`, `value_sampled`, `trend_add_requested`, `inspect_requested`,
`watch_toggle_requested`, …) to the core, the trends, the dashboard, the watch
window and the memory viewer. `_set_profile(regs, path)` is the single entry
point for "this is the map now".

### Threads and queues

`ModbusCore` (`core/modbus_core.py`) is a `QThread`. Each loop it serves, in
order of priority:

1. `op_queue` — synchronous operations for macros and the scanner
   (`request_op()` blocks the caller on a one-slot result queue);
2. `raw_queue` — raw frames from the console, sent past the framer;
3. `write_queue` — writes from the table, the dashboard and the watch window;
4. `array_read_queue` — one-shot reads for the memory viewer;
5. `poll_list` — cyclic polling; a full cycle starts no sooner than every
   `poll_rate` ms.

It reports through `status_changed(bool, str)`, `data_updated(int key, str)`,
`log_msg(str level, str message)` and `array_read_finished(int, list)`.
`retry_count` failed polls in a row mean "connection lost"; with
`auto_reconnect` the core retries every `reconnect_interval` s, otherwise it
stops. On shutdown queued writes are dropped, never sent on a later connect.

Other threads: `MacroRunner` (`core/macro_engine.py`) talks to the device only
through `request_op`; `ScannerWorker` the same way; `SnifferWorker` and
`SlaveServer` own their own ports; the update check and download run in
`QThread`s owned by `gui/update.py`.

## 4. Modules

### app/

| Module | Responsibility |
|---|---|
| `settings_manager.py` | `DEFAULT_SETTINGS`; crash-safe load/save (absolute path, atomic write, `.bak`, `.corrupt`); where the settings live (installed / portable / read-only folder). |
| `settings_schema.py` | The Settings dialog as data: `Field` / `Section` / `Page`. |
| `app_context.py` | `AppContext` — settings, core, translator, theme tokens, stylesheet. |
| `commands.py` | `Command` registry: pages, header actions, shortcuts, rail groups. |
| `i18n.py` | `STRINGS` (ru/en) and `get_translator()`. |
| `version.py` | Version, release date, update repository, licence id, donation link. |
| `fonts.py` | Font list for the picker without symbol fonts; validation of the saved face. |
| `paths.py` | Project root and bundled resources. |

### core/

| Module | Responsibility |
|---|---|
| `modbus_core.py` | The master link thread: queues, polling, reads, writes, raw frames, frame logging. |
| `modbus_client.py` | The app's own Modbus client: `RtuMaster` (serial, t3.5 framing, echo and noise handling), `TcpMaster` (MBAP; drains late answers, reopens a connection the device closed) and `RtuOverTcpMaster` (RTU frames through a converter's socket, via `SocketLine`); every answer carries its outcome — ok / exception / timeout / crc; `link_error_kind` names why a link did not open. |
| `transports.py` | `Transport` registry — serial, Modbus TCP, RTU over TCP; one-line link summary, device-address range per link, the recent-links list; parity normalisation. |
| `linktest.py` | «Проверить связь»: one request, a diagnosis in words; for TCP also tries other unit ids and the other framing. |
| `netscan.py` | Finds Modbus TCP devices in an IP range (parallel probes); the PC's own IPv4 addresses and subnets. |
| `datatypes.py` | Register type registry, codecs, address span, Modbus tables (`AREAS`), register keys. |
| `byteorder.py` | 16/32/64-bit byte-order permutations. |
| `scaling.py` | Engineering units: `raw × scale + offset`, enum labels. |
| `linestats.py` | Line statistics: counts each answer's outcome and response time. |
| `scanner_engine.py` | Device and register scans. |
| `sniffer_core.py` | CRC16, frame carving and decoding, the passive sniffer thread. |
| `slave_core.py` | The slave emulator: pure `build_response`, `SlaveStore`, `SlaveServer` (COM port), `SlaveTcpServer` (Modbus TCP or RTU over TCP, many masters at once). |
| `macro_engine.py` | Macro runner: AST gate, restricted builtins, domain API, stop via line tracer. |
| `dash_model.py` | Dashboard widget kinds, snapping, the automation graph, gate conditions. |
| `datalog.py` | CSV logger writer (UTF-8 with BOM, rotation, buffered flushing). |
| `snapshots.py` | Snapshot and comparison of all register values. |
| `mapimport.py` | Register map import from CSV / XLSX: header detection, column mapping, address conventions. |
| `formats.py` | Versioned envelopes and migrations for profiles, projects and dashboards. |
| `profile_manager.py` | Profile loading, validation (overlaps, duplicate names), the editor's address chain. |
| `updater.py` | Release feed, verified download, hand-over to the new build. |

### gui/

| Module | Responsibility |
|---|---|
| `main_window.py` | `ModernScadaApp` — the coordinator described in §3. |
| `register_table.py` | The register grid: columns registry, formatting, view modes, column fitting, intent signals. |
| `map_editor.py` | The map editor overlay with live drag reordering and undo. |
| `dashboard.py`, `dashboard_dialog.py` | Dashboard canvas, cards, wires, selection, zoom; the widget dialog. |
| `trends.py` | Live trend cards and the expanded chart. |
| `log.py`, `console.py`, `views.py` | One log store with several views; the raw-frame console; the console page. |
| `scanner.py`, `sniffer.py`, `slave.py`, `logger.py`, `snapshot_view.py`, `macros.py` | The tool pages. |
| `watch.py` | The watch window. |
| `settings.py` | The schema-driven Settings dialog. |
| `update.py` | Update checks, the update dialog, download thread. |
| `rail.py`, `toolbar.py`, `statusbar.py` | Window chrome. |
| `connection.py` | The connection card under the header's link chip. |
| `import_dialog.py`, `scaling_dialog.py`, `memory_viewer.py`, `onboarding.py`, `welcome.py`, `dialogs.py` | Dialogs, the memory viewer, the first-launch card and the button tour. |
| `widgets.py` | Shared widgets: segmented control, toggle, slider, empty states, row-number header, drop button. |
| `theme_manager.py`, `styles.py`, `icons.py`, `qt_utils.py` | Theme tokens, the stylesheet, the SVG icon set, guarded timers. |

## 5. Extension points

| To add | Change |
|---|---|
| A register type | One `_dt(...)` entry in `core/datatypes.py` `TYPES`. Polling, the editor, macros, the dashboard and address maths follow. |
| A setting | A default in `DEFAULT_SETTINGS` and one `Field` in `app/settings_schema.py`; the dialog renders itself. |
| A page or header action | One `Command` in `app/commands.py`, its widget in `_view_pages()` or its handler in `_command_handler_map()`. |
| A transport | One `Transport` in `core/transports.py`. |
| A dashboard widget kind | One `WidgetKind` in `core/dash_model.py` and a paint branch in `gui/dashboard.py`. |
| An accent, scheme or theme | An entry in `ACCENT_PALETTES`, `SCHEMES` or `THEMES` (`gui/theme_manager.py`); token keys must match across themes. |
| An icon | An SVG path in `gui/icons.py` `_PATHS`. |
| A UI string | A key in both language maps of `app/i18n.py`. |
| A file-format change | One migration in `core/formats.py` and a version bump; existing migrations are never edited. |

## 6. Data and file formats

**Register** (one row of a map):

```python
{"addr": 16, "name": "Температура", "name_en": "Temperature",
 "type": "FLOAT", "length": 2, "rw": "R",
 "area": "input",                    # omitted for holding registers
 "unit": "°C", "scale": 0.1, "offset": 0.0,
 "enum": {"0": "Стоп", "1": "Работа"},
 "default": "", "comment": ""}       # optional keys are written only when set
```

A register's identity is its *key*: `area.code << 16 | addr`. Holding registers
have `key == addr`, so every binding written before the other tables existed
still resolves. People read keys through `datatypes.key_label`
(`0x0010`, `IR 0x0010`, `CO 0x0010`, `DI 0x0010`).

**Files.** Every document is a JSON envelope `{"format": …, "version": …}` and
opens through a chain of migrations, so a file written by any earlier build
still loads.

| File | Format id | Version | Contents |
|---|---|---|---|
| `.json` map | `modbusreader.profile` | 2 | `name`, `registers` |
| `.mbproj` project | `modbusreader.project` | 1 | `name`, `connection`, `profile`, `dashboards`, `layout` |
| `.mbdash` dashboard | `modbusreader.dashboard` | 1 | `name`, `widgets`, `links` |
| `.mbsnap` snapshot | `modbus-snapshot` | 1 | values of every register at one moment |
| logger `.csv` | — | — | one column per register, one row per sample; UTF-8 with BOM |

Dashboard widgets keep their geometry in logical (unzoomed) pixels. Settings
are a flat JSON object merged over `DEFAULT_SETTINGS`; unknown keys are kept.

## 7. Updates and installation

**When.** A frozen copy checks 1.5 s after start-up (`gui/update.py`
`FIRST_CHECK_MS` — the downloadable installer is the same file for months, so a
fresh install updates itself first) and then every six hours. An automatic
offer never stacks on the first-launch guide or a modal dialog; it waits for
them (`_pending`). Source checkouts never check by themselves.

**Feed.** `core/updater.py` reads the latest (non-draft, non-pre-release)
GitHub release of `version.UPDATE_REPO` anonymously. A copy updates the way it
was installed: an installed copy (an `unins*.exe` next to the program or next
to its version folder) takes the
`ModbusReader-Setup.exe` asset (any `ModbusReader-Setup*` name), a portable copy takes the asset with its own
file name. A download is accepted only if its SHA-256 matches the digest GitHub
stores for the asset, its size matches and it starts with `MZ`.

**Hand-over** — no script interpreter is involved:

- *portable*: the downloaded exe is started as
  `--finish-update --wait <pids> --target <old exe>`; it waits for the old
  process and its one-file bootloader, copies itself next to the old exe,
  replaces it (retrying while the file is held) and starts it. If the swap fails
  the old exe is started.
- *installed* (since 26.10.3 — a folder per version, see **Installer**): the
  new installer runs invisibly **while the app keeps working**
  (`updater.background_install_args`: `/VERYSILENT /NOLAUNCH
  /NOCLOSEAPPLICATIONS /PROGRESS=<file>` and the install mode); it writes the
  next version into its own folder, so no file in use is touched. Its progress
  comes through the file (`updater.read_progress`). Then «Перезапустить»
  starts the launcher (`updater.launcher_path`) and quits — a restart costs a
  start. Automatically (`update_auto`) a per-user copy downloads and installs
  in the background without a question and shows «Обновить до …» in the rail;
  an all-users copy downloads, then asks once (Windows will ask for
  permission). Not restarting is fine: the next start picks the newest folder.
  That start removes older version folders (`updater.cleanup_old_versions`
  renames a folder first — Windows refuses while a program in it runs — so a
  folder in use is never half-deleted).
- *installed the old way* (≤ 26.10.2, the program in the installation folder):
  the installer is started with `/SILENT … /WAITPID=<pid>`; its
  `InitializeSetup` waits for the app to exit, it moves the copy to the new
  layout and its `[Run]` entry starts it. An update keeps the install mode
  (`UsePreviousPrivileges`); an all-users installer elevates itself, so
  Windows asks (UAC). The app never starts the installer elevated: only a
  self-elevated Setup starts the program again without admin rights
  (`postinstall` runs as the original user).

`ModernScadaApp.quit_for_update()` asks everything a normal close would ask
before starting the new copy, and keeps the window if the start fails.
Children are started with `updater.child_env()` (no inherited bundle paths,
`PYINSTALLER_RESET_ENVIRONMENT=1`). A source checkout never checks by itself.

**Installer.** `ModbusReader_setup.spec` builds the one-folder program;
`installer/launcher/Launcher.cs` is compiled by `tools/build_launcher.py` with
the C# compiler of .NET Framework 4 (part of Windows); `installer/ModbusReader.iss`
packs both. The layout:

```
ModbusReader\ModbusReader.exe      the launcher: starts the newest version
                                   folder holding ".installed" (shortcuts,
                                   taskbar pins, .mbproj files point here)
ModbusReader\app-26.10.3\…         a version (the PyInstaller folder)
ModbusReader\unins000.exe          the uninstaller (removes every app-* folder)
```

The installer writes `.installed` into the version folder last, so the
launcher never starts a half-copied version. The app sets the same
AppUserModelID as the Start-menu shortcut (`main.APP_USER_MODEL_ID`), so
pinning the running window pins the launcher, not a version folder.

Setup looks like the app: `WizardStyle=modern dynamic windows11 hidebevels`
(light or dark as Windows is), the app's background colours, no stock images,
one page of its own (logo, title, folder, desktop shortcut) instead of Inno's
directory and task pages, the finished page laid out the same way. It first
asks for the install mode — for me only (the default, `%LOCALAPPDATA%\Programs\ModbusReader`,
updates without any question) or for all users (`C:\Program Files\ModbusReader`,
Windows asks for permission at the install and at every update);
`/ALLUSERS`, `/CURRENTUSER` answer it on the command line. «Изменить…» opens
the Explorer folder picker (new folders, context menu) through COM from the
`[Code]` section and appends `\ModbusReader` to the chosen folder.

The installer is a plain Inno Setup build on purpose. A wrapper of our own (a
Qt window that unpacked the Inno engine and ran it silently) was tried: the
antivirus on the development machine deleted it — an exe that drops and runs
another installer looks like a dropper. An installed copy keeps its settings in
`%APPDATA%\ModbusReader` of each user; a portable copy keeps them next to the
exe. The demo project is copied to
`Documents\ModbusReader` before it is opened.

## 8. Rules and known pitfalls

Each of these was learned from a real defect; most are pinned by tests.

**Device protocol**
- The byte-order defaults (SHORT `AB`, LONG `ABCD`, FLOAT `BADC`) are a proven
  device protocol and must not change; `tests/test_byteorder.py` guards them
  bit for bit against the original implementation.
- Area pseudo-types (`MEMORY_AREA`, `UNUSED_AREA`) are never polled
  (`datatypes.should_poll`).
- Integers are parsed without going through `float`, so 64-bit values stay
  exact.

**Safety**
- The dashboard's edit mode never writes to the device; a gate whose value is
  unknown never passes a pulse.
- A pasted group of dashboard widgets never keeps a wire to a widget outside the
  group.
- Macros pass an AST gate (no imports, no dunder names) and a line tracer makes
  Stop work for any script; this is a guard rail, not a security boundary.
- A file read from disk is validated and fails with a readable message;
  addresses are clamped to 16 bits and lengths to the address range.

**Qt**
- Every deferred callback that touches a widget goes through `qt_utils.later`
  or checks `sip.isdeleted` first. `QAbstractAnimation.stop()` does not emit
  `finished` — clean up explicitly.
- Two shortcuts on one key in one window are ambiguous and neither fires.
- A plain `QWidget` container inherits the global background; give it an
  object name and a transparent background.
- A `QLabel` with any stylesheet padding gets an automatic indent; the global
  stylesheet sets `qproperty-indent: 0`.
- A layout set on a widget gets the style's default margins; set them
  explicitly. Stylesheet `margin` on a layout-managed widget has no effect.
- A `QTextEdit` placeholder is clipped to one line.
- Stylesheet border triangles render as filled boxes; arrows are images
  (`icons.icon_url`).
- In-cell editors must be opaque, or the old text shows through.
- A top-level window keeps the size it was shown with: size dynamic content
  before the first show.
- `setStyleSheet` on the application costs time proportional to the widget
  count; skip it when the stylesheet is unchanged and debounce previews.

**Settings and files**
- The settings path is absolute; writes are atomic with a `.bak`.
- Defaults are deep-copied on load; nothing mutates a list that may still be a
  default.
- The bundled demo project is never opened in place.

## 9. Testing

```bash
.venv\Scripts\python -m pytest
```

About 900 tests run headless (`QT_QPA_PLATFORM=offscreen` is set by
`tests/conftest.py`), which also points the settings file at a temporary
directory for the whole session. Conventions:

- Test the real path: drive the real mouse and keyboard events and the real
  dialogs, not only the handlers behind them.
- Pure logic gets direct tests with explicit vectors (byte orders, frames,
  migrations, comparisons).
- Guards scan the sources (`tests/_paths.source_files()`): no hardcoded UI
  strings, no unknown icon names, no native input dialogs.
- Nothing may touch the developer's real settings, Documents or network;
  automatic update checks are disabled for source checkouts.

Two tools render the UI headless for review: `tools/ui_snapshots.py` (every
page, menu, dialog and settings page) and `tools/readme_shots.py` (the README
pictures, from the demo project).

## 10. Build and release

| File | Builds |
|---|---|
| `ModbusReader.spec` | one-file portable exe with splash |
| `ModbusReader_debug.spec` | the same with a console |
| `ModbusReader_setup.spec` | one-folder program for the installer |
| `installer/ModbusReader.iss` | the installer (Inno Setup 6) |
| `ModbusReader_unix.spec` | Linux and macOS: the program as a folder / `ModbusReader.app` |

Release builds come from `.github/workflows/build.yml`, one runner per
system (PyInstaller does not cross-compile). **Windows**: the tests, then
`tools/build_installer.py` in two halves — `--portable --only programs`
(the one-folder program, the launcher, the portable exes) and
`--only installer` (ISCC) — with a SignPath signing request after each, so
the installer carries signed files and is signed itself; then a silent
per-user install, a start of the launcher and the same 20-second check as
below. SignPath Foundation signs only artifacts of this workflow, after a
person approves each request; the job signs while the repository has the
variable `SIGNPATH_ORGANIZATION_ID` and builds the same files unsigned
without it (`installer/signpath/` — the artifact configurations and the
set-up; the public policy is `docs/code-signing.md`). A local
`tools/build_installer.py` build is for testing: it is never signed.
**Linux and macOS**: `tools/build_unix.py` on an Ubuntu 22.04
runner — `ModbusReader-x86_64.AppImage`, built on the oldest supported glibc
so it runs on newer ones — and a macOS arm64 runner —
`ModbusReader-macOS-arm64.zip`, ad-hoc signed, not notarized. Each build is
started under a real windowing system (Xvfb + xcb, the macOS desktop) and kept
only if it is still running 20 s later with no error log; a screenshot goes
with it. These builds update by the release page (`install_kind() == "page"`)
and keep their settings in `~/.config/ModbusReader` /
`~/Library/Application Support/ModbusReader`.

**Dependencies are pinned.** `requirements.txt` holds the exact runtime
versions the releases are built with, `requirements-dev.txt` adds pytest and
PyInstaller. A library update is a reviewed change: Dependabot
(`.github/dependabot.yml`) opens a weekly pull request — minor and patch
updates grouped, a major version on its own — and CI runs the suite on it.
`tests/test_library_contracts.py` checks, one assumption per test, what the
code relies on inside the libraries (the pyserial port API the RTU master
uses, the pyqtgraph API of the trends), that the tests run on the pinned
versions and that pymodbus — replaced by `core/modbus_client` — never comes
back;
`tools/build_installer.py` refuses to build in an environment that differs
from the pins.

`python tools/build_installer.py --portable` builds all of them and prints the
SHA-256 of each file. Versions are calendar versions `YY.MM.N`;
`python tools/release.py` computes the next number and writes it to
`app/version.py`, the CHANGELOG heading and, if present, the README. The repository
keeps one release, always the latest: a new version replaces its
`ModbusReader-Setup.exe`, `ModbusReader.exe` and `ModbusReader_debug.exe` (the
names the updater looks for; the installer's never changes, so
`releases/latest/download/ModbusReader-Setup.exe` is a permanent link) and then
moves it to the version's tag `vYY.MM.N` — files first, so no copy ever sees
the new number next to the old build. Every version keeps its tag; only the
release is single. `tools/release.py` prints the steps. Commit messages carry a type
prefix (`feat`, `fix`, `ui`, `refactor`, `docs`, `tools`, `release`) and each
commit passes the test suite.

## 11. Known limitations

- Polling reads one register per request; block reads are not implemented yet.
- Windows builds are signed only once SignPath Foundation has accepted the
  project; until then, and for a new version with few downloads, Windows
  SmartScreen warns on first installation. Linux and macOS builds are not
  signed (macOS: ad-hoc only).
- `ModernScadaApp` is still the largest module and the natural next candidate
  for splitting (project handling, overlay management).
