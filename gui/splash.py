# gui/splash.py
"""The start-up card: what the user sees between the double-click and the
main window.

One painter, two uses:

* ``StartupSplash`` — the live window of the installed program (and of a
  source run). It appears as soon as QApplication exists, says what is
  happening (a stage and a bar) while the modules load and the window is
  built, and fades out once the window is up.
* ``tools/make_splash.py`` renders the same card into ``assets/splash.png``
  for the one-file exe, whose PyInstaller splash covers the seconds the exe
  spends unpacking itself — before any Python, so before this module, runs.

The look follows the README banner (docs/images/hero.png): graphite with a
faint grid, the mark, the name and what the program is for, plus a few
bits of a real Modbus frame on the line. It is dark in every theme: it is the
brand card, and the one-file build shows it before any setting is read.
"""
import time

from PyQt6.QtCore import (QElapsedTimer, QEventLoop, QPointF, QPropertyAnimation,
                          QRectF, Qt, QTimer)
from PyQt6.QtGui import (QBrush, QColor, QCursor, QFont, QGuiApplication, QImage,
                         QLinearGradient, QPainter, QPainterPath, QPen,
                         QRadialGradient)
from PyQt6.QtWidgets import QApplication, QWidget

from app.i18n import get_translator
from app.paths import resource

W, H = 560, 332            # the card, logical px
RADIUS = 14
SHADOW = 28                # room around the live card for its soft shadow
FADE_IN_MS = 110
FADE_OUT_MS = 180
FINISH_DELAY_MS = 120      # let the window paint before the card leaves

# The mark's colours (tools/make_icon.py) and the banner's greys.
BLUE = QColor("#2f8fe6")
GREEN = QColor("#7fe3a0")
TEXT_1 = QColor("#f3f5f7")
TEXT_2 = QColor("#b9c0c9")
TEXT_3 = QColor("#8b939d")
TEXT_4 = QColor("#5f6873")

# The first bytes of a read request — 0A 03 00 10 — as the line carries
# them: idle high, then per byte a start bit, eight data bits LSB first and
# a stop bit (8N1).
FRAME = (0x0A, 0x03, 0x00, 0x10)


def frame_bits(data=FRAME, idle: int = 3) -> list:
    bits = [1] * idle
    for byte in data:
        bits += [0] + [(byte >> i) & 1 for i in range(8)] + [1]
    return bits + [1] * idle


def _font(px: int, weight=QFont.Weight.Normal) -> QFont:
    f = QFont("Segoe UI")
    f.setPixelSize(px)
    f.setWeight(weight)
    return f


_mark_cache: dict = {}


def _mark(px: int) -> QImage:
    """The app icon at *px* device pixels, scaled once from the 256 px PNG."""
    img = _mark_cache.get(px)
    if img is None:
        src = QImage(resource("assets", "app.png"))
        img = src.scaled(px, px, Qt.AspectRatioMode.KeepAspectRatio,
                         Qt.TransformationMode.SmoothTransformation) if not src.isNull() else src
        _mark_cache[px] = img
    return img


