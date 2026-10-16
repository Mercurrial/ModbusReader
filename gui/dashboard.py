# gui_dash.py
"""Dashboard — a free-form mini-HMI with wired automation.

Two modes (like every professional editor):
  * **Run** — widgets are live: buttons write, inputs send, timers tick.
    Nothing can be moved by accident.
  * **Edit** — widgets are dragged/resized freely; PowerPoint-style alignment
    guides snap them to their neighbours' edges and centers (hold Alt for raw
    pixel placement). Ports appear on the sides and can be **wired**: drag from
    a widget's right dot to another widget's left dot and the source's pulse
    activates the target (timer → button → register write).

Widget kinds live in ``dash_model.KINDS``; the layout math and the automation
graph are pure and unit-tested there. This module owns painting + interaction.

Safety: **no device writes happen in edit mode** — timers are stopped and the
controls are inert while the canvas is being arranged.
"""

import math
import time
import uuid
from collections import deque

from PyQt6.QtCore import (
    Qt, QRectF, QRect, QPoint, QPointF, QTimer, pyqtSignal,
)
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QFont, QPolygonF, QPainterPath, QBrush, QPixmap,
    QLinearGradient, QRadialGradient,
)
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QMenu, QLineEdit, QComboBox, QFileDialog,
)
from PyQt6 import sip

from core import datatypes
from core import formats

from gui import icons
from gui.widgets import EmptyState, EmptyOverlay
from core import scaling
from core import dash_model as dm
from gui.dialogs import themed_info, themed_input
from gui.dashboard_dialog import WidgetDialog

STALE_AFTER = 5.0          # s without a sample -> dim the card
SPARK_LEN = 60             # samples kept for the value-card sparkline
CHART_LEN = 240            # longer window for the chart kind
PORT_R = 5                 # port dot radius
PASTE_STEP = 24            # each repeated paste steps this far down-right
PULSE_TRAVEL = 0.5         # s a pulse takes to visibly cross one wire
PULSE_FADE = 0.28          # s for a card's activation flash to fade out
SHEET_W, SHEET_H = 1600, 1000   # logical work-sheet size (like a slide)
PAN_MARGIN = 240           # px of slack past the viewport, so panning always
                           # has somewhere to go
HANDLE = 14                # resize handle size


def _f(text, default=0.0) -> float:
    try:
        return float(str(text).replace(",", "."))
    except (TypeError, ValueError):
        return default


