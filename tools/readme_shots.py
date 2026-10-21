# tools/readme_shots.py
"""The pictures in README.md — rendered from the DEMO project, never from a
private device map.

    python tools/readme_shots.py [--out docs/images]
    python tools/readme_shots.py --lang en          # → docs/images/en

A small simulated "device" (temperature drifting around the setpoint, a
heater, a fan, supply voltage …) feeds every screen through the same
handlers the real Modbus link uses, so the pictures show the real UI in a
believable state: the map with live values and trends, the dashboard, the
console, scanner, sniffer, logger, macros, the slave emulator, snapshots,
the editor, the watch window, the update dialog and four colour themes.
The live trend is also written as an animated PNG (APNG — GitHub plays it).
``--lang en`` renders the same set with the English UI for the English pages
of the project site; social.png (the link preview, 2:1) is cut from the hero.

Rendered at 2× (QT_SCALE_FACTOR) so the images stay sharp on HiDPI
screens; corners are rounded with a hairline border, outside transparent.
"""
import argparse
import math
import os
import random
import struct
import sys
import tempfile
import time
import zlib

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", "C:/Windows/Fonts")
os.environ["QT_SCALE_FACTOR"] = "2"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
DEMO = os.path.join(ROOT, "examples", "demo.mbproj")

# The look of the pictures — fixed here, so a re-render never depends on the
# settings of whoever runs the tool.
LOOK = {"theme": "Dark", "scheme": "slate", "contrast": "high",
        "accent": "rose", "font_family": "Inter, Segoe UI, system-ui, sans-serif",
        "font_size": 9, "font_choice": "inter", "row_height": 26,
        "zebra_rows": True}
WIN_W, WIN_H = 1440, 860


# ── the simulated device ───────────────────────────────────────────
def device(t: float) -> dict:
    """Raw register values at time *t* (seconds), keyed by register name."""
    temp = 24.6 + 1.3 * math.sin(2 * math.pi * t / 15.0) + 0.12 * math.sin(t * 1.9)
    return {
        "Температура": round(temp, 2),
        "Уставка температуры": 25.0,
        "Режим": 1,
        "Мощность нагревателя": int(10 * (46 + 14 * math.sin(2 * math.pi * t / 15.0 + 2.2))),
        "Наработка": 1834,
        "Слово состояния": 0b0000_0000_0010_0101,
        "Код ошибки": 0,
        "Задержка аварии": 30,
        "Напряжение питания": int(2412 + 6 * math.sin(t / 3.0)),
        "Ток датчика": int(round(12 + 2.5 * math.sin(2 * math.pi * t / 15.0))),
        "Нагреватель": 1,
        "Вентилятор": 0,
        "Дверь открыта": 0,
    }


def feed(w, regs, t: float):
    from core import datatypes as dt
    vals = device(t)
    for r in regs:
        if r["name"] in vals:
            raw = vals[r["name"]]
            w._on_data_updated(dt.reg_key(r), dt.read_to_str(r["type"], dt.encode(r["type"], raw)))


# ── image helpers ──────────────────────────────────────────────────
def finish(img, radius=14):
    """Rounded corners + hairline border, transparent outside."""
    from PyQt6.QtCore import QRectF, Qt
    from PyQt6.QtGui import QImage, QPainter, QPainterPath, QPen, QColor
    dpr = img.devicePixelRatio() or 1.0
    out = QImage(img.size(), QImage.Format.Format_ARGB32_Premultiplied)
    out.setDevicePixelRatio(dpr)
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    w, h = img.width() / dpr, img.height() / dpr
    path = QPainterPath()
    path.addRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), radius, radius)
    p.setClipPath(path)
    p.drawImage(0, 0, img)
    p.setClipping(False)
    p.setPen(QPen(QColor(255, 255, 255, 38), 1))
    p.drawPath(path)
    p.end()
    return out


