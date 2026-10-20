# tools/make_splash.py
"""Generate assets/splash.png — the start-up splash of the one-file exe.

A one-file PyInstaller build unpacks itself for seconds before Python even
starts; without a splash the double-click shows nothing at all, which is the
moment a user decides the program "did not start". PyInstaller's Splash
target puts this image on screen at once (see ModbusReader.spec) and main.py
closes it when the window is up. The installed program has no unpacking to
cover and shows the live card instead (gui/splash.py) — this is the same
card, painted by the same code, minus what only a live window can show (the
stage, the bar, the version).

The image carries no version number on purpose: it is a static asset, so a
release can never ship a splash that names the previous version.

Rounded corners: PyInstaller's Tk window keys out pure magenta, so a pixel is
either fully shown or fully gone — a half-transparent edge pixel would show
a pink fringe. The anti-aliased corner pixels are therefore flattened onto
the card's own dark frame colour, where they look the same as before.

Run from the repo root:  python tools/make_splash.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PyQt6.QtGui import QColor, QImage  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

EDGE = QColor("#0b0e12")          # what a half-covered corner pixel sits on


def flatten_corners(img: QImage, radius: int) -> QImage:
    """Every partly transparent pixel in the four corner squares becomes
    opaque (blended over EDGE); fully transparent ones stay transparent."""
    img = img.convertToFormat(QImage.Format.Format_ARGB32)
    w, h = img.width(), img.height()
    r = radius + 2
    for cx in (range(0, r), range(w - r, w)):
        for cy in (range(0, r), range(h - r, h)):
            for x in cx:
                for y in cy:
                    c = img.pixelColor(x, y)
                    a = c.alpha()
                    if 0 < a < 255:
                        k = a / 255
                        img.setPixelColor(x, y, QColor(
                            round(c.red() * k + EDGE.red() * (1 - k)),
                            round(c.green() * k + EDGE.green() * (1 - k)),
                            round(c.blue() * k + EDGE.blue() * (1 - k))))
    return img


def paint() -> QImage:
    from app.i18n import get_translator
    from gui import splash
    t = get_translator("ru")             # the program's first language
    img = splash.render_static(t("splashTagline"), t("splashStart"))
    return flatten_corners(img, splash.RADIUS)


def main():
    # The real platform, not "offscreen": that one has no fonts to draw with.
    _app = QApplication.instance() or QApplication(sys.argv)  # noqa: F841
    out = os.path.join(ROOT, "assets", "splash.png")
    paint().save(out)
    print("wrote", out)


if __name__ == "__main__":
    main()
