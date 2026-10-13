# gui_trends.py
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
from PyQt6.QtGui import QColor

from theme_manager import get_theme
from i18n import get_translator
import icons
from dialogs import themed_info


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
#  TREND CARD
# ═══════════════════════════════════════════════════════════════════
class TrendCard(QWidget):
    """Single trend card: header, stats, relative chart, time-window footer."""

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

        # (button, icon_name) for theme recolor
        self._icon_btns: list[tuple[QPushButton, str]] = []

        self.setObjectName("trendCard")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        # Taller card so the plot row (1fr) gets real height instead of
        # collapsing to a thin strip (md "КОРЕНЬ ВСЕГО — нет высоты").
        self.setFixedHeight(248)

        self._build_ui()

        self._render_timer = QTimer(self)
        self._render_timer.timeout.connect(self._render_if_dirty)
        self._render_timer.start(RENDER_MS)

    # ──────────────────────────── icon button helper

    def _icon_button(self, name: str, tooltip: str, callback, size: int = 22) -> QPushButton:
        b = QPushButton()
        b.setObjectName("gIconBtn")
        b.setFixedSize(size, size)
        b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setIconSize(QSize(13, 13))
        b.setToolTip(tooltip)
        b.setIcon(icons.icon(name, self.theme["text_3"], 13))
        b.clicked.connect(callback)
        self._icon_btns.append((b, name))
        return b

    # ──────────────────────────── build

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Header: grip · color · title · meta · pause · close ──
        header = QHBoxLayout()
        header.setContentsMargins(10, 9, 10, 6)
        header.setSpacing(8)

        grip = self._grip = QLabel()
        grip.setObjectName("gGrip")
        grip.setFixedSize(12, 14)
        grip.setPixmap(icons.pixmap("grip", self.theme["text_4"], 14))
        grip.setCursor(Qt.CursorShape.OpenHandCursor)
        grip.setToolTip(self.t("trendReorderHint"))
        grip.installEventFilter(self)   # grip is the drag handle for reordering

        self._color_dot = QWidget()
        self._color_dot.setObjectName("gColor")
        self._color_dot.setFixedSize(8, 8)
        self._color_dot.setStyleSheet(f"background: {self.color}; border-radius: 2px;")

        self.lbl_title = ElidingLabel(self.reg_name)
        self.lbl_title.setObjectName("gTitle")
        self.lbl_title.setToolTip(f"{self.reg_name}  [{self.reg_id}]")

        self.lbl_meta = QLabel(self._meta_text())
        self.lbl_meta.setObjectName("gMeta")

        self.btn_pause = self._icon_button("pause", self.t("pause"), self._toggle_pause)
        btn_close = self._icon_button("x", self.t("close"),
                                      lambda: self.remove_requested.emit(self.reg_id))

        header.addWidget(grip)
        header.addWidget(self._color_dot)
        header.addWidget(self.lbl_title, 1)
        header.addWidget(self.lbl_meta)
        header.addWidget(self.btn_pause)
        header.addWidget(btn_close)

        # ── Stats: cur (colored) · min · max · avg ──
        stats = QHBoxLayout()
        stats.setContentsMargins(10, 0, 10, 6)
        stats.setSpacing(0)

        self._stat_labels: dict[str, QLabel] = {}
        self._stat_key_labels: dict[str, QLabel] = {}
        self._stat_defs = [("cur", "now"), ("min", "min"), ("max", "max"), ("avg", "avg")]
        for key, tkey in self._stat_defs:
            col = QWidget()
            # Without this the column inherits the global `QWidget` bg_1 rule,
            # painting a band DARKER than the card (bg_2) under the stat text.
            col.setStyleSheet("background: transparent;")
            cl = QVBoxLayout(col)
            cl.setSpacing(1)
            cl.setContentsMargins(0, 0, 0, 0)

            lbl_k = QLabel(self.t(tkey))
            lbl_k.setObjectName("gStatLbl")
            self._stat_key_labels[key] = lbl_k

            lbl_v = QLabel("—")
            lbl_v.setObjectName("gStatVal")
            if key == "cur":
                lbl_v.setProperty("current", "true")

            cl.addWidget(lbl_k)
            cl.addWidget(lbl_v)
            self._stat_labels[key] = lbl_v
            stats.addWidget(col, 1)

        # ── Plot ── (chart area inherits the CARD background, per design)
        self.plot = pg.PlotWidget(background=self.theme["bg_2"])
        self.plot.setMenuEnabled(False)
        self.plot.setMouseEnabled(x=False, y=False)
        self.plot.hideButtons()
        self.plot.showGrid(x=True, y=True, alpha=0.18)
        self.plot.getPlotItem().getViewBox().setDefaultPadding(0.0)
        self.plot.showAxis("top", False)
        self.plot.showAxis("right", False)
        # X labels are drawn as an overlay row below the plot (see _xax), so the
        # pyqtgraph bottom axis is hidden — its edge labels were being clipped
        # ("10s" → "0s") and scrambled.
        self.plot.showAxis("bottom", False)
        self.plot.setObjectName("gPlot")
        self._apply_plot_frame()

        ax = self.plot.getAxis("left")
        ax.setPen(pg.mkPen(None))          # no axis baseline line ("черта")
        ax.setTextPen(pg.mkPen(self.theme["text_4"]))
        ax.setStyle(tickLength=0, tickTextOffset=5)
        ax.setWidth(40)
        self.plot.setMinimumHeight(120)   # md: chart min-height
        # Clean empty-state Y axis: exactly 3 ticks (top / mid / bottom) instead
        # of pyqtgraph's default 0.2/0.4/0.6/0.8 stack shown before data arrives.
        self.plot.setYRange(0, 1, padding=0)
        self._update_y_ticks(0.0, 1.0)

        self.curve = self.plot.plot(
            pen=pg.mkPen(color=self.color, width=1.6),
            fillLevel=0, brush=self._fill_brush(self.color),
            antialias=self._antialias,
        )
        self.last_dot = pg.ScatterPlotItem(
            size=6, pen=pg.mkPen(None), brush=pg.mkBrush(self.color)
        )
        self.plot.addItem(self.last_dot)
        self._apply_value_color(self.color)
        # Double-click anywhere on the plot → open the fullscreen expanded view.
        self.plot.scene().sigMouseClicked.connect(self._on_plot_clicked)

        # ── Footer: tw-seg · focus(autofit) · trash(clear) ──
        foot = QWidget()
        foot.setObjectName("gFoot")
        footer = QHBoxLayout(foot)
        footer.setContentsMargins(10, 6, 10, 8)
        footer.setSpacing(4)

        seg = QWidget()
        seg.setObjectName("twSeg")
        sl = QHBoxLayout(seg)
        sl.setContentsMargins(2, 2, 2, 2)
        sl.setSpacing(1)
        self._win_btns: dict[int, QPushButton] = {}
        for label, sec in WINDOWS:
            btn = QPushButton(label)
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

        # ── X-axis labels: overlay row of real labels (HTML-like, per the
        #    reference). Evenly distributed; first left-aligned, last
        #    right-aligned — so it reads oldest→now left-to-right with no
        #    pyqtgraph edge clipping.
        self._xax = QWidget()
        self._xax.setObjectName("gXax")
        self._xax.setStyleSheet("background: transparent;")
        self._xax.setFixedHeight(15)
        xl = QHBoxLayout(self._xax)
        xl.setContentsMargins(44, 0, 12, 0)   # left ≈ Y-axis width: align to data
        xl.setSpacing(0)
        _aligns = [Qt.AlignmentFlag.AlignLeft, Qt.AlignmentFlag.AlignHCenter,
                   Qt.AlignmentFlag.AlignHCenter, Qt.AlignmentFlag.AlignHCenter,
                   Qt.AlignmentFlag.AlignRight]
        self._x_labels: list[QLabel] = []
        for i in range(5):
            lab = QLabel("")
            lab.setObjectName("gXLbl")
            lab.setAlignment(_aligns[i] | Qt.AlignmentFlag.AlignVCenter)
            lab.setStyleSheet(self._xlbl_qss())
            self._x_labels.append(lab)
            xl.addWidget(lab, 1)

        root.addLayout(header)
        root.addLayout(stats)
        root.addWidget(self.plot, 1)
        root.addWidget(self._xax)
        root.addWidget(foot)

        self._set_window(self.window_seconds)
        self._refresh_focus()

    # ──────────────────────────── helpers

    def _meta_text(self) -> str:
        return f"{self.reg_id} · {SEC_LABEL.get(self.window_seconds, str(self.window_seconds) + 's')}"

    @staticmethod
    def _fill_brush(color: str):
        col = QColor(color)
        col.setAlpha(36)            # ≈ 0.14 opacity, matches design .area
        return pg.mkBrush(col)

    def _apply_plot_frame(self):
        """No border — the chart shares the card surface (same bg_2) so it blends
        seamlessly under the stats text instead of reading as a framed inset."""
        self.plot.setStyleSheet("border: none;")

    def _apply_value_color(self, color: str):
        cur = self._stat_labels.get("cur")
        if cur:
            cur.setStyleSheet(f"color: {color};")

    def _refresh_focus(self):
        col = self.theme["accent"] if self.autofit else self.theme["text_3"]
        self.btn_focus.setIcon(icons.icon("focus", col, 13))

    def _xlbl_qss(self) -> str:
        return (f"color:{self.theme['text_4']}; background:transparent; "
                f"font-family:'JetBrains Mono','Consolas',monospace; font-size:9px;")

    def _update_x_ticks(self, now: float):
        """Update the 5 overlay X labels (leftmost = window-ago, rightmost = now)
        and lock the plot's X range to the visible window."""
        win = self.window_seconds if self.window_seconds > 0 else 60
        for i in range(5):
            frac = i / 4.0
            self._x_labels[i].setText(_ago_label(win * (1.0 - frac), self.t))
        self.plot.setXRange(now - win, now + win * 0.012, padding=0)

    def _update_y_ticks(self, lo: float, hi: float):
        """Three ticks: bottom (lo), middle, top (hi)."""
        mid = (lo + hi) / 2.0
        ticks = [(lo, self._fmt(lo)), (mid, self._fmt(mid)), (hi, self._fmt(hi))]
        self.plot.getAxis("left").setTicks([ticks])

    # ──────────────────────────── window selection

    def _set_window(self, sec: int):
        self.window_seconds = sec
        self._dirty = True
        self.lbl_meta.setText(self._meta_text())
        self._update_x_ticks(self._ts[-1] if self._ts else time.time())
        for s, btn in self._win_btns.items():
            btn.setProperty("active", "true" if s == sec else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    # ──────────────────────────── controls

    def _toggle_pause(self):
        self.paused = not self.paused
        self.btn_pause.setToolTip(self.t("resume") if self.paused else self.t("pause"))
        name = "play" if self.paused else "pause"
        self.btn_pause.setIcon(icons.icon(name, self.theme["text_3"], 13))
        # keep registry name in sync for theme recolor
        for i, (b, _n) in enumerate(self._icon_btns):
            if b is self.btn_pause:
                self._icon_btns[i] = (b, name)
                break

    def _toggle_autofit(self):
        self.autofit = not self.autofit
        self._refresh_focus()
        self._dirty = True

    def clear(self):
        self._ts.clear()
        self._vs.clear()
        self.curve.setData([], [])
        self.last_dot.setData([], [])
        for lbl in self._stat_labels.values():
            lbl.setText("—")

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
        self._dirty = True

    def _render_if_dirty(self):
        if not self._dirty or not self._ts:
            return
        self._dirty = False

        xs = np.fromiter(self._ts, dtype=np.float64, count=len(self._ts))
        ys = np.fromiter(self._vs, dtype=np.float64, count=len(self._vs))
        self.curve.setData(xs, ys)

        now = xs[-1]
        self._update_x_ticks(now)
        if self.window_seconds > 0:
            ys_win = ys[xs >= (now - self.window_seconds)]
        else:
            ys_win = ys

        if len(ys_win) == 0:
            return

        cur = float(ys_win[-1])
        mn  = float(ys_win.min())
        mx  = float(ys_win.max())
        avg = float(ys_win.mean())

        self.curve.setFillLevel(mn)
        self.last_dot.setData([xs[-1]], [ys[-1]])

        # Degenerate-range guard: pad is never zero, so the line never flatlines.
        pad = (mx - mn) * 0.15 or abs(cur * 0.05) or 1.0
        lo, hi = mn - pad, mx + pad
        if self.autofit:
            self.plot.setYRange(lo, hi, padding=0)
            self._update_y_ticks(lo, hi)
        else:
            self.plot.enableAutoRange(axis="y")
            self.plot.getAxis("left").setTicks(None)

        unit = f" {self.unit}" if self.unit else ""
        self._stat_labels["cur"].setText(self._fmt(cur) + unit)
        self._stat_labels["min"].setText(self._fmt(mn))
        self._stat_labels["max"].setText(self._fmt(mx))
        self._stat_labels["avg"].setText(self._fmt(avg))

    @staticmethod
    def _fmt(v: float) -> str:
        if abs(v) >= 10000 or (v != 0 and abs(v) < 0.01):
            return f"{v:.3e}"
        s = f"{v:.3f}".rstrip("0").rstrip(".")
        return s or "0"

    # ──────────────────────────── i18n

    def retranslate(self, t):
        self.t = t
        self._update_x_ticks(self._ts[-1] if self._ts else time.time())
        for key, tkey in self._stat_defs:
            self._stat_key_labels[key].setText(t(tkey))
        self.btn_pause.setToolTip(t("resume") if self.paused else t("pause"))
        self.btn_focus.setToolTip(t("autoFocus"))
        self.btn_clear.setToolTip(t("clearChart"))

    # ──────────────────────────── theme

    def apply_theme(self, theme: dict, color: str | None = None):
        self.theme = theme
        if color:
            self.color = color
            self.curve.setPen(pg.mkPen(color=color, width=1.6))
            self.curve.setBrush(self._fill_brush(color))
            self.last_dot.setBrush(pg.mkBrush(color))
            self._color_dot.setStyleSheet(f"background: {color}; border-radius: 2px;")
            self._apply_value_color(color)
        self.plot.setBackground(theme["bg_2"])
        self._apply_plot_frame()
        ax = self.plot.getAxis("left")
        ax.setPen(pg.mkPen(None))          # no axis baseline line ("черта")
        ax.setTextPen(pg.mkPen(theme["text_4"]))
        for lab in self._x_labels:
            lab.setStyleSheet(self._xlbl_qss())
        # recolor icons + grip
        for btn, name in self._icon_btns:
            btn.setIcon(icons.icon(name, theme["text_3"], 13))
        self._grip.setPixmap(icons.pixmap("grip", theme["text_4"], 14))
        self._refresh_focus()

    # ──────────────────────────── drag-to-reorder (grip handle)

    def eventFilter(self, obj, ev):
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
        meta = QLabel(self._card.reg_id)
        meta.setStyleSheet(
            f"color: {self.theme['text_3']}; background: transparent; "
            f"font-family:'JetBrains Mono','Consolas',monospace; font-size: 11px;")

        seg = QWidget()
        sl = QHBoxLayout(seg)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(2)
        self._win_btns: dict[int, QPushButton] = {}
        for label, sec in WINDOWS:
            b = QPushButton(label)
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
        self._stat_labels["cur"].setText(TrendCard._fmt(cur) + unit)
        self._stat_labels["min"].setText(TrendCard._fmt(mn))
        self._stat_labels["max"].setText(TrendCard._fmt(mx))
        self._stat_labels["avg"].setText(TrendCard._fmt(avg))

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
        # are refreshed later by gui_main on a settings change.)
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

    def _apply_grid(self, plot):
        """Honor the trend_grid setting on a pyqtgraph plot."""
        g = bool(self.ctx.settings.get("trend_grid", True))
        plot.showGrid(x=g, y=g, alpha=0.18)

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
        self._apply_grid(dlg.plot)
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