def crop(img, x, y, w, h):
    """Crop in LOGICAL pixels (the image is 2×)."""
    from PyQt6.QtCore import QRect
    d = img.devicePixelRatio() or 1.0
    c = img.copy(QRect(int(x * d), int(y * d), int(w * d), int(h * d)))
    c.setDevicePixelRatio(d)
    return c


def png_bytes(img) -> bytes:
    from PyQt6.QtCore import QBuffer, QIODevice
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return bytes(buf.data())


def _chunks(data: bytes):
    pos = 8
    while pos < len(data):
        n = struct.unpack(">I", data[pos:pos + 4])[0]
        yield data[pos + 4:pos + 8], data[pos + 8:pos + 8 + n]
        pos += 12 + n


def _chunk(kind: bytes, body: bytes) -> bytes:
    return (struct.pack(">I", len(body)) + kind + body
            + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF))


def write_apng(path: str, frames: list, delay_ms: int):
    """Animated PNG from same-sized QImages (full frames, endless loop).
    Pillow is not a dependency, and APNG is just PNG chunks re-ordered."""
    pngs = [png_bytes(f) for f in frames]
    first = list(_chunks(pngs[0]))
    ihdr = dict(first)[b"IHDR"]
    w, h = struct.unpack(">II", ihdr[:8])
    out = b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr)
    for kind, body in first:                       # sRGB, pHYs … once
        if kind not in (b"IHDR", b"IDAT", b"IEND"):
            out += _chunk(kind, body)
    out += _chunk(b"acTL", struct.pack(">II", len(pngs), 0))
    seq = 0
    for i, data in enumerate(pngs):
        out += _chunk(b"fcTL", struct.pack(">IIIIIHHBB", seq, w, h, 0, 0,
                                           delay_ms, 1000, 0, 0))
        seq += 1
        for kind, body in _chunks(data):
            if kind != b"IDAT":
                continue
            if i == 0:
                out += _chunk(b"IDAT", body)
            else:
                out += _chunk(b"fdAT", struct.pack(">I", seq) + body)
                seq += 1
    out += _chunk(b"IEND", b"")
    open(path, "wb").write(out)


# The words drawn into the pictures, per UI language.
TEXT = {
    "ru": {"tagline": "Наладка и мониторинг приборов\nпо Modbus RTU — мастер и эмулятор",
           "tools": "Карта регистров · графики · дашборд · сканер · сниффер · макросы",
           "pill": "Бесплатно  ·  открытый код  ·  Windows",
           "log_project": "Проект: Демо-термоконтроллер (13 регистров)",
           "log_connected": "Подключено: COM3, 115200 8N1, ID 1",
           "log_timeout": "Таймаут: DI 0x0000 — нет ответа за 1000 мс",
           "log_path": r"D:\Логи\линия-3_2026-10-16.csv",
           "macro_cols": ("Температура", "Мощность нагревателя", "Ток датчика"),
           "macro_log": "цикл {i} готов",
           "notes": "• Чтение блоками: вся карта одним запросом\n"
                    "• Тревоги по порогам прямо в таблице\n"
                    "• Исправлено: Esc в редакторе после Alt+Tab"},
    "en": {"tagline": "Commissioning and monitoring\nof Modbus RTU devices — master and slave",
           "tools": "Register map · trends · dashboard · scanner · sniffer · macros",
           "pill": "Free  ·  open source  ·  Windows",
           "log_project": "Project: Demo temperature controller (13 registers)",
           "log_connected": "Connected: COM3, 115200 8N1, ID 1",
           "log_timeout": "Timeout: DI 0x0000 — no answer within 1000 ms",
           "log_path": r"D:\Logs\line-3_2026-10-16.csv",
           "macro_cols": ("Temperature", "Heater power", "Sensor current"),
           "macro_log": "cycle {i} done",
           "notes": "• Block reads: the whole map in one request\n"
                    "• Threshold alarms right in the table\n"
                    "• Fixed: Esc in the editor after Alt+Tab"},
}


