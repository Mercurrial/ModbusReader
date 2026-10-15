import copy
import json
import os
import sys
import shutil

# Anchor the settings file to a STABLE absolute location instead of a path
# relative to the current working directory. A relative "app_settings.json" is
# read/written against whatever CWD the app happened to launch with, so running
# from a different folder silently created a *fresh* file (defaults) and left
# the real settings behind — the "my settings reset themselves" bug. Anchoring
# to the app directory keeps it the same file no matter how the app is started.
if getattr(sys, "frozen", False):          # PyInstaller / packaged build
    _APP_DIR = os.path.dirname(os.path.abspath(sys.argv[0]))
else:                                       # running from source
    _APP_DIR = os.path.dirname(os.path.abspath(__file__))


def _settings_dir() -> str:
    """Prefer the app folder (portable use, existing installs); fall back to
    %APPDATA%/ModbusReader when the install location is read-only (e.g. the
    app was put into Program Files) — otherwise every save would fail and the
    settings would silently reset on the next launch. An old file left in the
    read-only folder is migrated to the per-user dir once."""
    try:
        probe = os.path.join(_APP_DIR, ".write_probe")
        with open(probe, "w") as f:
            f.write("")
        os.remove(probe)
        return _APP_DIR
    except OSError:
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        d = os.path.join(base, "ModbusReader")
        os.makedirs(d, exist_ok=True)
        old = os.path.join(_APP_DIR, "app_settings.json")
        new = os.path.join(d, "app_settings.json")
        if os.path.exists(old) and not os.path.exists(new):
            try:
                shutil.copy2(old, new)      # one-time migration
            except OSError:
                pass
        return d


SETTINGS_FILE = os.path.join(_settings_dir(), "app_settings.json")


def _backup_file() -> str:
    """Backup path, derived at CALL time.

    It used to be a module constant computed at import, so anything that
    reassigned ``SETTINGS_FILE`` afterwards (tests, a second install, the
    %APPDATA% fallback) kept reading and OVERWRITING the backup belonging to
    the original path — a real settings file could be clobbered by a run that
    was pointed somewhere else entirely."""
    return SETTINGS_FILE + ".bak"

DEFAULT_SETTINGS = {
    # Connection — transport selector (transports.py registry).
    # "serial" (default) | "tcp". TCP is functional but not surfaced in the
    # Settings UI yet — set it here / in app_settings.json to use it.
    "transport":        "serial",

    # Connection — serial
    "port":             "COM1",
    "baudrate":         "115200",
    "stopbits":         "1",
    "parity":           "None (N)",

    # Polling
    "timeout":          1000,
    "poll_rate":        500,

    # Device
    "slave_id":         10,

    # Byte/word order per data type (see byteorder.py). The defaults are the
    # proven historical codecs — DO NOT change them here, existing devices
    # depend on them; users pick different orders in Settings if needed.
    "order_short":      "AB",
    "order_long":       "ABCD",
    "order_float":      "BADC",

    # Appearance
    "theme":            "Dark",
    "accent":           "neutral",
    # Appearance v1.8: surface family + how hard surfaces/text are pushed
    # apart. Absent in older settings files -> these defaults apply, and
    # "graphite"/"paper" reproduce the previous look exactly.
    "scheme":           "graphite",
    "contrast":         "normal",
    "font_choice":      "inter",
    "font_family":      "Inter, Segoe UI, system-ui, sans-serif",
    "font_size":        9,
    "lang":             "ru",

    # Table
    "show_addr":        True,
    "show_name":        True,
    "show_type":        True,
    "show_access":      True,
    "show_current":     True,
    "show_new":         True,
    "show_row_nums":    True,
    "zebra_rows":       True,
    "mono_values":      True,
    "highlight_changes": True,
    "row_height":       26,

    # Graphs
    "trend_history":    1200,
    "trend_grid":       True,
    "default_window_sec": 30,
    "graph_autofit_y":  True,
    "graph_anim":       "smooth",
    "graph_width":      420,

    # Log
    "show_log":         True,
    "log_height":       150,
    "log_autoscroll":   True,
    "log_verbosity":    "normal",
    "log_max":          200,

    # Connection — extra
    "retry_count":      3,       # failed polls in a row before "connection lost"
    "interframe_delay": 50,
    # On connection loss: if False, stop and require pressing Connect again.
    # If True, keep silently retrying every reconnect_interval seconds.
    "auto_reconnect":     False,
    "reconnect_interval": 5,     # seconds between silent reconnect attempts

    # General
    "load_last":        True,

    # State
    "last_profile_path": "",
    "recent_profiles":   [],     # most-recently-loaded profile paths (newest first)
    # Projects are the primary object; the register map is what a project
    # contains. Kept as its own list so a recent project never gets pushed out
    # by a run of bare .json maps.
    "recent_projects":   [],     # most-recently-opened .mbproj paths
    "last_project_path": "",
    "last_project_name": "",
    "viewer_configs":    {},
    "console_history":   [],     # raw-console command history (newest last)
    "console_visible":   True,   # raw-console strip shown under the log
    "open_trends":       [],     # trend cards open at exit: {id,name,unit,win}
    # Watch window: watched addresses (in order), pin, geometry, open at exit.
    "watch_list":        [],
    "watch_on_top":      False,
    "watch_geom":        None,
    "watch_visible":     False,
    # Slave (device emulator): its own port and identity, remembered.
    "slave_port":        "",
    "slave_baud":        "",
    "slave_sid":         None,
    "slave_delay":       0,
    "last_view":         "view_table",   # nav view active at exit
    # 2.0–2.1: which views showed as top-bar tabs. The 2.2 rail shows every
    # page; the key stays so projects written by older versions round-trip.
    "pinned_views":      ["view_table", "view_console",
                          "view_scanner", "view_sniffer"],
    "rail_collapsed":    False,   # left rail: icons only
    # Dashboards: a LIST of {name, widgets, links}; dash_index selects the one
    # on screen. (dash_widgets/dash_links are the pre-1.6 single-dashboard
    # keys — still read once and migrated, see gui_dash.load_dashboards.)
    "dashboards":        [],
    "dash_index":        0,
    "dash_widgets":      [],     # legacy single dashboard (migrated away)
    "dash_links":        [],     # legacy single dashboard wires

    # Window layout — restored on launch (size / position / maximized / log).
    "win_x":             None,
    "win_y":             None,
    "win_w":             1280,
    "win_h":             780,
    "win_maximized":     False,

    # First-run coach-mark guides (set once auto-shown, so they don't reopen).
    "guide_seen_main":   False,
    "guide_seen_macros": False,
    "guide_seen_editor": False,
}

