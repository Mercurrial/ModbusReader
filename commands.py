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

To add a page: one ``Command(..., place="view", group=...)`` below plus its
page in gui_main._view_pages(); to add a header action: one
``Command(..., place="button")`` plus ``"cmd_id": self._handler`` in
gui_main._command_handler_map(). The rail entry / button, its global shortcut
and its tooltip all follow automatically.
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
    place     where it appears:
                "view"   — a page in the left navigation rail (gui_rail.py);
                           gets the [active="true"] highlight while shown.
                "rail"   — a rail entry pinned to the rail's bottom (settings,
                           help) — the app's own housekeeping, not a page.
                "button" — action button in the header bar (connect, watch);
                           click dispatches via command_triggered(cmd_id).
                "icon"   — icon-only header-bar button (toolbar-internal).
                "hidden" — no button; shortcut-only (the action lives in a
                           dropdown, e.g. New/Open inside the project menu).
    group     rail section of a "view": "monitor" — where you watch the
              device (map, dashboard); "tools" — instruments you pick up for a
              job (console, scanner, …). Places and tools are separate so the
              rail reads as two short lists instead of one long one.
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
    group: str = ""


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

    # Pages — the left rail, in this order, every one always visible (no
    # overflow menu: ten entries fit a vertical rail, they never fit a top bar).
    Command("view_table",   "registerMap", icon="table",    shortcut="Ctrl+1",
            place="view", group="monitor"),
    Command("view_dash",    "viewDash",    icon="gauge",    shortcut="Ctrl+6",
            place="view", group="monitor"),
    Command("view_console", "viewConsole", icon="terminal", shortcut="Ctrl+3",
            place="view", group="tools"),
    Command("view_scanner", "viewScanner", icon="radar",    shortcut="Ctrl+4",
            place="view", group="tools"),
    Command("view_sniffer", "viewSniffer", icon="eye",      shortcut="Ctrl+5",
            place="view", group="tools"),
    Command("view_snapshot", "viewSnapshot", icon="camera", shortcut="Ctrl+7",
            place="view", group="tools"),
    Command("view_logger",  "viewLogger",  icon="logfile", shortcut="Ctrl+8",
            place="view", group="tools"),
    Command("view_macros",  "macros",      icon="code",     shortcut="Ctrl+M",
            place="view", group="tools"),
    Command("view_slave",   "viewSlave",   icon="cpu",      shortcut="Ctrl+9",
            place="view", group="tools"),

    # Rail footer — the app's own housekeeping.
    Command("settings", "settings", icon="sliders",  shortcut="Ctrl+,",
            place="rail"),
    Command("help",     "help",     icon="help",     shortcut="F1",
            place="rail"),

    # Header-bar actions — rendered right-to-left of the connection chip.
    Command("watch",    "watchTitle", icon="watch",  shortcut="F6"),
    Command("connect",  "connect",  icon="plug",     shortcut="F5"),

    # Right cluster — icon-only, behavior handled inside the toolbar.
    Command("theme",  "theme",  icon="moon",  shortcut="Ctrl+T", place="icon"),
    Command("layout", "layout", icon="table",                    place="icon"),
)


# ── derived views (computed once at import; do not hand-edit) ─────────────
BY_ID = {c.cmd_id: c for c in COMMANDS}
# Labelled action buttons the toolbar renders in a loop (in declaration order).
BUTTONS = tuple(c for c in COMMANDS if c.place == "button")
# Pages of the left rail (in declaration order) and its footer entries.
VIEWS = tuple(c for c in COMMANDS if c.place == "view")
RAIL_FOOTER = tuple(c for c in COMMANDS if c.place == "rail")
# Rail sections, in display order: (group id, i18n caption key).
GROUPS = (("monitor", "navGroupMonitor"), ("tools", "navGroupTools"))
# Commands whose shortcut should be registered as a real global QShortcut.
SHORTCUTS = tuple(c for c in COMMANDS if c.shortcut and c.register)