# The English pictures show the English demo (what the English UI opens):
# same registers, English units, enum labels and widget titles. Register
# "name" is Russian in both files — device() and the lookups below key on it.
DEMO_EN = os.path.join(ROOT, "examples", "demo_en.mbproj")


def social(hero_img):
    """The link preview (Open Graph, 1280×640): the hero's left part — the
    mark, the name and the tagline — scaled to the 2:1 frame."""
    from PyQt6.QtCore import Qt
    h = hero_img.height()
    part = hero_img.copy(0, 0, h * 2, h)
    part.setDevicePixelRatio(1)
    return part.scaled(1280, 640, Qt.AspectRatioMode.IgnoreAspectRatio,
                       Qt.TransformationMode.SmoothTransformation)


def hero(window_img, text=TEXT["ru"]):
    """The banner at the top of the README: the mark, the name, what it is —
    and the real window beside it (bleeding off the right edge)."""
    from PyQt6.QtCore import QRectF, Qt
    from PyQt6.QtGui import (QImage, QPainter, QPainterPath, QPen, QColor,
                             QFont, QFontMetrics, QLinearGradient, QBrush)
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    from make_icon import paint as paint_icon
    W, H, d = 1280, 430, 2
    img = QImage(W * d, H * d, QImage.Format.Format_ARGB32_Premultiplied)
    img.setDevicePixelRatio(d)
    p = QPainter(img)
    for hint in (QPainter.RenderHint.Antialiasing, QPainter.RenderHint.TextAntialiasing,
                 QPainter.RenderHint.SmoothPixmapTransform):
        p.setRenderHint(hint)
    g = QLinearGradient(0, 0, W, H)
    g.setColorAt(0, QColor("#11151a"))
    g.setColorAt(1, QColor("#181d24"))
    p.fillRect(QRectF(0, 0, W, H), QBrush(g))
    p.setPen(QPen(QColor(255, 255, 255, 9), 1))
    for x in range(0, W, 40):
        p.drawLine(x, 0, x, H)
    for y in range(0, H, 40):
        p.drawLine(0, y, W, y)

    def font(px, bold=False):
        f = QFont("Segoe UI", 1)
        f.setPixelSize(px)
        if bold:
            f.setWeight(QFont.Weight.Bold)
        return f
    left = 60
    p.drawImage(QRectF(left, 104, 84, 84), paint_icon(168))
    p.setFont(font(54, bold=True))
    p.setPen(QColor("#f3f5f7"))
    p.drawText(QRectF(left + 104, 100, 520, 90),
               Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "ModbusReader")
    p.setFont(font(22))
    p.setPen(QColor("#b9c0c9"))
    p.drawText(QRectF(left, 212, 520, 70), Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWordWrap,
               text["tagline"])
    p.setFont(font(15))
    p.setPen(QColor("#8b939d"))
    p.drawText(QRectF(left, 290, 540, 24), Qt.AlignmentFlag.AlignLeft,
               text["tools"])
    label = text["pill"]
    pf = font(15, bold=True)
    pw = QFontMetrics(pf).horizontalAdvance(label) + 40
    pill = QRectF(left, 334, pw, 36)
    p.setPen(QPen(QColor("#38414c"), 1))
    p.setBrush(QColor(24, 29, 36))
    p.drawRoundedRect(pill, 18, 18)
    p.setFont(pf)
    p.setPen(QColor("#d6dce3"))
    p.drawText(pill, Qt.AlignmentFlag.AlignCenter, label)

    # the window, as a floating card cut by the right edge
    win_w = 700
    win_h = win_w * window_img.height() / window_img.width()
    rect = QRectF(W - win_w + 70, (H - win_h) / 2, win_w, win_h)
    for i in range(18, 0, -3):
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 16))
        p.drawRoundedRect(rect.adjusted(-i, -i + 10, i, i + 10), 12 + i, 12 + i)
    path = QPainterPath()
    path.addRoundedRect(rect, 12, 12)
    p.save()
    p.setClipPath(path)
    p.drawImage(rect, window_img)
    p.restore()
    p.setPen(QPen(QColor("#3a434e"), 1))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(path)
    p.end()
    return img


