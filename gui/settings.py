# gui_settings.py
"""Settings dialog — design-faithful: icon sidebar, sectioned content,
segmented / toggle / slider controls.

The dialog is *schema-driven*: it owns no per-setting code. It renders itself by
walking ``settings_schema.PAGES`` (a Descriptor + Registry, see settings_schema.py)
— building one control per Field and reading them all back in get_new_settings().
To add a setting, add one Field to the schema; this file does not change."""

import copy
import os

from PyQt6.QtWidgets import (
    QDialog, QWidget, QHBoxLayout, QVBoxLayout, QStackedWidget,
    QListWidget, QListWidgetItem, QLabel, QLineEdit, QComboBox,
    QPushButton, QFrame, QScrollArea, QMessageBox,
)
from PyQt6.QtCore import Qt, QSize, QUrl, pyqtSignal
from PyQt6.QtGui import QFont, QFontDatabase  # noqa: F401 — patched by tests
from PyQt6.QtWidgets import QCompleter

from gui.theme_manager import get_theme
from gui.widgets import Segmented, ToggleSwitch, LabeledSlider, SwatchPicker
from app.settings_schema import PAGES, tr, iter_fields
from gui.dialogs import themed_message
from gui.qt_utils import later, debounce
from app import fonts
from app.version import APP_VERSION, RELEASE_DATE


def _settings_path() -> str:
    from app import settings_manager
    return settings_manager.SETTINGS_FILE


def _link_html(url: str, text: str, color: str) -> str:
    """Rich-text link for a QLabel (markup, not UI text — kept out of the
    widget call so the i18n guard reads only real strings)."""
    return f'<a href="{url}" style="color:{color};">{text}</a>'


def _license_path() -> str:
    """The GPL text shipped with this copy: next to the sources, inside the
    one-file bundle, or beside an installed exe ("" if none is found)."""
    import sys
    from app.paths import RESOURCES, ROOT
    for base in (RESOURCES, ROOT,
                 os.path.dirname(os.path.abspath(sys.executable))):
        for name in ("LICENSE", "LICENSE.txt"):
            p = os.path.join(base, name) if base else ""
            if p and os.path.isfile(p):
                return p
    return ""


from gui import icons


