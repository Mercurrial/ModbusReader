# tools/ui_snapshots.py
"""Render every screen and secondary surface headless, for design review.

    python tools/ui_snapshots.py OUT_DIR [--theme Dark|Light] [--lang ru|en]
                                 [--settings path/to/app_settings.json]
                                 [--only main,detail,trend]

Writes PNGs of: every page (with a map loaded and values), the empty map,
the collapsed rail, the connected state; menus (project, table context,
layout), message / input cards, the line-stats popup, the watch window, the
dashboard widget dialog, scaling, memory viewer, every settings page, the
import dialog, the empty editor, the guide; the trends panel in its states.

Menus and dialogs are made non-blocking (QMenu.exec → popup, QDialog.exec →
show) so they can be photographed. Overlays are closed with _close_overlay()
— reject() can raise a modal "save changes?" that hangs an offscreen run.
Pass --settings dist/app_settings.json to review in the user's own theme.
Set QT_QPA_FONTDIR=C:/Windows/Fonts, or text renders as boxes.
"""
import argparse
import json
import math
import os
import random
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

APPEARANCE = ("theme", "accent", "scheme", "contrast", "font_family",
              "font_size", "font_choice", "row_height", "zebra_rows")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--theme", default="Dark")
    ap.add_argument("--lang", default="ru")
    ap.add_argument("--settings", default="")
    ap.add_argument("--only", default="main,detail,trend")
    args = ap.parse_args()
    out = os.path.abspath(args.out)
    os.makedirs(out, exist_ok=True)
    os.chdir(ROOT)

    from PyQt6.QtWidgets import QApplication, QMenu, QDialog, QComboBox
    from PyQt6.QtCore import QPoint
    app = QApplication(sys.argv)

    import settings_manager
    settings_manager.SETTINGS_FILE = os.path.join(tempfile.mkdtemp(), "app_settings.json")
    s = dict(settings_manager.DEFAULT_SETTINGS)
    s.update({"theme": args.theme, "lang": args.lang, "guide_seen_main": True,
              "guide_seen_macros": True, "load_last": False})
    if args.settings:
        user = json.load(open(args.settings, encoding="utf-8"))
        s.update({k: user[k] for k in APPEARANCE if k in user})
    json.dump(s, open(settings_manager.SETTINGS_FILE, "w", encoding="utf-8"))

    from styles import get_stylesheet
    from theme_manager import set_active
    import icons
    app.setWindowIcon(icons.app_icon())
    set_active(s["scheme"], s["contrast"], s["accent"])
    app.setStyleSheet(get_stylesheet(s["theme"], s["font_family"], s["font_size"], s["accent"]))

    shown = []

    def _menu_exec(self, *a):
        self.popup(a[0] if a and isinstance(a[0], QPoint) else QPoint(300, 200))
        shown.append(self)
    QMenu.exec = _menu_exec

    def _dlg_exec(self):
        self.show()
        shown.append(self)
        return 0
    QDialog.exec = _dlg_exec

    def pump(n=3):
        # Spin for a moment, not just n passes: zero-delay timers (column
        # re-fits after the scrollbar appears) must fire before the photo.
        end = time.monotonic() + 0.12
        while time.monotonic() < end:
            app.processEvents()
        for _ in range(n):
            app.processEvents()

    def grab(widget, name):
        pump()
        widget.grab().save(os.path.join(out, name))

    only = set(args.only.split(","))
    import gui_main
    import datatypes as dt
    w = gui_main.ModernScadaApp()
    w.resize(1440, 860)
    w.show()
    # A real device map when there is one (kept out of the repository),
    # else the demo project every checkout has.
    map_path = os.path.join(ROOT, "tld_auto.json")
    if os.path.exists(map_path):
        regs = json.load(open(map_path, encoding="utf-8"))
    else:
        import formats
        map_path = os.path.join(ROOT, "examples", "demo.mbproj")
        regs = formats.load_project(map_path)["profile"]["registers"]
    NUMERIC = ("SHORT", "LONG", "FLOAT", "UINT16", "UINT32")
    numeric = [r for r in regs if r["type"] in NUMERIC]

    def load_map():
        w._set_profile(regs, map_path)
        w.register_table.set_connected(True)
        random.seed(4)
        for r in regs[:30]:
            if r["type"] in NUMERIC:
                v = (round(random.uniform(15, 30), 2) if r["type"] == "FLOAT"
                     else random.randint(0, 600))
                w._on_data_updated(dt.reg_key(r), str(v))
    load_map()
    st = w.modbus_core.stats
    for _ in range(1340):
        st.record("ok", random.uniform(0.008, 0.02))
    for _ in range(4):
        st.record("timeout")
    st.record("crc")
    w._refresh_line_stats()
    core = w.modbus_core
    w._log("SYS", "Подключено: COM3, 115200 8N1")
    core._log_tx_read(0, 6, 3)
    core._log_rx_read([0, 1, 2, 3, 4, 5], 3)
    core._log_tx_write(0x10, 0x2A, 6)
    core._log_rx_write(0x10, 0x2A, 6)
    w._log("ERR", "Таймаут 0x0010")
    trend_reg = numeric[min(10, len(numeric) - 1)]
    trend_id = dt.reg_id(dt.reg_key(trend_reg))
    w._add_to_trend(trend_id, trend_reg["name"])
    card = w.trends_manager.active_trends.get(trend_id)
    if card is not None:
        now = time.time()
        for i in range(60):
            card._ts.append(now - 30 + i * 0.5)
            card._vs.append(21 + 1.5 * math.sin(i / 7))
        card._last_rx = time.monotonic()
        card._apply_state("live")
        card._dirty = True
        card._render_if_dirty()

    if "main" in only:
        grab(w, "01_table.png")
        for i, v in enumerate(["view_console", "view_scanner", "view_sniffer",
                               "view_dash", "view_snapshot", "view_logger",
                               "view_slave", "view_macros"], 2):
            w._switch_view(v)
            grab(w, f"{i:02d}_{v}.png")
        w._switch_view("view_table")
        w._open_settings()
        grab(w, "10_settings.png")
        w._close_overlay()
        w._open_editor(True)
        grab(w, "11_editor.png")
        w._close_overlay()
        w._set_profile([], "")
        grab(w, "13_nomap.png")
        load_map()
        w.nav_rail.set_collapsed(True)
        grab(w, "14_collapsed.png")
        w.nav_rail.set_collapsed(False)
        w._on_connection_status(True, "")
        grab(w, "15_connected.png")
        w._on_connection_status(False, "")

    if "detail" in only:
        def last():
            pump()
            return shown[-1]
        w._switch_view("view_table")
        w._open_profile_menu()
        grab(last(), "d01_project_menu.png")
        last().close()
        from gui_table import COL_NAME
        rt = w.register_table
        rt._show_context_menu(rt.visualItemRect(rt.item(3, COL_NAME)).center())
        grab(last(), "d02_table_menu.png")
        last().close()
        w.main_toolbar._open_layout_menu()
        grab(last(), "d03_layout_menu.png")
        last().close()
        from dialogs import themed_message, themed_info, themed_input
        from PyQt6.QtWidgets import QMessageBox
        themed_message(w, s["theme"], "warning", "Несохранённые изменения",
                       "В карте есть изменения, которые не сохранены. Сохранить их перед выходом?",
                       [("Отмена", QMessageBox.ButtonRole.RejectRole, False),
                        ("Не сохранять", QMessageBox.ButtonRole.DestructiveRole, False),
                        ("Сохранить", QMessageBox.ButtonRole.AcceptRole, True)])
        grab(last(), "d04_message.png")
        last().close()
        themed_input(w, s["theme"], "Сохранить проект как", "Имя проекта", "plant")
        grab(last(), "d05_input.png")
        last().close()
        sb = w.status_bar
        sb._toggle_stats()
        grab(sb.stats_popup, "d06_stats.png")
        sb.stats_popup.hide()
        for r in numeric[-5:]:
            w.watch_window.add(dt.reg_key(r))
        for r in regs[:20]:
            if r["type"] in NUMERIC:
                w._on_data_updated(dt.reg_key(r), "21.5" if r["type"] == "FLOAT" else "42")
        ww = w.watch_window
        ww.show()
        ww.resize(480, 400)
        grab(ww, "d07_watch.png")
        ww.hide()
        w._switch_view("view_dash")
        w.dash_view._add_widget()
        grab(last(), "d08_dash_dialog.png")
        last().close()
        from gui_scaling_dialog import ScalingDialog
        d = ScalingDialog(regs[3], s["theme"], w.t, w)
        d.show()
        grab(d, "d09_scaling.png")
        d.close()
        from memory_viewer import MemoryViewerDialog
        mv = MemoryViewerDialog(0x20, 16, "Буфер", ctx=w.ctx)
        mv.set_real_data(list(range(16)))
        mv.show()
        mv.resize(900, 600)
        grab(mv, "d10_memory.png")
        mv.close()
        w._switch_view("view_table")
        w._open_settings()
        dlg = w._overlay_page
        for i in range(dlg.nav.count()):
            dlg.nav.setCurrentRow(i)
            grab(w, f"d11_settings_{i}.png")
        w._close_overlay()
        csv_path = os.path.join(tempfile.mkdtemp(), "map.csv")
        open(csv_path, "w", encoding="utf-8").write("\n".join([
            "Адрес;Имя;Тип;Доступ;Ед.", "40001;Температура;FLOAT;R;°C",
            "40003;Уставка;SHORT;RW;°C", "40004;Режим;UINT16;RW;"]) + "\n")
        from gui_import_dialog import ImportMapDialog
        imp = ImportMapDialog(w.ctx, csv_path, w)
        imp.show()
        imp.resize(980, 640)
        grab(imp, "d13_import.png")
        imp.close()
        w._open_editor(False)
        grab(w, "d14_editor_empty.png")
        w._close_overlay()
        w._open_settings()
        dlg = w._overlay_page
        combos = [c for c in dlg.findChildren(QComboBox) if c.isVisible()]
        if combos:
            combos[0].showPopup()
            pump()
            grab(combos[0].view().window(), "d15_combo_popup.png")
            combos[0].hidePopup()
        w._close_overlay()
        import gui_update
        import updater
        rel = updater.Release(
            "2.4.0", "• Чтение блоками: вся карта одним запросом\n"
                     "• Тревоги по порогам прямо в таблице\n"
                     "• Исправлено: Esc в редакторе после Alt+Tab",
            "https://github.com/", "ModbusReader.exe",
            "https://github.com/x/ModbusReader.exe", 59_000_000, "a" * 64)
        ud = gui_update.UpdateDialog(w.ctx, rel, "portable", w)
        ud.show()
        grab(ud, "d17_update.png")
        gui_update._DownloadThread.start = lambda self: None   # no network
        ud._start_download()
        ud._on_progress(23_400_000, 59_000_000)
        grab(ud, "d18_update_progress.png")
        ud._dl = None
        ud.close()
        w.nav_rail.set_busy({"view_logger": True, "view_macros": True})
        grab(w, "d16_busy.png")
        w.nav_rail.set_busy({})
        w._show_help()
        pump()
        g = w._guide
        grab(w, "d12_guide_0.png")
        if g is not None and hasattr(g, "_next"):
            g._next()
            grab(w, "d12_guide_1.png")
            g.close()

    if "trend" in only:
        from gui_trends import TrendsManager
        tm = TrendsManager(w.ctx)
        tm.resize(420, 880)
        tm.show()
        tm.add_trend("0x0014", "Температура датчик 1", "°C")
        tm.add_trend("0x000C", "Значение теневого тока канал 1 (длинное имя регистра)", "")
        tm.add_trend("0x0006", "Длительность измерения", "с")
        now = time.time()
        c1, c2 = tm.active_trends["0x0014"], tm.active_trends["0x000C"]
        for i in range(60):
            t = now - 30 + i * 0.5
            c1._ts.append(t)
            c1._vs.append(21.0 + 1.6 * math.sin(i / 7.0) + 0.15 * math.sin(i * 1.7))
            c2._ts.append(t)
            c2._vs.append(380 + (i * 3 if i < 40 else 120 - (i - 40) * 2) + (i % 5))
        c1._last_rx = time.monotonic()
        c1._apply_state("live")
        c2._last_rx = time.monotonic() - 12
        c2._refresh_state()
        for c in (c1, c2):
            c._dirty = True
            c._render_if_dirty()
        grab(tm, "t01_trends.png")

    w._overlay_page = None
    print("done:", out)


if __name__ == "__main__":
    main()
