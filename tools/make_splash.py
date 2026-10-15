# tools/make_splash.py
"""Generate assets/splash.png — the start-up splash of the one-file exe.

A one-file PyInstaller build unpacks itself for a few seconds before Python
even starts; without a splash the double-click shows nothing at all, which is
the moment a user decides the program "did not start". PyInstaller's Splash
target puts this image on screen at once (see ModbusReader.spec) and main.py
closes it when the window is up.

The image carries no version number on purpose: it is a static asset, so a
release can never ship a splash that names the previous version.

Run from the repo root:  python tools/make_splash.py
"""
import os
import sys

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import (QColor, QFont, QGuiApplication, QImage, QPainter,
                         QPen)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
W, H = 520, 300


def paint() -> QImage:
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    from make_icon import paint as paint_icon

    img = QImage(W, H, QImage.Format.Format_RGB32)
    img.fill(QColor("#101316"))                  # the app's dark chrome (bg_1)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    # Hairline frame: a splash floats over whatever is on the desktop.
    p.setPen(QPen(QColor("#2a2e33"), 1))
    p.drawRect(QRectF(0.5, 0.5, W - 1, H - 1))
    # The mark, drawn natively at this size (same painter as the exe icon).
    p.drawImage(44, 74, paint_icon(96))
    # Name + tagline.
    name = QFont("Segoe UI", 26)
    name.setWeight(QFont.Weight.Bold)
    p.setFont(name)
    p.setPen(QColor("#f0f2f4"))
    p.drawText(QRectF(164, 82, W - 190, 46),
               Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "ModbusReader")
    tag = QFont("Segoe UI", 11)
    p.setFont(tag)
    p.setPen(QColor("#a2a8b0"))
    p.drawText(QRectF(166, 128, W - 190, 24),
               Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
               "Modbus RTU · commissioning & monitoring")
    # A quiet status line — no progress bar: the splash cannot animate, and
    # a bar frozen at a third reads as a hang.
    p.setPen(QColor("#868d97"))
    small = QFont("Segoe UI", 9)
    p.setFont(small)
    p.drawText(QRectF(44, H - 46, W - 88, 20),
               Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
               "Starting…")
    p.end()
    return img


def main():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    _app = QGuiApplication.instance() or QGuiApplication(sys.argv)  # noqa: F841
    out = os.path.join(ROOT, "assets", "splash.png")
    paint().save(out)
    print("wrote", out)


if __name__ == "__main__":
    main()