class SettingsDialog(QDialog):
    # Emitted while the user is still deciding, so the whole window shows
    # the appearance instead of a swatch in a settings row. The receiver
    # restyles WITHOUT persisting; Cancel puts the old look back.
    appearance_changed = pyqtSignal(dict)

    # Discrete controls only: previewing on every keystroke of the font
    # combo would repolish the whole window per character.
    PREVIEW_KEYS = ("theme", "scheme", "contrast", "accent")


    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)
        self.settings = settings.copy()
        # Snapshot for the unsaved-changes guard (compared on reject/Esc).
        self._original = copy.deepcopy(self.settings)
        self.lang = self.settings.get("lang", "ru")
        self._theme_name = self.settings.get("theme", "Dark")
        self.c = get_theme(self._theme_name, self.settings.get("accent"))

        self.setWindowTitle(self.L("Настройки", "Settings"))
        self.setMinimumSize(900, 600)
        self.resize(940, 640)
        self._build_ui()

    # ── bilingual helper ──────────────────────────────────────────
    def L(self, ru: str, en: str) -> str:
        return ru if self.lang == "ru" else en

    # ── build ─────────────────────────────────────────────────────
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # No header bar at all: the top-bar nav highlight says where you are,
        # Esc closes (overlay-level shortcut in gui_main) and F1 opens the
        # settings guide (_show_help delegates to the open overlay).
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        # Sidebar
        self.nav = QListWidget()
        self.nav.setObjectName("stSide")
        self.nav.setFixedWidth(220)
        self.nav.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.nav.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.stack = QStackedWidget()

        # Pages are built lazily: constructing all 8 up-front (each with custom
        # painted controls) made opening the dialog and the first tab switch
        # sluggish. We add an empty scroll container per category now and fill
        # its inner widget the first time that tab is shown; re-visits are free.
        # Every page comes from the schema registry; controls land in _controls.
        self._pages_by_key = {p.key: p for p in PAGES}
        self._controls: dict[str, QWidget] = {}
        self._page_keys: list[str] = []
        self._page_scrolls: list[QScrollArea] = []
        self._built_pages: set[int] = set()

        self.nav.setIconSize(QSize(16, 16))
        for page in PAGES:
            item = QListWidgetItem(icons.icon(page.glyph, self.c["text_3"], 16),
                                   f"  {tr(page.title, self.lang)}")
            item.setSizeHint(QSize(220, 40))
            self.nav.addItem(item)
            sa = self._scroll(None)
            self._page_keys.append(page.key)
            self._page_scrolls.append(sa)
            self.stack.addWidget(sa)

        self.nav.currentRowChanged.connect(self._on_nav_changed)
        self.nav.setCurrentRow(0)   # builds + shows the first page

        body.addWidget(self.nav)
        body.addWidget(self.stack, 1)
        root.addLayout(body, 1)

        root.addWidget(self._build_footer())

    def _build_footer(self) -> QWidget:
        foot = QWidget()
        foot.setObjectName("stFooter")
        foot.setFixedHeight(60)
        lo = QHBoxLayout(foot)
        lo.setContentsMargins(24, 0, 24, 0)
        lo.setSpacing(12)
        lo.addStretch()

        btn_cancel = QPushButton(self.L("Отмена", "Cancel"))
        btn_cancel.setFixedSize(110, 34)
        btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cancel.clicked.connect(self.reject)

        self.btn_save = QPushButton(self.L("Сохранить", "Save"))
        self.btn_save.setObjectName("btnPrimary")
        self.btn_save.setFixedSize(130, 34)
        self.btn_save.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_save.clicked.connect(self.accept)

        lo.addWidget(btn_cancel)
        lo.addWidget(self.btn_save)
        return foot

    # ── lazy page loading ─────────────────────────────────────────
    def _on_nav_changed(self, row: int):
        if row < 0:
            return
        if row not in self._built_pages:
            key = self._page_keys[row]
            self._page_scrolls[row].setWidget(self._build_page(self._pages_by_key[key]))
            self._built_pages.add(row)
        self.stack.setCurrentIndex(row)
        # The selected page's glyph takes the accent — the same signal the
        # main rail gives its active page.
        for i, page in enumerate(PAGES):
            item = self.nav.item(i)
            if item is not None:
                item.setIcon(icons.icon(
                    page.glyph, self.c["accent"] if i == row else self.c["text_3"], 16))

    # ── layout helpers ────────────────────────────────────────────
    def _scroll(self, inner: QWidget | None) -> QScrollArea:
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setFrameShape(QFrame.Shape.NoFrame)
        sa.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        if inner is not None:
            sa.setWidget(inner)
        return sa

    def _page(self) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        page.setObjectName("stContent")
        outer = QHBoxLayout(page)
        outer.setContentsMargins(36, 28, 36, 60)
        outer.setSpacing(0)
        # A readable column: a label at the far left and its control 1 000 px
        # away across a wide monitor is a form nobody can scan.
        col = QWidget()
        col.setObjectName("stColumn")
        col.setMaximumWidth(860)
        lo = QVBoxLayout(col)
        lo.setContentsMargins(0, 0, 0, 0)
        lo.setSpacing(0)
        lo.setAlignment(Qt.AlignmentFlag.AlignTop)
        outer.addWidget(col, 10)
        outer.addStretch(1)
        return page, lo

    def _section(self, parent_lo: QVBoxLayout, title: str, desc: str = "") -> QVBoxLayout:
        # Air ABOVE every section but the first. (A QSS margin-bottom on the
        # wrapper did nothing — layouts ignore it — so "Опрос" sat glued to
        # the last row of the section before.)
        if parent_lo.count():
            parent_lo.addSpacing(36)
        wrap = QWidget()
        wrap.setObjectName("stSection")
        v = QVBoxLayout(wrap)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        h = QLabel(title)
        h.setObjectName("stSectionTitle")
        v.addWidget(h)
        if desc:
            d = QLabel(desc)
            d.setObjectName("stSectionDesc")
            d.setWordWrap(True)
            v.addWidget(d)
        parent_lo.addWidget(wrap)
        return v

    def _field(self, section_lo: QVBoxLayout, name: str, control: QWidget, hint: str = ""):
        row = QWidget()
        row.setObjectName("stField")
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 14, 0, 14)
        h.setSpacing(28)

        label_col = QVBoxLayout()
        # Zero margins: a layout set on a widget gets the style's default
        # ~9 px, which pushed every label in from the section title and made
        # each row a tall slab.
        label_col.setContentsMargins(0, 0, 0, 0)
        label_col.setSpacing(3)
        nm = QLabel(name)
        nm.setObjectName("stFieldName")
        label_col.addWidget(nm)
        if hint:
            ht = QLabel(hint)
            ht.setObjectName("stFieldHint")
            ht.setWordWrap(True)
            label_col.addWidget(ht)
        lw = QWidget()
        lw.setObjectName("stFieldLabel")      # transparent (see styles.py)
        lw.setLayout(label_col)
        lw.setFixedWidth(240)

        h.addWidget(lw)
        h.addWidget(control)
        h.addStretch()
        section_lo.addWidget(row)

    def _toggle(self, checked: bool) -> ToggleSwitch:
        return ToggleSwitch(checked, theme=self.c)

    def _update_font_preview(self, family: str | None = None,
                             size: int | None = None):
        """Re-render the typography sample with the currently picked font."""
        prev = getattr(self, "_font_preview", None)
        if prev is None:
            return
        if family is not None:
            self._preview_family = family
        if size is not None:
            self._preview_size = size
        f = QFont(self._preview_family)
        # Sample is drawn a bit larger than the UI size so the face is easy
        # to judge, but still tracks the size slider.
        f.setPointSize(max(8, self._preview_size + 2))
        prev.setFont(f)
        warn = getattr(self, "_font_warn", None)
        if warn is not None:
            missing = not fonts.has_cyrillic(self._preview_family)
            warn.setText(self.L(
                "В этом шрифте нет кириллицы — русский текст будет "
                "подставлен из другого шрифта.",
                "This font has no Cyrillic — Russian text will be "
                "substituted from another face.") if missing else "")

    def _input(self, text: str, width: int = 160) -> QLineEdit:
        le = QLineEdit(text)
        le.setObjectName("stInput")
        le.setFixedWidth(width)
        return le

    # ── schema-driven page rendering ──────────────────────────────
    def _build_page(self, page) -> QWidget:
        """Build one page widget from its schema Page descriptor.

        Data pages render their sections/fields and register each control in
        ``self._controls[key]``; informational pages defer to a static builder."""
        widget, lo = self._page()
        if page.static:
            getattr(self, page.static)(lo)
            return widget
        for section in page.sections:
            s = self._section(lo, tr(section.title, self.lang), tr(section.desc, self.lang))
            for fld in section.fields:
                control = self._make_control(fld)
                self._controls[fld.key] = control
                if fld.key in self.PREVIEW_KEYS:
                    self._wire_preview(fld, control)
                self._field(s, tr(fld.label, self.lang), control, tr(fld.hint, self.lang))
        return widget

    def _make_control(self, fld) -> QWidget:
        """Construct the control for one Field, seeded from current settings."""
        init = fld.to_widget(self.settings.get(fld.key, fld.default))
        kind = fld.kind
        if kind == "toggle":
            return self._toggle(bool(init))
        if kind == "segmented":
            options = [(val, tr(label, self.lang)) for val, label in fld.options]
            return Segmented(options, init)
        if kind == "slider":
            sl = LabeledSlider(fld.minimum, fld.maximum, int(init),
                               step=fld.step, unit=tr(fld.unit, self.lang))
            if fld.key == "font_size":
                # Live-link the size slider to the font preview (built by the
                # "font" field just above it in the Typography section).
                sl.valueChanged.connect(
                    lambda v: self._update_font_preview(size=int(v)))
            return sl
        if kind == "swatch":
            return SwatchPicker(list(fld.swatches), init, ring=self.c["text_1"])
        if kind == "text":
            return self._input(str(init), fld.width)
        if kind == "font":
            # System-font picker with SEARCH (type to filter, match anywhere)
            # + a live sample that tracks family AND size. A plain QComboBox
            # (not QFontComboBox) so the saved family stays selectable even if
            # it isn't installed here. Items are added in one addItems() call
            # and the per-item FontRole (each family in its own face) is
            # assigned in deferred chunks — building 300 QFonts synchronously
            # was the visible lag when opening the Appearance tab.
            box = QWidget()
            box.setObjectName("stFieldLabel")     # a transparent holder
            v = QVBoxLayout(box)
            v.setContentsMargins(0, 0, 0, 0)
            v.setSpacing(8)
            row = QHBoxLayout()
            row.setSpacing(8)
            cb = QComboBox()
            cb.setObjectName("stInput")
            cb.setFixedWidth(fld.width)
            # Symbol families (Wingdings, the Segoe icon fonts…) are excluded:
            # choosing one turned every label — including this page — into
            # dingbats, with no readable way back.
            families = [str(f) for f in fonts.ui_families()]
            if str(init) not in families:
                families.insert(0, str(init))
            cb.addItems(families)
            cb.setCurrentText(str(init))
            cb.setMaxVisibleItems(14)
            cb.setEditable(True)
            cb.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
            comp = cb.completer()
            comp.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
            comp.setFilterMode(Qt.MatchFlag.MatchContains)
            comp.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)

            def _assign_fonts(start=0, _cb=cb):
                # The dialog may be closed (and the combo deleted) between
                # chunks — the deferred timer outlives the widget, so every
                # hop goes through the guarded qt_utils.later.
                end = min(start + 60, _cb.count())
                for i in range(start, end):
                    _cb.setItemData(i, QFont(_cb.itemText(i)),
                                    Qt.ItemDataRole.FontRole)
                if end < _cb.count():
                    later(0, _cb, _assign_fonts, end)
            later(0, cb, _assign_fonts)

            # One click back to a known-good face, from a control that is still
            # readable whatever the current font does.
            btn_reset = QPushButton(self.L("Сбросить", "Reset"))
            btn_reset.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_reset.setFixedHeight(30)
            btn_reset.clicked.connect(
                lambda: cb.setCurrentText(fonts.default_family()))
            row.addWidget(cb)
            row.addWidget(btn_reset)
            row.addStretch()

            prev = QLabel("АаБбВв · AaBbCc · 0123456789")
            prev.setObjectName("stFontPreview")
            prev.setWordWrap(True)
            self._font_preview = prev
            self._preview_family = str(init)
            self._preview_size = int(self.settings.get("font_size", 9))
            # A family with no Cyrillic still "works" (Qt falls back per glyph)
            # but mixes two typefaces on one line — say so instead of letting
            # the user wonder why the UI looks patchy.
            self._font_warn = QLabel("")
            self._font_warn.setWordWrap(True)
            self._font_warn.setStyleSheet(
                f"color:{self.c['warn']}; background:transparent; font-size:11px;")
            self._update_font_preview()
            cb.currentTextChanged.connect(
                lambda fam: self._update_font_preview(family=fam))
            v.addLayout(row)
            v.addWidget(prev)
            v.addWidget(self._font_warn)
            box._font_combo = cb          # read back in _read_control
            return box
        if kind == "combo":
            cb = QComboBox()
            cb.setObjectName("stInput")
            # (value, i18n-key) options: show the translated label, store the
            # value. Used by the colour-scheme picker, whose list also depends
            # on the current theme — a light scheme on a dark base is unusable,
            # so only the matching family is offered.
            opts = fld.options_fn() if fld.options_fn else fld.options
            if opts and isinstance(opts[0], tuple):
                from gui.theme_manager import schemes_for
                allowed = schemes_for(self.settings.get("theme", "Dark")) \
                    if fld.key == "scheme" else None
                cb.setProperty("_valueCombo", True)
                for value, label_key in opts:
                    if allowed is not None and value not in allowed:
                        continue
                    cb.addItem(tr(label_key, self.lang), value)
                idx = cb.findData(str(init))
                cb.setCurrentIndex(idx if idx >= 0 else 0)
                cb.setFixedWidth(fld.width)
                return cb
            # Dynamic item lists (e.g. detected COM ports) come from options_fn,
            # evaluated at render time; static lists from options.
            items = [str(o) for o in opts]
            # Keep the saved value selectable even when it isn't detected
            # (unplugged adapter, remote port).
            if str(init) and str(init) not in items:
                items.insert(0, str(init))
            cb.addItems(items)
            if fld.editable:
                cb.setEditable(True)
            cb.setCurrentText(str(init))
            cb.setFixedWidth(fld.width)
            return cb
        raise ValueError(f"Unknown field kind: {kind!r}")

    # ── live preview ──────────────────────────────────────────────
    def _wire_preview(self, fld, control):
        """Fire a preview whenever an appearance control changes."""
        for signal_name in ("valueChanged", "currentIndexChanged"):
            sig = getattr(control, signal_name, None)
            if sig is not None:
                sig.connect(lambda *_: self._emit_preview())
                return

    def _emit_preview(self):
        """Publish the appearance the user is currently pointing at.

        Debounced, and COALESCING: one restyle repolishes every live widget
        (~0.5 ms each, and this page alone adds several hundred), so clicking
        through schemes with a plain timer queued one full restyle per click
        and they ran one after another. Only the appearance the user landed on
        is worth rendering."""
        debounce(90, self, "preview", self._do_emit_preview)

    def _do_emit_preview(self):
        values = {}
        for key in self.PREVIEW_KEYS:
            control = self._controls.get(key)
            if control is None:
                continue
            fld = next((f for f in iter_fields() if f.key == key), None)
            if fld is not None:
                values[key] = self._read_control(fld, control)
        # The scheme list is per-theme; if the theme just flipped, the stored
        # scheme may belong to the other family and would be ignored anyway.
        from gui.theme_manager import schemes_for, DEFAULT_SCHEME
        theme = values.get("theme", self._theme_name)
        if values.get("scheme") not in schemes_for(theme):
            values["scheme"] = DEFAULT_SCHEME.get(str(theme).lower(), "")
        self.appearance_changed.emit(values)

    def _read_control(self, fld, control):
        """Read a control's current value back into a settings value."""
        kind = fld.kind
        if kind == "toggle":
            value = control.isChecked()
        elif kind in ("segmented", "swatch", "slider"):
            value = control.value()
        elif kind == "text":
            value = control.text()
        elif kind == "combo":
            value = (control.currentData() if control.property("_valueCombo")
                     else control.currentText())
        elif kind == "font":
            value = control._font_combo.currentText()
        else:
            raise ValueError(f"Unknown field kind: {kind!r}")
        return fld.from_widget(value)

    # ── static (informational) pages ──────────────────────────────
    # Keys handled inside particular widgets (not global commands). The global
    # part of the page is GENERATED from commands.COMMANDS — the hand-written
    # list it replaced had drifted (Ctrl+7 listed as Slave after Snapshots
    # took it; Ctrl+N/O still described as "profile" after the project took
    # them; Ctrl+S, Ctrl+8, Ctrl+9 missing).
    _LOCAL_KEYS = (
        ("scGroupTable", (
            ("scEditValue", "F2"), ("scNextRow", "Tab / Shift+Tab"),
            ("scContextMenu", "RMB"), ("scMemoryViewer", "2× LMB"),
            ("scVerboseDot", "LMB ●"),
        )),
        ("scGroupEditor", (
            ("scUndo", "Ctrl+Z"), ("scRedo", "Ctrl+Shift+Z"),
            ("scSaveMap", "Ctrl+S"), ("scSaveMapAs", "Ctrl+Shift+S"),
            ("scDeleteRow", "Del"),
        )),
        ("scGroupDash", (
            ("scDashEdit", "Ctrl+E"), ("scDashZoom", "Ctrl+± / Ctrl+0"),
            ("scDashCopy", "Ctrl+C / Ctrl+X / Ctrl+V"), ("scDashDup", "Ctrl+D"),
            ("scDashSelectAll", "Ctrl+A"), ("scDashDelete", "Del"),
            ("scDashNudge", "← ↑ → ↓  (Shift ×10)"),
        )),
    )

    @staticmethod
    def _keys(seq: str) -> list:
        """'Ctrl+Shift+N' -> ['Ctrl', 'Shift', 'N']; free text stays whole."""
        if " " in seq or "/" in seq:
            return [seq]
        return [k for k in seq.split("+") if k] or [seq]

    def _static_shortcuts(self, lo: QVBoxLayout):
        from app import commands
        by_place = {"view": [], "doc": [], "global": []}
        doc_ids = {"new_project", "open_project", "save_project",
                   "new_config", "open_config", "view_map"}
        for cmd in commands.COMMANDS:
            if not cmd.shortcut:
                continue
            if cmd.place == "view":
                by_place["view"].append(cmd)
            elif cmd.cmd_id in doc_ids:
                by_place["doc"].append(cmd)
            else:
                by_place["global"].append(cmd)
        groups = (("scGroupViews", by_place["view"]),
                  ("scGroupDocs", by_place["doc"]),
                  ("scGroupGlobal", by_place["global"]))
        for title_key, cmds in groups:
            s = self._section(lo, tr(title_key, self.lang))
            for cmd in cmds:
                label = tr(cmd.label_key, self.lang).rstrip("…").rstrip(".")
                s.addWidget(self._shortcut_row(label, self._keys(cmd.shortcut)))
            if title_key == "scGroupViews":
                s.addWidget(self._shortcut_row(tr("scCloseOverlay", self.lang),
                                               ["Esc"]))
        for title_key, rows in self._LOCAL_KEYS:
            s = self._section(lo, tr(title_key, self.lang))
            for label_key, seq in rows:
                s.addWidget(self._shortcut_row(tr(label_key, self.lang),
                                               self._keys(seq)))

    def _shortcut_row(self, label: str, keys: list[str]) -> QWidget:
        row = QWidget()
        row.setObjectName("stShortcutRow")
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 8, 0, 8)
        lbl = QLabel(label)
        lbl.setObjectName("stShortcutLbl")
        h.addWidget(lbl)
        h.addStretch()
        for k in keys:
            pill = QLabel(k)
            pill.setObjectName("kbdPill")
            h.addWidget(pill)
        return row

    def _static_about(self, lo: QVBoxLayout):
        # Identity first, like every About screen: the mark, the name, the
        # version — then the reference rows.
        hero = QWidget()
        hero.setObjectName("stFieldLabel")
        hl = QHBoxLayout(hero)
        hl.setContentsMargins(0, 0, 0, 0)       # _section adds the air below
        hl.setSpacing(18)
        mark = QLabel()
        mark.setObjectName("stFieldLabel")
        logo = icons.app_icon()
        if not logo.isNull():
            mark.setPixmap(logo.pixmap(QSize(64, 64), self.devicePixelRatioF()))
        mark.setFixedSize(64, 64)
        hl.addWidget(mark, 0, Qt.AlignmentFlag.AlignTop)
        names = QVBoxLayout()
        names.setSpacing(2)
        nm = QLabel("ModbusReader")
        nm.setObjectName("stSectionTitle")
        names.addWidget(nm)
        ver = QLabel(self.L(f"Версия {APP_VERSION} · {RELEASE_DATE}",
                            f"Version {APP_VERSION} · {RELEASE_DATE}"))
        ver.setObjectName("stAboutKey")
        names.addWidget(ver)
        desc = QLabel(self.L(
            "Наладка и мониторинг приборов по Modbus RTU — как мастер и как "
            "эмулятор прибора.",
            "Commissioning and monitoring of Modbus RTU devices — as a master "
            "and as a device emulator."))
        desc.setObjectName("stSectionDesc")
        desc.setWordWrap(True)
        names.addSpacing(6)
        names.addWidget(desc)
        hl.addLayout(names, 1)
        lo.addWidget(hero)
        self._about_updates(lo)
        s = self._section(lo, self.L("Сведения", "Details"))
        import sys
        from PyQt6.QtCore import PYQT_VERSION_STR
        for label, val in [
            (self.L("Протокол", "Protocol"),
             self.L("Modbus RTU · FC 01–06, 15, 16",
                    "Modbus RTU · FC 01–06, 15, 16")),
            ("Python · PyQt", f"{sys.version.split()[0]} · {PYQT_VERSION_STR}"),
            (self.L("Файл настроек", "Settings file"), _settings_path()),
        ]:
            row = QWidget()
            row.setObjectName("stAboutRow")
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 8, 0, 8)
            k = QLabel(label)
            k.setObjectName("stAboutKey")
            v = QLabel(val)
            v.setObjectName("stAboutVal")
            v.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            h.addWidget(k)
            h.addStretch()
            h.addWidget(v)
            s.addWidget(row)
        self._about_license(lo)

    def _about_license(self, lo: QVBoxLayout):
        """«Проект»: the licence, the absence of warranty and where the
        source is (GPL asks a program that talks to the user to say so), and
        the one quiet place that mentions support — no pop-ups, ever."""
        from app.version import DONATE_URL, LICENSE_ID, SOURCE_URL
        s = self._section(lo, self.L("Проект", "Project"))
        lic_file = _license_path()
        lic_url = (QUrl.fromLocalFile(lic_file).toString() if lic_file
                   else f"{SOURCE_URL}/blob/main/LICENSE")
        link = self.c["text_1"]
        for label, text, url in [
            (self.L("Текст лицензии", "Licence text"), LICENSE_ID, lic_url),
            (self.L("Исходный код", "Source code"),
             SOURCE_URL.removeprefix("https://"), SOURCE_URL),
            (self.L("Поддержать проект", "Support the project"),
             DONATE_URL.removeprefix("https://"), DONATE_URL),
        ]:
            row = QWidget()
            row.setObjectName("stAboutRow")
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 8, 0, 8)
            k = QLabel(label)
            k.setObjectName("stAboutKey")
            v = QLabel(_link_html(url, text, link))
            v.setObjectName("stAboutVal")
            v.setOpenExternalLinks(True)
            h.addWidget(k)
            h.addStretch()
            h.addWidget(v)
            s.addWidget(row)
        note = QLabel(self.L(
            "Свободная программа: её можно использовать, изменять и "
            "распространять на условиях GNU GPL версии 3 или более поздней. "
            "Предоставляется без каких-либо гарантий.",
            "Free software: you may use, modify and redistribute it under "
            "the GNU GPL version 3 or later. It comes with absolutely no "
            "warranty."))
        note.setObjectName("stFieldHint")
        note.setWordWrap(True)
        s.addWidget(note)

    def _about_updates(self, lo: QVBoxLayout):
        """«Обновления»: where the last check stands + «Проверить сейчас».
        The controller lives on the main window (gui_update)."""
        # Embedded as an overlay the dialog is re-parented into the page
        # stack, so look up the chain for the window that owns the controller.
        owner = self.parent()
        while owner is not None and not hasattr(owner, "update_ctl"):
            owner = owner.parent()
        ctl = getattr(owner, "update_ctl", None)
        if ctl is None:
            return
        s = self._section(lo, tr("updSection", self.lang))
        row = QWidget()
        row.setObjectName("stAboutRow")
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 8, 0, 8)
        self.lbl_update = QLabel(ctl.status_text)
        self.lbl_update.setObjectName("stAboutKey")
        self.lbl_update.setWordWrap(True)
        ctl.status_changed.connect(self.lbl_update.setText)
        btn = QPushButton(tr("updCheckNow", self.lang))
        btn.setObjectName("btnSecondary")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(lambda: ctl.check(manual=True))
        self.btn_check_updates = btn
        h.addWidget(self.lbl_update, 1)
        h.addWidget(btn)
        s.addWidget(row)
        if ctl.kind == "source":
            note = QLabel(tr("updSourceNote", self.lang))
            note.setObjectName("stFieldHint")
            note.setWordWrap(True)
            s.addWidget(note)

    # ── result ────────────────────────────────────────────────────
    def _ensure_all_pages_built(self):
        """Force-build any lazily-skipped pages so their controls exist before
        we read them. Cheap: only unbuilt pages pay the cost, and only on Save."""
        for row, key in enumerate(self._page_keys):
            if row not in self._built_pages:
                self._page_scrolls[row].setWidget(self._build_page(self._pages_by_key[key]))
                self._built_pages.add(row)

    def get_new_settings(self) -> dict:
        """Read every control back into the settings dict (schema order).

        Mutates and returns ``self.settings`` in place — callers rely on that."""
        self._ensure_all_pages_built()
        st = self.settings
        for fld in iter_fields():
            control = self._controls.get(fld.key)
            if control is None:
                continue
            value = self._read_control(fld, control)
            st[fld.key] = value
            if fld.derive:
                st.update(fld.derive(value))
        # Preserved passthrough (no dedicated control).
        st["show_row_nums"] = st.get("show_row_nums", True)
        return st

    # ── unsaved-changes guard ─────────────────────────────────────
    def _has_unsaved_changes(self) -> bool:
        """True if any control differs from the values the dialog opened with.
        Reads the live controls without disturbing the original snapshot."""
        snapshot = copy.deepcopy(self.settings)
        try:
            current = copy.deepcopy(self.get_new_settings())
        finally:
            # get_new_settings() mutates self.settings in place; restore it so a
            # later Cancel/Save behaves exactly as before this check ran.
            self.settings = snapshot
        return any(current.get(k) != v for k, v in self._original.items()) \
            or any(k not in self._original for k in current)

    def reject(self):
        if self._has_unsaved_changes():
            # Ask the question the user is actually facing, and put the
            # consequence in the body instead of a vague "what would you like
            # to do?". Order: cancel · discard · save (save is the default).
            choice = themed_message(
                self, self._theme_name, "warning",
                self.L("Сохранить изменения?", "Save changes?"),
                self.L("Если закрыть настройки сейчас, изменения будут потеряны.",
                       "Closing settings now will discard your changes."),
                [(self.L("Отмена", "Cancel"),
                  QMessageBox.ButtonRole.RejectRole, False),
                 (self.L("Не сохранять", "Discard"),
                  QMessageBox.ButtonRole.DestructiveRole, False),
                 (self.L("Сохранить", "Save"),
                  QMessageBox.ButtonRole.AcceptRole, True)])
            if choice == 2:                   # Save
                self.accept()
                return
            if choice != 1:                   # anything but Discard -> stay
                return
            # choice == 1 (Discard) -> fall through and throw the edits away
        super().reject()

    # ── Guide ─────────────────────────────────────────────────────
    def _show_guide(self):
        """Coach-mark tour of the settings — focuses on connection setup."""
        if getattr(self, "_guide", None) is not None:
            return
        from gui.onboarding import OnboardingGuide
        L = self.L
        # Jump to the Connection page so its controls exist and are visible
        # before the guide tries to spotlight them.
        if "connection" in self._page_keys:
            self.nav.setCurrentRow(self._page_keys.index("connection"))
        steps = [
            {"target": None,
             "title": L("Настройки приложения", "Application settings"),
             "body":  L("Слева — разделы настроек. Самое важное для начала — "
                        "раздел «Подключение»: без верных параметров порта "
                        "устройство не отвечает.",
                        "On the left are the settings categories. The most "
                        "important one to start with is «Connection» — without "
                        "the right port parameters the device won't respond.")},
            {"target": self.nav,
             "title": L("Разделы", "Categories"),
             "body":  L("Переключайтесь между разделами: общие, внешний вид, "
                        "таблица, графики, журнал, подключение и горячие клавиши.",
                        "Switch between categories: general, appearance, table, "
                        "graphs, log, connection and shortcuts.")},
            {"target": self._controls.get("port"),
             "title": L("COM-порт", "COM port"),
             "body":  L("Укажите имя порта (например, COM3) и скорость, "
                        "совпадающие с настройками устройства.",
                        "Enter the port name (e.g. COM3) and baud rate that match "
                        "your device's configuration.")},
            {"target": self._controls.get("baudrate"),
             "title": L("Скорость и параметры", "Baud rate & framing"),
             "body":  L("Скорость, чётность и стоп-биты должны совпадать с "
                        "устройством. Здесь же — период опроса и таймаут.",
                        "Baud rate, parity and stop bits must match the device. "
                        "Polling period and timeout live here too.")},
            {"target": self.btn_save,
             "title": L("Сохранить", "Save"),
             "body":  L("Сохраняет настройки и применяет их сразу. При выходе "
                        "без сохранения приложение предупредит о потере "
                        "изменений.",
                        "Saves the settings and applies them immediately. If you "
                        "leave without saving, the app warns you about losing "
                        "changes.")},
        ]
        self._guide = OnboardingGuide(self, steps, self._theme_name,
                                      self.settings.get("accent"), self.lang)
        self._guide.finished.connect(lambda: setattr(self, "_guide", None))
        self._guide.show_guide()
