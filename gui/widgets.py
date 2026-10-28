# gui/widgets.py
"""Reusable design-system controls: Segmented, ToggleSwitch, LabeledSlider, SwatchPicker.

These mirror the React prototype's Seg / Toggle / Slider / swatch controls so the
settings dialog (and anywhere else) can be built declaratively.
"""

from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QPushButton, QSlider, QLabel, QHeaderView,
)
from PyQt6.QtCore import Qt, pyqtSignal, QSize
from PyQt6.QtGui import QPainter, QColor, QPen, QPalette


class Segmented(QWidget):
    """Horizontal segmented button group. options: list of (value, label)."""

    valueChanged = pyqtSignal(object)

    def __init__(self, options, value=None, parent=None):
        super().__init__(parent)
        self.setObjectName("segmented")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        # Fixed height: inside a stretching layout the pill would grow into a
        # tall gray rectangle (same bug the toolbar RU/EN switch had).
        self.setFixedHeight(30)
        self._buttons: dict = {}

        lo = QHBoxLayout(self)
        lo.setContentsMargins(2, 2, 2, 2)
        lo.setSpacing(1)

        for val, label in options:
            b = QPushButton(str(label))
            b.setObjectName("segItem")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.clicked.connect(lambda _, v=val: self.setValue(v))
            self._buttons[val] = b
            lo.addWidget(b)

        self._value = value if value is not None else (options[0][0] if options else None)
        self._refresh()

    def _refresh(self):
        for val, b in self._buttons.items():
            active = "true" if val == self._value else "false"
            b.setChecked(val == self._value)
            b.setProperty("active", active)
            b.style().unpolish(b)
            b.style().polish(b)

    def setValue(self, value):
        if value not in self._buttons or value == self._value:
            self._refresh()
            return
        self._value = value
        self._refresh()
        self.valueChanged.emit(value)

    def value(self):
        return self._value


class ToggleSwitch(QPushButton):
    """Painted toggle (36x20). The track takes the ACCENT when on, like every
    other "selected" state in the app (segments, the RU/EN pill) — a green
    switch next to an accent segmented control was two colours for one
    meaning."""

    def __init__(self, checked: bool = False, theme: dict | None = None, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setFixedSize(36, 20)
        t = theme or {}
        self._c_off  = QColor(t.get("bg_4", "#363a4b"))
        self._c_on   = QColor(t.get("accent", "#4db888"))
        self._c_knob_on = QColor(t.get("accent_fg", "#ffffff"))
        bg0 = QColor(t.get("bg_0", "#0a0c0f"))
        # Off knob: white on a light theme, the text colour on a dark one.
        self._c_knob = (QColor("#ffffff") if bg0.lightnessF() > 0.5
                        else QColor(t.get("text_1", "#f3f4f7")))

    def sizeHint(self) -> QSize:
        return QSize(36, 20)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        on = self.isChecked()

        # Track
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self._c_on if on else self._c_off)
        p.drawRoundedRect(0, 0, 36, 20, 10, 10)

        # Knob
        knob = self._c_knob_on if on else self._c_knob
        p.setBrush(knob)
        x = 18 if on else 2
        p.drawEllipse(x, 2, 16, 16)
        p.end()


class LabeledSlider(QWidget):
    """Horizontal slider + monospace value readout with unit suffix."""

    valueChanged = pyqtSignal(int)

    def __init__(self, minimum: int, maximum: int, value: int,
                 step: int = 1, unit: str = "", parent=None):
        super().__init__(parent)
        self._unit = unit

        lo = QHBoxLayout(self)
        lo.setContentsMargins(0, 0, 0, 0)
        lo.setSpacing(12)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setMinimum(minimum)
        self.slider.setMaximum(maximum)
        self.slider.setSingleStep(step)
        self.slider.setPageStep(step)
        self.slider.setValue(value)
        self.slider.setFixedWidth(220)
        self.slider.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self.lbl = QLabel()
        self.lbl.setObjectName("sliderVal")
        self.lbl.setMinimumWidth(54)

        self.slider.valueChanged.connect(self._on_change)
        lo.addWidget(self.slider)
        lo.addWidget(self.lbl)
        self._update_label(value)

    def _on_change(self, v: int):
        self._update_label(v)
        self.valueChanged.emit(v)

    def _update_label(self, v: int):
        self.lbl.setText(f"{v}{self._unit}")

    def value(self) -> int:
        return self.slider.value()