def paint_card(p: QPainter, card: QRectF, tagline: str, status: str = "",
               version: str = "", progress=None, dpr: float = 1.0) -> None:
    """The card itself, into *card* (logical px). ``progress`` None = no bar
    (the static image: a bar that never moves reads as a hang)."""
    p.save()
    for hint in (QPainter.RenderHint.Antialiasing, QPainter.RenderHint.TextAntialiasing,
                 QPainter.RenderHint.SmoothPixmapTransform):
        p.setRenderHint(hint)
    x0, y0 = card.left(), card.top()
    shape = QPainterPath()
    shape.addRoundedRect(card, RADIUS, RADIUS)
    p.setClipPath(shape)

    # Graphite, a shade lighter towards the far corner — the banner's.
    g = QLinearGradient(card.topLeft(), card.bottomRight())
    g.setColorAt(0.0, QColor("#11151a"))
    g.setColorAt(1.0, QColor("#1a2028"))
    p.fillRect(card, QBrush(g))
    # The mark's blue, glowing faintly from behind it.
    glow = QRadialGradient(QPointF(x0 + 74, y0 + 82), 300)
    glow.setColorAt(0.0, QColor(47, 143, 230, 58))
    glow.setColorAt(1.0, QColor(47, 143, 230, 0))
    p.fillRect(card, QBrush(glow))
    # The banner's grid.
    p.setPen(QPen(QColor(255, 255, 255, 9), 1))
    step = 28
    for i in range(1, int(card.width() // step) + 1):
        x = x0 + i * step + 0.5
        p.drawLine(QPointF(x, y0), QPointF(x, card.bottom()))
    for i in range(1, int(card.height() // step) + 1):
        y = y0 + i * step + 0.5
        p.drawLine(QPointF(x0, y), QPointF(card.right(), y))

    # Mark + name, side by side as in the banner.
    left = x0 + 44
    mark = 60
    p.drawImage(QRectF(left, y0 + 50, mark, mark), _mark(round(mark * dpr)))
    p.setFont(_font(38, QFont.Weight.Bold))
    p.setPen(TEXT_1)
    p.drawText(QRectF(left + mark + 18, y0 + 46, card.width() - mark - 106, 68),
               Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "ModbusReader")
    p.setFont(_font(15))
    p.setPen(TEXT_2)
    p.drawText(QRectF(left, y0 + 132, card.width() - 88, 24),
               Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, tagline)

    # A frame on the line: fades in from the left edge, ends in the mark's
    # green "live" dot.
    bits = frame_bits()
    end_x = card.right() - 44
    bit_w = (end_x - x0) / len(bits)
    hi, lo = y0 + 204, y0 + 226
    wave = QPainterPath(QPointF(x0, hi if bits[0] else lo))
    for i, b in enumerate(bits):
        y = hi if b else lo
        wave.lineTo(QPointF(x0 + i * bit_w, y))
        wave.lineTo(QPointF(x0 + (i + 1) * bit_w, y))
    fade = QLinearGradient(QPointF(x0, 0), QPointF(end_x, 0))
    for at, alpha in ((0.0, 0), (0.45, 110), (1.0, 235)):
        c = QColor(BLUE)
        c.setAlpha(alpha)
        fade.setColorAt(at, c)
    for width, k in ((7.0, 0.22), (1.8, 1.0)):              # glow, then the trace
        pen = QPen(QBrush(fade), width)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setOpacity(k)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(wave)
    p.setOpacity(1.0)
    dot = QPointF(end_x, hi)
    halo = QRadialGradient(dot, 16)
    halo.setColorAt(0.0, QColor(127, 227, 160, 120))
    halo.setColorAt(1.0, QColor(127, 227, 160, 0))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(halo))
    p.drawEllipse(dot, 16, 16)
    p.setBrush(GREEN)
    p.drawEllipse(dot, 4.5, 4.5)

    # Status line: what is happening on the left, the version on the right.
    base = card.bottom() - 58
    if status:
        p.setFont(_font(13))
        p.setPen(TEXT_3)
        p.drawText(QRectF(left, base, card.width() - 200, 22),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, status)
    if version:
        p.setFont(_font(12))
        p.setPen(TEXT_4)
        p.drawText(QRectF(card.right() - 244, base, 200, 22),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, version)
    # Progress: a hairline along the bottom edge.
    if progress is not None:
        track = QRectF(x0, card.bottom() - 3, card.width(), 3)
        p.fillRect(track, QColor(255, 255, 255, 12))
        done = QRectF(track.left(), track.top(),
                      track.width() * max(0.0, min(1.0, float(progress))), track.height())
        bar = QLinearGradient(track.topLeft(), track.topRight())
        bar.setColorAt(0.0, BLUE)
        bar.setColorAt(1.0, GREEN)
        p.fillRect(done, QBrush(bar))
    p.restore()

    # Hairline frame, outside the clip so it stays crisp.
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(QPen(QColor(255, 255, 255, 26), 1))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(card.adjusted(0.5, 0.5, -0.5, -0.5), RADIUS, RADIUS)
    p.restore()


class StartupSplash(QWidget):
    """The live card. ``show_now()`` → ``step()``… → ``finish()``."""

    def __init__(self, lang: str = "ru", version: str = ""):
        super().__init__(None, Qt.WindowType.SplashScreen
                         | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.t = get_translator(lang)
        self.tagline = self.t("splashTagline")
        self.status = self.t("splashStart")
        self.version = version
        self.progress = 0.06
        self._fade = None
        self.setFixedSize(W + 2 * SHADOW, H + 2 * SHADOW)
        # Where the user is: the screen under the pointer they double-clicked with.
        screen = (QGuiApplication.screenAt(QCursor.pos())
                  or QGuiApplication.primaryScreen())
        if screen is not None:
            a = screen.availableGeometry()
            self.move(a.x() + (a.width() - self.width()) // 2,
                      a.y() + (a.height() - self.height()) // 2)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        card = QRectF(SHADOW, SHADOW - 6, W, H)
        # Soft shadow, a little below the card: stacked translucent shapes.
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 4))
        for i in range(SHADOW - 4, 0, -1):
            p.drawRoundedRect(card.adjusted(-i, -i + 8, i, i + 8), RADIUS + i, RADIUS + i)
        paint_card(p, card, self.tagline, self.status, self.version, self.progress,
                   self.devicePixelRatioF())
        p.end()

    # ── the sequence ────────────────────────────────────────────────
    def _pump(self):
        QApplication.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)

    def show_now(self):
        """Show with a short fade-in and make sure it is painted before the
        caller blocks the thread with imports again."""
        self.setWindowOpacity(0.0)
        self.show()
        clock = QElapsedTimer()
        clock.start()
        while clock.elapsed() < FADE_IN_MS:
            self.setWindowOpacity(clock.elapsed() / FADE_IN_MS)
            self._pump()
            time.sleep(0.008)
        self.setWindowOpacity(1.0)
        self.repaint()
        self._pump()

    def step(self, key: str, progress: float):
        """Next stage: an i18n key for the status line and the bar's share."""
        self.status = self.t(key)
        self.progress = progress
        self.repaint()
        self._pump()

    def finish(self):
        """The window is up: fill the bar, give the window a moment to paint,
        then fade out and close."""
        self.progress = 1.0
        self.repaint()
        QTimer.singleShot(FINISH_DELAY_MS, self._fade_out)

    def _fade_out(self):
        anim = QPropertyAnimation(self, b"windowOpacity", self)
        anim.setDuration(FADE_OUT_MS)
        anim.setStartValue(1.0)
        anim.setEndValue(0.0)
        anim.finished.connect(self.close)
        anim.start()
        self._fade = anim


def render_static(tagline: str, status: str = "", scale: float = 1.0) -> QImage:
    """The card alone on a transparent image — for assets/splash.png."""
    img = QImage(round(W * scale), round(H * scale), QImage.Format.Format_ARGB32_Premultiplied)
    img.setDevicePixelRatio(scale)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    paint_card(p, QRectF(0, 0, W, H), tagline, status, dpr=scale)
    p.end()
    return img