# ── the run ────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None)
    ap.add_argument("--lang", choices=tuple(TEXT), default="ru")
    args = ap.parse_args()
    lang = args.lang
    text = TEXT[lang]
    out = os.path.abspath(args.out or os.path.join(
        ROOT, "docs", "images", *(() if lang == "ru" else (lang,))))
    os.makedirs(out, exist_ok=True)
    os.chdir(ROOT)

    from PyQt6.QtWidgets import QApplication, QMenu, QDialog
    from PyQt6.QtCore import QPoint
    app = QApplication(sys.argv)

    import json
    from app import settings_manager
    settings_manager.SETTINGS_FILE = os.path.join(tempfile.mkdtemp(), "app_settings.json")
    s = dict(settings_manager.DEFAULT_SETTINGS)
    s.update(LOOK)
    s.update({"lang": lang, "load_last": False, "highlight_changes": False,
              "guide_seen_main": True, "guide_seen_macros": True,
              "guide_seen_editor": True, "update_auto": False})
    json.dump(s, open(settings_manager.SETTINGS_FILE, "w", encoding="utf-8"))

    from gui.styles import get_stylesheet
    from gui.theme_manager import set_active
    from gui import icons
    app.setWindowIcon(icons.app_icon())
    set_active(s["scheme"], s["contrast"], s["accent"])
    app.setStyleSheet(get_stylesheet(s["theme"], s["font_family"], s["font_size"], s["accent"]))

    QMenu.exec = lambda self, *a: self.popup(a[0] if a and isinstance(a[0], QPoint) else QPoint(300, 200))
    QDialog.exec = lambda self: (self.show(), 0)[1]

    def pump(sec=0.15):
        end = time.monotonic() + sec
        while time.monotonic() < end:
            app.processEvents()

    def save(img, name, rounded=True):
        (finish(img) if rounded else img).save(os.path.join(out, name))
        print(f"  {name:24} {os.path.getsize(os.path.join(out, name)) / 1024:7.0f} KB")

    from gui import main_window as gui_main
    from core import datatypes as dt
    from core import formats
    w = gui_main.ModernScadaApp()
    w.resize(WIN_W, WIN_H)
    w.show()
    pump()
    demo = DEMO if lang == "ru" else DEMO_EN
    w._open_project(demo)
    pump()
    regs = formats.load_project(demo)["profile"]["registers"]
    w._on_connection_status(True, "")
    w.register_table.set_connected(True)

    # 30 s of history for the history-keeping widgets (dashboard chart):
    # two calm periods, not a saw-tooth of six.
    for i in range(60):
        feed(w, regs, i * 0.5 - 30)
    pump()

    # Line statistics and a believable exchange log.
    random.seed(7)
    st = w.modbus_core.stats
    for _ in range(4180):
        st.record("ok", random.uniform(0.009, 0.019))
    for _ in range(3):
        st.record("timeout")
    w._refresh_line_stats()
    core = w.modbus_core
    core.slave_id = 1
    # Start the log clean: opening the project logged its full LOCAL path
    # (a user name in a public picture).
    w.log_panel.store.clear()
    w._log("SYS", text["log_project"])
    w._log("SYS", text["log_connected"])
    holding = [0x41C4, 0xCCCD, 0x41C8, 0x0000, 1, 573, 0, 1834, 0x25, 0, 30]
    for cycle in range(5):
        core._log_tx_read(0, 11, 0x03)
        core._log_rx_read(holding, 0x03)
        core._log_tx_read(0, 2, 0x04)
        core._log_rx_read([2412, 12 + cycle % 3], 0x04)
        core._log_tx_read(0, 2, 0x01)
        core._log_rx_read([1, 0], 0x01)
        if cycle == 2:
            core._log_tx_write(0x000A, 45, 0x06)
            core._log_rx_write(0x000A, 45, 0x06)
        if cycle == 3:
            core._log_tx_read(0, 1, 0x02)
            w._log("ERR", text["log_timeout"])

    # Two live trend cards with a clean 60 s history.
    def trend(reg_name, base_fn):
        r = next(r for r in regs if r["name"] == reg_name)
        rid = dt.reg_id(dt.reg_key(r))
        if rid not in w.trends_manager.active_trends:
            w._add_to_trend(rid, r["name"] if lang == "ru" else r.get("name_en", r["name"]))
        card = w.trends_manager.active_trends.get(rid)
        now = time.time()
        card._ts.clear()
        card._vs.clear()
        for i in range(120):
            t = i * 0.5 - 60
            card._ts.append(now + t)
            card._vs.append(base_fn(t))
        card._last_rx = time.monotonic()
        card._apply_state("live")
        card._dirty = True
        card._render_if_dirty()
        return card
    def reset_trends():
        """Every feed() also lands in the trend cards (at the REAL time) —
        rebuild their clean 60 s history before a picture shows them."""
        card = trend("Температура", lambda t: device(t)["Температура"])
        trend("Ток датчика", lambda t: 12 + 2.5 * math.sin(2 * math.pi * t / 15.0))
        return card
    feed(w, regs, 0)
    t_card = reset_trends()
    pump(0.3)

    print("README images →", out)
    PAGE = (212, 53, WIN_W - 212, WIN_H - 53 - 28)   # right of the rail, above the status bar

    # 1. the main window
    w._switch_view("view_table")
    reset_trends()
    pump()
    main_img = w.grab().toImage()
    save(main_img, "main.png")
    hero_img = hero(main_img, text)
    save(hero_img, "hero.png")
    save(social(hero_img), "social.png", rounded=False)

    # 2. dashboard
    w._switch_view("view_dash")
    pump(0.3)
    save(crop(w.grab().toImage(), 212, 53, WIN_W - 212, 600), "dashboard.png")

    # 3. console
    w._switch_view("view_console")
    pump()
    save(crop(w.grab().toImage(), *PAGE), "console.png")

    # 4. scanner with a finished bus scan
    w._switch_view("view_scanner")
    sv = w.scanner_view
    for sid, ms in ((1, 11), (3, 12), (10, 14), (17, 13)):
        sv._on_found({"mode": "devices", "id": sid, "state": "alive", "ms": ms})
    sv._on_found({"mode": "devices", "id": 24, "state": "exception", "ms": 15})
    sv._on_finished(5, 32, 6.4)
    pump()
    save(crop(w.grab().toImage(), 212, 53, WIN_W - 212, 330), "scanner.png")

    # 5. sniffer: real frames, decoded by the real decoder
    from core import sniffer_core
    from core.slave_core import with_crc
    w._switch_view("view_sniffer")
    nv = w.sniffer_view
    words = [0x41C4, 0xCCCD, 0x41C8, 0x0000, 1, 573, 0, 1834, 0x25, 0, 30]
    frames = [
        bytes([1, 3, 0, 0, 0, 11]),
        bytes([1, 3, 22]) + b"".join(struct.pack(">H", v) for v in words),
        bytes([1, 6, 0, 0x0A, 0, 45]),
        bytes([1, 6, 0, 0x0A, 0, 45]),
        bytes([1, 4, 0, 0, 0, 2]),
        bytes([1, 4, 4, 0x09, 0x6C, 0x00, 0x0C]),
        bytes([3, 1, 0, 0, 0, 2]),
        bytes([3, 1, 1, 0x01]),
        bytes([10, 3, 0, 0x40, 0, 4]),
        bytes([10, 0x83, 0x02]),
    ]
    for body in frames:
        nv._on_frame(sniffer_core.decode_frame(with_crc(body)))
    bad = bytearray(with_crc(bytes([1, 3, 0, 0, 0, 11])))
    bad[-1] ^= 0x5A
    nv._on_frame(sniffer_core.decode_frame(bytes(bad)))
    pump()
    save(crop(w.grab().toImage(), 212, 53, WIN_W - 212, 420), "sniffer.png")

    # 6. logger, recording
    w._switch_view("view_logger")
    lv = w.logger_view
    lv.ed_path.setText(os.path.join(tempfile.mkdtemp(), "plant_2026-10-16.csv"))
    lv._confirm_target = lambda p: p
    lv.start()
    for i in range(1, 8):
        feed(w, regs, i * 1.0)
        lv._tick()
    # On screen: a neutral path (the real one is a temp dir with the user
    # name in it) and one row per second, as a 1000 ms period gives.
    lv.ed_path.setText(text["log_path"])
    rows = lv.table.rowCount()
    for r in range(rows):
        it = lv.table.item(r, 0)
        if it is not None:
            it.setText(f"12:00:{rows - 1 - r:02d}")
    pump()
    save(crop(w.grab().toImage(), 212, 53, WIN_W - 212, 430), "logger.png")
    lv.stop()

    # 7. macros with a result table
    w._switch_view("view_macros")
    mv = w.macro_view
    for i in range(8):
        v = device(i * 1.0)
        c_temp, c_power, c_current = text["macro_cols"]
        mv._on_row({"#": i, "time": f"12:00:{i:02d}", c_temp: v["Температура"],
                    c_power: v["Мощность нагревателя"] / 10,
                    c_current: v["Ток датчика"]})
    for i in range(3):
        mv._on_log("INFO", text["macro_log"].format(i=i))
    pump()
    save(crop(w.grab().toImage(), *PAGE), "macros.png")

    # 8. slave emulator, serving a master
    from core import slave_core
    w._switch_view("view_slave")
    slv = w.slave_view
    pump()
    vals = device(0)
    for r in slv.store.registers:                  # the emulated device's RAW words
        if r["name"] in vals:
            slv.store.set_value(r, str(vals[r["name"]]))
    slv._render_table()
    slv.spin_sid.setValue(1)
    slv._set_controls(True)
    lo, hi = slv.store.span()
    slv.lbl_info.setText(w.ctx.t("slvServing").format(
        sid=1, port=slv.combo_port.currentText() or "COM4", baud=115200,
        framing="8N1", n=len(slv.store.registers),
        lo=dt.key_label(lo), hi=dt.key_label(hi)))
    for req in (bytes([1, 3, 0, 0, 0, 11]), bytes([1, 6, 0, 0x0A, 0, 45]),
                bytes([1, 1, 0, 0, 0, 2]), bytes([1, 4, 0, 0, 0, 2]),
                bytes([1, 3, 0, 0, 0, 11])):
        frame = with_crc(req)
        info = slave_core.build_response(frame, slv.store, 1)
        info["request"] = frame
        info["time"] = time.time()
        slv._on_exchange(info)
    pump()
    save(crop(w.grab().toImage(), 212, 53, WIN_W - 212, 560), "slave.png")
    slv._set_controls(False)

    # 9. snapshots: before / after a setpoint change
    w._switch_view("view_snapshot")
    snv = w.snapshot_view
    snv.take_snapshot()
    vals = device(0)
    for name, raw in (("Уставка температуры", 28.0), ("Режим", 2),
                      ("Код ошибки", 3), ("Вентилятор", 1)):
        r = next(r for r in regs if r["name"] == name)
        w._on_data_updated(dt.reg_key(r), dt.read_to_str(r["type"], dt.encode(r["type"], raw)))
    snv.compare_now()
    pump()
    save(crop(w.grab().toImage(), 212, 53, WIN_W - 212, 520), "snapshots.png")
    feed(w, regs, 0)

    # 10. the map editor
    w._switch_view("view_table")
    w._open_editor(True)
    pump(0.3)
    save(crop(w.grab().toImage(), 212, 53, WIN_W - 212, 520), "editor.png")
    w._close_overlay()
    pump()

    # 11. the watch window (its own chrome; transparent around the card)
    ww = w.watch_window
    for name in ("Температура", "Уставка температуры", "Мощность нагревателя",
                 "Ток датчика", "Режим"):
        r = next(r for r in regs if r["name"] == name)
        ww.add(dt.reg_key(r))
    feed(w, regs, 0.5)
    ww.show()
    ww.resize(460, 430)
    pump(0.3)
    save(ww.grab().toImage(), "watch.png", rounded=False)
    ww.hide()

    # 12. the update dialog
    from gui import update as gui_update
    from core import updater
    rel = updater.Release(
        "26.11.0", text["notes"],
        "https://github.com/", "ModbusReader-Setup.exe",
        "https://github.com/x/ModbusReader-Setup.exe", 43_000_000, "a" * 64)
    ud = gui_update.UpdateDialog(w.ctx, rel, "installed", w)
    ud.show()
    pump(0.3)
    save(ud.grab().toImage(), "update.png", rounded=False)
    ud.close()

    # 13. the live trend, animated (one 15 s period → a seamless loop)
    frames = []
    t_card = reset_trends()
    now = t_card._ts[-1]
    for i in range(30):
        t = 0.5 * (i + 1)
        t_card._ts.append(now + t)
        t_card._vs.append(device(t)["Температура"])
        t_card._last_rx = time.monotonic()
        t_card._dirty = True
        t_card._render_if_dirty()
        pump(0.02)
        frames.append(finish(t_card.grab().toImage(), radius=12))
    path = os.path.join(out, "trend.png")
    write_apng(path, frames, 160)
    print(f"  {'trend.png (animated)':24} {os.path.getsize(path) / 1024:7.0f} KB")

    # 14. four looks of the same window
    from PyQt6.QtGui import QImage, QPainter
    from PyQt6.QtCore import Qt
    looks = [{"theme": "Dark", "scheme": "slate", "accent": "rose", "contrast": "high"},
             {"theme": "Light", "scheme": "paper", "accent": "blue", "contrast": "normal"},
             {"theme": "Dark", "scheme": "midnight", "accent": "emerald", "contrast": "normal"},
             {"theme": "Light", "scheme": "sand", "accent": "amber", "contrast": "normal"}]
    tiles = []
    feed(w, regs, 0)
    for lk in looks:
        # The path Settings → Save takes: rail and header icons follow too.
        prev_style = {k: w.settings.get(k) for k in w._STYLE_KEYS}
        w._finish_settings_apply(dict(lk), w.lang, prev_style)
        reset_trends()
        pump(0.4)
        tiles.append(w.grab().toImage())
    d = tiles[0].devicePixelRatio()
    tw, th = int(WIN_W * d / 2), int(WIN_H * d / 2)
    gap = int(16 * d)
    sheet = QImage(tw * 2 + gap, th * 2 + gap, QImage.Format.Format_ARGB32_Premultiplied)
    sheet.fill(Qt.GlobalColor.transparent)
    p = QPainter(sheet)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    for i, tile in enumerate(tiles):
        small = tile.scaled(tw, th, Qt.AspectRatioMode.IgnoreAspectRatio,
                            Qt.TransformationMode.SmoothTransformation)
        small.setDevicePixelRatio(1)
        p.drawImage((i % 2) * (tw + gap), (i // 2) * (th + gap), finish(small, 18))
    p.end()
    save(sheet, "themes.png", rounded=False)

    w._closing_for_update = True
    w.close()
    print("done")


if __name__ == "__main__":
    main()
