# gui/trends.py
"""Live-graphs: throttled rendering, per-window stats, design-faithful cards."""

import math
import time
import collections

import numpy as np
import pyqtgraph as pg

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QScrollArea, QSizePolicy,
    QFrame, QDialog,
)
from PyQt6.QtCore import Qt, QTimer, QSize, QEvent, pyqtSignal
from PyQt6.QtGui import QColor, QBrush, QFont, QGradient, QLinearGradient

from gui.theme_manager import get_theme
from app.i18n import get_translator
from core import datatypes
from gui import icons
from gui.dialogs import themed_info


pg.setConfigOptions(antialias=True, useOpenGL=False)
pg.setConfigOption("foreground", "#888888")

MAX_TRENDS  = 8
HISTORY_LEN = 1200
RENDER_MS   = 100

WINDOWS = [
    ("10s",  10),
    ("30s",  30),
    ("2m",   120),
    ("10m",  600),
]
SEC_LABEL = {sec: label for label, sec in WINDOWS}


def win_label(sec: int, t) -> str:
    """A chart window in the UI language: "30 с", "2 мин" ("30 s", "2 min").
    The bare "30s"/"2m" read as English shorthand in the Russian UI, right
    next to the axis that already said "30с … сейчас"."""
    if sec < 60:
        return f"{sec}{t('unitSec')}"
    return f"{sec // 60} {t('unitMin')}"


class ElidingLabel(QLabel):
    """QLabel that ellipsises its text to fit the available width."""

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self._full = text
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(0)

    def setText(self, text: str):
        self._full = text
        self._elide()

    def fullText(self) -> str:
        return self._full

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._elide()

    def _elide(self):
        fm = self.fontMetrics()
        super().setText(fm.elidedText(self._full, Qt.TextElideMode.ElideRight, self.width()))


def _ago_label(ago: float, t=None) -> str:
    """Time-ago label: 'now' / '8s' / '3m' (translated when *t* is given)."""
    if t is None:
        t = get_translator("en")
    if ago <= 0.5:
        return t("agoNow")
    if ago >= 60:
        return t("agoMin").format(n=round(ago / 60))
    return t("agoSec").format(n=round(ago))


# ═══════════════════════════════════════════════════════════════════
#  VALUE FORMATTING (shared by the card and the expanded view)
# ═══════════════════════════════════════════════════════════════════
STALE_AFTER = 5.0          # s without a sample → the card says "no data"


def decimals_for(values) -> int:
    """One precision for every number on a card, chosen from the data.

    Before, each number stripped its own zeros: «22.309 · 19.29 · 21.299» —
    three precisions in one row read as noise. Integer data shows integers;
    otherwise enough digits to resolve about 1 % of the visible range."""
    vals = [v for v in values if math.isfinite(v)]
    if not vals:
        return 2
    if all(float(v).is_integer() for v in vals):
        return 0
    span = max(vals) - min(vals)
    ref = span if span > 0 else max(abs(v) for v in vals) or 1.0
    d = math.ceil(-math.log10(ref / 100.0)) if ref > 0 else 2
    return max(0, min(4, d))


def fmt_value(v: float, decimals: int) -> str:
    """Engineering number: fixed precision, thin-space thousands, and an
    exponent only where fixed notation would lie (|v| < 1e-4 or ≥ 1e9)."""
    if not math.isfinite(v):
        return "—"
    if v != 0 and (abs(v) < 1e-4 or abs(v) >= 1e9):
        return f"{v:.3e}"
    s = f"{v:,.{decimals}f}".replace(",", " ")
    return "0" if s in ("-0", "-0.0", "-0.00", "-0.000", "-0.0000") else s


def _gradient_brush(color: str, top_alpha: int = 90):
    """Area under the line: the series colour fading to nothing — a flat
    14 % slab made every chart look like a filled shape, not a signal."""
    g = QLinearGradient(0, 0, 0, 1)
    g.setCoordinateMode(QGradient.CoordinateMode.ObjectBoundingMode)
    top, bottom = QColor(color), QColor(color)
    top.setAlpha(top_alpha)
    bottom.setAlpha(0)
    g.setColorAt(0.0, top)
    g.setColorAt(1.0, bottom)
    return QBrush(g)


def _mono(size_pt: float, bold: bool = False) -> QFont:
    f = QFont("JetBrains Mono")
    f.setStyleHint(QFont.StyleHint.Monospace)
    f.setFamilies(["JetBrains Mono", "Consolas", "monospace"])
    f.setPointSizeF(size_pt)
    if bold:
        f.setWeight(QFont.Weight.DemiBold)
    return f


