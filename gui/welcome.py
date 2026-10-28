# gui/welcome.py
"""First launch: «make it yours» — language, theme, accent, menu, font.

Shown once, before the button tour (gui/onboarding.py), as a card over the
live window. Every pick applies AT ONCE — the window restyles behind a light
veil — so the choice is made on the real thing, not on a swatch: a dark theme
with a teal accent and the menu on top looks different from what either of
those words promises.

Nothing here is first-launch-only: all of it lives in Settings → Appearance,
and the card says so. The card only emits ``changed({key: value})``; the
window applies it exactly as a saved Settings page (gui/main_window.py,
``_apply_welcome``), then hands the card the new palette (``apply_theme``)
and language (``retranslate``).
"""

from PyQt6.QtCore import Qt, QEvent, QRectF, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontDatabase, QPainter, QPen
from PyQt6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel,
                             QPushButton, QVBoxLayout, QWidget)

from app import fonts
from app.i18n import get_translator
from app.settings_schema import ACCENT_SWATCHES, _font_to_family
from gui.theme_manager import _mix
from gui.widgets import Segmented, SwatchPicker

# Interface faces worth offering, in order; the card shows the first few that
# this machine has (plus the one in use). Windows: Segoe UI, Bahnschrift (the
# DIN-like face of control panels), Verdana (wide, for a far-away screen).
CURATED_FONTS = ("Segoe UI", "Inter", "IBM Plex Sans", "Roboto", "Bahnschrift",
                 "Verdana", "Calibri", "SF Pro Text", "Ubuntu", "Noto Sans",
                 "DejaVu Sans", "Arial")
FONT_TILES = 4
SIZES = ((9, "sizeNormal"), (10, "sizeLarger"), (11, "sizeLarge"))
RAIL_TILES = (("left", "railLeft"), ("top", "railTop"), ("right", "railRight"))


def font_choices(current: str = "") -> list:
    """Up to FONT_TILES installed interface families; the one in use first."""
    installed = set(QFontDatabase.families())
    picks = [f for f in CURATED_FONTS
             if f in installed and not fonts.is_symbol_font(f)]
    if current and current in installed and current not in picks:
        picks.insert(0, current)
    return picks[:FONT_TILES]


# ── tiles: a painted choice with a caption ──────────────────────────────
class _Tile(QWidget):
    clicked = pyqtSignal(object)

    def __init__(self, key, w: int, h: int, parent=None):
        super().__init__(parent)
        self.key = key
        self._selected = False
        self._hover = False
        self._c: dict = {}
        self.setFixedSize(w, h)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_theme(self, c: dict):
        self._c = c
        self.update()

    def set_selected(self, on: bool):
        if on != self._selected:
            self._selected = on
            self.update()

    def enterEvent(self, e):
        self._hover = True
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover = False
        self.update()
        super().leaveEvent(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.key)

    def paintEvent(self, _e):
        c = self._c
        if not c:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        box = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        if self._selected:
            p.setPen(QPen(QColor(c["accent"]), 2))
            p.setBrush(QColor(c["bg_3"]))
        else:
            p.setPen(QPen(QColor(c["line_strong" if self._hover else "line"]), 1))
            p.setBrush(QColor(c["bg_3" if self._hover else "bg_1"]))
        p.drawRoundedRect(box, 8, 8)
        self.paint_content(p, c)
        p.end()

    def paint_content(self, p: QPainter, c: dict):
        raise NotImplementedError


class _LayoutTile(_Tile):
    """A tiny window with the menu where this choice puts it."""

    def __init__(self, key: str, caption: str, parent=None):
        super().__init__(key, 92, 74, parent)
        self.caption = caption

    def paint_content(self, p, c):
        win = QRectF(14, 9, self.width() - 28, 38)
        p.setPen(QPen(QColor(c["line_strong"]), 1))
        p.setBrush(QColor(c["bg_0"]))
        p.drawRoundedRect(win, 3, 3)
        rail = QColor(c["accent"] if self._selected else c["text_4"])
        body = QRectF(win)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(rail)
        if self.key == "top":
            p.drawRoundedRect(QRectF(win.left() + 2, win.top() + 2, win.width() - 4, 6), 1.5, 1.5)
            body.setTop(win.top() + 10)
        elif self.key == "right":
            p.drawRoundedRect(QRectF(win.right() - 13, win.top() + 2, 11, win.height() - 4),
                              1.5, 1.5)
            body.setRight(win.right() - 14)
        else:
            p.drawRoundedRect(QRectF(win.left() + 2, win.top() + 2, 11, win.height() - 4),
                              1.5, 1.5)
            body.setLeft(win.left() + 14)
        # a few table rows in what is left
        rows = QColor(c["text_4"])
        rows.setAlpha(110)
        p.setBrush(rows)
        y = body.top() + 5
        for n in range(3):
            if y + 2 > body.bottom() - 2:
                break
            w = (body.width() - 10) * (1.0, 0.7, 0.85)[n]
            p.drawRoundedRect(QRectF(body.left() + 5, y, w, 2.5), 1, 1)
            y += 8
        p.setPen(QColor(c["text_1" if self._selected else "text_2"]))
        f = QFont(self.font())
        f.setPixelSize(12)
        p.setFont(f)
        p.drawText(QRectF(0, 50, self.width(), 20), int(Qt.AlignmentFlag.AlignCenter),
                   self.caption)