class _Swatch(QWidget):
    """A single painted color swatch. Selected = larger fill + contrasting ring."""

    clicked = pyqtSignal(str)

    BOX = 34   # outer box so the selected ring has room to breathe

    def __init__(self, key: str, hex_color: str, ring: str, parent=None):
        super().__init__(parent)
        self._key   = key
        self._color = QColor(hex_color)
        self._ring  = QColor(ring)
        self._selected = False
        self.setFixedSize(self.BOX, self.BOX)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(key)

    def setSelected(self, sel: bool):
        if sel != self._selected:
            self._selected = sel
            self.update()

    def mousePressEvent(self, _e):
        self.clicked.emit(self._key)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        cx, cy = self.width() / 2, self.height() / 2

        if self._selected:
            # Larger fill (24px) + a clear contrasting ring around it.
            d = 24
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(self._color)
            p.drawRoundedRect(int(cx - d / 2), int(cy - d / 2), d, d, 8, 8)
            pen = QPen(self._ring)
            pen.setWidth(2)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            r = d + 7
            p.drawRoundedRect(int(cx - r / 2), int(cy - r / 2), r, r, 10, 10)
        else:
            # Smaller fill (18px) with a faint border.
            d = 18
            pen = QPen(QColor(self._ring))
            pen.setColor(QColor(self._ring.red(), self._ring.green(),
                                self._ring.blue(), 40))
            pen.setWidth(1)
            p.setPen(pen)
            p.setBrush(self._color)
            p.drawRoundedRect(int(cx - d / 2), int(cy - d / 2), d, d, 6, 6)
        p.end()


class SwatchPicker(QWidget):
    """Row of color swatches; emits the selected key.

    *ring* is the contrast color used for the selection ring — pass the theme's
    primary text color so the indicator reads on both light and dark surfaces."""

    valueChanged = pyqtSignal(str)

    def __init__(self, swatches, value=None, ring: str = "#f3f4f7", parent=None):
        """swatches: list of (key, hex_color)."""
        super().__init__(parent)
        self._buttons: dict = {}

        lo = QHBoxLayout(self)
        lo.setContentsMargins(0, 0, 0, 0)
        lo.setSpacing(6)

        for key, hex_color in swatches:
            sw = _Swatch(key, hex_color, ring)
            sw.clicked.connect(self.setValue)
            self._buttons[key] = sw
            lo.addWidget(sw)
        lo.addStretch()

        self._value = value if value is not None else (swatches[0][0] if swatches else None)
        self._refresh()

    def _refresh(self):
        for key, b in self._buttons.items():
            b.setSelected(key == self._value)

    def setValue(self, key: str):
        if key not in self._buttons:
            return
        self._value = key
        self._refresh()
        self.valueChanged.emit(key)

    def value(self):
        return self._value

    def set_ring(self, ring: str):
        """The selection ring's colour — the theme's text colour, so a theme
        switch under a live picker (the welcome card) keeps it readable."""
        for sw in self._buttons.values():
            sw._ring = QColor(ring)
            sw.update()


class EmptyState(QWidget):
    """"Nothing here yet" — an icon in a soft tile, a title, one or two
    sentences and (optionally) the action that fills the page.

    Replaces bare black grids: an empty page is where a newcomer decides
    whether the tool is broken, so it says what the page is for and offers
    the first step. ``setText`` keeps the old QLabel#emptyState call sites
    working (it sets the body)."""

    def __init__(self, icon_name: str = "info", title: str = "", body: str = "",
                 parent=None):
        super().__init__(parent)
        from PyQt6.QtWidgets import QVBoxLayout
        self.setObjectName("emptyPane")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._icon_name = icon_name
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.addStretch(2)
        col = QVBoxLayout()
        col.setSpacing(8)
        # Into the widget FIRST: a label added to a layout that is not yet
        # attached has no parent, so the setVisible(True) in _fit_body()
        # showed it as a top-level window — five of them flashed at start-up,
        # each taking the foreground and handing it back to the previous
        # program, which then kept it: the main window opened behind it.
        outer.addLayout(col)
        self.tile = QLabel()
        self.tile.setObjectName("emptyTile")
        self.tile.setFixedSize(52, 52)
        self.tile.setAlignment(Qt.AlignmentFlag.AlignCenter)
        col.addWidget(self.tile, 0, Qt.AlignmentFlag.AlignHCenter)
        col.addSpacing(6)
        self.lbl_title = QLabel(title)
        self.lbl_title.setObjectName("emptyTitle")
        self.lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        col.addWidget(self.lbl_title)
        self.lbl_body = QLabel(body)
        self.lbl_body.setObjectName("emptyBody")
        self.lbl_body.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_body.setWordWrap(True)
        self.lbl_body.setFixedWidth(440)
        col.addWidget(self.lbl_body, 0, Qt.AlignmentFlag.AlignHCenter)
        self._fit_body()
        self._actions = QHBoxLayout()
        self._actions.setSpacing(8)
        self._actions.addStretch(1)
        self._actions_end = QWidget()          # marker; buttons go before it
        self._actions_end.setFixedSize(0, 0)
        self._actions.addWidget(self._actions_end)
        self._actions.addStretch(1)
        col.addSpacing(14)
        col.addLayout(self._actions)
        outer.addStretch(3)
        self.buttons: list[QPushButton] = []

    def add_action(self, text: str, callback, primary: bool = False) -> QPushButton:
        b = QPushButton(text)
        # Own name for the outline button: pages with a local stylesheet
        # (the map editor) restyle "btnSecondary" as a ghost button.
        b.setObjectName("btnPrimary" if primary else "btnOutline")
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.clicked.connect(callback)
        self._actions.insertWidget(self._actions.indexOf(self._actions_end), b)
        self.buttons.append(b)
        return b

    def set_content(self, title: str = None, body: str = None):
        if title is not None:
            self.lbl_title.setText(title)
            self.lbl_title.setVisible(bool(title))
        if body is not None:
            self.lbl_body.setText(body)
            self._fit_body()

    def _fit_body(self):
        # A wrapped label inside centring layouts is sized from its one-line
        # hint and gets clipped; pin the height its width actually needs.
        self.lbl_body.ensurePolished()
        self.lbl_body.setFixedHeight(max(0, self.lbl_body.heightForWidth(440)))
        self.lbl_body.setVisible(bool(self.lbl_body.text()))

    # The final font is only known once the widget is polished — a page with
    # its own stylesheet (the map editor) restyles the body after __init__,
    # and a height computed earlier clipped its second line.
    def showEvent(self, e):
        super().showEvent(e)
        self._fit_body()

    def changeEvent(self, e):
        super().changeEvent(e)
        from PyQt6.QtCore import QEvent
        if e.type() in (QEvent.Type.StyleChange, QEvent.Type.FontChange):
            self._fit_body()

    def setText(self, body: str):             # QLabel-compatible
        self.set_content(body=body)

    def text(self) -> str:
        return self.lbl_body.text()

    def apply_theme(self, tokens: dict):
        from gui import icons
        self.tile.setPixmap(icons.pixmap(self._icon_name, tokens["text_3"], 24))