# ═══════════════════════════════════════════════════════════════════
#  TREND CARD
# ═══════════════════════════════════════════════════════════════════
class TrendCard(QWidget):
    """One live register on a chart.

        ● Температура датчик 1                    ⏸  ⤢  ✕
        22.31 °C                                   ↑ 1.27
        мин 19.29   макс 22.73   ср 21.30         0x0014
        ╭─────────────────────────────── chart ───────────╮
        [10 с | 30 с | 2 мин | 10 мин]               ⌖  🗑

    The current value is THE number (large, monospace, one precision shared
    with min/max/avg); the delta says which way it went over the window; the
    chart's scale sits on the window's real min and max. States: waiting for
    the first sample, live, no data for N s (link dropped), paused."""

    remove_requested = pyqtSignal(str)
    expand_requested = pyqtSignal(str)         # (reg_id) — open fullscreen view
    drag_started = pyqtSignal(object)          # (card)
    drag_moved   = pyqtSignal(object, object)  # (card, global QPoint)
    drag_dropped = pyqtSignal(object)          # (card)

    def __init__(self, reg_id: str, reg_name: str,
                 theme: dict, color: str,
                 default_window_sec: int = 30,
                 history_len: int = HISTORY_LEN,
                 t=None, unit: str = "",
                 autofit: bool = True, antialias: bool = True,
                 parent=None):
        super().__init__(parent)
        self.reg_id   = reg_id
        self.reg_name = reg_name
        self.theme    = theme
        self.color    = color
        self.unit     = unit
        self.t        = t or get_translator("ru")

        self._ts = collections.deque(maxlen=history_len)
        self._vs = collections.deque(maxlen=history_len)

        self.paused         = False
        self.autofit        = bool(autofit)
        self._antialias     = bool(antialias)
        self.window_seconds = default_window_sec
        self._dirty         = False
        self._latest_value  = None
        self._dragging      = False
        self._state         = "waiting"       # waiting | live | stale | paused
        self._last_rx       = None            # monotonic time of the last sample

        # (button, icon_name) for theme recolor
        self._icon_btns: list[tuple[QPushButton, str]] = []

        self.setObjectName("trendCard")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(252)

        self._build_ui()

        self._render_timer = QTimer(self)
        self._render_timer.timeout.connect(self._render_if_dirty)
        self._render_timer.start(RENDER_MS)
        # Staleness is time-driven (no sample = no event): a slow tick.
        self._age_timer = QTimer(self)
        self._age_timer.timeout.connect(self._refresh_state)
        self._age_timer.start(1000)

    # ──────────────────────────── helpers
    def _icon_button(self, name: str, tooltip: str, callback, size: int = 24) -> QPushButton:
        b = QPushButton()
        b.setObjectName("gIconBtn")
        b.setFixedSize(size, size)
        b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setIconSize(QSize(14, 14))
        b.setToolTip(tooltip)
        b.setIcon(icons.icon(name, self.theme["text_3"], 14))
        b.clicked.connect(callback)
        self._icon_btns.append((b, name))
        return b

    @staticmethod
    def _clear_bg(w: QWidget):
        # Plain containers inherit the global `QWidget { background: bg_1 }`
        # and would paint a darker band across the card (bg_2).
        w.setStyleSheet("background: transparent;")
        return w

    # ──────────────────────────── build
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Header: grip/dot · title · pause · expand · close ──
        header = QHBoxLayout()
        header.setContentsMargins(10, 10, 8, 0)
        header.setSpacing(6)

        # The drag handle shows on hover; at rest the slot holds the series
        # colour, so the header is not cluttered with a permanent grip.
        self._grip = QLabel()
        self._grip.setObjectName("gGrip")
        self._grip.setFixedSize(14, 16)
        self._grip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._grip.setCursor(Qt.CursorShape.OpenHandCursor)
        self._grip.setToolTip(self.t("trendReorderHint"))
        self._grip.installEventFilter(self)

        self.lbl_title = ElidingLabel(self.reg_name)
        self.lbl_title.setObjectName("gTitle")
        self.lbl_title.setToolTip(f"{self.reg_name}  [{datatypes.id_label(self.reg_id)}]")

        self.btn_pause = self._icon_button("pause", self.t("pause"), self._toggle_pause)
        self.btn_expand = self._icon_button("expand", self.t("trendExpand"),
                                            lambda: self.expand_requested.emit(self.reg_id))
        btn_close = self._icon_button("x", self.t("close"),
                                      lambda: self.remove_requested.emit(self.reg_id))

        header.addWidget(self._grip)
        header.addWidget(self.lbl_title, 1)
        header.addWidget(self.btn_pause)
        header.addWidget(self.btn_expand)
        header.addWidget(btn_close)

        # ── Value: big current reading + unit · delta / state on the right ──
        value_row = QHBoxLayout()
        value_row.setContentsMargins(14, 2, 14, 0)
        value_row.setSpacing(6)
        self.lbl_value = QLabel("—")
        self.lbl_value.setObjectName("gValue")
        self.lbl_unit = QLabel(self.unit)
        self.lbl_unit.setObjectName("gUnit")
        self.lbl_delta = QLabel("")
        self.lbl_delta.setObjectName("gDelta")
        self.lbl_delta.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        value_row.addWidget(self.lbl_value, 0, Qt.AlignmentFlag.AlignBaseline)
        value_row.addWidget(self.lbl_unit, 0, Qt.AlignmentFlag.AlignBaseline)
        value_row.addStretch(1)
        value_row.addWidget(self.lbl_delta, 0, Qt.AlignmentFlag.AlignVCenter)

        # ── Secondary stats · address ──
        stats_row = QHBoxLayout()
        stats_row.setContentsMargins(14, 0, 14, 4)
        stats_row.setSpacing(14)
        self._stat_labels: dict[str, QLabel] = {}
        self._stat_key_labels: dict[str, QLabel] = {}
        self._stat_defs = [("min", "trendMin"), ("max", "trendMax"), ("avg", "trendAvg")]
        for key, tkey in self._stat_defs:
            pair = QHBoxLayout()
            pair.setSpacing(5)
            k = QLabel(self.t(tkey))
            k.setObjectName("gStatLbl")
            v = QLabel("—")
            v.setObjectName("gStatVal")
            pair.addWidget(k)
            pair.addWidget(v)
            self._stat_key_labels[key] = k
            self._stat_labels[key] = v
            stats_row.addLayout(pair)
        stats_row.addStretch(1)
        self.lbl_addr = QLabel(datatypes.id_label(self.reg_id))
        self.lbl_addr.setObjectName("gMeta")
        stats_row.addWidget(self.lbl_addr)
        # "cur" kept for callers that read the old stat map.
        self._stat_labels["cur"] = self.lbl_value

        # ── Plot ── (shares the card surface: no frame, no inset)
        self.plot = pg.PlotWidget(background=self.theme["bg_2"])
        self.plot.setMenuEnabled(False)
        self.plot.setMouseEnabled(x=False, y=False)
        self.plot.hideButtons()
        self.plot.showGrid(x=False, y=True, alpha=0.10)
        self.plot.getPlotItem().getViewBox().setDefaultPadding(0.0)
        self.plot.getPlotItem().layout.setContentsMargins(0, 4, 6, 2)
        self.plot.showAxis("top", False)
        self.plot.showAxis("right", False)
        self.plot.showAxis("bottom", False)   # the window is named in the footer
        self.plot.setObjectName("gPlot")
        self.plot.setStyleSheet("border: none;")
        ax = self.plot.getAxis("left")
        ax.setPen(pg.mkPen(None))              # no axis baseline
        ax.setStyle(tickLength=0, tickTextOffset=6)
        ax.setWidth(46)
        self._style_axis()
        self.plot.setYRange(0, 1, padding=0)
        ax.setTicks([[]])                      # no numbers before data
        self.plot.setMinimumHeight(96)

        self.curve = self.plot.plot(
            pen=pg.mkPen(color=self.color, width=2.0),
            fillLevel=0, brush=_gradient_brush(self.color),
            antialias=self._antialias)
        # The live end of the line: a dot inside a soft halo.
        self.last_halo = pg.ScatterPlotItem(size=15, pen=pg.mkPen(None),
                                            brush=pg.mkBrush(self._alpha(self.color, 60)))
        self.last_dot = pg.ScatterPlotItem(size=7, pen=pg.mkPen(self.theme["bg_2"], width=1.5),
                                           brush=pg.mkBrush(self.color))
        self.plot.addItem(self.last_halo)
        self.plot.addItem(self.last_dot)
        self.plot.scene().sigMouseClicked.connect(self._on_plot_clicked)

        # Empty chart: say so, in the middle of where the line will be.
        self.lbl_wait = QLabel(self.t("trendWaiting"), self.plot)
        self.lbl_wait.setObjectName("gWait")
        self.lbl_wait.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.plot.installEventFilter(self)

        # ── Footer: window · autofit · clear ──
        foot = QWidget()
        foot.setObjectName("gFoot")
        footer = QHBoxLayout(foot)
        footer.setContentsMargins(10, 6, 8, 8)
        footer.setSpacing(4)
        seg = QWidget()
        seg.setObjectName("twSeg")
        sl = QHBoxLayout(seg)
        sl.setContentsMargins(2, 2, 2, 2)
        sl.setSpacing(1)
        self._win_btns: dict[int, QPushButton] = {}
        for _label, sec in WINDOWS:
            btn = QPushButton(win_label(sec, self.t))
            btn.setObjectName("twBtn")
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _, s=sec: self._set_window(s))
            self._win_btns[sec] = btn
            sl.addWidget(btn)
        self.btn_focus = self._icon_button("focus", self.t("autoFocus"), self._toggle_autofit)
        self.btn_clear = self._icon_button("trash", self.t("clearChart"), self.clear)
        footer.addWidget(seg)
        footer.addStretch()
        footer.addWidget(self.btn_focus)
        footer.addWidget(self.btn_clear)

        for lay in (header, value_row, stats_row):
            holder = self._clear_bg(QWidget())
            holder.setLayout(lay)
            root.addWidget(holder)
        root.addWidget(self.plot, 1)
        root.addWidget(foot)

        self._paint_grip(False)
        self._set_window(self.window_seconds)
        self._refresh_focus()
        self._apply_state("waiting")

    # ──────────────────────────── look
    @staticmethod
    def _alpha(color: str, a: int) -> QColor:
        c = QColor(color)
        c.setAlpha(a)
        return c

    def _style_axis(self):
        ax = self.plot.getAxis("left")
        ax.setTextPen(pg.mkPen(self.theme["text_4"]))
        ax.setStyle(tickFont=_mono(7.5))

    def _paint_grip(self, hover: bool):
        if hover:
            self._grip.setPixmap(icons.pixmap("grip", self.theme["text_3"], 14))
        else:
            self._grip.setPixmap(icons.pixmap("dot", self.color, 14))

    def _refresh_focus(self):
        col = self.theme["accent"] if self.autofit else self.theme["text_3"]
        self.btn_focus.setIcon(icons.icon("focus", col, 14))

    # kept for callers / older code paths
    def _meta_text(self) -> str:
        return f"{datatypes.id_label(self.reg_id)} · {win_label(self.window_seconds, self.t)}"

    @staticmethod
    def _fill_brush(color: str):
        return _gradient_brush(color)

    # ──────────────────────────── state: waiting / live / stale / paused
    def _apply_state(self, state: str, age: float = 0.0):
        self._state = state
        t = self.t
        self.lbl_wait.setVisible(state == "waiting")
        if state == "paused":
            self.lbl_delta.setText(t("trendPaused"))
        elif state == "stale":
            self.lbl_delta.setText(t("trendNoData").format(age=_ago_label(age, t)))
        for w in (self.lbl_value, self.lbl_delta):
            w.setProperty("state", state)
            w.style().unpolish(w)
            w.style().polish(w)
        dim = state in ("stale", "waiting")
        self.last_dot.setBrush(pg.mkBrush(self.theme["text_4"] if dim else self.color))
        self.last_halo.setVisible(not dim)
        # An old line must not look live: it fades with its value.
        self.curve.setOpacity(0.45 if state == "stale" else 1.0)
        self.lbl_unit.setVisible(bool(self.unit) and state != "waiting")

    def _refresh_state(self):
        if self.paused:
            if self._state != "paused":
                self._apply_state("paused")
            return
        if self._last_rx is None:
            if self._state != "waiting":
                self._apply_state("waiting")
            return
        age = time.monotonic() - self._last_rx
        if age > STALE_AFTER:
            self._apply_state("stale", age)
        elif self._state != "live":
            self._apply_state("live")
            self._dirty = True                # put the delta back

    # ──────────────────────────── window selection
    def _update_x_ticks(self, now: float):
        """Lock the X range to the visible window (labels: the footer)."""
        win = self.window_seconds if self.window_seconds > 0 else 60
        self.plot.setXRange(now - win, now + win * 0.015, padding=0)

    def _set_window(self, sec: int):
        self.window_seconds = sec
        self._dirty = True
        self._update_x_ticks(self._ts[-1] if self._ts else time.time())
        for s, btn in self._win_btns.items():
            btn.setProperty("active", "true" if s == sec else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)
        self.lbl_delta.setToolTip(self.t("trendDeltaTip").format(
            win=win_label(sec, self.t)))

    # ──────────────────────────── controls
    def _toggle_pause(self):
        self.paused = not self.paused
        self.btn_pause.setToolTip(self.t("resume") if self.paused else self.t("pause"))
        name = "play" if self.paused else "pause"
        self.btn_pause.setIcon(icons.icon(name, self.theme["text_3"], 14))
        for i, (b, _n) in enumerate(self._icon_btns):
            if b is self.btn_pause:
                self._icon_btns[i] = (b, name)
                break
        if not self.paused:
            self._state = ""                  # force a fresh state below
        self._refresh_state()

    def _toggle_autofit(self):
        self.autofit = not self.autofit
        self._refresh_focus()
        self._dirty = True

    def clear(self):
        self._ts.clear()
        self._vs.clear()
        self._last_rx = None
        self.curve.setData([], [])
        self.last_dot.setData([], [])
        self.last_halo.setData([], [])
        for lbl in self._stat_labels.values():
            lbl.setText("—")
        self.lbl_delta.setText("")
        self.plot.getAxis("left").setTicks([[]])
        self._apply_state("paused" if self.paused else "waiting")

    # ──────────────────────────── data
    def set_antialias(self, on: bool):
        """Settings → Графики → «Сглаживание линий» (the graph_anim key)."""
        on = bool(on)
        if on != self._antialias:
            self._antialias = on
            self.curve.opts["antialias"] = on
            self.curve.updateItems(styleUpdate=True)

    def add_value(self, value: float):
        if self.paused:
            return
        try:
            v = float(value)
        except (TypeError, ValueError):
            return
        if not math.isfinite(v):
            return            # NaN/inf would wreck min/max/avg and the Y range
        self._ts.append(time.time())
        self._vs.append(v)
        self._latest_value = value
        self._last_rx = time.monotonic()
        self._dirty = True
        if self._state != "live":
            self._apply_state("live")

    def _render_if_dirty(self):
        if not self._dirty or not self._ts:
            return
        self._dirty = False

        xs = np.fromiter(self._ts, dtype=np.float64, count=len(self._ts))
        ys = np.fromiter(self._vs, dtype=np.float64, count=len(self._vs))
        self.curve.setData(xs, ys)

        now = xs[-1]
        self._update_x_ticks(now)
        ys_win = ys[xs >= (now - self.window_seconds)] if self.window_seconds > 0 else ys
        if len(ys_win) == 0:
            return

        cur = float(ys_win[-1])
        mn, mx = float(ys_win.min()), float(ys_win.max())
        avg = float(ys_win.mean())
        d = decimals_for(ys_win)

        self.curve.setFillLevel(mn)
        self.last_dot.setData([xs[-1]], [ys[-1]])
        self.last_halo.setData([xs[-1]], [ys[-1]])

        # Room above and below, so the min/max ticks sit INSIDE the plot (the
        # old ticks at the exact edges were clipped — one card showed no
        # numbers at all, another a lone middle value).
        pad = (mx - mn) * 0.18 or abs(cur * 0.05) or 1.0
        ax = self.plot.getAxis("left")
        if self.autofit:
            self.plot.setYRange(mn - pad, mx + pad, padding=0)
            ticks = [(mn, fmt_value(mn, d)), (mx, fmt_value(mx, d))]
            if mx - mn > 0:
                mid = (mn + mx) / 2
                ticks.insert(1, (mid, fmt_value(mid, d)))
            ax.setTicks([ticks])
        else:
            self.plot.enableAutoRange(axis="y")
            ax.setTicks(None)

        self.lbl_value.setText(fmt_value(cur, d))
        self._stat_labels["min"].setText(fmt_value(mn, d))
        self._stat_labels["max"].setText(fmt_value(mx, d))
        self._stat_labels["avg"].setText(fmt_value(avg, d if d else 1))
        if self._state == "live":
            delta = cur - float(ys_win[0])
            if abs(delta) < 10 ** (-d) / 2:
                self.lbl_delta.setText("= " + fmt_value(0.0, d))
            else:
                arrow = "↑" if delta > 0 else "↓"
                self.lbl_delta.setText(f"{arrow} {fmt_value(abs(delta), d)}")

    @staticmethod
    def _fmt(v: float) -> str:
        """Single number, no shared context (older callers)."""
        return fmt_value(v, decimals_for([v]))

    # ──────────────────────────── i18n
    def retranslate(self, t):
        self.t = t
        for sec, btn in self._win_btns.items():
            btn.setText(win_label(sec, t))
        for key, tkey in self._stat_defs:
            self._stat_key_labels[key].setText(t(tkey))
        self.lbl_wait.setText(t("trendWaiting"))
        self.btn_pause.setToolTip(t("resume") if self.paused else t("pause"))
        self.btn_expand.setToolTip(t("trendExpand"))
        self.btn_focus.setToolTip(t("autoFocus"))
        self.btn_clear.setToolTip(t("clearChart"))
        self._grip.setToolTip(t("trendReorderHint"))
        self._set_window(self.window_seconds)
        self._apply_state(self._state or "waiting")

    # ──────────────────────────── theme
    def apply_theme(self, theme: dict, color: str | None = None):
        self.theme = theme
        if color:
            self.color = color
        self.curve.setPen(pg.mkPen(color=self.color, width=2.0))
        self.curve.setBrush(_gradient_brush(self.color))
        self.last_halo.setBrush(pg.mkBrush(self._alpha(self.color, 60)))
        self.last_dot.setPen(pg.mkPen(theme["bg_2"], width=1.5))
        self.plot.setBackground(theme["bg_2"])
        self._style_axis()
        for btn, name in self._icon_btns:
            btn.setIcon(icons.icon(name, theme["text_3"], 14))
        self._paint_grip(self.underMouse())
        self._refresh_focus()
        self._apply_state(self._state or "waiting")

    # ──────────────────────────── hover / drag / expand
    def event(self, e):
        et = e.type()
        if et == QEvent.Type.HoverEnter:
            self._paint_grip(True)
        elif et == QEvent.Type.HoverLeave and not self._dragging:
            self._paint_grip(False)
        return super().event(e)

    def eventFilter(self, obj, ev):
        if obj is self.plot and ev.type() == QEvent.Type.Resize:
            self.lbl_wait.setGeometry(0, 0, self.plot.width(), self.plot.height())
            return False
        if obj is self._grip:
            t = ev.type()
            if (t == QEvent.Type.MouseButtonPress
                    and ev.button() == Qt.MouseButton.LeftButton):
                self._dragging = True
                self._grip.setCursor(Qt.CursorShape.ClosedHandCursor)
                self.drag_started.emit(self)
                return True
            if t == QEvent.Type.MouseMove and self._dragging:
                self.drag_moved.emit(self, ev.globalPosition().toPoint())
                return True
            if (t == QEvent.Type.MouseButtonRelease and self._dragging
                    and ev.button() == Qt.MouseButton.LeftButton):
                self._dragging = False
                self._grip.setCursor(Qt.CursorShape.OpenHandCursor)
                self.drag_dropped.emit(self)
                return True
        return super().eventFilter(obj, ev)

    def _on_plot_clicked(self, ev):
        """pyqtgraph scene click — fire expand on double-click only."""
        try:
            if ev.double():
                self.expand_requested.emit(self.reg_id)
        except Exception:
            pass

    def mouseDoubleClickEvent(self, event):
        # Double-click on the card chrome (header / stats) also expands.
        self.expand_requested.emit(self.reg_id)
        super().mouseDoubleClickEvent(event)

    def closeEvent(self, event):
        self._render_timer.stop()
        self._age_timer.stop()
        super().closeEvent(event)