class _FontTile(_Tile):
    """«Aa» set in the face itself, its name underneath."""

    def __init__(self, family: str, parent=None):
        super().__init__(family, 104, 74, parent)
        self.setToolTip(family)

    def paint_content(self, p, c):
        f = QFont(self.key)
        f.setPixelSize(24)
        p.setFont(f)
        p.setPen(QColor(c["text_1"]))
        p.drawText(QRectF(0, 8, self.width(), 36), int(Qt.AlignmentFlag.AlignCenter), "Aa")
        small = QFont(self.key)
        small.setPixelSize(11)
        p.setFont(small)
        p.setPen(QColor(c["text_1" if self._selected else "text_2"]))
        name = p.fontMetrics().elidedText(self.key, Qt.TextElideMode.ElideRight,
                                          self.width() - 12)
        p.drawText(QRectF(0, 48, self.width(), 18), int(Qt.AlignmentFlag.AlignCenter), name)


class _TileRow(QWidget):
    """One choice out of a row of tiles."""

    valueChanged = pyqtSignal(object)

    def __init__(self, tiles, value=None, parent=None):
        super().__init__(parent)
        self.tiles = list(tiles)
        lo = QHBoxLayout(self)
        lo.setContentsMargins(0, 0, 0, 0)
        lo.setSpacing(8)
        for t in self.tiles:
            t.clicked.connect(self.setValue)
            lo.addWidget(t)
        lo.addStretch(1)
        self._value = value
        self._refresh()

    def _refresh(self):
        for t in self.tiles:
            t.set_selected(t.key == self._value)

    def setValue(self, value):
        if value == self._value:
            return
        self._value = value
        self._refresh()
        self.valueChanged.emit(value)

    def value(self):
        return self._value

    def set_theme(self, c: dict):
        for t in self.tiles:
            t.set_theme(c)