RECENT_MAX = 8


def _read_json(path):
    """Parse *path* as a settings dict, or return None if unreadable/invalid.

    A valid settings file must be a non-empty JSON object — an empty file or a
    JSON list/scalar (a sign of a truncated or corrupt write) counts as invalid
    so the caller can fall back to the backup instead of adopting garbage."""
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError, ValueError) as e:
        print(f"Ошибка чтения настроек ({os.path.basename(path)}): {e}")
        return None
    if not isinstance(data, dict) or not data:
        print(f"Настройки повреждены ({os.path.basename(path)}): не объект JSON")
        return None
    return data


def load_settings():
    """Load settings, merged over defaults. Falls back to the backup if the
    primary file is missing/corrupt, and never silently discards a corrupt file
    without preserving it (renamed to *.corrupt) so data can be recovered."""
    data = _read_json(SETTINGS_FILE)
    if data is None:
        # Primary unreadable — try the last known-good backup.
        data = _read_json(_backup_file())
        if data is not None:
            print("Настройки восстановлены из резервной копии (.bak)")
        elif os.path.exists(SETTINGS_FILE):
            # Corrupt primary and no usable backup: keep the bad file for
            # forensics/recovery instead of overwriting it with defaults.
            try:
                shutil.copy2(SETTINGS_FILE, SETTINGS_FILE + ".corrupt")
                print("Повреждённый файл сохранён как app_settings.json.corrupt")
            except OSError:
                pass
    # DEEP copies of the defaults: several are lists/dicts (recent files,
    # pinned views, dashboards, viewer configs). A shallow merge handed the
    # app the very objects that live in DEFAULT_SETTINGS, so editing one in
    # place quietly changed the "defaults" for everything created afterwards.
    merged = copy.deepcopy(DEFAULT_SETTINGS)
    if data is not None:
        merged.update(data)
    return merged


def save_settings(settings_dict):
    """Persist settings atomically.

    Writes to a temp file in the same directory, fsyncs it, backs up the current
    good file, then os.replace()s it into place. os.replace is atomic on the
    same filesystem, so a crash or exception mid-write can never truncate the
    real file (the old "open('w') then dump" left an empty file on any failure,
    which then loaded as defaults — the settings-reset bug)."""
    tmp = SETTINGS_FILE + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(settings_dict, f, indent=4, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        # Keep a rolling backup of the last good file before replacing it.
        if os.path.exists(SETTINGS_FILE):
            try:
                shutil.copy2(SETTINGS_FILE, _backup_file())
            except OSError:
                pass
        os.replace(tmp, SETTINGS_FILE)      # atomic swap
    except Exception as e:
        print(f"Ошибка сохранения настроек: {e}")
        # Don't leave a partial temp file lying around.
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