# ═══════════════════════════════════════════════════════════════════
#  CHART EXPAND  (fullscreen single-trend view)
# ═══════════════════════════════════════════════════════════════════
class ChartExpandDialog(QDialog):
    """Fullscreen live view of one trend. Reads the source card's history
    buffers so it stays live while open. Esc / the × button closes it."""

    def __init__(self, card: "TrendCard", parent=None):
        super().__init__(parent)
        self._card  = card
        self.theme  = card.theme
        self.color  = card.color
        self.unit   = card.unit
        self.t      = card.t
        self.window_seconds = card.window_seconds
        self.autofit        = card.autofit

        self.setWindowTitle(card.reg_name)
        self.setObjectName("chartExpand")
        self.setModal(False)
        self.setMinimumSize(720, 480)
        self.setStyleSheet(f"QDialog#chartExpand {{ background: {self.theme['bg_1']}; }}")

        self._build_ui()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._render)
        self._timer.start(RENDER_MS)
        self._render()

    # ──────────────────────────── build
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        # Top bar: color · title · window-seg · autofit · close
        bar = QHBoxLayout()
        bar.setSpacing(10)

        dot = QWidget()
        dot.setFixedSize(10, 10)
        dot.setStyleSheet(f"background: {self.color}; border-radius: 3px;")

        title = QLabel(self._card.reg_name)
        title.setStyleSheet(
            f"color: {self.theme['text_1']}; background: transparent; "
            f"font-size: 16px; font-weight: 700;")
        meta = QLabel(datatypes.id_label(self._card.reg_id))
        meta.setStyleSheet(
            f"color: {self.theme['text_3']}; background: transparent; "
            f"font-family:'JetBrains Mono','Consolas',monospace; font-size: 11px;")

        seg = QWidget()
        sl = QHBoxLayout(seg)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(2)
        self._win_btns: dict[int, QPushButton] = {}
        for label, sec in WINDOWS:
            b = QPushButton(win_label(sec, self.t))
            b.setObjectName("twBtn")
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _, s=sec: self._set_window(s))
            self._win_btns[sec] = b
            sl.addWidget(b)

        self.btn_focus = QPushButton(self.t("autoFocus"))
        self.btn_focus.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_focus.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_focus.setIcon(icons.icon("focus", self.theme["text_3"], 13))
        self.btn_focus.clicked.connect(self._toggle_autofit)

        btn_close = QPushButton("  Esc")
        btn_close.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_close.setIcon(icons.icon("x", self.theme["text_3"], 13))
        btn_close.clicked.connect(self.accept)

        bar.addWidget(dot)
        bar.addWidget(title)
        bar.addWidget(meta)
        bar.addStretch()
        bar.addWidget(seg)
        bar.addWidget(self.btn_focus)
        bar.addWidget(btn_close)
        root.addLayout(bar)

        # Big stats row
        stats = QHBoxLayout()
        stats.setSpacing(28)
        self._stat_labels: dict[str, QLabel] = {}
        for key, tkey in [("cur", "now"), ("min", "min"), ("max", "max"), ("avg", "avg")]:
            col = QVBoxLayout()
            col.setSpacing(2)
            k = QLabel(self.t(tkey))
            k.setStyleSheet(
                f"color: {self.theme['text_4']}; background: transparent; "
                f"font-size: 10px; font-weight: 700; letter-spacing: 1px;")
            v = QLabel("—")
            color = self.color if key == "cur" else self.theme["text_1"]
            v.setStyleSheet(
                f"color: {color}; background: transparent; "
                f"font-family:'JetBrains Mono','Consolas',monospace; "
                f"font-size: 22px; font-weight: 600;")
            col.addWidget(k)
            col.addWidget(v)
            self._stat_labels[key] = v
            stats.addLayout(col)
        stats.addStretch()
        root.addLayout(stats)

        # Big plot. X values are wall-clock seconds: a plain axis labelled
        # them "1.76e9"; a DateAxisItem prints the time of day instead.
        self.plot = pg.PlotWidget(background=self.theme["bg_2"],
                                  axisItems={"bottom": pg.DateAxisItem()})
        self.plot.setMenuEnabled(False)
        self.plot.setMouseEnabled(x=False, y=False)
        self.plot.hideButtons()
        self.plot.showGrid(x=True, y=True, alpha=0.18)
        self.plot.getPlotItem().getViewBox().setDefaultPadding(0.0)
        self.plot.showAxis("top", False)
        self.plot.showAxis("right", False)
        self.plot.setStyleSheet("border: none;")
        ax = self.plot.getAxis("left")
        ax.setPen(pg.mkPen(None))
        ax.setTextPen(pg.mkPen(self.theme["text_4"]))
        ax.setStyle(tickLength=0, tickTextOffset=6)
        ax.setWidth(52)
        bx = self.plot.getAxis("bottom")
        bx.setPen(pg.mkPen(None))
        bx.setTextPen(pg.mkPen(self.theme["text_4"]))
        self.curve = self.plot.plot(
            pen=pg.mkPen(color=self.color, width=2.0),
            fillLevel=0, brush=TrendCard._fill_brush(self.color),
            antialias=self._card._antialias)
        self.last_dot = pg.ScatterPlotItem(
            size=8, pen=pg.mkPen(None), brush=pg.mkBrush(self.color))
        self.plot.addItem(self.last_dot)
        root.addWidget(self.plot, 1)

        self._set_window(self.window_seconds)
        self._refresh_focus()

    # ──────────────────────────── controls
    def _set_window(self, sec: int):
        self.window_seconds = sec
        for s, b in self._win_btns.items():
            b.setProperty("active", "true" if s == sec else "false")
            b.style().unpolish(b)
            b.style().polish(b)
        self._render()

    def _toggle_autofit(self):
        self.autofit = not self.autofit
        self._refresh_focus()
        self._render()

    def _refresh_focus(self):
        col = self.theme["accent"] if self.autofit else self.theme["text_3"]
        self.btn_focus.setIcon(icons.icon("focus", col, 13))

    # ──────────────────────────── render from source card buffers
    def _render(self):
        ts, vs = self._card._ts, self._card._vs
        if not ts:
            return
        xs = np.fromiter(ts, dtype=np.float64, count=len(ts))
        ys = np.fromiter(vs, dtype=np.float64, count=len(vs))
        self.curve.setData(xs, ys)
        now = xs[-1]
        win = self.window_seconds if self.window_seconds > 0 else 60
        self.plot.setXRange(now - win, now + win * 0.012, padding=0)
        ys_win = ys[xs >= (now - win)] if self.window_seconds > 0 else ys
        if len(ys_win) == 0:
            return
        cur = float(ys_win[-1]); mn = float(ys_win.min())
        mx = float(ys_win.max()); avg = float(ys_win.mean())
        self.curve.setFillLevel(mn)
        self.last_dot.setData([xs[-1]], [ys[-1]])
        pad = (mx - mn) * 0.15 or abs(cur * 0.05) or 1.0
        if self.autofit:
            self.plot.setYRange(mn - pad, mx + pad, padding=0)
        else:
            self.plot.enableAutoRange(axis="y")
        unit = f" {self.unit}" if self.unit else ""
        d = decimals_for(ys_win)                 # one precision, like the card
        self._stat_labels["cur"].setText(fmt_value(cur, d) + unit)
        self._stat_labels["min"].setText(fmt_value(mn, d))
        self._stat_labels["max"].setText(fmt_value(mx, d))
        self._stat_labels["avg"].setText(fmt_value(avg, d if d else 1))

    def closeEvent(self, event):
        self._timer.stop()
        super().closeEvent(event)


