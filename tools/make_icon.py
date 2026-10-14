# tools/make_icon.py
"""Generate the application icon: assets/app.png (256 px) + assets/app.ico.

The mark is the toolbar's "M" redrawn as a signal trace — up, down, up,
down — on a deep blue tile: it reads as the app's initial and as a line on a
scope. Every size is painted natively (not scaled down from 256), so the
16 px taskbar icon keeps a crisp stroke instead of a blurred one.

Run from the repo root:  python tools/make_icon.py
"""
import os
import struct
import sys

from PyQt6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, QRectF, Qt
from PyQt6.QtGui import (QColor, QGuiApplication, QImage, QLinearGradient,
                         QPainter, QPainterPath, QPen)

SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "assets")


def paint(size: int) -> QImage:
    img = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = float(size)

    # Tile: rounded square, a top-to-bottom blue gradient.
    m = s * 0.04
    tile = QRectF(m, m, s - 2 * m, s - 2 * m)
    grad = QLinearGradient(tile.topLeft(), tile.bottomLeft())
    grad.setColorAt(0.0, QColor("#2f8fe6"))
    grad.setColorAt(1.0, QColor("#145aa8"))
    path = QPainterPath()
    path.addRoundedRect(tile, s * 0.22, s * 0.22)
    p.fillPath(path, grad)
    # A faint top highlight gives the tile some depth at large sizes.
    if size >= 48:
        hl = QLinearGradient(tile.topLeft(), tile.center())
        hl.setColorAt(0.0, QColor(255, 255, 255, 40))
        hl.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.fillPath(path, hl)

    # The "M": a square-shouldered signal trace.
    w = max(1.6, s * 0.095)
    pen = QPen(QColor("#ffffff"), w)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    x0, x1 = s * 0.26, s * 0.74
    top, bottom, mid = s * 0.30, s * 0.70, s * 0.56
    trace = QPainterPath(QPointF(x0, bottom))
    trace.lineTo(x0, top)
    trace.lineTo(s * 0.50, mid)
    trace.lineTo(x1, top)
    trace.lineTo(x1, bottom)
    p.drawPath(trace)

    # The live data point at the end of the trace (dropped where it would
    # only be a smudge).
    if size >= 32:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#7fe3a0"))
        r = s * 0.065
        p.drawEllipse(QPointF(x1, bottom), r, r)
    p.end()
    return img


def png_bytes(img: QImage) -> bytes:
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    buf.close()
    return bytes(ba)


def write_ico(path: str, images: list) -> None:
    """ICO with PNG-compressed entries (supported since Windows Vista)."""
    blobs = [png_bytes(im) for im in images]
    header = struct.pack("<HHH", 0, 1, len(blobs))
    offset = 6 + 16 * len(blobs)
    entries = b""
    for im, blob in zip(images, blobs):
        dim = im.width()
        entries += struct.pack("<BBBBHHII", dim % 256, dim % 256, 0, 0, 1, 32,
                               len(blob), offset)
        offset += len(blob)
    with open(path, "wb") as f:
        f.write(header + entries + b"".join(blobs))


def main():
    _app = QGuiApplication.instance() or QGuiApplication(sys.argv)  # keep alive
    os.makedirs(OUT, exist_ok=True)
    images = [paint(n) for n in SIZES]
    images[-1].save(os.path.join(OUT, "app.png"), "PNG")
    write_ico(os.path.join(OUT, "app.ico"), images)
    print("written:", os.path.join(OUT, "app.png"), os.path.join(OUT, "app.ico"))


if __name__ == "__main__":
    main()
