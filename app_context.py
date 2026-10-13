# app_context.py
"""Application context — the one object that owns the cross-cutting services the
whole UI shares: the settings dict, the Modbus worker thread, the active
translator, and the theme/accent.

This is the first step in dissolving the `gui_main` "god object". Instead of
every child widget reaching back into the main window for settings / translator /
core / theme, it receives ONE ``AppContext``. The window itself sources these
through the context too — its ``settings`` / ``modbus_core`` / ``lang`` / ``t``
are read-through properties onto this object (single owner, no divergence).

Framework note: this holds a ``ModbusCore`` (a QThread) but defines no Qt signals
and builds no widgets — it is plain shared state plus the *derivations* of it
(translator, theme tokens, stylesheet). Refreshing the UI after a change
(restyle / retranslate / toolbar buttons) stays the window's job; the context
just keeps the canonical values and knows how to derive from them.
"""
from modbus_core import ModbusCore
from settings_manager import save_settings
from i18n import get_translator
from theme_manager import get_theme, set_active
from styles import get_stylesheet
import datatypes

_FONT_DEFAULT = "Inter, Segoe UI, system-ui, sans-serif"


class AppContext:
    """Shared services: settings + core + translator + theme.

    Construct once (with the loaded settings dict) and pass it to the window and,
    over time, to each child component.
    """

    def __init__(self, settings: dict):
        self.settings = settings
        self.lang = settings.get("lang", "ru")
        self.t = get_translator(self.lang)
        # Apply the user's byte-order choice to the type codecs (defaults ==
        # the historical device protocol, so a fresh install decodes as before).
        datatypes.configure_orders(settings)
        self.sync_appearance()
        self.core = ModbusCore()
        self.core.t = self.t          # the core's log lines follow the UI language
        self.core.setup_connection(settings, settings.get("slave_id", 10))

    # ── translation ────────────────────────────────────────────────
    def set_lang(self, lang: str) -> bool:
        """Switch UI language; re-derive the translator and mirror it into
        settings. Returns True if the language actually changed (so the caller
        can decide whether to retranslate the UI)."""
        changed = lang != self.lang
        self.lang = lang
        self.settings["lang"] = lang
        self.t = get_translator(lang)
        if getattr(self, "core", None) is not None:
            self.core.t = self.t
        return changed

    # ── theme ──────────────────────────────────────────────────────
    @property
    def theme(self) -> str:
        return self.settings.get("theme", "Dark")

    @property
    def accent(self) -> str:
        return self.settings.get("accent", "neutral")

    def theme_tokens(self) -> dict:
        """Color-token dict for the active theme + scheme + contrast +
        accent."""
        self.sync_appearance()
        return get_theme(self.theme, self.accent)

    def sync_appearance(self) -> None:
        """Publish the appearance so palette lookups that only know a theme
        name (dialogs, popups) match the rest of the window."""
        set_active(self.settings.get("scheme"),
                   self.settings.get("contrast"), self.accent)

    def stylesheet(self) -> str:
        """Full QSS for the active theme / scheme / contrast / font."""
        self.sync_appearance()
        return get_stylesheet(
            self.theme,
            self.settings.get("font_family", _FONT_DEFAULT),
            self.settings.get("font_size", 9),
            self.accent,
        )

    # ── settings persistence ───────────────────────────────────────
    def update(self, changes: dict) -> None:
        """Merge *changes* into settings (in place, preserving the dict identity
        the window/children share) and persist. The translator is re-derived if
        the language key changed."""
        self.settings.update(changes)
        self.sync_appearance()
        if self.settings.get("lang", self.lang) != self.lang:
            self.set_lang(self.settings["lang"])
        datatypes.configure_orders(self.settings)
        self.save()

    def save(self) -> None:
        save_settings(self.settings)