# ═══════════════════════════════════════════════════════════════════
#  TRENDS MANAGER
# ═══════════════════════════════════════════════════════════════════
class TrendsManager(QWidget):
    """Right-panel container for TrendCard widgets."""

    state_changed = pyqtSignal(bool)  # True = has cards

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        # App-specific manager: reads its initial theme / window / history /
        # translator from the AppContext. (default_window_sec and history_len
        # are refreshed later by gui/main_window.py on a settings change.)
        self.ctx                = ctx
        self._autofit_default   = bool(ctx.settings.get("graph_autofit_y", True))
        self.theme              = get_theme(ctx.theme)   # no accent (unchanged)
        self.default_window_sec = ctx.settings.get("default_window_sec", 30)
        self.history_len        = ctx.settings.get("trend_history", 1200)
        self.t                  = ctx.t
        self.active_trends: dict[str, TrendCard] = {}
        self._color_idx = 0

        self.setObjectName("trendsPanel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.lbl_title = QLabel(self.t("liveMonitoring"))
        self.lbl_title.setObjectName("trendsZoneTitle")
        self.lbl_title.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        root.addWidget(self.lbl_title)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.content = QWidget()
        self.content.setObjectName("trendsScrollContent")
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.content_layout.setSpacing(10)
        self.content_layout.setContentsMargins(10, 10, 10, 10)

        self.scroll.setWidget(self.content)
        root.addWidget(self.scroll, 1)

    # ──────────────────────────── API

    def set_theme(self, theme_name: str):
        self.theme = get_theme(theme_name)
        for i, card in enumerate(self.active_trends.values()):
            color = self.theme["plot_colors"][i % len(self.theme["plot_colors"])]
            card.apply_theme(self.theme, color)

    def retranslate(self, t):
        self.t = t
        self.lbl_title.setText(t("liveMonitoring"))
        for card in self.active_trends.values():
            card.retranslate(t)

    def _next_color(self) -> str:
        colors = self.theme["plot_colors"]
        c = colors[self._color_idx % len(colors)]
        self._color_idx += 1
        return c

    def add_trend(self, reg_id: str, reg_name: str, unit: str = ""):
        if reg_id in self.active_trends:
            return
        if len(self.active_trends) >= MAX_TRENDS:
            themed_info(self, self.ctx.theme, "warning",
                        self.t("trendLimitTitle"),
                        self.t("trendLimitText").format(n=MAX_TRENDS))
            return

        was_empty = (len(self.active_trends) == 0)
        card = TrendCard(
            reg_id=reg_id,
            reg_name=reg_name,
            theme=self.theme,
            color=self._next_color(),
            default_window_sec=self.default_window_sec,
            history_len=self.history_len,
            t=self.t,
            unit=unit,
            autofit=bool(self.ctx.settings.get("graph_autofit_y", True)),
            antialias=self.ctx.settings.get("graph_anim", "smooth") != "off",
        )
        card.remove_requested.connect(self.remove_trend)
        card.expand_requested.connect(self._on_card_expand)
        card.drag_started.connect(self._on_card_drag_started)
        card.drag_moved.connect(self._on_card_drag_moved)
        card.drag_dropped.connect(self._on_card_drag_dropped)
        self._apply_grid(card.plot)
        self.content_layout.addWidget(card)
        self.active_trends[reg_id] = card
        if was_empty:
            self.state_changed.emit(True)

    def _apply_grid(self, plot, vertical: bool = False):
        """Honor the trend_grid setting on a pyqtgraph plot. Cards get level
        lines only: vertical lines at arbitrary seconds were noise in a strip
        this narrow (the expanded view keeps both)."""
        g = bool(self.ctx.settings.get("trend_grid", True))
        plot.showGrid(x=g and vertical, y=g, alpha=0.10 if not vertical else 0.18)

    def apply_settings(self):
        """Re-apply settings-driven options to live cards (after Apply).

        «Автомасштаб оси Y» and «Сглаживание линий» used to be stored and then
        read by nothing at all — two switches in Settings that did nothing.
        Autofit is the DEFAULT for cards: changing the setting re-aligns the
        open cards, and each card's target button still overrides it."""
        autofit = bool(self.ctx.settings.get("graph_autofit_y", True))
        antialias = self.ctx.settings.get("graph_anim", "smooth") != "off"
        changed = autofit != getattr(self, "_autofit_default", autofit)
        self._autofit_default = autofit
        for card in self.active_trends.values():
            self._apply_grid(card.plot)
            card.set_antialias(antialias)
            if changed and card.autofit != autofit:
                card._toggle_autofit()

    # ──────────────────────────── expand to fullscreen

    def _on_card_expand(self, reg_id: str):
        card = self.active_trends.get(reg_id)
        if not card:
            return
        dlg = ChartExpandDialog(card, parent=self.window())
        self._apply_grid(dlg.plot, vertical=True)
        dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        dlg.showMaximized()

    # ──────────────────────────── drag-to-reorder

    def _ordered_cards(self) -> list:
        lay = self.content_layout
        return [lay.itemAt(i).widget() for i in range(lay.count())
                if lay.itemAt(i).widget() is not None]

    def _on_card_drag_started(self, card):
        card.raise_()
        card.setProperty("dragging", "true")
        card.style().unpolish(card)
        card.style().polish(card)

    def _on_card_drag_moved(self, card, gpos):
        cards = self._ordered_cards()
        if card not in cards:
            return
        cur = cards.index(card)
        y = gpos.y()
        target = cur
        if cur > 0 and y < cards[cur - 1].mapToGlobal(
                cards[cur - 1].rect().center()).y():
            target = cur - 1
        elif cur < len(cards) - 1 and y > cards[cur + 1].mapToGlobal(
                cards[cur + 1].rect().center()).y():
            target = cur + 1
        if target != cur:
            self.content_layout.removeWidget(card)
            self.content_layout.insertWidget(target, card)
            self._sync_order()

    def _on_card_drag_dropped(self, card):
        card.setProperty("dragging", "false")
        card.style().unpolish(card)
        card.style().polish(card)
        self._sync_order()

    def _sync_order(self):
        """Re-key active_trends to match the on-screen card order."""
        self.active_trends = {c.reg_id: c for c in self._ordered_cards()
                              if isinstance(c, TrendCard)}

    def remove_trend(self, reg_id: str):
        if reg_id not in self.active_trends:
            return
        card = self.active_trends.pop(reg_id)
        self.content_layout.removeWidget(card)
        card.deleteLater()
        if not self.active_trends:
            self.state_changed.emit(False)

    def update_trend_data(self, reg_id: str, value: float):
        card = self.active_trends.get(reg_id)
        if card:
            card.add_value(value)

    def clear_all(self):
        for reg_id in list(self.active_trends.keys()):
            self.remove_trend(reg_id)