# ── the overlay ─────────────────────────────────────────────────────────
class WelcomeSetup(QWidget):
    """The first-launch card. ``finished(True)``: go on to the tour."""

    changed = pyqtSignal(dict)
    finished = pyqtSignal(bool)

    def __init__(self, parent, settings: dict, theme: dict, lang: str = "ru"):
        super().__init__(parent)
        self.setObjectName("welcomeOverlay")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.t = get_translator(lang)
        self._c = theme
        self._labels: list[tuple[QLabel, str]] = []
        self._build(settings)
        self.apply_theme(theme)
        self.retranslate(lang)
        parent.installEventFilter(self)

    # ── build ─────────────────────────────────────────────────────────
    def _build(self, s: dict):
        self.card = QFrame(self)
        self.card.setObjectName("welcomeCard")
        lay = QVBoxLayout(self.card)
        lay.setContentsMargins(28, 24, 28, 22)
        lay.setSpacing(6)

        self.lbl_kicker = QLabel()
        self.lbl_title = QLabel()
        self.lbl_title.setWordWrap(True)
        self.lbl_body = QLabel()
        self.lbl_body.setWordWrap(True)
        lay.addWidget(self.lbl_kicker)
        lay.addWidget(self.lbl_title)
        lay.addWidget(self.lbl_body)
        lay.addSpacing(14)

        grid = QGridLayout()
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(14)
        grid.setColumnMinimumWidth(0, 110)

        self.seg_lang = Segmented([("ru", "Русский"), ("en", "English")], s.get("lang", "ru"))
        self.seg_theme = Segmented([("Dark", "dark"), ("Light", "light")],
                                   s.get("theme", "Dark"))
        self.swatches = SwatchPicker(ACCENT_SWATCHES, s.get("accent", "neutral"))
        self.rail_tiles = _TileRow([_LayoutTile(k, "") for k, _key in RAIL_TILES],
                                   s.get("rail_position", "left"))
        current = fonts.safe_family(_font_to_family(s.get("font_choice", "")))
        self.font_tiles = _TileRow([_FontTile(f) for f in font_choices(current)], current)
        self.seg_size = Segmented([(v, key) for v, key in SIZES], s.get("font_size", 9))

        rows = (("language", self.seg_lang), ("theme", self.seg_theme),
                ("accentColor", self.swatches), ("railSection", self.rail_tiles),
                ("welcomeFont", self.font_tiles), ("welcomeSize", self.seg_size))
        for n, (key, control) in enumerate(rows):
            lbl = QLabel()
            self._labels.append((lbl, key))
            align = (Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
                     if isinstance(control, _TileRow)
                     else Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            grid.addWidget(lbl, n, 0, align)
            grid.addWidget(control, n, 1, Qt.AlignmentFlag.AlignLeft)
        if not self.font_tiles.tiles:            # no font database (headless)
            for w in (self._labels[4][0], self.font_tiles):
                w.hide()
        lay.addLayout(grid)
        lay.addSpacing(18)

        self.seg_lang.valueChanged.connect(lambda v: self.changed.emit({"lang": v}))
        self.seg_theme.valueChanged.connect(lambda v: self.changed.emit({"theme": v}))
        self.swatches.valueChanged.connect(lambda v: self.changed.emit({"accent": v}))
        self.rail_tiles.valueChanged.connect(
            lambda v: self.changed.emit({"rail_position": v}))
        self.font_tiles.valueChanged.connect(
            lambda v: self.changed.emit({"font_choice": v}))
        self.seg_size.valueChanged.connect(lambda v: self.changed.emit({"font_size": v}))

        row = QHBoxLayout()
        row.setSpacing(8)
        self.btn_skip = QPushButton()
        self.btn_tour = QPushButton()
        for b in (self.btn_skip, self.btn_tour):
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_skip.clicked.connect(lambda: self._finish(False))
        self.btn_tour.clicked.connect(lambda: self._finish(True))
        row.addWidget(self.btn_skip)
        row.addStretch(1)
        row.addWidget(self.btn_tour)
        lay.addLayout(row)

    # ── palette / language (the window calls these after applying) ────
    def apply_theme(self, c: dict):
        self._c = c
        self.card.setStyleSheet(f"""
            QFrame#welcomeCard {{
                background: {c['bg_2']};
                border: 1px solid {c['line_strong']};
                border-radius: 14px;
            }}
        """)
        self.lbl_kicker.setStyleSheet(
            f"color:{c['text_3']}; background:transparent; font-size:12px; "
            f"font-weight:700; letter-spacing:1.5px;")
        self.lbl_title.setStyleSheet(
            f"color:{c['text_1']}; background:transparent; font-size:20px; font-weight:700;")
        self.lbl_body.setStyleSheet(
            f"color:{c['text_2']}; background:transparent; font-size:13px;")
        for lbl, _key in self._labels:
            lbl.setStyleSheet(f"color:{c['text_2']}; background:transparent; font-size:13px;")
        self.btn_skip.setStyleSheet(f"""
            QPushButton {{ color:{c['text_2']}; background:transparent;
                           border:none; font-size:13px; padding:8px 6px; }}
            QPushButton:hover {{ color:{c['text_1']}; }}
        """)
        self.btn_tour.setStyleSheet(f"""
            QPushButton {{ color:{c['accent_fg']}; background:{c['accent']};
                           border:none; border-radius:7px; font-size:13px;
                           font-weight:600; padding:8px 20px; }}
            QPushButton:hover {{ background:{_mix(c['accent'], c['text_1'], 0.16)}; }}
        """)
        self.swatches.set_ring(c["text_1"])
        self.rail_tiles.set_theme(c)
        self.font_tiles.set_theme(c)
        self.update()

    def retranslate(self, lang: str):
        t = self.t = get_translator(lang)
        self.lbl_kicker.setText(t("welcomeKicker"))
        self.lbl_title.setText(t("welcomeTitle"))
        self.lbl_body.setText(t("welcomeBody"))
        for lbl, key in self._labels:
            lbl.setText(t(key))
        for val, key in (("Dark", "dark"), ("Light", "light")):
            self.seg_theme._buttons[val].setText(t(key))
        for val, key in SIZES:
            self.seg_size._buttons[val].setText(t(key))
        for tile, (_k, key) in zip(self.rail_tiles.tiles, RAIL_TILES):
            tile.caption = t(key)
            tile.update()
        self.btn_skip.setText(t("welcomeNoTour"))
        self.btn_tour.setText(t("welcomeTour"))
        self._fit()

    # ── lifecycle ─────────────────────────────────────────────────────
    def show_setup(self):
        self.setGeometry(self.parentWidget().rect())
        self.show()
        self.raise_()
        self.setFocus()
        self._fit()

    def _finish(self, tour: bool):
        p = self.parentWidget()
        if p is not None:
            p.removeEventFilter(self)
        self.hide()
        self.finished.emit(bool(tour))
        self.deleteLater()

    def _fit(self):
        self.card.setFixedWidth(max(620, self.card.sizeHint().width()))
        self.card.adjustSize()
        full = self.rect()
        self.card.move(max(16, (full.width() - self.card.width()) // 2),
                       max(16, (full.height() - self.card.height()) // 2))

    # ── events ────────────────────────────────────────────────────────
    def paintEvent(self, _e):
        # A light veil: the window behind is the preview, it must stay
        # readable (the tour's spotlight dim would hide what you pick).
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(8, 10, 14, 110))

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self._finish(False)
        elif e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._finish(True)
        else:
            super().keyPressEvent(e)

    def eventFilter(self, obj, e):
        if obj is self.parentWidget() and e.type() == QEvent.Type.Resize:
            self.setGeometry(obj.rect())
            self._fit()
        return super().eventFilter(obj, e)
