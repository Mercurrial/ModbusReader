# gui_widgets.py
"""Reusable design-system controls: Segmented, ToggleSwitch, LabeledSlider, SwatchPicker.

These mirror the React prototype's Seg / Toggle / Slider / swatch controls so the
settings dialog (and anywhere else) can be built declaratively.
"""

from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QPushButton, QSlider, QLabel,
)
from PyQt6.QtCore import Qt, pyqtSignal, QSize
from PyQt6.QtGui import QPainter, QColor, QPen


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
    """iOS-style painted toggle (36x20). Green track when on."""

    def __init__(self, checked: bool = False, theme: dict | None = None, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setFixedSize(36, 20)
        t = theme or {}
        self._c_off  = QColor(t.get("bg_4", "#363a4b"))
        self._c_on   = QColor(t.get("ok", "#4db888"))
        self._c_knob = QColor(t.get("text_1", "#f3f4f7"))

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
        knob = QColor("#ffffff") if on else self._c_knob
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