def _tidy(v) -> str:
    """Short numeric label: no trailing zeros, no '.0' on whole numbers."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    if not math.isfinite(f):
        return str(f)                    # int(inf) would raise inside paint
    if f == int(f) and abs(f) < 1e15:
        return str(int(f))
    return f"{f:.3f}".rstrip("0").rstrip(".")


def alarm_state(cfg: dict, value) -> bool:
    """True when *value* violates the optional low/high alarm thresholds."""
    if value is None:
        return False
    try:
        v = float(value)
        lo = None if cfg.get("alo") is None else float(cfg.get("alo"))
        hi = None if cfg.get("ahi") is None else float(cfg.get("ahi"))
    except (TypeError, ValueError):
        return False                     # a hand-edited threshold: no alarm
    if lo is not None and v < lo:
        return True
    if hi is not None and v > hi:
        return True
    return False


def led_on(cfg: dict, value) -> bool:
    """LED semantics: on when value > threshold (XOR the invert flag)."""
    if value is None:
        return False
    try:
        on = float(value) > _f(cfg.get("thr", 0.5))
    except (TypeError, ValueError):
        return False
    return (not on) if cfg.get("invert") else on


# ═══════════════════════════════════════════════════════════════════════
#  ONE WIDGET
# ═══════════════════════════════════════════════════════════════════════
class DashCard(QWidget):
    """A single dashboard widget: painted by kind, draggable in edit mode,
    interactive in run mode."""

    edit_requested      = pyqtSignal(str)
    duplicate_requested = pyqtSignal(str)
    remove_requested    = pyqtSignal(str)
    clip_requested      = pyqtSignal(str, str)        # uid, "copy" | "cut"
    # uid + "was Ctrl/Shift held" — the view needs the modifier to decide
    # between replacing the selection and extending it.
    selected            = pyqtSignal(str, bool)
    move_started        = pyqtSignal(str, QPoint)     # uid, grab offset
    move_moved          = pyqtSignal(str, QPoint)     # global cursor
    move_finished       = pyqtSignal(str)
    resize_moved        = pyqtSignal(str, QPoint)
    resize_finished     = pyqtSignal(str)
    wire_started        = pyqtSignal(str)
    wire_moved          = pyqtSignal(QPoint)
    wire_finished       = pyqtSignal(QPoint)
    fired               = pyqtSignal(str, object)     # uid, payload
    watch_requested     = pyqtSignal(str)             # reg_id

    _THRESHOLD = 4

    def __init__(self, cfg: dict, ctx, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.ctx = ctx
        self.value = None
        self.stale = False
        self.state_on = False              # toggle state / timer running
        self.pulse = 0.0                   # 0..1 activation flash
        self._pulse_at = 0.0               # when it was triggered
        # The chart kind is the history — it keeps a longer window than the
        # sparkline that only hints at the trend.
        self.history: deque = deque(
            maxlen=CHART_LEN if cfg.get("kind") == "chart" else SPARK_LEN)
        self._slider_frac = None           # 0..1 while a slider is grabbed
        self._select_value = None          # last picked option (select kind)
        self.last_sample = 0.0
        self.edit = False
        self.is_selected = False
        self.wire_candidate = False        # a wire is looking for a target
        self.wire_hover = False            # …and this widget is under it
        self._press = None
        self._mode = None                  # "move" | "resize" | "wire"
        self._pan_via_canvas = False       # right/middle drag routed to canvas
        self._zoom = 1.0                   # screen px per logical px
        self.setMouseTracking(True)
        self.setObjectName("dashCard")

        # Real input field for the "input" kind (typing needs a live widget).
        self.editor = None
        if cfg.get("kind") == "input":
            self.editor = QLineEdit(self)
            self.editor.setObjectName("dashInput")
            self.editor.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.editor.returnPressed.connect(self._send_input)
        self._layout_children()

    # ── LOGICAL geometry ─────────────────────────────────────────────
    # Everything below (painting, ports, hit-testing) works in *logical*
    # pixels: the widget occupies ``logical × zoom`` on screen and paintEvent
    # scales the painter. That is what makes zoom grow the TEXT and the
    # controls, not just the box — a card at 200 % is the same card, twice the
    # size, instead of the same fonts rattling around in a bigger frame.
    def set_zoom(self, z: float):
        if abs(z - self._zoom) > 1e-6:
            self._zoom = z
            self._layout_children()
            self.update()

    @property
    def pw(self) -> float:
        return self.width() / self._zoom

    @property
    def ph(self) -> float:
        return self.height() / self._zoom

    def prect(self) -> QRectF:
        return QRectF(0, 0, self.pw, self.ph)

    def to_logical(self, pt: QPoint) -> QPoint:
        """Widget (screen) pixels → logical pixels, for hit-testing."""
        return QPoint(int(pt.x() / self._zoom), int(pt.y() / self._zoom))

    def _layout_children(self):
        if self.editor is not None:
            z = self._zoom
            self.editor.setGeometry(int(14 * z), int(44 * z),
                                    int(max(60.0, self.pw - 28) * z),
                                    int(30 * z))
            f = QFont(self.editor.font())
            f.setPointSizeF(max(6.0, 10.0 * z))
            self.editor.setFont(f)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._layout_children()

    # Ports sit one radius inside the border so the dots aren't clipped by the
    # widget rect; wires start/end at the same points. LOGICAL coordinates —
    # callers on the canvas multiply by zoom.
    def in_port_pos(self) -> QPoint:
        return QPoint(PORT_R, int(self.ph // 2))

    def out_port_pos(self) -> QPoint:
        return QPoint(int(self.pw - PORT_R), int(self.ph // 2))

    def _handle_rect(self) -> QRect:
        return QRect(int(self.pw - HANDLE), int(self.ph - HANDLE), HANDLE, HANDLE)

    def _port_rect(self, out: bool) -> QRect:
        p = self.out_port_pos() if out else self.in_port_pos()
        r = PORT_R + 4
        return QRect(p.x() - r, p.y() - r, 2 * r, 2 * r)

    # ── mode / data ──────────────────────────────────────────────────
    def set_edit(self, edit: bool):
        self.edit = edit
        if self.editor is not None:
            self.editor.setEnabled(not edit)
            self.editor.setAttribute(
                Qt.WidgetAttribute.WA_TransparentForMouseEvents, edit)
        self.setCursor(Qt.CursorShape.OpenHandCursor if edit
                       else self._run_cursor())
        self.update()

    def _run_cursor(self):
        k = dm.kind(self.cfg.get("kind", "value"))
        return (Qt.CursorShape.PointingHandCursor if k.writes
                or self.cfg.get("kind") == "timer"
                else Qt.CursorShape.ArrowCursor)

    def set_selected(self, on: bool):
        if on != self.is_selected:
            self.is_selected = on
            self.update()

    def set_wire_candidate(self, on: bool):
        if on != self.wire_candidate:
            self.wire_candidate = on
            self.update()

    def set_wire_hover(self, on: bool):
        if on != self.wire_hover:
            self.wire_hover = on
            self.update()

    def update_value(self, value):
        self.value = value
        self.last_sample = time.monotonic()
        self.stale = False
        try:
            self.history.append(float(value))
        except (TypeError, ValueError):
            pass
        self.update()

    def set_stale(self, stale: bool):
        if stale != self.stale:
            self.stale = stale
            self.update()

    def flash(self):
        """Short accent pulse when the widget is activated (by click or wire).

        There is deliberately NO per-card animation object here. A
        QVariantAnimation whose callback touches the card can outlive it, and
        touching a dead C++ object is an access violation — not something a
        guard can reliably catch. Instead the card records *when* it was hit
        and the view's single repaint timer fades every card (see
        ``decay_pulse``): no extra objects, nothing to leak, nothing to fire
        after the card is gone."""
        self.pulse = 1.0
        self._pulse_at = time.monotonic()
        self.update()

    def decay_pulse(self, now: float) -> bool:
        """Advance the fade; True while this card still needs repainting."""
        if self.pulse <= 0.0:
            return False
        frac = (now - self._pulse_at) / PULSE_FADE
        self.pulse = 0.0 if frac >= 1.0 else (1.0 - frac) ** 3   # OutCubic
        self.update()
        return self.pulse > 0.0

    def stop_flash(self):
        """Cancel a running pulse (called before the card is destroyed)."""
        self.pulse = 0.0

    def title_text(self) -> str:
        return (self.cfg.get("title") or self.cfg.get("name")
                or datatypes.id_label(self.cfg.get("reg_id", "")))

    # ── interaction ──────────────────────────────────────────────────
    def _canvas(self):
        """The scrollable surface this card lives on (its parent)."""
        p = self.parentWidget()
        return p if hasattr(p, "pan_press") else None

    def mousePressEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton:
            # Pan gestures must work over widgets too, not just empty canvas.
            cv = self._canvas()
            if cv is not None and cv.pan_press(e.globalPosition().toPoint(),
                                               e.button()):
                self._pan_via_canvas = True
                e.accept()
                return
            return super().mousePressEvent(e)
        self._pan_via_canvas = False
        pos = self.to_logical(e.position().toPoint())
        additive = bool(e.modifiers() & (Qt.KeyboardModifier.ControlModifier
                                         | Qt.KeyboardModifier.ShiftModifier))
        self.selected.emit(self.cfg["uid"], additive)
        if self.edit:
            spec = dm.kind(self.cfg.get("kind", "value"))
            if self._handle_rect().contains(pos):
                self._mode = "resize"
            elif spec.has_out and self._port_rect(True).contains(pos):
                self._mode = "wire"
                self.wire_started.emit(self.cfg["uid"])
            else:
                self._mode = "move"
            self._press = pos
            return
        # Run mode: a slider is grabbed and followed until release; everything
        # else acts on the press.
        if self.cfg.get("kind") == "slider":
            self._mode = "slide"
            self.slider_set_from_x(pos.x())
            return
        self._activate_by_user()

    def mouseMoveEvent(self, e):
        if self._pan_via_canvas:
            cv = self._canvas()
            if cv is not None and cv.pan_move(e.globalPosition().toPoint()):
                e.accept()
                return
        if self._mode == "slide":
            self.slider_set_from_x(self.to_logical(e.position().toPoint()).x())
            if self.cfg.get("live"):
                self.fired.emit(self.cfg["uid"], self.slider_value())
            return
        if self.edit and self._mode is None:
            # Hover feedback: the corner resizes, the right dot starts a wire.
            pos = self.to_logical(e.position().toPoint())
            spec = dm.kind(self.cfg.get("kind", "value"))
            if self._handle_rect().contains(pos):
                self.setCursor(Qt.CursorShape.SizeFDiagCursor)
            elif spec.has_out and self._port_rect(True).contains(pos):
                self.setCursor(Qt.CursorShape.CrossCursor)
            else:
                self.setCursor(Qt.CursorShape.OpenHandCursor)
        # A drag only exists while the button is actually held. Without this
        # check any lost release (a modal dialog opened by the double-click
        # swallows it) left the card glued to the cursor afterwards.
        if not (e.buttons() & Qt.MouseButton.LeftButton):
            if self._mode in ("move", "resize", "wire"):
                self._cancel_gesture()
            return super().mouseMoveEvent(e)
        if not self.edit or self._press is None or self._mode is None:
            return super().mouseMoveEvent(e)
        g = e.globalPosition().toPoint()
        if self._mode == "move":
            if (self.to_logical(e.position().toPoint()) - self._press).manhattanLength() \
                    >= self._THRESHOLD or self.property("_moving"):
                self.setProperty("_moving", True)
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
                # Pass WHERE inside the card it was grabbed, so the view can
                # keep that point under the cursor instead of teleporting the
                # card to a fixed offset.
                self.move_started.emit(self.cfg["uid"], self._press)
                self.move_moved.emit(self.cfg["uid"], g)
        elif self._mode == "resize":
            self.resize_moved.emit(self.cfg["uid"], g)
        elif self._mode == "wire":
            self.wire_moved.emit(g)

    def mouseReleaseEvent(self, e):
        if self._pan_via_canvas:
            self._pan_via_canvas = False
            cv = self._canvas()
            outcome = cv.pan_release() if cv is not None else ""
            if outcome == "click":
                self._show_card_menu(e.globalPosition().toPoint())
            e.accept()
            return
        if self._mode == "slide":
            value = self.slider_value()
            self._mode = None
            self._slider_frac = None        # fall back to the live value again
            self.update()
            if value is not None:
                self.fired.emit(self.cfg["uid"], value)
            return
        if self.edit and self._mode:
            g = e.globalPosition().toPoint()
            if self._mode == "move":
                self.setProperty("_moving", False)
                self.setCursor(Qt.CursorShape.OpenHandCursor)
                self.move_finished.emit(self.cfg["uid"])
            elif self._mode == "resize":
                self.resize_finished.emit(self.cfg["uid"])
            elif self._mode == "wire":
                self.wire_finished.emit(g)
            self._mode = None
            self._press = None
            return
        super().mouseReleaseEvent(e)

    def _cancel_gesture(self):
        """Drop any in-flight move/resize/wire and restore the idle cursor."""
        was = self._mode
        self._mode = None
        self._press = None
        self.setProperty("_moving", False)
        if self.edit:
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        if was == "move":
            self.move_finished.emit(self.cfg["uid"])
        elif was == "wire":
            self.wire_finished.emit(self.mapToGlobal(QPoint(-9999, -9999)))

    def mouseDoubleClickEvent(self, e):
        if self.edit and e.button() == Qt.MouseButton.LeftButton:
            # The press that preceded this double-click armed a move. The edit
            # dialog is modal, so the release never comes back here — drop the
            # gesture NOW or the card follows the cursor once the dialog closes.
            #
            # And do NOT call super(): QWidget's default double-click handler
            # forwards to mousePressEvent, which would immediately re-arm the
            # very move we just cancelled.
            self._cancel_gesture()
            e.accept()
            self.edit_requested.emit(self.cfg["uid"])
            return
        super().mouseDoubleClickEvent(e)

    def _show_card_menu(self, global_pos: QPoint):
        t = self.ctx.t
        m = QMenu(self)
        act_edit = m.addAction(t("dashEdit"))
        act_dup = m.addAction(t("dashDuplicate"))
        m.addSeparator()
        act_copy = m.addAction(t("dashCopy"))
        act_cut = m.addAction(t("dashCut"))
        m.addSeparator()
        act_del = m.addAction(t("deleteRow"))
        act_watch = None
        if self.cfg.get("reg_id"):
            m.addSeparator()
            act_watch = m.addAction(t("watchAddTo"))
        chosen = m.exec(global_pos)
        # The menu ran its own event loop; anything armed before it is stale.
        self._cancel_gesture()
        if chosen is act_edit:
            self.edit_requested.emit(self.cfg["uid"])
        elif chosen is act_dup:
            self.duplicate_requested.emit(self.cfg["uid"])
        elif chosen is act_copy:
            self.clip_requested.emit(self.cfg["uid"], "copy")
        elif chosen is act_cut:
            self.clip_requested.emit(self.cfg["uid"], "cut")
        elif chosen is act_del:
            self.remove_requested.emit(self.cfg["uid"])
        elif act_watch is not None and chosen is act_watch:
            self.watch_requested.emit(str(self.cfg["reg_id"]))

    def contextMenuEvent(self, e):
        # Right-press is a pan gesture now; the menu is opened from the release
        # when the pointer did not travel. Swallow Qt's own context-menu event
        # so the menu never appears mid-pan.
        e.accept()

    def _send_input(self):
        if not self.edit and self.editor is not None:
            self.fired.emit(self.cfg["uid"], self.editor.text().strip())

    def _activate_by_user(self):
        """Run-mode click: what it means depends on the kind."""
        k = self.cfg.get("kind", "value")
        if k in ("button", "toggle", "timer"):
            self.fired.emit(self.cfg["uid"], None)
        elif k == "input" and self.editor is not None:
            self._send_input()
        elif k == "select":
            self._open_select_menu()

    def _open_select_menu(self):
        """Pick a named value. Nothing is written until an item is chosen —
        opening the list must never touch the device."""
        opts = self.select_options()
        if not opts:
            return
        m = QMenu(self)
        acts = {m.addAction(label): val for val, label in opts}
        box = self.select_box().bottomLeft() * self._zoom
        chosen = m.exec(self.mapToGlobal(box.toPoint()))
        if chosen in acts:
            self._select_value = acts[chosen]
            self.update()
            self.fired.emit(self.cfg["uid"], acts[chosen])

    # ═══════════════════ painting ═══════════════════
    def paintEvent(self, _e):
        c = self.ctx.theme_tokens()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # One scale here is what makes zoom real: every painter below draws in
        # logical pixels and comes out correctly sized, fonts included.
        p.scale(self._zoom, self._zoom)
        r = self.prect().adjusted(1, 1, -1, -1)
        k = self.cfg.get("kind", "value")
        alarm = alarm_state(self.cfg, self.value) and not self.stale

        # Card body: a very shallow top-to-bottom gradient reads as a lit
        # surface instead of a flat rectangle, without becoming decoration.
        grad = QLinearGradient(0, r.top(), 0, r.bottom())
        top = QColor(c["bg_1"]).lighter(106 if self.ctx.theme == "Dark" else 102)
        grad.setColorAt(0.0, top)
        grad.setColorAt(1.0, QColor(c["bg_1"]))
        p.setPen(QPen(QColor(c["line"]), 1))
        p.setBrush(QBrush(grad))
        p.drawRoundedRect(r, 10, 10)
        if self.pulse > 0.01:
            glow = QColor(c["accent"])
            glow.setAlpha(int(90 * self.pulse))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(glow)
            p.drawRoundedRect(r, 10, 10)
        if alarm:
            p.setPen(QPen(QColor(c["error"]), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(r, 10, 10)
        elif self.is_selected and self.edit:
            p.setPen(QPen(QColor(c["accent"]), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(r, 10, 10)

        # title
        if k != "label":
            p.setPen(QColor(c["text_3"]))
            f = QFont(self.font())
            f.setPointSize(8)
            p.setFont(f)
            p.drawText(QRectF(14, 8, self.pw - 40, 18),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       self.title_text())
            # Stale is otherwise only "the text went grey" — an explicit dot in
            # the corner says *why*: no fresh sample from the device.
            if self.stale:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(c["warn"]))
                p.drawEllipse(QPointF(self.pw - 15, 16), 3.0, 3.0)

        painter = {
            "value": self._paint_value, "led": self._paint_led,
            "bar": self._paint_bar, "gauge": self._paint_gauge,
            "bits": self._paint_bits, "chart": self._paint_chart,
            "button": self._paint_button, "toggle": self._paint_toggle,
            "slider": self._paint_slider, "select": self._paint_select,
            "timer": self._paint_timer, "input": self._paint_input,
            "gate": self._paint_gate, "label": self._paint_label,
        }.get(k, self._paint_value)
        painter(p, c, alarm)

        if self.edit:
            self._paint_edit_chrome(p, c)
        p.end()

    def _paint_edit_chrome(self, p: QPainter, c: dict):
        spec = dm.kind(self.cfg.get("kind", "value"))
        # While a wire is being dragged, legal drop targets glow and the one
        # under the cursor is outlined — no guessing where a wire may land.
        if self.wire_candidate:
            col = QColor(c["info"])
            if self.wire_hover:
                p.setPen(QPen(col, 2))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRoundedRect(self.prect().adjusted(1, 1, -1, -1), 10, 10)
            halo = QColor(col)
            halo.setAlpha(70 if self.wire_hover else 32)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(halo)
            ip = self.in_port_pos()
            p.drawEllipse(QPointF(ip), PORT_R + (9 if self.wire_hover else 5),
                          PORT_R + (9 if self.wire_hover else 5))
        p.setPen(Qt.PenStyle.NoPen)
        for is_out, has in ((False, spec.has_in), (True, spec.has_out)):
            if not has:
                continue
            pos = self.out_port_pos() if is_out else self.in_port_pos()
            r = PORT_R + (1.5 if (not is_out and self.wire_hover) else 0)
            p.setBrush(QColor(c["accent"] if is_out else c["info"]))
            p.drawEllipse(QPointF(pos), r, r)
            p.setBrush(QColor(c["bg_1"]))
            p.drawEllipse(QPointF(pos), r - 2.2, r - 2.2)
        # resize handle (two short strokes in the corner)
        p.setPen(QPen(QColor(c["text_4"]), 1.6))
        hr = self._handle_rect()
        p.drawLine(hr.right() - 2, hr.bottom() - 8, hr.right() - 8, hr.bottom() - 2)
        p.drawLine(hr.right() - 2, hr.bottom() - 3, hr.right() - 3, hr.bottom() - 2)

    # value helpers
    def _value_color(self, c, alarm):
        if self.stale:
            return QColor(c["text_4"])
        return QColor(c["error"] if alarm else c["text_1"])

    def _fill_color(self, c, alarm):
        if self.stale:
            return QColor(c["bg_4"])
        return QColor(c["error"] if alarm else c["accent"])

    def _value_text(self) -> str:
        if self.value is None:
            return "—"
        v = self.value
        if isinstance(v, float) and not v.is_integer():
            return f"{v:.2f}"
        return str(int(v)) if isinstance(v, float) else str(v)

    def _fraction(self) -> float:
        frac = self._range_frac(self.value)
        return 0.0 if frac is None else frac

    def _range_frac(self, v):
        """Position of *v* inside [vmin, vmax] as 0..1, or None if unusable."""
        if v is None:
            return None
        vmin = _f(self.cfg.get("vmin", 0))
        vmax = _f(self.cfg.get("vmax", 100))
        if vmax <= vmin:
            return None
        try:
            return max(0.0, min(1.0, (float(v) - vmin) / (vmax - vmin)))
        except (TypeError, ValueError):
            return None

    def _mono(self, size, bold=True) -> QFont:
        f = QFont("JetBrains Mono")
        if not f.exactMatch():
            f.setFamily("Consolas")
        f.setPointSize(size)
        f.setBold(bold)
        return f

    def _fit_pt(self, base: int) -> int:
        """Scale the main font with the card so resizing actually helps."""
        return max(9, min(base, int(self.ph / 5)))

    # ── display kinds ────────────────────────────────────────────────
    def _paint_value(self, p, c, alarm):
        h = self.ph
        p.setPen(self._value_color(c, alarm))
        p.setFont(self._mono(self._fit_pt(24)))
        p.drawText(QRectF(0, 26, self.pw, h * 0.42),
                   Qt.AlignmentFlag.AlignCenter, self._value_text())
        p.setPen(QColor(c["text_3"]))
        f2 = QFont(self.font())
        f2.setPointSize(9)
        p.setFont(f2)
        p.drawText(QRectF(0, 26 + h * 0.42, self.pw, 18),
                   Qt.AlignmentFlag.AlignCenter, self.cfg.get("unit", ""))
        if len(self.history) >= 2 and h > 110:
            x0, x1 = 14.0, self.pw - 14.0
            y1, y0 = h - 12.0, h - 40.0
            lo, hi = min(self.history), max(self.history)
            span = (hi - lo) or 1.0
            pts = QPolygonF()
            n = len(self.history)
            for i, v in enumerate(self.history):
                pts.append(QPointF(x0 + (x1 - x0) * i / (n - 1),
                                   y1 - (y1 - y0) * (v - lo) / span))
            p.setPen(QPen(QColor(c["text_4"] if self.stale else c["accent_soft"]), 1.4))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPolyline(pts)

    def _paint_led(self, p, c, _alarm):
        on = led_on(self.cfg, self.value) and not self.stale
        cy = self.ph * 0.52
        rad = max(14, min(30, self.ph * 0.22))
        cx = self.pw / 2
        color = QColor(c["ok"]) if on else QColor(c["bg_4"])
        if on:
            glow = QColor(c["ok"])
            glow.setAlpha(60)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(glow)
            p.drawEllipse(QPointF(cx, cy), rad + 8, rad + 8)
        # A real lamp is lit from above: a radial gradient offset to the
        # upper-left reads as a glass dome instead of a flat disc.
        lamp = QRadialGradient(cx - rad * 0.3, cy - rad * 0.35, rad * 1.5)
        lamp.setColorAt(0.0, color.lighter(150 if on else 118))
        lamp.setColorAt(1.0, color.darker(115))
        p.setPen(QPen(QColor(c["line_strong"]), 1))
        p.setBrush(QBrush(lamp))
        p.drawEllipse(QPointF(cx, cy), rad, rad)
        p.setPen(QColor(c["text_4"] if self.stale else c["text_3"]))
        f = QFont(self.font())
        f.setPointSize(9)
        p.setFont(f)
        p.drawText(QRectF(0, self.ph - 30, self.pw, 20),
                   Qt.AlignmentFlag.AlignCenter, self._value_text())

    def _paint_bar(self, p, c, alarm):
        x, w = 20, self.pw - 40
        y, hh = self.ph * 0.42, 16
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(c["bg_3"]))
        p.drawRoundedRect(QRectF(x, y, w, hh), hh / 2, hh / 2)
        frac = self._fraction()
        if frac > 0:
            fill = self._fill_color(c, alarm)
            g = QLinearGradient(x, y, x, y + hh)
            g.setColorAt(0.0, fill.lighter(122))
            g.setColorAt(1.0, fill)
            p.setBrush(QBrush(g))
            p.drawRoundedRect(QRectF(x, y, max(hh, w * frac), hh), hh / 2, hh / 2)
        # alarm thresholds as ticks on the track — the limit is visible before
        # it is crossed, not only once the card turns red
        for key in ("alo", "ahi"):
            tick = self._range_frac(self.cfg.get(key))
            if tick is None:
                continue
            p.setPen(QPen(QColor(c["error"]), 1.5))
            tx = x + w * tick
            p.drawLine(QPointF(tx, y - 3), QPointF(tx, y + hh + 3))
            p.setPen(Qt.PenStyle.NoPen)
        p.setPen(self._value_color(c, alarm))
        p.setFont(self._mono(self._fit_pt(13)))
        p.drawText(QRectF(0, y + hh + 6, self.pw, 26),
                   Qt.AlignmentFlag.AlignCenter,
                   f"{self._value_text()} {self.cfg.get('unit', '')}".strip())
        p.setPen(QColor(c["text_4"]))
        f2 = QFont(self.font())
        f2.setPointSize(7)
        p.setFont(f2)
        p.drawText(QRectF(x, y + hh + 2, 70, 14), Qt.AlignmentFlag.AlignLeft,
                   str(self.cfg.get("vmin", 0)))
        p.drawText(QRectF(x + w - 70, y + hh + 2, 70, 14),
                   Qt.AlignmentFlag.AlignRight, str(self.cfg.get("vmax", 100)))

    def _paint_gauge(self, p, c, alarm):
        cx = self.pw / 2
        cy = self.ph * 0.60
        rad = max(28, min(self.pw, self.ph * 1.15) * 0.30)
        rect = QRectF(cx - rad, cy - rad, 2 * rad, 2 * rad)
        start, span = 225, -270
        pen = QPen(QColor(c["bg_3"]), 9)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawArc(rect, start * 16, span * 16)
        # minor ticks around the dial — turns a coloured arc into a scale
        p.setPen(QPen(QColor(c["line_strong"]), 1))
        for i in range(11):
            a = math.radians(start + span * i / 10)
            ca, sa = math.cos(a), math.sin(a)
            r0 = rad + (6 if i % 5 == 0 else 7)
            r1 = rad + 11
            p.drawLine(QPointF(cx + r0 * ca, cy - r0 * sa),
                       QPointF(cx + r1 * ca, cy - r1 * sa))
        frac = self._fraction()
        if frac > 0:
            pen.setColor(self._fill_color(c, alarm))
            p.setPen(pen)
            p.drawArc(rect, start * 16, int(span * frac) * 16)
        ang = math.radians(start + span * frac)
        needle = QColor(c["text_4"] if self.stale else c["text_1"])
        p.setPen(QPen(needle, 2))
        p.drawLine(int(cx), int(cy),
                   int(cx + (rad - 12) * math.cos(ang)),
                   int(cy - (rad - 12) * math.sin(ang)))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(needle)
        p.drawEllipse(QPointF(cx, cy), 4, 4)
        p.setPen(self._value_color(c, alarm))
        p.setFont(self._mono(self._fit_pt(12)))
        p.drawText(QRectF(0, self.ph - 30, self.pw, 24),
                   Qt.AlignmentFlag.AlignCenter,
                   f"{self._value_text()} {self.cfg.get('unit', '')}".strip())

    def _paint_bits(self, p, c, _alarm):
        """A 16-bit status word as 16 cells, MSB left — how a Modbus status
        register is actually read in a datasheet."""
        try:
            word = int(round(float(self.value))) & 0xFFFF
        except (TypeError, ValueError):
            word = None
        top = 32.0
        avail_h = self.ph - top - 10
        rows = 1 if (self.pw > 470 and avail_h < 54) else 2
        per = 16 // rows
        pad = 12.0
        cw = (self.pw - 2 * pad) / per
        ch = min(30.0, avail_h / rows - 12)
        f = QFont(self.font())
        f.setPointSize(7)
        for i in range(16):
            bit = 15 - i                       # MSB first, left to right
            row, col = divmod(i, per)
            x = pad + col * cw
            y = top + row * (ch + 15)
            cell = QRectF(x + 1.5, y, cw - 3, ch)
            on = word is not None and (word >> bit) & 1
            p.setPen(Qt.PenStyle.NoPen)
            if on and not self.stale:
                p.setBrush(QColor(c["accent"]))
            else:
                p.setBrush(QColor(c["bg_3"]))
            p.drawRoundedRect(cell, 3, 3)
            if on and not self.stale:
                p.setPen(QColor(c["accent_fg"]))
                fb = QFont(f)
                fb.setBold(True)
                p.setFont(fb)
                p.drawText(cell, Qt.AlignmentFlag.AlignCenter, "1")
            p.setPen(QColor(c["text_4"]))
            p.setFont(f)
            p.drawText(QRectF(x, y + ch, cw, 13),
                       Qt.AlignmentFlag.AlignCenter, str(bit))
        p.setPen(QColor(c["text_3"]))
        f2 = self._mono(9)
        p.setFont(f2)
        p.drawText(QRectF(0, 10, self.pw - 14, 16),
                   Qt.AlignmentFlag.AlignRight,
                   "—" if word is None else f"0x{word:04X}")

    def _paint_chart(self, p, c, alarm):
        """A real mini-trend: filled area, min/max labels and the last value.
        The value card's sparkline answers 'is it moving'; this answers
        'what has it been doing'."""
        left, right = 40.0, 12.0
        top, bottom = 30.0, 22.0
        plot = QRectF(left, top, max(20.0, self.pw - left - right),
                      max(16.0, self.ph - top - bottom))
        p.setPen(QPen(QColor(c["line_soft"]), 1))
        p.setBrush(QColor(c["bg_0"]))
        p.drawRoundedRect(plot, 5, 5)
        hist = list(self.history)
        f = QFont(self.font())
        f.setPointSize(7)
        p.setFont(f)
        if len(hist) < 2:
            p.setPen(QColor(c["text_4"]))
            p.drawText(plot, Qt.AlignmentFlag.AlignCenter, "…")
            return
        lo, hi = min(hist), max(hist)
        # A dead-flat signal must not become a full-height line: pad the span.
        if hi - lo < 1e-9:
            lo, hi = lo - 1.0, hi + 1.0
        span = hi - lo
        n = len(hist)
        pts = [QPointF(plot.left() + plot.width() * i / (n - 1),
                       plot.bottom() - plot.height() * (v - lo) / span)
               for i, v in enumerate(hist)]
        col = self._fill_color(c, alarm)
        area = QPainterPath(QPointF(pts[0].x(), plot.bottom()))
        for pt in pts:
            area.lineTo(pt)
        area.lineTo(pts[-1].x(), plot.bottom())
        area.closeSubpath()
        g = QLinearGradient(0, plot.top(), 0, plot.bottom())
        c0, c1 = QColor(col), QColor(col)
        c0.setAlpha(90)
        c1.setAlpha(0)
        g.setColorAt(0.0, c0)
        g.setColorAt(1.0, c1)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(g))
        p.drawPath(area)
        p.setPen(QPen(col, 1.6))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPolyline(QPolygonF(pts))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(col)
        p.drawEllipse(pts[-1], 2.6, 2.6)
        # axis labels
        p.setPen(QColor(c["text_4"]))
        for val, y in ((hi, plot.top()), (lo, plot.bottom() - 10)):
            p.drawText(QRectF(2, y, left - 6, 11),
                       Qt.AlignmentFlag.AlignRight, _tidy(val))
        p.setPen(self._value_color(c, alarm))
        p.setFont(self._mono(10))
        p.drawText(QRectF(0, self.ph - 20, self.pw - 12, 16),
                   Qt.AlignmentFlag.AlignRight,
                   f"{self._value_text()} {self.cfg.get('unit', '')}".strip())

    # ── control kinds ────────────────────────────────────────────────
    def _paint_button(self, p, c, _alarm):
        """A real push button: label on the face, and what it writes shown as
        a quiet caption underneath (the old '→ 1.0' inside the button read as
        a cryptic arrow)."""
        pressed = self.pulse > 0.01
        r = QRectF(16, 34, self.pw - 32, max(30.0, self.ph - 62))
        # soft shadow, lifted when idle and flattened while it fires
        if not pressed:
            sh = QColor(0, 0, 0, 60)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(sh)
            p.drawRoundedRect(r.translated(0, 2), 9, 9)
        face = QColor(c["accent"])
        if pressed:
            face = QColor(c["text_1"])
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(face)
        p.drawRoundedRect(r, 9, 9)
        p.setPen(QColor(c["accent_fg"]))
        f = QFont(self.font())
        f.setPointSize(max(9, min(12, int(r.height() / 2.6))))
        f.setBold(True)
        p.setFont(f)
        label = self.cfg.get("title") or self.cfg.get("name") or self.ctx.t("dashKindButton")
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, label)
        # caption: "0x0010 ← 1"
        p.setPen(QColor(c["text_4"]))
        f2 = QFont(self.font())
        f2.setPointSize(8)
        p.setFont(f2)
        val = self.cfg.get("value_on", 1)
        val = int(val) if isinstance(val, float) and val.is_integer() else val
        p.drawText(QRectF(0, self.ph - 24, self.pw, 16),
                   Qt.AlignmentFlag.AlignCenter,
                   f"{datatypes.id_label(self.cfg.get('reg_id', ''))} ← {val}")

    def _paint_toggle(self, p, c, _alarm):
        on = self.state_on
        tw, th = 62, 30
        x = (self.pw - tw) / 2
        y = self.ph * 0.45
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(c["ok"] if on else c["bg_4"]))
        p.drawRoundedRect(QRectF(x, y, tw, th), th / 2, th / 2)
        p.setBrush(QColor(c["text_1"]))
        knob = th - 8
        p.drawEllipse(QRectF(x + (tw - knob - 4 if on else 4), y + 4, knob, knob))
        p.setPen(QColor(c["text_3"]))
        f = QFont(self.font())
        f.setPointSize(9)
        p.setFont(f)
        p.drawText(QRectF(0, y + th + 4, self.pw, 18),
                   Qt.AlignmentFlag.AlignCenter,
                   str(self.cfg.get("value_on" if on else "value_off", "")))

    def _paint_timer(self, p, c, _alarm):
        running = self.state_on
        cy = self.ph * 0.55
        col = QColor(c["ok"] if running else c["text_3"])
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(col)
        cx = self.pw / 2
        if running:                                   # stop square
            p.drawRoundedRect(QRectF(cx - 9, cy - 9, 18, 18), 3, 3)
        else:                                          # play triangle
            tri = QPolygonF([QPointF(cx - 7, cy - 10), QPointF(cx + 11, cy),
                             QPointF(cx - 7, cy + 10)])
            p.drawPolygon(tri)
        p.setPen(QColor(c["text_3"]))
        f = QFont(self.font())
        f.setPointSize(9)
        p.setFont(f)
        p.drawText(QRectF(0, self.ph - 26, self.pw, 18),
                   Qt.AlignmentFlag.AlignCenter,
                   f"{int(self.cfg.get('interval', 1000))} ms")

    # ── slider ───────────────────────────────────────────────────────
    def slider_track(self) -> QRectF:
        """The draggable track — one definition shared by paint and hit-test,
        so the knob always lands exactly where the cursor is."""
        return QRectF(24.0, self.ph * 0.58 - 4,
                      max(20.0, self.pw - 48), 8.0)

    def slider_value(self):
        """Pending value while dragging, otherwise the live register value."""
        if self._slider_frac is not None:
            vmin = _f(self.cfg.get("vmin", 0))
            vmax = _f(self.cfg.get("vmax", 100))
            step = _f(self.cfg.get("step", 1), 1.0) or 1.0
            raw = vmin + (vmax - vmin) * self._slider_frac
            return round(round(raw / step) * step, 6)
        return self.value

    def slider_set_from_x(self, x: float):
        tr = self.slider_track()
        self._slider_frac = max(0.0, min(1.0, (x - tr.left()) / max(1.0, tr.width())))
        self.update()

    def _paint_slider(self, p, c, alarm):
        tr = self.slider_track()
        val = self.slider_value()
        frac = self._range_frac(val)
        frac = 0.0 if frac is None else frac
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(c["bg_3"]))
        p.drawRoundedRect(tr, 4, 4)
        fill = QColor(c["accent"]) if not self.stale else QColor(c["bg_4"])
        p.setBrush(fill)
        p.drawRoundedRect(QRectF(tr.left(), tr.top(), tr.width() * frac, tr.height()),
                          4, 4)
        kx = tr.left() + tr.width() * frac
        ky = tr.center().y()
        if self._slider_frac is not None:            # grabbed: soft halo
            halo = QColor(c["accent"])
            halo.setAlpha(60)
            p.setBrush(halo)
            p.drawEllipse(QPointF(kx, ky), 15, 15)
        p.setPen(QPen(QColor(c["line_strong"]), 1))
        p.setBrush(QColor(c["text_1"]))
        p.drawEllipse(QPointF(kx, ky), 9, 9)
        p.setPen(self._value_color(c, alarm))
        p.setFont(self._mono(self._fit_pt(15)))
        p.drawText(QRectF(0, 26, self.pw, 24), Qt.AlignmentFlag.AlignCenter,
                   f"{_tidy(val) if val is not None else '—'} "
                   f"{self.cfg.get('unit', '')}".strip())
        p.setPen(QColor(c["text_4"]))
        f2 = QFont(self.font())
        f2.setPointSize(7)
        p.setFont(f2)
        p.drawText(QRectF(tr.left() - 6, tr.bottom() + 5, 70, 13),
                   Qt.AlignmentFlag.AlignLeft, _tidy(self.cfg.get("vmin", 0)))
        p.drawText(QRectF(tr.right() - 64, tr.bottom() + 5, 70, 13),
                   Qt.AlignmentFlag.AlignRight, _tidy(self.cfg.get("vmax", 100)))

    # ── select ───────────────────────────────────────────────────────
    def select_options(self) -> list:
        """``[(value, label)]`` — copied from the register enum at edit time so
        the widget still shows labels when the profile is not loaded."""
        out = []
        for item in (self.cfg.get("options") or []):
            try:
                out.append((float(item[0]), str(item[1])))
            except (TypeError, ValueError, IndexError):
                continue
        return out

    def select_label(self) -> str:
        opts = self.select_options()
        pick = self._select_value if self._select_value is not None else self.value
        if pick is not None:
            for v, label in opts:
                if abs(v - float(pick)) < 1e-9:
                    return label
        return _tidy(pick) if pick is not None else "—"

    def select_box(self) -> QRectF:
        return QRectF(16.0, self.ph * 0.45 - 17,
                      max(40.0, self.pw - 32), 34.0)

    def _paint_select(self, p, c, _alarm):
        box = self.select_box()
        p.setPen(QPen(QColor(c["line"]), 1))
        p.setBrush(QColor(c["bg_0"]))
        p.drawRoundedRect(box, 7, 7)
        p.setPen(QColor(c["text_4"] if self.stale else c["text_1"]))
        f = QFont(self.font())
        f.setPointSize(11)
        p.setFont(f)
        p.drawText(box.adjusted(11, 0, -28, 0),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                   self.select_label())
        # chevron (an image-free triangle is fine here — we own the painter)
        p.setPen(QPen(QColor(c["text_3"]), 1.5))
        ax, ay = box.right() - 17, box.center().y() - 2
        p.drawLine(QPointF(ax - 4, ay), QPointF(ax, ay + 4))
        p.drawLine(QPointF(ax, ay + 4), QPointF(ax + 4, ay))
        if not self.select_options():
            p.setPen(QColor(c["warn"]))
            f2 = QFont(self.font())
            f2.setPointSize(8)
            p.setFont(f2)
            p.drawText(QRectF(14, self.ph - 24, self.pw - 28, 18),
                       int(Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWordWrap),
                       self.ctx.t("dashNoEnum"))

    # ── gate ─────────────────────────────────────────────────────────
    def _paint_gate(self, p, c, _alarm):
        open_ = dm.gate_pass(self.cfg, self.value)
        col = QColor(c["ok"] if open_ else c["text_4"])
        sign = dm.CONDITION_SIGNS.get(str(self.cfg.get("cond", "gt")), ">")
        p.setPen(QColor(c["text_1"] if not self.stale else c["text_4"]))
        p.setFont(self._mono(self._fit_pt(15)))
        p.drawText(QRectF(0, self.ph * 0.28, self.pw, 26),
                   Qt.AlignmentFlag.AlignCenter,
                   f"{self._value_text()} {sign} {_tidy(self.cfg.get('cmp', 0))}")
        # state pill: the wire either continues past this block, or stops
        label = self.ctx.t("dashGateOpen" if open_ else "dashGateClosed")
        f = QFont(self.font())
        f.setPointSize(8)
        f.setBold(True)
        p.setFont(f)
        tw = p.fontMetrics().horizontalAdvance(label) + 22
        pill = QRectF((self.pw - tw) / 2, self.ph - 32, tw, 20)
        tint = QColor(col)
        tint.setAlpha(46)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(tint)
        p.drawRoundedRect(pill, 10, 10)
        p.setPen(col)
        p.drawText(pill, Qt.AlignmentFlag.AlignCenter, label)

    def _paint_input(self, p, c, _alarm):
        # The QLineEdit child draws the field; paint the send affordance.
        p.setPen(QColor(c["text_4"]))
        f = QFont(self.font())
        f.setPointSize(8)
        p.setFont(f)
        p.drawText(QRectF(14, self.ph - 24, self.pw - 28, 16),
                   Qt.AlignmentFlag.AlignLeft, self.ctx.t("dashInputHint"))

    def _paint_label(self, p, c, _alarm):
        p.setPen(QColor(c["text_1"]))
        f = QFont(self.font())
        f.setPointSize(max(10, min(18, int(self.ph / 3.2))))
        f.setBold(True)
        p.setFont(f)
        p.drawText(self.prect().adjusted(12, 8, -12, -8),
                   int(Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap),
                   self.cfg.get("title") or self.ctx.t("dashKindLabel"))


# ═══════════════════════════════════════════════════════════════════════
#  CANVAS (paints wires + guides UNDER the cards)
# ═══════════════════════════════════════════════════════════════════════
class _Canvas(QWidget):
    """Scrollable, zoomable surface. Cards are real child widgets placed at
    ``logical * zoom``; the canvas paints the grid, wires and guides."""

    def __init__(self, view):
        super().__init__()
        self._view = view
        self._pan_from = None
        self._pan_btn = None
        self._pan_moved = 0
        self.setObjectName("dashCanvas")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

    def paintEvent(self, e):
        # Pass the exposed rect: repainting only what Qt asked for keeps a big
        # scrolled canvas cheap (the grid is the expensive part).
        self._view.paint_canvas(self, e.rect())

    def wheelEvent(self, e):
        """The wheel zooms around the cursor (canvas-editor convention);
        panning is done by dragging with the right or middle button."""
        self._view.zoom_by(1.1 if e.angleDelta().y() > 0 else 1 / 1.1,
                           anchor=e.position().toPoint())
        e.accept()

    # ── panning (shared: cards delegate here so a drag that starts ON a
    #    widget pans too — otherwise the gesture died wherever a card sat) ──
    def pan_press(self, global_pos: QPoint, button) -> bool:
        if button not in (Qt.MouseButton.MiddleButton, Qt.MouseButton.RightButton):
            return False
        self._pan_from = QPoint(global_pos)
        self._pan_moved = 0
        self._pan_btn = button
        self.setCursor(Qt.CursorShape.ClosedHandCursor)
        return True

    def pan_move(self, global_pos: QPoint) -> bool:
        if self._pan_from is None:
            return False
        delta = self._pan_from - global_pos
        self._pan_moved += abs(delta.x()) + abs(delta.y())
        self._view.pan_by(delta)
        self._pan_from = QPoint(global_pos)
        return True

    def pan_release(self) -> str:
        """'' if no pan was active, 'pan' if it moved, 'click' if it did not
        (the caller then shows its context menu)."""
        if self._pan_from is None:
            return ""
        was_right = self._pan_btn == Qt.MouseButton.RightButton
        moved = self._pan_moved
        self._pan_from = None
        self._pan_btn = None
        self.unsetCursor()
        return "click" if (was_right and moved < 6) else "pan"

    def mousePressEvent(self, e):
        # Right / middle button grabs the canvas and pans it. A right button
        # released WITHOUT movement still opens the context menu (below).
        if self.pan_press(e.globalPosition().toPoint(), e.button()):
            e.accept()
            return
        self._view.canvas_press(e)

    def mouseMoveEvent(self, e):
        if self.pan_move(e.globalPosition().toPoint()):
            e.accept()
            return
        # Left button held on empty canvas = rubber-band select.
        if (e.buttons() & Qt.MouseButton.LeftButton) and \
                self._view.canvas_drag(e.position().toPoint()):
            e.accept()
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        outcome = self.pan_release()
        if outcome:
            if outcome == "click":
                self._view.canvas_menu(e.position().toPoint())
            e.accept()
            return
        if self._view.canvas_drag_end():
            e.accept()
            return
        super().mouseReleaseEvent(e)


# ═══════════════════════════════════════════════════════════════════════
#  THE VIEW
# ═══════════════════════════════════════════════════════════════════════
class DashboardView(QWidget):
    """Free-form canvas of DashCards + the wire graph + run/edit modes."""

    write_requested = pyqtSignal(int, str, str)      # addr, dtype, value
    watch_requested = pyqtSignal(int)                # addr → watch window

    def __init__(self, ctx, get_registers, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.get_registers = get_registers
        self.cards: dict[str, DashCard] = {}
        # A project can hold several dashboards; boards[index] is on screen.
        self.boards = self._load_boards(ctx.settings)
        self.index = max(0, min(int(ctx.settings.get("dash_index", 0) or 0),
                                len(self.boards) - 1))
        self.graph = dm.Graph(self.boards[self.index].get("links", []))
        self.edit = False
        self.zoom = 1.0
        # Selection is a LIST, not a single uid: building a real scheme means
        # moving eight widgets together, not eight widgets one at a time. The
        # order is click order, and the last entry is the "primary" — the one
        # a drag is anchored to and the one `sel_uid` reports, so every older
        # single-selection code path keeps working unchanged.
        self._sel: list[str] = []
        self.sel_wire = None
        self._marquee = None            # QRect in canvas px while band-selecting
        self._band_from = None          # where the band was ANCHORED (see below)
        self._move_origin: dict = {}    # uid -> (x, y) at the start of a drag
        self._timers: dict[str, QTimer] = {}
        self._reg_index = None         # reg_id -> [card]; rebuilt on demand
        # Where inside the card the drag started — kept under the cursor for
        # the whole drag (without it the card teleported to a fixed offset).
        self._grab: QPoint | None = None
        self._guides = ([], [])
        self._wire_src = None
        self._wire_pos = None
        self._wire_hover = None        # uid of the input port under the cursor
        self._wire_phase = 0           # marching-ants offset for the live wire
        self._hot_links: dict = {}     # (from, to) -> t of the last pulse
        self.setObjectName("dashView")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        lo = QVBoxLayout(self)
        lo.setContentsMargins(14, 10, 14, 10)
        lo.setSpacing(10)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        # Dashboard selector: a project can carry several screens.
        self.combo_board = QComboBox()
        self.combo_board.setObjectName("stInput")
        self.combo_board.setMinimumWidth(170)
        self.combo_board.currentIndexChanged.connect(self._on_board_picked)
        bar.addWidget(self.combo_board)
        self.btn_boards = QPushButton()
        self.btn_boards.setObjectName("iconBtn")
        self.btn_boards.setFixedSize(30, 30)
        self.btn_boards.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_boards.setIcon(icons.icon("dots", ctx.theme_tokens()["text_2"], 15))
        self.btn_boards.setToolTip(ctx.t("dashBoardsMenu"))
        self.btn_boards.clicked.connect(self._open_boards_menu)
        bar.addWidget(self.btn_boards)

        self.btn_add = QPushButton("  " + ctx.t("dashAddWidget"))
        self.btn_add.setObjectName("btnPrimary")
        self.btn_add.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_add.setIcon(icons.icon("plus", ctx.theme_tokens()["accent_fg"], 14))
        self.btn_add.clicked.connect(self._add_widget)
        bar.addWidget(self.btn_add)

        self.btn_mode = QPushButton()
        self.btn_mode.setObjectName("tbBtn")
        self.btn_mode.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_mode.clicked.connect(lambda: self.set_edit(not self.edit))
        bar.addWidget(self.btn_mode)

        # The mode as a small status pill; the how-to sentence that used to
        # sit here in full lives in its tooltip (and in the F1 guide).
        self.lbl_hint = QLabel("")
        self.lbl_hint.setObjectName("modeBadge")
        bar.addWidget(self.lbl_hint)
        bar.addStretch()
        self.lbl_zoom = QLabel("100%")
        self.lbl_zoom.setObjectName("mhBadge")
        self.lbl_zoom.setToolTip(ctx.t("dashZoomHint"))
        self.lbl_zoom.setVisible(False)
        bar.addWidget(self.lbl_zoom)
        lo.addLayout(bar)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        # A canvas is panned (right-drag) and zoomed (wheel), like every
        # design surface; permanent scrollbars along an empty board read as
        # a page that did not fit. The bars keep their ranges for pan_by().
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.canvas = _Canvas(self)
        self.canvas.setMinimumSize(400, 400)
        # Centre a canvas smaller than the viewport, so zooming grows from the
        # middle of the screen instead of pinning everything to the top-left.
        self.scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.scroll.setWidget(self.canvas)
        lo.addWidget(self.scroll, 1)

        # An empty board says what a board is for and offers the first step
        # (it used to be one grey sentence under a black canvas).
        self.lbl_empty = EmptyState("gauge", ctx.t("dashEmptyTitle"), ctx.t("dashEmpty"))
        # Outline, not filled: the toolbar right above already carries the
        # same action as the page's one accent button.
        self.lbl_empty.add_action(ctx.t("dashAddWidget"), self._add_widget)
        self.lbl_empty.apply_theme(ctx.theme_tokens())
        self._empty_ov = EmptyOverlay(self.scroll, self.lbl_empty,
                                      is_empty=lambda: not self.cards)

        self._stale_timer = QTimer(self)
        self._stale_timer.setInterval(2000)
        self._stale_timer.timeout.connect(self._check_stale)
        self._stale_timer.start()

        # Marching-ants animation — runs ONLY while a wire is being dragged.
        self._ants = QTimer(self)
        self._ants.setInterval(60)
        self._ants.timeout.connect(self._tick_ants)

        self._load_widgets(self.boards[self.index].get("widgets", []))
        self._grow_canvas()
        self._refresh_board_combo()
        self.set_edit(False)
        self._refresh_empty()

    # ── mode ─────────────────────────────────────────────────────────
    def set_edit(self, edit: bool):
        self.edit = bool(edit)
        t = self.ctx.t
        c = self.ctx.theme_tokens()
        self.btn_mode.setText("  " + (t("dashModeRun") if self.edit
                                      else t("dashModeEdit")))
        self.btn_mode.setIcon(icons.icon(
            "play" if self.edit else "edit", c["text_2"], 14))
        self.lbl_hint.setText(t("dashBadgeEdit") if self.edit else t("dashBadgeRun"))
        self.lbl_hint.setToolTip(t("dashHintEdit") if self.edit else t("dashHintRun"))
        self.lbl_hint.setProperty("state", "edit" if self.edit else "run")
        self.lbl_hint.style().unpolish(self.lbl_hint)
        self.lbl_hint.style().polish(self.lbl_hint)
        # Always visible: the empty dashboard says «press Add widget», and in
        # run mode that button used to be hidden. Pressing it switches to
        # edit mode first (see _add_widget).
        self.btn_add.setVisible(True)
        self._refresh_board_combo()      # the ⋯ menu is edit-mode only
        for card in self.cards.values():
            card.set_edit(self.edit)
        if self.edit:
            self._stop_all_timers()          # never write while arranging
        else:
            self.sel_uid = self.sel_wire = None
            for card in self.cards.values():
                card.set_selected(False)
            self._start_autostart_timers()
        self.canvas.update()

    # ── card lifecycle ───────────────────────────────────────────────
    def _make_card(self, cfg: dict):
        # A uid already on the board (a hand-edited or generated file) gets a
        # fresh one: cards are keyed by uid, and a duplicate used to replace
        # the earlier card in that dict — it stayed on screen but never got
        # another value, could not be selected and was not saved.
        if not cfg.get("uid") or cfg["uid"] in self.cards:
            cfg["uid"] = uuid.uuid4().hex[:8]
        k = cfg.get("kind", "value")
        dw, dh = dm.default_size(k)
        # NB: setdefault is not enough — the dialog sends explicit None for a
        # brand-new widget, and int(None) blew up inside the click handler
        # (the widget silently never appeared).
        if not cfg.get("w"):
            cfg["w"] = dw
        if not cfg.get("h"):
            cfg["h"] = dh
        if cfg.get("x") is None:
            cfg["x"] = dm.CANVAS_MARGIN
        if cfg.get("y") is None:
            cfg["y"] = dm.CANVAS_MARGIN
        z = self.zoom
        card = DashCard(cfg, self.ctx, self.canvas)
        card.set_zoom(z)               # a card added while zoomed must match
        card.setGeometry(int(cfg["x"] * z), int(cfg["y"] * z),
                         int(cfg["w"] * z), int(cfg["h"] * z))
        card.edit_requested.connect(self._edit_widget)
        card.duplicate_requested.connect(self._duplicate_widget)
        card.remove_requested.connect(self._on_card_remove_requested)
        card.clip_requested.connect(self._on_clip_requested)
        card.selected.connect(self._on_card_selected)
        card.move_started.connect(self._on_move_started)
        card.move_moved.connect(self._on_move_moved)
        card.move_finished.connect(self._on_move_finished)
        card.resize_moved.connect(self._on_resize_moved)
        card.resize_finished.connect(self._on_move_finished)
        card.wire_started.connect(self._on_wire_started)
        card.wire_moved.connect(self._on_wire_moved)
        card.wire_finished.connect(self._on_wire_finished)
        card.fired.connect(self.fire)
        card.watch_requested.connect(self._relay_watch)
        card.set_edit(self.edit)
        card.show()
        self.cards[cfg["uid"]] = card
        self._invalidate_index()
        return card

    def _load_widgets(self, cfgs):
        """Build cards from saved configs.

        Pre-v3 entries have no coordinates: they're laid out with the old
        auto-flow grid FIRST (an existing dashboard must look unchanged), then
        created — `_make_card` fills geometry defaults, so a missing position
        has to be resolved before it gets one."""
        cfgs = [dict(c) for c in cfgs
                if isinstance(c, dict) and c.get("kind")]
        legacy = [c for c in cfgs if c.get("x") is None or c.get("y") is None]
        if legacy:
            width = self.canvas.width() or 900
            for cfg, (x, y) in zip(legacy, dm.flow_positions(len(legacy), width)):
                cfg["x"], cfg["y"] = x, y
        for cfg in cfgs:
            self._make_card(cfg)
        if legacy:
            self._persist()

    def _add_widget(self):
        if not self.edit:
            self.set_edit(True)          # adding is arranging: no live writes
        dlg = WidgetDialog(self.ctx, self.get_registers() or [], None, self)
        dlg.exec()
        if not dlg.result_cfg:
            return
        cfg = dlg.result_cfg
        cfg["x"], cfg["y"] = self._free_slot(cfg["kind"])
        self._make_card(cfg)
        self._grow_canvas()
        self._persist()
        self._refresh_empty()
        self.canvas.update()

    def _free_slot(self, kind_key) -> tuple:
        """First non-overlapping spot on a coarse grid (new cards never land
        on top of an existing one)."""
        w, h = dm.default_size(kind_key)
        taken = [(c.cfg.get("x", 0), c.cfg.get("y", 0),
                  c.cfg.get("w", 100), c.cfg.get("h", 80))
                 for c in self.cards.values()]
        cw = max(int(self.canvas.width() / self.zoom), 600)
        step_x, step_y = w + 12, h + 12
        for row in range(12):
            for col in range(max(1, cw // step_x)):
                x, y = dm.CANVAS_MARGIN + col * step_x, dm.CANVAS_MARGIN + row * step_y
                if not any(x < ox + ow and x + w > ox and y < oy + oh and y + h > oy
                           for ox, oy, ow, oh in taken):
                    return x, y
        return dm.CANVAS_MARGIN, dm.CANVAS_MARGIN

    def _edit_widget(self, uid: str):
        card = self.cards.get(uid)
        if card is None:
            return
        dlg = WidgetDialog(self.ctx, self.get_registers() or [], card.cfg, self)
        dlg.exec()
        if not dlg.result_cfg:
            return
        new_cfg = dlg.result_cfg
        if new_cfg.get("kind") != card.cfg.get("kind"):
            # kind changed -> rebuild the card (different painter/children)
            x, y, w, h = card.x(), card.y(), card.width(), card.height()
            self._destroy_card(uid)
            new_cfg.update({"x": x, "y": y, "w": w, "h": h})
            self._make_card(new_cfg)
        else:
            card.cfg.update(new_cfg)
            self._invalidate_index()   # reg_id may have changed
            card.update()
        self._persist()
        self._sync_timer(new_cfg["uid"])
        self.canvas.update()

    def _duplicate_widget(self, uid: str):
        """Duplicate one widget, or the whole selection if *uid* is in it."""
        group = [u for u in self._moving_group(uid) if u in self.cards]
        if not group:
            return
        self._paste_group(self._snapshot(group), dx=20, dy=20)

    # ── copy / paste ─────────────────────────────────────────────────
    # The clipboard lives on the VIEW, so a copy survives switching to another
    # dashboard — copying a control block from one screen onto another is the
    # main reason to have copy at all.
    def _snapshot(self, uids) -> dict:
        """Deep-ish copy of *uids* and of the wires BETWEEN them.

        Wires with only one end in the set are deliberately dropped: pasting
        them would silently re-attach a copy to the original, which is never
        what "copy these five widgets" means."""
        inside = set(uids)
        return {
            "widgets": [dict(self.cards[u].cfg) for u in uids if u in self.cards],
            "links": [dict(l) for l in self.graph.links
                      if l["from"] in inside and l["to"] in inside],
        }

    def copy_selection(self) -> int:
        if not self._sel:
            return 0
        self._clipboard = self._snapshot(list(self._sel))
        self._paste_count = 0
        return len(self._clipboard["widgets"])

    def cut_selection(self) -> int:
        n = self.copy_selection()
        if n:
            self._remove_selection()
        return n

    def paste_clipboard(self) -> int:
        clip = getattr(self, "_clipboard", None)
        if not clip or not clip.get("widgets"):
            return 0
        # Each successive paste steps further down-right, so pasting three
        # times gives three visible copies instead of one stack of three.
        self._paste_count = getattr(self, "_paste_count", 0) + 1
        off = PASTE_STEP * self._paste_count
        return self._paste_group(clip, dx=off, dy=off)

    def _paste_group(self, clip: dict, dx: int, dy: int) -> int:
        """Materialise *clip* at an offset, giving everything fresh uids and
        rewiring the copied links to point at the copies."""
        remap: dict[str, str] = {}
        made: list[str] = []
        for cfg in clip.get("widgets", []):
            new = dict(cfg)
            old_uid = new.get("uid")
            new["uid"] = uuid.uuid4().hex[:8]
            if old_uid:
                remap[old_uid] = new["uid"]
            new["x"], new["y"] = dm.clamp_rect(
                new.get("x", 0) + dx, new.get("y", 0) + dy,
                new.get("w", 100), new.get("h", 80))
            self._make_card(new)
            made.append(new["uid"])
        for link in clip.get("links", []):
            src, dst = remap.get(link.get("from")), remap.get(link.get("to"))
            if src and dst:
                self.graph.add(src, dst)
        if made:
            self._select(made)
            for uid in made:
                self._sync_timer(uid)
            self._grow_canvas()
            self._persist()
            self._refresh_empty()
            self.canvas.update()
        return len(made)

    def _remove_selection(self):
        for uid in list(self._sel):
            self._destroy_card(uid)
            self.graph.remove_widget(uid)
        self._sel = []
        self._persist()
        self._refresh_empty()
        self.canvas.update()

    def _destroy_card(self, uid: str):
        card = self.cards.pop(uid, None)
        self._invalidate_index()
        self._kill_timer(uid)
        # Drop it from the selection HERE, so no code path can leave a uid in
        # the list with no card behind it.
        if uid in getattr(self, "_sel", ()):
            self._sel.remove(uid)
        if card is not None:
            card.stop_flash()          # no animation may outlive the widget
            card.setParent(None)
            card.deleteLater()

    def _remove_card(self, uid: str):
        self._destroy_card(uid)
        self.graph.remove_widget(uid)
        self._persist()
        self._refresh_empty()
        self.canvas.update()

    def _on_card_remove_requested(self, uid: str):
        """Delete from a card's own menu. If that card is part of a
        multi-selection the whole selection goes — the menu was opened on the
        group, not on one member of it."""
        if uid in self._sel and len(self._sel) > 1:
            return self._remove_selection()
        self._remove_card(uid)

    def _on_clip_requested(self, uid: str, action: str):
        if uid not in self._sel:
            self._select([uid])
        n = self.cut_selection() if action == "cut" else self.copy_selection()
        self._toast_copied(n)

    def _refresh_empty(self):
        if hasattr(self, "_empty_ov"):
            self._empty_ov.refresh()

    # ── dashboard set (a project can hold several screens) ───────────
    def _load_boards(self, settings) -> list:
        """Dashboards from settings, migrating the pre-1.6 single-dashboard
        keys (dash_widgets/dash_links) on first run so nothing is lost."""
        raw = settings.get("dashboards") or []
        boards = [formats.normalize_dashboard(b) for b in raw
                  if isinstance(b, dict)]
        if not boards:
            legacy = settings.get("dash_widgets") or []
            boards = [formats.normalize_dashboard(
                {"name": "", "widgets": legacy,
                 "links": settings.get("dash_links") or []})]
        for i, b in enumerate(boards):
            b["name"] = b.get("name") or f"{self.ctx.t('dashBoard')} {i + 1}"
        return boards

    def _capture_board(self) -> dict:
        """Snapshot of what's on screen, in the board dict shape."""
        return {"name": self.boards[self.index].get("name", ""),
                "widgets": [dict(c.cfg) for c in self.cards.values()],
                "links": self.graph.as_list()}

    def _persist(self):
        # cfg already holds LOGICAL geometry (card.x() would be zoom-scaled).
        self.boards[self.index] = self._capture_board()
        self.ctx.settings["dashboards"] = [dict(b) for b in self.boards]
        self.ctx.settings["dash_index"] = self.index
        # Keep the legacy keys in sync with the ACTIVE board so an older build
        # (or anything still reading them) still sees a valid dashboard.
        self.ctx.settings["dash_widgets"] = self.boards[self.index]["widgets"]
        self.ctx.settings["dash_links"] = self.boards[self.index]["links"]

    def _refresh_board_combo(self):
        self.combo_board.blockSignals(True)
        self.combo_board.clear()
        self.combo_board.addItems([b.get("name", "") for b in self.boards])
        self.combo_board.setCurrentIndex(self.index)
        self.combo_board.blockSignals(False)
        self.combo_board.setVisible(len(self.boards) > 1 or self.edit)
        self.btn_boards.setVisible(self.edit)

    def _on_board_picked(self, index: int):
        if 0 <= index < len(self.boards) and index != self.index:
            self.switch_board(index)

    def switch_board(self, index: int):
        """Save the current screen, then load another one."""
        if not (0 <= index < len(self.boards)) or index == self.index:
            return
        self._persist()
        self._stop_all_timers()
        for uid in list(self.cards):
            self._destroy_card(uid)
        self.index = index
        self.graph = dm.Graph(self.boards[index].get("links", []))
        self.sel_uid = self.sel_wire = None
        self._load_widgets(self.boards[index].get("widgets", []))
        self._grow_canvas()
        self._refresh_board_combo()
        self._refresh_empty()
        if not self.edit:
            self._start_autostart_timers()
        self.ctx.settings["dash_index"] = index
        self.canvas.update()

    def add_board(self, name: str = "", widgets=None, links=None,
                  switch: bool = True):
        self._persist()
        self.boards.append(formats.normalize_dashboard(
            {"name": name or f"{self.ctx.t('dashBoard')} {len(self.boards) + 1}",
             "widgets": widgets or [], "links": links or []}))
        self._refresh_board_combo()
        if switch:
            self.switch_board(len(self.boards) - 1)
        else:
            self._persist()

    def _open_boards_menu(self):
        t = self.ctx.t
        m = QMenu(self)
        act_new = m.addAction(t("dashBoardNew"))
        act_ren = m.addAction(t("dashBoardRename"))
        act_dup = m.addAction(t("dashBoardDuplicate"))
        act_del = m.addAction(t("dashBoardDelete"))
        act_del.setEnabled(len(self.boards) > 1)
        m.addSeparator()
        act_exp = m.addAction(t("dashBoardExport"))
        act_imp = m.addAction(t("dashBoardImport"))
        chosen = m.exec(self.btn_boards.mapToGlobal(
            self.btn_boards.rect().bottomLeft()))
        if chosen is act_new:
            self.add_board()
        elif chosen is act_ren:
            self._rename_board()
        elif chosen is act_dup:
            b = self._capture_board()
            self.add_board(f"{b['name']} ({t('dashCopySuffix')})",
                           b["widgets"], b["links"])
        elif chosen is act_del:
            self._delete_board()
        elif chosen is act_exp:
            self.export_board()
        elif chosen is act_imp:
            self.import_board()

    def _rename_board(self):
        name, ok = themed_input(
            self, self.ctx.theme, self.ctx.t("dashBoardRename").rstrip("…."),
            self.ctx.t("dashBoardName"), self.boards[self.index].get("name", ""),
            ok_label=self.ctx.t("apply"), cancel_label=self.ctx.t("cancel"))
        if ok and name.strip():
            self.boards[self.index]["name"] = name.strip()
            self._persist()
            self._refresh_board_combo()

    def _delete_board(self):
        if len(self.boards) <= 1:
            return
        self.boards.pop(self.index)
        self.index = max(0, self.index - 1)
        for uid in list(self.cards):
            self._destroy_card(uid)
        self.graph = dm.Graph(self.boards[self.index].get("links", []))
        self._load_widgets(self.boards[self.index].get("widgets", []))
        self._refresh_board_combo()
        self._refresh_empty()
        self._persist()
        self.canvas.update()

    # ── single-dashboard file (.mbdash) ──────────────────────────────
    def export_board(self):
        board = self._capture_board()
        path, _ = QFileDialog.getSaveFileName(
            self, self.ctx.t("dashBoardExport"),
            f"{board['name'] or 'dashboard'}.mbdash",
            self.ctx.t("filterDashboard") + " (*.mbdash)")
        if not path:
            return
        try:
            formats.dump_dashboard(path, board["name"], board["widgets"],
                                   board["links"])
        except Exception as e:
            themed_info(self, self.ctx.theme, "error", self.ctx.t("error"),
                        f"{type(e).__name__}: {e}")

    def import_board(self):
        path, _ = QFileDialog.getOpenFileName(
            self, self.ctx.t("dashBoardImport"), "",
            self.ctx.t("filterDashboard") + " (*.mbdash);;JSON (*.json)")
        if not path:
            return
        try:
            doc = formats.load_dashboard(path)
        except Exception as e:
            themed_info(self, self.ctx.theme, "error", self.ctx.t("error"),
                        f"{type(e).__name__}: {e}")
            return
        self.add_board(doc.get("name", ""), doc.get("widgets"),
                       doc.get("links"))

    # ── project integration (gui_main saves/loads .mbproj) ───────────
    def all_boards(self) -> list:
        """Every dashboard, with the on-screen one up to date."""
        self._persist()
        return [dict(b) for b in self.boards]

    def load_boards(self, boards: list):
        """Replace the whole set (opening a project)."""
        self._stop_all_timers()
        for uid in list(self.cards):
            self._destroy_card(uid)
        self.boards = [formats.normalize_dashboard(b) for b in (boards or [])] \
            or [formats.normalize_dashboard({})]
        for i, b in enumerate(self.boards):
            b["name"] = b.get("name") or f"{self.ctx.t('dashBoard')} {i + 1}"
        self.index = 0
        self.graph = dm.Graph(self.boards[0].get("links", []))
        self._load_widgets(self.boards[0].get("widgets", []))
        self._grow_canvas()
        self._refresh_board_combo()
        self._refresh_empty()
        self._persist()
        self.canvas.update()

    # ── selection ────────────────────────────────────────────────────
    # One writer (`_select`) keeps the list, the per-card highlight and the
    # repaint in step. `sel_uid` stays readable/writable so every caller that
    # only ever cared about one widget is unaffected.
    @property
    def sel_uid(self):
        """The primary selection — last clicked — or None."""
        return self._sel[-1] if self._sel else None

    @sel_uid.setter
    def sel_uid(self, uid):
        self._select([uid] if uid else [])

    @property
    def sel_uids(self) -> tuple:
        return tuple(self._sel)

    def _select(self, uids, *, add: bool = False):
        """Make *uids* the selection (or add to it). Unknown uids are dropped
        so a stale reference can never leave a highlight nobody can clear."""
        if not hasattr(self, "cards"):
            return                       # called from __init__, nothing to paint
        keep = list(self._sel) if add else []
        for uid in uids:
            if uid in self.cards and uid not in keep:
                keep.append(uid)
        self._sel = [u for u in keep if u in self.cards]
        chosen = set(self._sel)
        for u, card in self.cards.items():
            card.set_selected(u in chosen)

    def _toggle_selected(self, uid: str):
        if uid in self._sel:
            self._sel.remove(uid)
            card = self.cards.get(uid)
            if card is not None:
                card.set_selected(False)
        else:
            self._select([uid], add=True)

    def select_all(self):
        self._select(list(self.cards))
        self.sel_wire = None
        self.canvas.update()

    def clear_selection(self):
        self._select([])
        self.sel_wire = None
        self.canvas.update()

    # ── canvas interaction ───────────────────────────────────────────
    def _on_card_selected(self, uid: str, additive: bool = False):
        if not self.edit:
            return
        self.sel_wire = None
        if additive:
            self._toggle_selected(uid)
        elif uid not in self._sel:
            # Clicking a widget that is ALREADY part of a multi-selection must
            # keep that selection — otherwise grabbing the group to drag it
            # would silently collapse to the one card under the cursor.
            self._select([uid])
        else:
            self._sel.append(self._sel.pop(self._sel.index(uid)))  # make primary
        card = self.cards.get(uid)
        if card is not None:
            card.raise_()
        self.canvas.update()

    def canvas_press(self, e):
        """Left-press on empty canvas: pick a wire, or start a rubber band."""
        if not self.edit:
            return
        pos = e.position().toPoint()
        wire = self._wire_at(pos)
        additive = bool(e.modifiers() & (Qt.KeyboardModifier.ControlModifier
                                         | Qt.KeyboardModifier.ShiftModifier))
        self.sel_wire = wire
        if wire is None:
            if not additive:
                self._select([])
            # Keep the ANCHOR, not the rect's corner. A normalized rect's
            # topLeft() is its geometric top-left, which stops being the point
            # the user pressed as soon as the drag goes up or to the left —
            # feeding that back in each frame collapsed the band and made
            # right-to-left selection impossible.
            self._band_from = QPoint(pos)
            self._marquee = QRect(pos, pos)
            self._band_base = list(self._sel) if additive else []
        self.setFocus()
        self.canvas.update()

    def canvas_drag(self, pos: QPoint):
        """Grow the rubber band and light up everything it touches, live.

        The band is always measured from the anchor, so it works in all four
        directions — up-left is as valid a drag as down-right."""
        if self._band_from is None:
            return False
        self._marquee = QRect(self._band_from, pos).normalized()
        self._select(self._band_base + self._uids_in(self._marquee))
        self.canvas.update()
        return True

    def canvas_drag_end(self) -> bool:
        if self._band_from is None:
            return False
        self._band_from = None
        self._marquee = None
        self.canvas.update()
        return True

    def _uids_in(self, rect: QRect) -> list:
        """Cards touched by *rect* (canvas pixels). Intersect, not contain:
        requiring full containment means you cannot band-select a row of
        widgets without also enclosing everything below them."""
        return [u for u, card in self.cards.items()
                if rect.intersects(card.geometry())]

    # ── zoom / pan ───────────────────────────────────────────────────
    def zoom_by(self, factor: float, anchor: QPoint | None = None):
        """Scale the canvas around *anchor* (canvas coords), keeping the point
        under the cursor put — the behaviour every drawing tool has."""
        new = max(dm.ZOOM_MIN, min(dm.ZOOM_MAX, self.zoom * factor))
        if abs(new - self.zoom) < 1e-3:
            return
        h_bar, v_bar = (self.scroll.horizontalScrollBar(),
                        self.scroll.verticalScrollBar())
        if anchor is not None:
            logical = (anchor.x() / self.zoom, anchor.y() / self.zoom)
        self.zoom = new
        self._apply_zoom()
        if anchor is not None:
            h_bar.setValue(int(logical[0] * self.zoom
                               - (anchor.x() - h_bar.value())))
            v_bar.setValue(int(logical[1] * self.zoom
                               - (anchor.y() - v_bar.value())))
        self._update_zoom_label()

    def zoom_reset(self):
        self.zoom = 1.0
        self._apply_zoom()
        self._update_zoom_label()

    def _apply_zoom(self):
        """Re-place every card at ``logical * zoom``; the painters read
        width()/height(), so the content scales with the box for free."""
        z = self.zoom
        for card in self.cards.values():
            cfg = card.cfg
            card.set_zoom(z)
            card.setGeometry(int(cfg.get("x", 0) * z), int(cfg.get("y", 0) * z),
                             max(24, int(cfg.get("w", 100) * z)),
                             max(20, int(cfg.get("h", 80) * z)))
        self._grow_canvas()
        self.canvas.update()

    def _update_zoom_label(self):
        self.lbl_zoom.setText(f"{int(round(self.zoom * 100))}%")
        self.lbl_zoom.setVisible(abs(self.zoom - 1.0) > 1e-3)

    def pan_by(self, delta: QPoint):
        self.scroll.horizontalScrollBar().setValue(
            self.scroll.horizontalScrollBar().value() + delta.x())
        self.scroll.verticalScrollBar().setValue(
            self.scroll.verticalScrollBar().value() + delta.y())

    def canvas_menu(self, pos):
        if not self.edit:
            return
        t = self.ctx.t
        m = QMenu(self)
        wire = self._wire_at(pos)
        if wire:
            act_del = m.addAction(t("dashDeleteWire"))
            if m.exec(self.canvas.mapToGlobal(pos)) is act_del:
                self.graph.remove(*wire)
                self.sel_wire = None
                self._persist()
                self.canvas.update()
            return
        act_add = m.addAction(t("dashAddWidget"))
        act_paste = m.addAction(t("dashPaste"))
        act_paste.setEnabled(bool(getattr(self, "_clipboard", None)
                                  and self._clipboard.get("widgets")))
        m.addSeparator()
        act_all = m.addAction(t("dashSelectAll"))
        act_all.setEnabled(bool(self.cards))
        chosen = m.exec(self.canvas.mapToGlobal(pos))
        if chosen is act_add:
            self._add_widget()
        elif chosen is act_paste:
            self._toast_pasted(self.paste_clipboard())
        elif chosen is act_all:
            self.select_all()

    def keyPressEvent(self, e):
        """Dashboard shortcuts. Zoom works in both modes; the editing ones are
        gated on edit mode so a stray Del can't wreck a running dashboard."""
        key, mods = e.key(), e.modifiers()
        ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)

        if ctrl and key in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
            return self.zoom_by(1.1)
        if ctrl and key == Qt.Key.Key_Minus:
            return self.zoom_by(1 / 1.1)
        if ctrl and key == Qt.Key.Key_0:
            return self.zoom_reset()
        if ctrl and key == Qt.Key.Key_E:
            return self.set_edit(not self.edit)

        if self.edit:
            if ctrl and key == Qt.Key.Key_A:
                return self.select_all()
            if ctrl and key == Qt.Key.Key_C:
                return self._toast_copied(self.copy_selection())
            if ctrl and key == Qt.Key.Key_X:
                return self._toast_copied(self.cut_selection())
            if ctrl and key == Qt.Key.Key_V:
                return self._toast_pasted(self.paste_clipboard())
            if key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
                if self.sel_wire:
                    self.graph.remove(*self.sel_wire)
                    self.sel_wire = None
                    self._persist()
                    self.canvas.update()
                    return
                if self._sel:
                    return self._remove_selection()
            if ctrl and key == Qt.Key.Key_D and self.sel_uid:
                return self._duplicate_widget(self.sel_uid)
            if key == Qt.Key.Key_Escape:
                return self.clear_selection()
            step = dm.NUDGE_BIG if (mods & Qt.KeyboardModifier.ShiftModifier) \
                else dm.NUDGE
            deltas = {Qt.Key.Key_Left: (-step, 0), Qt.Key.Key_Right: (step, 0),
                      Qt.Key.Key_Up: (0, -step), Qt.Key.Key_Down: (0, step)}
            if key in deltas and self._sel:
                return self._nudge_selection(*deltas[key])
        super().keyPressEvent(e)

    def _toast_copied(self, n: int):
        if n:
            self.lbl_hint.setText(self.ctx.t("dashCopied").format(n=n))

    def _toast_pasted(self, n: int):
        if n:
            self.lbl_hint.setText(self.ctx.t("dashPasted").format(n=n))

    def _nudge_selection(self, dx: int, dy: int):
        """Arrow-key move of everything selected (pixel-accurate placement).

        Clamping is applied per card but the DELTA is shared, so a group that
        runs into the canvas edge stops together instead of squashing."""
        for uid in self._sel:
            self._nudge(uid, dx, dy, commit=False)   # one save for the group
        self._grow_canvas()
        self._persist()
        self.canvas.update()

    def _nudge(self, uid: str, dx: int, dy: int, commit: bool = True):
        """Arrow-key move of one widget (pixel-accurate placement).

        *commit* exists only so a group nudge writes the file once instead of
        once per member; a lone nudge still persists, as it always has."""
        card = self.cards.get(uid)
        if card is None:
            return
        x, y = dm.clamp_rect(card.cfg.get("x", 0) + dx,
                             card.cfg.get("y", 0) + dy,
                             card.cfg.get("w", 100), card.cfg.get("h", 80))
        card.cfg["x"], card.cfg["y"] = x, y
        card.move(int(x * self.zoom), int(y * self.zoom))
        if commit:
            self._grow_canvas()
            self._persist()
            self.canvas.update()

    # ── move / resize with alignment guides ──────────────────────────
    def _on_move_started(self, uid: str, grab: QPoint):
        if self._grab is None:
            self._grab = QPoint(grab)
            # Remember where the whole group started. Applying each frame's
            # delta to the LIVE positions would accumulate rounding and the
            # group would slowly shear apart over a long drag.
            self._move_origin = {u: (c.cfg.get("x", 0), c.cfg.get("y", 0))
                                 for u, c in self.cards.items()
                                 if u in self._moving_group(uid)}

    def _moving_group(self, uid: str) -> list:
        """Which cards this drag moves: the whole selection if the grabbed
        card is part of it, otherwise just the grabbed card."""
        return list(self._sel) if uid in self._sel else [uid]

    def _others(self, uid):
        """Neighbour rects in LOGICAL coordinates (snapping is zoom-agnostic).

        Everything being dragged is excluded, not just the grabbed card — a
        group must not snap to its own members, which would glue it together
        and stop it moving."""
        moving = set(self._moving_group(uid))
        return [(c.cfg.get("x", 0), c.cfg.get("y", 0),
                 c.cfg.get("w", 100), c.cfg.get("h", 80))
                for u, c in self.cards.items() if u not in moving]

    def _on_move_moved(self, uid: str, g: QPoint):
        card = self.cards.get(uid)
        if card is None:
            return
        if self._grab is None:
            # No recorded grab point means no real drag is in flight. Doing
            # anything here would jump the card to a made-up offset — which is
            # exactly the "it teleports under the cursor" complaint.
            return
        z = self.zoom
        local = self.canvas.mapFromGlobal(g)
        w, h = card.cfg.get("w", 100), card.cfg.get("h", 80)
        # Keep the grabbed point under the cursor (grab offset is in screen
        # pixels, hence the divide by zoom after subtracting).
        # Keep the grabbed point under the cursor. The grab offset is LOGICAL
        # (card coordinates), so the cursor is converted to logical too and the
        # card tracks the mouse exactly at any zoom.
        grab = self._grab
        raw_x = local.x() / z - grab.x()
        raw_y = local.y() / z - grab.y()
        snap = dm.compute_snap(
            (raw_x, raw_y, w, h), self._others(uid),
            canvas=(self.canvas.width() / z, self.canvas.height() / z),
            enabled=not self._alt_held())
        x, y = dm.clamp_rect(snap.x, snap.y, w, h)
        card.cfg["x"], card.cfg["y"] = x, y
        card.move(int(x * z), int(y * z))
        # The rest of the selection follows by the SAME delta, measured from
        # the positions captured at drag start. The primary card is the only
        # one that snaps; the others hold their relative offsets, because a
        # group that rearranges itself while you drag it is not a group.
        origin = self._move_origin.get(uid)
        if origin is not None and len(self._move_origin) > 1:
            dx, dy = x - origin[0], y - origin[1]
            for other, (ox, oy) in self._move_origin.items():
                if other == uid:
                    continue
                mate = self.cards.get(other)
                if mate is None:
                    continue
                mx, my = dm.clamp_rect(ox + dx, oy + dy,
                                       mate.cfg.get("w", 100),
                                       mate.cfg.get("h", 80))
                mate.cfg["x"], mate.cfg["y"] = mx, my
                mate.move(int(mx * z), int(my * z))
        self._guides = ([int(v * z) for v in snap.v_guides],
                        [int(v * z) for v in snap.h_guides])
        self.canvas.update()

    def _alt_held(self) -> bool:
        from PyQt6.QtWidgets import QApplication
        return bool(QApplication.keyboardModifiers()
                    & Qt.KeyboardModifier.AltModifier)

    def _on_resize_moved(self, uid: str, g: QPoint):
        card = self.cards.get(uid)
        if card is None:
            return
        z = self.zoom
        local = self.canvas.mapFromGlobal(g)
        mw, mh = dm.min_size(card.cfg.get("kind", "value"))
        w = max(mw, local.x() / z - card.cfg.get("x", 0))
        h = max(mh, local.y() / z - card.cfg.get("y", 0))
        if not self._alt_held():
            w, h = dm.snap_to_grid(w), dm.snap_to_grid(h)
        card.cfg["w"], card.cfg["h"] = int(w), int(h)
        card.resize(int(w * z), int(h * z))
        self.canvas.update()

    def _on_move_finished(self, uid: str):
        self._grab = None
        self._move_origin = {}
        self._guides = ([], [])
        self._grow_canvas()
        self._persist()
        self.canvas.update()

    def _grow_canvas(self):
        """Size the work surface.

        It is a SHEET, not a snug bounding box: always at least the logical
        sheet size (times zoom) and always bigger than the viewport, because a
        canvas exactly the size of its viewport gives the scrollbars zero range
        — and panning, which moves those scrollbars, then did nothing at all."""
        z = self.zoom
        w = h = 0
        if self.cards:
            w = max(c.cfg.get("x", 0) + c.cfg.get("w", 100)
                    for c in self.cards.values())
            h = max(c.cfg.get("y", 0) + c.cfg.get("h", 80)
                    for c in self.cards.values())
        vp = self.scroll.viewport()
        self.canvas.setMinimumSize(
            max(int(SHEET_W * z), int(w * z) + 60, vp.width() + PAN_MARGIN),
            max(int(SHEET_H * z), int(h * z) + 60, vp.height() + PAN_MARGIN))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._grow_canvas()          # the pan margin follows the viewport

    # ── wires ────────────────────────────────────────────────────────
    def _on_wire_started(self, uid: str):
        """Wiring begins: crosshair cursor everywhere + every legal target
        lights up its input port, so it's obvious what can be connected."""
        self._wire_src = uid
        self._wire_pos = None
        self._wire_hover = None
        self.canvas.setCursor(Qt.CursorShape.CrossCursor)
        for u, card in self.cards.items():
            card.set_wire_candidate(
                u != uid and dm.kind(card.cfg.get("kind")).has_in)
        self._ants.start()

    def _target_at(self, local: QPoint):
        """uid of the wire-able widget under a canvas point (None if any)."""
        if not self._wire_src:
            return None
        for uid, card in self.cards.items():
            if uid == self._wire_src or not dm.kind(card.cfg.get("kind")).has_in:
                continue
            if card.geometry().adjusted(-12, -4, 4, 4).contains(local):
                return uid
        return None

    def _on_wire_moved(self, g: QPoint):
        self._wire_pos = self.canvas.mapFromGlobal(g)
        hover = self._target_at(self._wire_pos)
        if hover != self._wire_hover:
            for uid, card in self.cards.items():
                card.set_wire_hover(uid == hover)
            self._wire_hover = hover
        self.canvas.update()

    def _on_wire_finished(self, g: QPoint):
        # Resolve the target BEFORE clearing _wire_src — _target_at() needs it
        # (clearing first made every drop a no-op).
        src = self._wire_src
        target = self._target_at(self.canvas.mapFromGlobal(g)) if src else None
        self._wire_src = None
        self._wire_pos = None
        self._wire_hover = None
        self.canvas.unsetCursor()
        for card in self.cards.values():
            card.set_wire_candidate(False)
            card.set_wire_hover(False)
        if src and target and self.graph.add(src, target):
            self._persist()
            card = self.cards.get(target)
            if card is not None:
                card.flash()               # confirm the new connection
        self.canvas.update()

    def _tick_ants(self):
        """The ONE animation timer: marching ants on the wire being dragged,
        card activation flashes, and the pulse-travel highlight.

        Everything animated on this view is driven from here on purpose —
        per-card animation objects could outlive their card and crash the
        process. It stops itself as soon as there is nothing left to animate."""
        now = time.monotonic()
        self._wire_phase = (self._wire_phase + 2) % 20
        busy = self._wire_pos is not None
        for card in self.cards.values():
            if card.decay_pulse(now):
                busy = True
        if self._hot_links:
            self._hot_links = {k: t for k, t in self._hot_links.items()
                               if now - t < PULSE_TRAVEL}
            busy = True
        self.canvas.update()
        if not busy and self._wire_src is None:
            self._ants.stop()

    def _animate(self):
        """Make sure the shared timer is running (idempotent)."""
        if not self._ants.isActive():
            self._ants.start()

    def _mark_hot(self, uid: str, order: list):
        """Light up the wires the pulse actually travelled.

        Cards already flash, but with several branches it was impossible to see
        WHICH way the signal went — especially past a gate that blocked one
        path. Only links between activated nodes are marked, so a blocked
        branch stays dark."""
        reached = {uid, *order}
        now = time.monotonic()
        for link in self.graph.links:
            if link["from"] in reached and link["to"] in reached:
                self._hot_links[(link["from"], link["to"])] = now
        self._animate()
        self.canvas.update()

    def _wire_points(self, link) -> tuple:
        a = self.cards.get(link["from"])
        b = self.cards.get(link["to"])
        if a is None or b is None:
            return None
        z = self.zoom
        return (a.pos() + a.out_port_pos() * z,
                b.pos() + b.in_port_pos() * z)

    def _wire_at(self, pos: QPoint, tol: int = 8):
        """(src, dst) of the wire near *pos*, or None. Sampled along the curve —
        exact enough for picking without any geometry library. A bounding-box
        reject skips the sampling for the (many) wires nowhere near the click."""
        for link in self.graph.links:
            pts = self._wire_points(link)
            if not pts:
                continue
            p0, p1 = pts
            pad = tol * 2 + 40                      # curve bulge + tolerance
            if not (min(p0.x(), p1.x()) - pad <= pos.x() <= max(p0.x(), p1.x()) + pad
                    and min(p0.y(), p1.y()) - pad <= pos.y() <= max(p0.y(), p1.y()) + pad):
                continue
            for i in range(21):
                pt = self._bezier_point(p0, p1, i / 20)
                if (pt - pos).manhattanLength() <= tol * 2:
                    return (link["from"], link["to"])
        return None

    @staticmethod
    def _bezier_point(p0: QPoint, p1: QPoint, t: float) -> QPoint:
        dx = max(40, abs(p1.x() - p0.x()) * 0.5)
        c0 = QPointF(p0.x() + dx, p0.y())
        c1 = QPointF(p1.x() - dx, p1.y())
        u = 1 - t
        x = (u ** 3 * p0.x() + 3 * u ** 2 * t * c0.x()
             + 3 * u * t ** 2 * c1.x() + t ** 3 * p1.x())
        y = (u ** 3 * p0.y() + 3 * u ** 2 * t * c0.y()
             + 3 * u * t ** 2 * c1.y() + t ** 3 * p1.y())
        return QPoint(int(x), int(y))

    def _grid_tile(self, c: dict):
        """40×40 grid tile, rebuilt only when the theme changes."""
        key = (c["line"], c["bg_0"])
        if getattr(self, "_grid_key", None) != key:
            step = 40
            tile = QPixmap(step, step)
            tile.fill(QColor(c["bg_0"]))
            tp = QPainter(tile)
            tp.setPen(QPen(QColor(c["line"]), 1, Qt.PenStyle.DotLine))
            tp.drawLine(0, 0, step, 0)
            tp.drawLine(0, 0, 0, step)
            tp.end()
            self._grid_pix, self._grid_key = tile, key
        return self._grid_pix

    def paint_canvas(self, canvas: QWidget, clip=None):
        c = self.ctx.theme_tokens()
        area = clip if clip is not None else canvas.rect()
        p = QPainter(canvas)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(area, QColor(c["bg_0"]))

        if self.edit:
            # Grid as a CACHED TILE: one fillRect instead of dozens of
            # drawLine calls per repaint (this is the hot path while dragging).
            p.fillRect(area, QBrush(self._grid_tile(c)))

        # wires
        for link in self.graph.links:
            pts = self._wire_points(link)
            if not pts:
                continue
            key = (link["from"], link["to"])
            self._draw_wire(p, c, pts[0], pts[1], self.sel_wire == key,
                            hot=self._hot_links.get(key))
        # wire being dragged — animated dashes, snapping to a hovered port
        if self._wire_src and self._wire_pos:
            a = self.cards.get(self._wire_src)
            if a is not None:
                end = self._wire_pos
                target = self.cards.get(self._wire_hover) if self._wire_hover else None
                if target is not None:
                    end = target.pos() + target.in_port_pos() * self.zoom
                self._draw_wire(p, c, a.pos() + a.out_port_pos() * self.zoom, end,
                                bool(target), dashed=not target,
                                phase=self._wire_phase)

        # alignment guides
        if self.edit and any(self._guides):
            pen = QPen(QColor(c["accent"]), 1, Qt.PenStyle.DashLine)
            p.setPen(pen)
            for x in self._guides[0]:
                p.drawLine(x, area.top(), x, area.bottom())
            for y in self._guides[1]:
                p.drawLine(area.left(), y, area.right(), y)

        # rubber band — a translucent accent wash so what is enclosed stays
        # readable while the band is being dragged over it
        if self.edit and self._marquee is not None:
            band = QColor(c["accent"])
            band.setAlpha(38)
            p.fillRect(self._marquee, band)
            p.setPen(QPen(QColor(c["accent"]), 1, Qt.PenStyle.DashLine))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(self._marquee.adjusted(0, 0, -1, -1))
        p.end()

    def _draw_wire(self, p, c, p0, p1, selected: bool, dashed: bool = False,
                   phase: int = 0, hot=None):
        # Idle wires are the accent at partial alpha: readable on every accent
        # palette (accent_soft alone vanished on the neutral one).
        col = QColor(c["info"] if (dashed or phase) else c["accent"])
        if not selected:
            col.setAlpha(150 if not dashed else 210)
        # A pulse just travelled here: brighten the whole wire and send a dot
        # along it, so a branching graph shows its actual path.
        travel = None
        if hot is not None:
            travel = min(1.0, (time.monotonic() - hot) / PULSE_TRAVEL)
            col = QColor(c["ok"])
        pen = QPen(col, 2.4 if (selected or travel is not None) else 1.8)
        if dashed:
            pen.setStyle(Qt.PenStyle.CustomDashLine)
            pen.setDashPattern([5, 4])
            pen.setDashOffset(phase)          # marching ants
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        path = QPainterPath(QPointF(p0))
        dx = max(40, abs(p1.x() - p0.x()) * 0.5)
        path.cubicTo(QPointF(p0.x() + dx, p0.y()),
                     QPointF(p1.x() - dx, p1.y()), QPointF(p1))
        p.drawPath(path)
        # arrow head
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(col)
        head = QPolygonF([QPointF(p1.x(), p1.y()),
                          QPointF(p1.x() - 9, p1.y() - 5),
                          QPointF(p1.x() - 9, p1.y() + 5)])
        p.drawPolygon(head)
        if travel is not None:
            dot = self._bezier_point(p0, p1, travel)
            glow = QColor(col)
            glow.setAlpha(int(120 * (1.0 - travel)))
            p.setBrush(glow)
            p.drawEllipse(QPointF(dot), 9, 9)
            p.setBrush(col)
            p.drawEllipse(QPointF(dot), 4, 4)

    def _relay_watch(self, reg_id: str):
        try:
            self.watch_requested.emit(int(str(reg_id), 16))
        except ValueError:
            pass

    # ── automation runtime ───────────────────────────────────────────
    def fire(self, uid: str, payload=None):
        """A widget was activated (clicked, Enter, or a timer tick): run its own
        action, then everything downstream. Nothing happens in edit mode."""
        if self.edit:
            return
        self._act(uid, payload)
        order = self.graph.propagate(uid, blocked=self._gate_blocks)
        for target in order:
            self._act(target, payload)
        self._mark_hot(uid, order)

    def _gate_blocks(self, uid: str) -> bool:
        """A closed condition gate stops the pulse here (it still flashes, so
        the operator can see the chain reached it and why it stopped)."""
        card = self.cards.get(uid)
        if card is None or card.cfg.get("kind") != "gate":
            return False
        return not dm.gate_pass(card.cfg, card.value)

    def _act(self, uid: str, payload):
        card = self.cards.get(uid)
        if card is None:
            return
        k = card.cfg.get("kind", "value")
        card.flash()
        self._animate()
        if k == "button":
            self._write(card.cfg, payload if payload not in (None, "")
                        else card.cfg.get("value_on", 1))
        elif k == "toggle":
            card.state_on = not card.state_on
            self._write(card.cfg, card.cfg.get(
                "value_on" if card.state_on else "value_off", 0))
            card.update()
        elif k == "input":
            value = payload if payload not in (None, "") else (
                card.editor.text().strip() if card.editor else "")
            if value != "":
                self._write(card.cfg, value)
        elif k == "slider":
            value = payload if payload not in (None, "") else card.slider_value()
            if value is not None:
                self._write(card.cfg, value)
        elif k == "select":
            value = payload if payload not in (None, "") else card._select_value
            if value is not None:
                self._write(card.cfg, value)
        elif k == "timer":
            self._toggle_timer(uid)

    def _write(self, cfg: dict, value):
        """Resolve the register (type + scaling) and emit a write intent."""
        reg_id = cfg.get("reg_id")
        if not reg_id:
            return
        try:
            addr = int(str(reg_id), 16) if str(reg_id).lower().startswith("0x") \
                else int(reg_id)
        except (TypeError, ValueError):
            return
        reg = next((r for r in (self.get_registers() or [])
                    if isinstance(r, dict) and datatypes.reg_key(r) == addr), None)
        dtype = (reg or {}).get("type", cfg.get("reg_type", "SHORT"))
        text = str(value)
        if reg is not None and scaling.has_scaling(reg):
            try:
                text = repr(round(scaling.to_raw(reg, float(str(value).replace(",", "."))), 6))
            except (TypeError, ValueError):
                pass
        self.write_requested.emit(addr, dtype, text)

    # ── timers ───────────────────────────────────────────────────────
    def _toggle_timer(self, uid: str):
        if uid in self._timers:
            self._kill_timer(uid)
        else:
            self._start_timer(uid)

    def _start_timer(self, uid: str):
        card = self.cards.get(uid)
        if card is None or self.edit:
            return
        t = QTimer(self)
        t.setInterval(max(50, int(card.cfg.get("interval", 1000))))
        t.timeout.connect(lambda u=uid: self._on_tick(u))
        t.start()
        self._timers[uid] = t
        card.state_on = True
        card.update()

    def _on_tick(self, uid: str):
        """Timer tick: pulse downstream (the timer itself must not re-toggle)."""
        if self.edit:
            return
        card = self.cards.get(uid)
        if card is not None:
            card.flash()
            self._animate()
        order = self.graph.propagate(uid, blocked=self._gate_blocks)
        for target in order:
            self._act(target, None)
        self._mark_hot(uid, order)

    def _kill_timer(self, uid: str):
        t = self._timers.pop(uid, None)
        if t is not None:
            t.stop()
            t.deleteLater()
        card = self.cards.get(uid)
        if card is not None:
            card.state_on = False
            card.update()

    def _stop_all_timers(self):
        for uid in list(self._timers):
            self._kill_timer(uid)

    def _start_autostart_timers(self):
        for uid, card in self.cards.items():
            if card.cfg.get("kind") == "timer" and card.cfg.get("autostart"):
                self._start_timer(uid)

    def _sync_timer(self, uid: str):
        if uid in self._timers:
            self._kill_timer(uid)
            self._start_timer(uid)

    def stop_if_running(self):
        self._stop_all_timers()

    # ── live values / stale ──────────────────────────────────────────
    def _invalidate_index(self):
        """Call whenever a card is created/destroyed or its register changes."""
        self._reg_index = None

    def _by_reg(self) -> dict:
        if self._reg_index is None:
            idx: dict[str, list] = {}
            for card in self.cards.values():
                rid = card.cfg.get("reg_id")
                if rid:
                    idx.setdefault(rid, []).append(card)
            self._reg_index = idx
        return self._reg_index

    def update_value(self, reg_id: str, value):
        """Poll results arrive once per register per cycle, so this used to be
        O(registers × cards) — an index makes it O(cards bound to THAT
        register), which on a busy board is the difference between a few µs
        and several ms per poll."""
        for card in self._by_reg().get(reg_id, ()):
            if not sip.isdeleted(card):
                card.update_value(value)

    def _check_stale(self):
        now = time.monotonic()
        for card in self.cards.values():
            if card.value is not None:
                card.set_stale(now - card.last_sample > STALE_AFTER)

    # ── app plumbing ─────────────────────────────────────────────────
    def apply_settings(self):
        for card in self.cards.values():
            card.update()
        self.canvas.update()
        self.lbl_empty.apply_theme(self.ctx.theme_tokens())

    def retranslate(self, t):
        self.btn_add.setText("  " + t("dashAddWidget"))
        self.lbl_empty.set_content(t("dashEmptyTitle"), t("dashEmpty"))
        self.lbl_empty.buttons[0].setText(t("dashAddWidget"))
        self.set_edit(self.edit)

    # ── guide (F1 / Справка) ──────────────────────────────────────────
    def _show_guide(self):
        """Coach marks for the dashboard: the two modes, free placement and
        the wire automation, which is the part nobody discovers unaided."""
        from gui.onboarding import OnboardingGuide
        ru = self.ctx.lang == "ru"
        L = (lambda r, e: r) if ru else (lambda r, e: e)
        steps = [
            {"target": None,
             "title": L("Дашборд", "Dashboard"),
             "body": L(
                 "Мини-HMI: показания, органы управления и логика на одном "
                 "листе. Значения обновляются, пока идёт опрос.",
                 "A mini HMI: readouts, controls and logic on one sheet. "
                 "Values update while polling runs.")},
            {"target": self.btn_mode,
             "title": L("Два режима", "Two modes"),
             "body": L(
                 "«Редактировать» — расставляете элементы. «Готово» — они "
                 "живые. В режиме редактирования НИ ОДНА запись не уходит в "
                 "устройство, а таймеры остановлены.",
                 "Edit — you arrange things. Done — they are live. In edit "
                 "mode NO write reaches the device and timers are stopped.")},
            {"target": self.btn_add,
             "title": L("14 типов блоков", "14 kinds of block"),
             "body": L(
                 "Показания (значение, лампа, полоса, прибор, биты, график), "
                 "управление (кнопка, ввод, тумблер, ползунок, выбор) и "
                 "логика (таймер, условие, надпись).",
                 "Readouts (value, lamp, bar, gauge, bits, chart), controls "
                 "(button, input, toggle, slider, select) and logic (timer, "
                 "condition, label).")},
            {"target": self.canvas,
             "title": L("Размещение и навигация", "Placing and navigating"),
             "body": L(
                 "Тяните элементы — они прилипают к краям соседей (Alt — без "
                 "привязки). Колесо — масштаб, правая кнопка — панорама, "
                 "стрелки — точный сдвиг.",
                 "Drag widgets — they snap to their neighbours' edges (hold "
                 "Alt for raw placement). Wheel zooms, right-drag pans, arrow "
                 "keys nudge.")},
            {"target": self.canvas,
             "title": L("Провода — это автоматика", "Wires are the automation"),
             "body": L(
                 "В режиме редактирования тяните от правой точки одного блока "
                 "к левой другого. Пример: таймер 1 с → условие (t > 80) → "
                 "кнопка «включить вентилятор». Сработавшие провода "
                 "подсвечиваются, заблокированная ветка остаётся тёмной.",
                 "In edit mode drag from one block's right dot to another's "
                 "left dot. Example: a 1 s timer → condition (t > 80) → a "
                 "button that writes \"fan on\". Wires that carried a pulse "
                 "light up; a blocked branch stays dark.")},
            {"target": self.combo_board,
             "title": L("Несколько дашбордов", "Several dashboards"),
             "body": L(
                 "Проект хранит сколько угодно экранов. Меню ⋯ рядом — "
                 "создать, переименовать, дублировать, экспортировать.",
                 "A project holds any number of screens. The ⋯ menu next to "
                 "it creates, renames, duplicates and exports them.")},
        ]
        g = OnboardingGuide(self.window(), steps, self.ctx.theme,
                            self.ctx.settings.get("accent"), self.ctx.lang)
        g.show_guide()
