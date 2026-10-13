# commands.py
"""Registry of application commands — the single source of truth for the
top-bar action buttons, their keyboard shortcuts, and their tooltips.

Descriptor + Registry style (mirrors datatypes.py / settings_schema.py): every
user-triggerable top-bar action is one frozen ``Command`` descriptor and
``COMMANDS`` is the ordered registry. From this one place:

  * the toolbar (gui_toolbar.py) builds its buttons — label, icon, order — and
    derives every tooltip ("label  (shortcut)");
  * the main window (gui_main.py) registers the global QShortcuts and dispatches
    a triggered command id to the matching handler.

Before, the same knowledge lived in three drifting places: a ``SHORTCUTS`` dict
(for tooltips), a separate ``_setup_shortcuts`` list (for the real bindings), and
hand-wired ``action_*`` signals (for the click handlers). Now the shortcut string,
label key and icon for each command live here once.

The descriptor holds only DATA. The actual handler is a bound method that lives
in the controller (gui_main), which maps ``cmd_id -> callable`` exactly once; this
module imports nothing from Qt or the GUI, exactly like the other registries.

To add a top-bar action button:
    1. add ONE ``Command(..., place="button")`` below — display order follows
       declaration order;
    2. add ``"cmd_id": self._handler`` to gui_main._command_handler_map().
The button, its global shortcut and its tooltip all follow automatically.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Command:
    """One user-triggerable action.

    cmd_id    stable id — the dispatch key AND the ``btn_<cmd_id>`` attribute the
              toolbar exposes (the onboarding guide spotlights e.g. btn_connect).
    label_key i18n key (see i18n.get_translator) for the button / tooltip label.
    icon      icons.icon name ("" = none). For ``theme`` the toolbar paints a
              dynamic moon/sun glyph instead of this static name.
    shortcut  QKeySequence string ("" = none); shown as the "(…)" tooltip hint.
    place     how it appears in the top bar:
                "button" — labelled action button; click dispatches to the
                           controller via command_triggered(cmd_id).
                "view"   — navigation button (main view switcher); dispatches
                           like a button and gets the [active="true"] highlight
                           when its view is the current one.
                "menu"   — labelled button that opens a dropdown (toolbar-internal).
                "icon"   — icon-only right-cluster button (toolbar-internal).
                "hidden" — no button; shortcut-only (the action lives in a
                           dropdown, e.g. New/Open inside the Profile menu).
    register  register ``shortcut`` as a global QShortcut. ``False`` makes it a
              display-only alias — the Profile button shows "(Ctrl+N)" but Ctrl+N
              itself is owned by the hidden ``new_config`` command.
    """
    cmd_id: str
    label_key: str
    icon: str = ""
    shortcut: str = ""
    place: str = "button"
    register: bool = True


# ── the registry (top-bar order == declaration order for place=="button") ──
COMMANDS: tuple = (
    # Shortcut-only members of the head-bar project dropdown (the dropdown
    # itself lives in the register-map head bar, not the top bar).
    #
    # The PROJECT owns the unmodified Ctrl+N/O/S. It is the document you work
    # in, and everywhere else in desktop software those three keys belong to
    # the document. The bare register map — one part of a project — takes the
    # Shift variants, which is the same convention every editor uses for
    # "the other, more specific New".
    Command("new_project",  "projectNew",    shortcut="Ctrl+N", place="hidden"),
    Command("open_project", "projectOpen",   shortcut="Ctrl+O", place="hidden"),
    Command("save_project", "projectSave",   shortcut="Ctrl+S", place="hidden"),
    Command("new_config",  "newProfile",  shortcut="Ctrl+Shift+N", place="hidden"),
    Command("open_config", "openProfile", shortcut="Ctrl+Shift+O", place="hidden"),
    # Focus the register search box (switches to the map view first).
    Command("search", "search", shortcut="Ctrl+F", place="hidden"),
    # The map editor opens as an overlay from the profile dropdown; Ctrl+2
    # stays as a power-user shortcut.
    Command("view_map", "viewMap", icon="edit", shortcut="Ctrl+2",
            place="hidden"),

    # Main views — the nav cluster. Which ones show as labelled tabs is the
    # user's choice (settings["pinned_views"]); the rest live in the toolbar's
    # overflow menu. The active one gets the highlight either way.
    Command("view_table",   "registerMap", icon="table",    shortcut="Ctrl+1",
            place="view"),
    Command("view_console", "viewConsole", icon="terminal", shortcut="Ctrl+3",
            place="view"),
    Command("view_scanner", "viewScanner", icon="radar",    shortcut="Ctrl+4",
            place="view"),
    Command("view_sniffer", "viewSniffer", icon="eye",      shortcut="Ctrl+5",
            place="view"),
    Command("view_dash",    "viewDash",    icon="gauge",    shortcut="Ctrl+6",
            place="view"),
    Command("view_snapshot", "viewSnapshot", icon="check",  shortcut="Ctrl+7",
            place="view"),
    Command("view_logger",  "viewLogger",  icon="download", shortcut="Ctrl+8",
            place="view"),
    Command("view_slave",   "viewSlave",   icon="cpu",      shortcut="Ctrl+9",
            place="view"),

    # Main action buttons — rendered left-to-right in this order.
    Command("settings", "settings", icon="sliders",  shortcut="Ctrl+,"),
    Command("macros",   "macros",   icon="play",     shortcut="Ctrl+M"),
    Command("connect",  "connect",  icon="plug",     shortcut="F5"),
    Command("help",     "help",     icon="help",     shortcut="F1"),

    # Right cluster — icon-only, behavior handled inside the toolbar.
    Command("theme",  "theme",  icon="moon",  shortcut="Ctrl+T", place="icon"),
    Command("layout", "layout", icon="table",                    place="icon"),
)


# ── derived views (computed once at import; do not hand-edit) ─────────────
BY_ID = {c.cmd_id: c for c in COMMANDS}
# Labelled action buttons the toolbar renders in a loop (in declaration order).
BUTTONS = tuple(c for c in COMMANDS if c.place == "button")
# Main-view nav buttons (the switcher cluster, in declaration order).
VIEWS = tuple(c for c in COMMANDS if c.place == "view")
# Commands whose shortcut should be registered as a real global QShortcut.
SHORTCUTS = tuple(c for c in COMMANDS if c.shortcut and c.register)