class RowNumberHeader(QHeaderView):
    """Row numbers that belong to their row: the zebra stripe runs through
    the number too. A stock vertical header paints every section on one
    colour, so each stripe started a number's width in from the edge — a
    stepped, chequered left margin.

    Qt stripes by position among the VISIBLE rows (a filtered-out row does
    not flip the colour), so the parity is counted the same way."""

    def __init__(self, parent=None):
        super().__init__(Qt.Orientation.Vertical, parent)
        self.setSectionsClickable(True)        # as QTableView's own header
        self.setHighlightSections(True)
        self._odd: set[int] = set()

    def paintEvent(self, event):
        view = self.parent()
        self._odd = set()
        if view is not None and view.alternatingRowColors():
            n = 0
            for v in range(self.count()):
                li = self.logicalIndex(v)
                if not self.isSectionHidden(li):
                    if n & 1:
                        self._odd.add(li)
                    n += 1
        super().paintEvent(event)

    def paintSection(self, painter, rect, logical):
        if logical in self._odd:
            painter.fillRect(rect, self.parent().palette().color(
                QPalette.ColorRole.AlternateBase))
        super().paintSection(painter, rect, logical)


class EmptyOverlay:
    """Lays an EmptyState over a scroll area's viewport while the area is
    empty. For a table, "empty" means no rows and the model's own row signals
    drive it — a view gets an empty state without touching its fill/clear
    logic. Anything else passes *is_empty*. *when()* adds a condition (e.g.
    "not while scanning"); call ``refresh()`` whenever either changes for a
    reason the overlay cannot see."""

    def __init__(self, area, pane: "EmptyState", is_empty=None, when=None):
        from PyQt6.QtCore import QObject, QEvent

        self.area, self.pane = area, pane
        self.is_empty = is_empty or (lambda: area.rowCount() == 0)
        self.when = when
        vp = area.viewport()
        pane.setParent(vp)

        class _Filter(QObject):
            def eventFilter(_s, obj, ev):
                if ev.type() == QEvent.Type.Resize:
                    pane.setGeometry(obj.rect())
                return False

        self._filter = _Filter(vp)
        vp.installEventFilter(self._filter)
        if is_empty is None and hasattr(area, "model"):
            m = area.model()
            for sig in (m.rowsInserted, m.rowsRemoved, m.modelReset):
                sig.connect(lambda *_: self.refresh())
        self.refresh()

    def refresh(self):
        from PyQt6 import sip
        if sip.isdeleted(self.area) or sip.isdeleted(self.pane):
            return                     # the model's last signals at teardown
        empty = bool(self.is_empty()) and (self.when() if self.when else True)
        self.pane.setGeometry(self.area.viewport().rect())
        self.pane.setVisible(empty)
        if empty:
            self.pane.raise_()


class DropButton(QPushButton):
    """A button that opens a menu: its label plus a drawn chevron at the right
    edge (the "▾" text glyph it replaces came from the font and never matched
    the stroke icons around it). Reserve the room with QSS padding-right."""

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self._chev = "#888888"

    def set_chevron_color(self, color: str):
        self._chev = color
        self.update()

    def paintEvent(self, e):
        super().paintEvent(e)
        from gui import icons
        p = QPainter(self)
        size = 10
        p.drawPixmap(self.width() - size - 9, (self.height() - size) // 2,
                     icons.pixmap("chevron", self._chev, size))
        p.end()
