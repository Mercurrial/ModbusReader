# gui/macros.py
"""Macro window — write & run real-Python automation scripts against the device.

Layout:  toolbar (Run/Stop/Clear/Export/Save/Open)  ·  code editor with line
numbers  ·  live results table  ·  log pane  ·  status bar.

The script is executed by macro_engine.MacroRunner in a worker thread; results
arrive here via signals and accumulate in the table for CSV / XLSX export.
"""

import csv

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QPlainTextEdit,
    QTableWidget, QTableWidgetItem, QSplitter, QFrame, QFileDialog,
    QMessageBox, QAbstractItemView, QDialog, QTextBrowser, QHeaderView,
)
from PyQt6.QtCore import Qt, QSize, QRect, pyqtSignal
from PyQt6.QtGui import QFont, QColor, QPainter, QTextOption

from core.macro_engine import MacroRunner
from gui.dialogs import themed_message, themed_info
from gui import icons
from app.fonts import MONO_CSS, mono_family


DEFAULT_MACRO = """# Пример: час замеров раз в секунду (карта — examples/demo.mbproj).
# Доступно: reg/read/write/wait/record/read_all/log/now/timestamp.
# Регистры — по имени из карты или по адресу: write(0x0002, 25).

write("Уставка температуры", 25)        # задать уставку

for i in range(3600):
    wait(1)                              # подождать 1 секунду
    row = {"#": i, "time": timestamp()}
    row["Температура"] = read("Температура")
    row["Мощность"] = read("Мощность нагревателя")
    record(row)                          # строка в таблицу результатов
    if i % 60 == 59:
        log("минута", (i + 1) // 60, "готова")

log("Замеры завершены")
"""

# The same example for the English UI (a Russian sample under English menus
# was the first thing an English-speaking user saw on this page). Registers
# can be named in either language (macro_engine indexes name_en too).
DEFAULT_MACRO_EN = """# Example: an hour of readings, once a second (map: examples/demo_en.mbproj).
# Available: reg/read/write/wait/record/read_all/log/now/timestamp.
# Address registers by their map name or by address: write(0x0002, 25).

write("Temperature setpoint", 25)       # set the setpoint

for i in range(3600):
    wait(1)                              # wait one second
    row = {"#": i, "time": timestamp()}
    row["Temperature"] = read("Temperature")
    row["Power"] = read("Heater power")
    record(row)                          # a row in the results table
    if i % 60 == 59:
        log("minute", (i + 1) // 60, "done")

log("Readings finished")
"""


def _mono(size=10) -> QFont:
    f = QFont(mono_family())
    f.setPointSize(size)
    return f


# ════════════════════════════════════════════════════════════════════
#  CODE EDITOR with line numbers
# ════════════════════════════════════════════════════════════════════
class _LineGutter(QWidget):
    def __init__(self, editor):
        super().__init__(editor)
        self._editor = editor

    def sizeHint(self):
        return QSize(self._editor.gutter_width(), 0)

    def paintEvent(self, event):
        self._editor.paint_gutter(event)


class CodeEditor(QPlainTextEdit):
    """Minimal Python editor: monospace, line numbers, soft-tab insertion."""

    def __init__(self, colors: dict, parent=None):
        super().__init__(parent)
        self._c = colors
        self.setFont(_mono(10))
        self.setWordWrapMode(QTextOption.WrapMode.NoWrap)
        self.setTabStopDistance(4 * self.fontMetrics().horizontalAdvance(" "))
        self.gutter = _LineGutter(self)
        self.blockCountChanged.connect(lambda _: self._update_gutter_width())
        self.updateRequest.connect(self._update_gutter_area)
        self._update_gutter_width()

    def gutter_width(self) -> int:
        digits = max(3, len(str(max(1, self.blockCount()))))
        return 12 + self.fontMetrics().horizontalAdvance("9") * digits

    def _update_gutter_width(self):
        self.setViewportMargins(self.gutter_width(), 0, 0, 0)

    def _update_gutter_area(self, rect, dy):
        if dy:
            self.gutter.scroll(0, dy)
        else:
            self.gutter.update(0, rect.y(), self.gutter.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self._update_gutter_width()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        cr = self.contentsRect()
        self.gutter.setGeometry(QRect(cr.left(), cr.top(), self.gutter_width(), cr.height()))

    def paint_gutter(self, event):
        painter = QPainter(self.gutter)
        painter.fillRect(event.rect(), QColor(self._c["bg_1"]))
        block = self.firstVisibleBlock()
        num = block.blockNumber()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + round(self.blockBoundingRect(block).height())
        painter.setFont(_mono(9))
        painter.setPen(QColor(self._c["text_4"]))
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                painter.drawText(0, top, self.gutter.width() - 6,
                                 self.fontMetrics().height(),
                                 int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                                 str(num + 1))
            block = block.next()
            top = bottom
            bottom = top + round(self.blockBoundingRect(block).height())
            num += 1

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Tab:
            self.insertPlainText("    ")
            return
        super().keyPressEvent(event)


# ════════════════════════════════════════════════════════════════════
#  MACRO WINDOW
# ════════════════════════════════════════════════════════════════════
class MacroWindow(QWidget):
    """Macro editor + runner. Since 2.2 a PAGE of the main window (a rail
    entry like every other tool, ``embedded=True``); it can still be built as
    a stand-alone window."""

    def __init__(self, ctx, get_registers, parent=None, embedded: bool = False):
        if embedded:
            super().__init__(parent)
        else:
            super().__init__(parent, Qt.WindowType.Window)
        self.embedded = embedded
        self.ctx = ctx
        self.settings = ctx.settings
        self.core = ctx.core
        self.get_registers = get_registers
        self.lang = ctx.lang
        self.c = ctx.theme_tokens()

        self._runner: MacroRunner | None = None
        self._columns: list[str] = []
        self._records: list[dict] = []

        self.setWindowTitle(self.L("Макросы", "Macros"))
        self.resize(960, 720)
        self.setObjectName("macroWin")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._build_ui()
        self._apply_qss()

        last = self.settings.get("last_macro")
        self.editor.setPlainText(
            last if last else (DEFAULT_MACRO if self.lang == "ru" else DEFAULT_MACRO_EN))

    # ── bilingual helper ──────────────────────────────────────────
    def L(self, ru: str, en: str) -> str:
        return ru if self.lang == "ru" else en

    # ── build ─────────────────────────────────────────────────────
    def _tb_button(self, icon_name, text, callback, primary=False):
        b = QPushButton(f"  {text}")
        b.setObjectName("mPrimary" if primary else "mBtn")
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        col = self.c["accent_fg"] if primary else self.c["text_2"]
        b.setIcon(icons.icon(icon_name, col, 16))
        b.setIconSize(QSize(15, 15))
        b.clicked.connect(callback)
        self._tb_icons.append((b, icon_name, primary))
        return b

    def _build_ui(self):
        self._tb_icons = []
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── toolbar ──
        bar = QWidget()
        bar.setObjectName("mToolbar")
        bar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(16, 10, 16, 10)
        bl.setSpacing(6)

        self.btn_run  = self._tb_button("play", self.L("Запустить", "Run"), self._run, primary=True)
        self.btn_stop = self._tb_button("stop", self.L("Стоп", "Stop"), self._stop)
        self.btn_stop.setEnabled(False)
        sep1 = QFrame(); sep1.setObjectName("mSep"); sep1.setFrameShape(QFrame.Shape.VLine); sep1.setFixedSize(1, 20)
        self.btn_clear = self._tb_button("trash", self.L("Очистить", "Clear"), self._clear_results)
        self.btn_csv   = self._tb_button("download", "CSV", self._export_csv)
        self.btn_xlsx  = self._tb_button("download", "XLSX", self._export_xlsx)
        sep2 = QFrame(); sep2.setObjectName("mSep"); sep2.setFrameShape(QFrame.Shape.VLine); sep2.setFixedSize(1, 20)
        self.btn_open  = self._tb_button("folder", self.L("Открыть", "Open"), self._open_script)
        self.btn_save  = self._tb_button("save", self.L("Сохранить", "Save"), self._save_script)
        sep3 = QFrame(); sep3.setObjectName("mSep"); sep3.setFrameShape(QFrame.Shape.VLine); sep3.setFixedSize(1, 20)
        self.btn_help  = self._tb_button("help", self.L("Справка", "Help"), self._show_help)

        for w in (self.btn_run, self.btn_stop, sep1, self.btn_clear,
                  self.btn_csv, self.btn_xlsx, sep2, self.btn_open, self.btn_save,
                  sep3, self.btn_help):
            bl.addWidget(w)
        bl.addStretch()
        self.lbl_status = QLabel(self.L("Готово", "Ready"))
        self.lbl_status.setObjectName("mStatus")
        bl.addWidget(self.lbl_status)
        root.addWidget(bar)

        # ── splitters: editor | (results / log) ──
        outer = QSplitter(Qt.Orientation.Vertical)
        outer.setObjectName("mSplit")
        outer.setHandleWidth(1)

        self.editor = CodeEditor(self.c)
        ed_wrap = self._titled(self.L("Скрипт", "Script"), self.editor)
        outer.addWidget(ed_wrap)

        lower = QSplitter(Qt.Orientation.Vertical)
        lower.setHandleWidth(1)

        self.table = QTableWidget(0, 0)
        self.table.horizontalHeader().setDefaultAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        # Columns fit their contents and the last one takes the rest — the
        # header used to stop half-way, an empty slab to its right.
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setObjectName("mTable")
        self.table.setFont(_mono(9))
        tbl_wrap = self._titled(self.L("Результаты", "Results"), self.table, count_label=True)
        from gui.widgets import EmptyState, EmptyOverlay
        self.empty = EmptyState(
            "table", self.L("Результатов пока нет", "No results yet"),
            self.L("Каждый вызов record({…}) в скрипте добавляет строку, колонки "
                   "берутся из ключей. Готовую таблицу можно сохранить в CSV или Excel.",
                   "Every record({…}) call in the script adds a row; the columns "
                   "come from its keys. Save the finished table as CSV or Excel."))
        self.empty.apply_theme(self.c)
        self._empty_ov = EmptyOverlay(self.table, self.empty)
        lower.addWidget(tbl_wrap)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setObjectName("mLog")
        self.log.setFont(_mono(9))
        self.log.setMaximumBlockCount(2000)
        self.log.setPlaceholderText(self.L("Здесь появится вывод log()",
                                           "Output of log() appears here"))
        log_wrap = self._titled(self.L("Журнал", "Log"), self.log)
        lower.addWidget(log_wrap)
        lower.setSizes([420, 160])

        outer.addWidget(lower)
        outer.setSizes([360, 360])
        root.addWidget(outer, 1)

    def _titled(self, title: str, body: QWidget, count_label=False) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        head = QHBoxLayout()
        head.setContentsMargins(12, 8, 12, 6)
        lbl = QLabel(title)
        lbl.setObjectName("mSectionTitle")
        head.addWidget(lbl)
        if count_label:
            self.lbl_rows = QLabel("0")
            self.lbl_rows.setObjectName("mRowCount")
            head.addStretch()
            head.addWidget(self.lbl_rows)
        v.addLayout(head)
        v.addWidget(body, 1)
        return w

    # ── QSS ───────────────────────────────────────────────────────
    def _apply_qss(self):
        c = self.c
        self.setStyleSheet(f"""
        QWidget#macroWin {{ background: {c['bg_0']}; }}
        QWidget#mToolbar {{ background: {c['bg_1']}; }}
        QLabel#mSectionTitle {{ color: {c['text_3']}; font-size: 8pt; font-weight: 600;
            text-transform: uppercase; letter-spacing: 1px; }}
        QLabel#mStatus {{ color: {c['text_3']}; }}
        QLabel#mRowCount {{ color: {c['text_4']}; font-family: {MONO_CSS}; }}
        QPushButton#mBtn, QPushButton#mPrimary {{
            border: 1px solid transparent; border-radius: 6px; padding: 0 12px;
            min-height: 30px; max-height: 30px;
            color: {c['text_2']}; background: transparent; font-weight: 500; }}
        QPushButton#mBtn:hover {{ background: {c['bg_3']}; color: {c['text_1']}; }}
        QPushButton#mBtn:disabled {{ color: {c['text_4']}; background: transparent; }}
        QPushButton#mPrimary {{ background: {c['accent']}; color: {c['accent_fg']}; font-weight: 600; }}
        QPushButton#mPrimary:hover {{ background: {c['accent']}; border-color: {c['text_1']}; }}
        QPushButton#mPrimary:disabled {{ background: {c['bg_3']}; color: {c['text_4']}; }}
        QFrame#mSep {{ background: {c['line']}; border: none; }}
        QPlainTextEdit {{ background: {c['bg_0']}; color: {c['text_1']};
            border: none; selection-background-color: {c['accent_soft']};
            font-family: {MONO_CSS}; }}
        QPlainTextEdit#mLog {{ background: {c['bg_0']}; color: {c['text_2']}; }}
        QTableWidget#mTable {{ background: {c['bg_0']}; alternate-background-color: {c['bg_1']};
            gridline-color: {c['line_soft']}; color: {c['text_1']};
            border: none; selection-background-color: {c['accent_soft']}; }}
        QHeaderView::section {{ background: {c['bg_2']}; color: {c['text_3']};
            padding: 5px 8px; border: none; border-right: 1px solid {c['line_soft']};
            border-bottom: 1px solid {c['line']}; font-weight: 600; }}
        QSplitter::handle {{ background: {c['line_soft']}; }}
        """)

    # ── results plumbing ──────────────────────────────────────────
    def _on_row(self, row: dict):
        new_cols = [k for k in row if k not in self._columns]
        if new_cols:
            self._columns.extend(new_cols)
            self.table.setColumnCount(len(self._columns))
            self.table.setHorizontalHeaderLabels([str(c) for c in self._columns])
        self._records.append(row)
        r = self.table.rowCount()
        self.table.insertRow(r)
        for col, key in enumerate(self._columns):
            item = QTableWidgetItem(self._fmt_cell(row.get(key, "")))
            item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)
            self.table.setItem(r, col, item)
        self.table.scrollToBottom()
        self.lbl_rows.setText(str(len(self._records)))

    @staticmethod
    def _fmt_cell(v) -> str:
        if isinstance(v, float):
            s = f"{v:.4f}".rstrip("0").rstrip(".")
            return s or "0"
        return str(v)

    def _on_log(self, level: str, message: str):
        self.log.appendPlainText(f"[{level}] {message}")

    # ── run / stop ────────────────────────────────────────────────
    # ── running somebody else's script ────────────────────────────
    def _confirm_foreign(self, code: str) -> bool:
        """Ask once before executing a script that came from a file.

        The engine refuses imports and dunder access, which stops the realistic
        escapes, but a macro is still real Python running with this process's
        rights. Loaded code therefore gets the same treatment as any downloaded
        script: one explicit confirmation. Editing it clears the flag."""
        path = getattr(self, "_foreign_source", "")
        if not path or code != getattr(self, "_foreign_code", None):
            return True
        import os
        from PyQt6.QtWidgets import QMessageBox
        choice = themed_message(
            self, self.settings.get("theme", "Dark"), "warning",
            self.L("Запустить скрипт из файла?", "Run a script from a file?"),
            self.L(
                f"«{os.path.basename(path)}» открыт из файла и не был написан "
                f"здесь. Макрос — это обычный Python: он выполнится с правами "
                f"этой программы. Запускайте только то, чему доверяете.",
                f"“{os.path.basename(path)}” was opened from a file and "
                f"was not written here. A macro is ordinary Python and runs with "
                f"this application's rights. Only run what you trust."),
            [(self.L("Отмена", "Cancel"), QMessageBox.ButtonRole.RejectRole, False),
             (self.L("Запустить", "Run"), QMessageBox.ButtonRole.AcceptRole, True)])
        if choice == 1:
            self._foreign_source = ""      # confirmed once, do not nag again
            return True
        return False

    def _run(self):
        if self._runner and self._runner.isRunning():
            return
        if not self.core.is_running:
            themed_info(self, self.settings.get("theme", "Dark"), "warning",
                        self.L("Нет связи", "Not connected"),
                        self.L("Подключитесь к устройству перед запуском макроса.",
                               "Connect to the device before running a macro."))
            return
        code = self.editor.toPlainText()
        if not self._confirm_foreign(code):
            return
        self._persist(code)
        regs = self.get_registers() or []

        self._runner = MacroRunner(code, self.core, regs, t=self.ctx.t)
        self._runner.sig_started.connect(lambda: self._set_running(True))
        self._runner.sig_row.connect(self._on_row)
        self._runner.sig_log.connect(self._on_log)
        self._runner.sig_progress.connect(lambda n: self.lbl_status.setText(
            self.L(f"Выполняется… записей: {n}", f"Running… rows: {n}")))
        self._runner.sig_finished.connect(self._on_finished)
        self._runner.start()

    def _stop(self):
        if self._runner and self._runner.isRunning():
            self._runner.request_stop()
            self.lbl_status.setText(self.L("Останавливаю…", "Stopping…"))

    def _set_running(self, running: bool):
        self.btn_run.setEnabled(not running)
        self.btn_stop.setEnabled(running)
        self.editor.setReadOnly(running)
        if running:
            self.lbl_status.setText(self.L("Выполняется…", "Running…"))

    def _on_finished(self, ok: bool, message: str):
        self._set_running(False)
        self.lbl_status.setText(message)
        self._on_log("SYS" if ok else "ERR", message)

    # ── results actions ───────────────────────────────────────────
    def _clear_results(self):
        self.table.setRowCount(0)
        self.table.setColumnCount(0)
        self._columns.clear()
        self._records.clear()
        self.lbl_rows.setText("0")

    def _export_csv(self):
        if not self._records:
            self._no_data()
            return
        path, _ = QFileDialog.getSaveFileName(
            self, self.L("Экспорт в CSV", "Export CSV"), "results.csv", "CSV (*.csv)")
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.DictWriter(f, fieldnames=[str(c) for c in self._columns])
                w.writeheader()
                for row in self._records:
                    w.writerow({str(k): row.get(k, "") for k in self._columns})
            self._on_log("SYS", self.L(f"Сохранено: {path}", f"Saved: {path}"))
        except Exception as e:
            themed_info(self, self.settings.get("theme", "Dark"), "error",
                        self.L("Ошибка", "Error"), str(e))

    def _export_xlsx(self):
        if not self._records:
            self._no_data()
            return
        try:
            from openpyxl import Workbook
        except ImportError:
            themed_info(self, self.settings.get("theme", "Dark"), "warning",
                        self.L("Нет модуля", "Missing module"),
                        self.L("Для экспорта в XLSX установите пакет openpyxl:\n"
                               "  pip install openpyxl",
                               "Install openpyxl to export XLSX:\n"
                               "  pip install openpyxl"))
            return
        path, _ = QFileDialog.getSaveFileName(
            self, self.L("Экспорт в Excel", "Export Excel"), "results.xlsx", "Excel (*.xlsx)")
        if not path:
            return
        def cell(v):
            # openpyxl only accepts primitives — stringify anything else
            # (a macro may record(x=[1,2]) / record(d={...})).
            return v if isinstance(v, (str, int, float, bool, type(None))) else str(v)
        try:
            wb = Workbook()
            ws = wb.active
            ws.title = "Macro results"
            ws.append([str(c) for c in self._columns])
            for row in self._records:
                ws.append([cell(row.get(k, "")) for k in self._columns])
            wb.save(path)
            self._on_log("SYS", self.L(f"Сохранено: {path}", f"Saved: {path}"))
        except Exception as e:
            themed_info(self, self.settings.get("theme", "Dark"), "error",
                        self.L("Ошибка", "Error"), str(e))

    def _no_data(self):
        themed_info(self, self.settings.get("theme", "Dark"), "info",
                    self.L("Нет данных", "No data"),
                    self.L("Таблица результатов пуста.", "The results table is empty."))

    # ── script load / save / persist ──────────────────────────────
    def _open_script(self):
        path, _ = QFileDialog.getOpenFileName(
            self, self.L("Открыть скрипт", "Open script"), "", "Python (*.py);;All files (*)")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                self.editor.setPlainText(f.read())
            # A macro is real Python. The engine blocks imports and dunder
            # access, but that is a guard-rail, not a sandbox — so code that
            # somebody else wrote gets an explicit confirmation before it
            # runs. Code the operator typed here does not.
            self._foreign_source = path
            self._foreign_code = self.editor.toPlainText()
        except OSError as e:
            themed_info(self, self.settings.get("theme", "Dark"), "error",
                        self.L("Ошибка", "Error"), str(e))

    def _save_script(self):
        path, _ = QFileDialog.getSaveFileName(
            self, self.L("Сохранить скрипт", "Save script"), "macro.py", "Python (*.py)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.editor.toPlainText())
            self._on_log("SYS", self.L(f"Скрипт сохранён: {path}", f"Script saved: {path}"))
        except OSError as e:
            themed_info(self, self.settings.get("theme", "Dark"), "error",
                        self.L("Ошибка", "Error"), str(e))

    def _persist(self, code: str):
        self.settings["last_macro"] = code
        try:
            self.ctx.save()
        except Exception:
            pass

    # ── help & guide ──────────────────────────────────────────────
    def _show_help(self):
        """Open the macro reference card. It also offers the interface tour."""
        dlg = _MacroHelpDialog(self.c, self.lang, self)
        dlg.tour_requested.connect(self._show_guide)
        dlg.exec()

    def _show_guide(self):
        """Coach-mark tour of the macro window layout."""
        if getattr(self, "_guide", None) is not None:
            return
        from gui.onboarding import OnboardingGuide
        ru = self.lang == "ru"
        L = lambda r, e: r if ru else e
        steps = [
            {"target": None,
             "title": L("Окно макросов", "Macros window"),
             "body":  L("Здесь пишутся Python-скрипты, которые читают и пишут "
                        "регистры устройства и собирают данные в таблицу. "
                        "Кнопка «Справка» открывает список доступных команд.",
                        "Here you write Python scripts that read and write the "
                        "device registers and collect data into a table. The "
                        "Help button lists every command you can call.")},
            {"target": self.editor,
             "title": L("Редактор скрипта", "Script editor"),
             "body":  L("Обычный Python: циклы, условия, переменные. Доступны "
                        "команды read/write/wait/record/read_all/log/now/"
                        "timestamp. Скрипт сохраняется между запусками.",
                        "Plain Python: loops, conditions, variables. The "
                        "read/write/wait/record/read_all/log/now/timestamp "
                        "commands are available. The script persists between "
                        "runs.")},
            {"target": self.btn_run,
             "title": L("Запустить", "Run"),
             "body":  L("Выполняет скрипт в фоне. Перед запуском нужно "
                        "подключиться к устройству. Остановить можно кнопкой "
                        "«Стоп».",
                        "Runs the script in the background. You must be connected "
                        "to the device first. Use Stop to interrupt it.")},
            {"target": self.table,
             "title": L("Результаты", "Results"),
             "body":  L("Каждый вызов record(...) добавляет строку. Колонки "
                        "формируются из ключей словаря автоматически.",
                        "Each record(...) call appends a row. Columns are built "
                        "from the dictionary keys automatically.")},
            {"target": [self.btn_csv, self.btn_xlsx],
             "title": L("Экспорт", "Export"),
             "body":  L("Сохраняет таблицу результатов в CSV или XLSX для "
                        "дальнейшего анализа.",
                        "Saves the results table to CSV or XLSX for further "
                        "analysis.")},
            {"target": self.btn_help,
             "title": L("Справка по командам", "Command reference"),
             "body":  L("Забыли команду? Эта кнопка открывает список всех "
                        "функций с примерами. Готово!",
                        "Forgot a command? This button opens the list of every "
                        "function with examples. Done!")},
        ]
        self._guide = OnboardingGuide(
            self, steps,
            self.settings.get("theme", "Dark"),
            self.settings.get("accent"), self.lang)
        self._guide.finished.connect(lambda: setattr(self, "_guide", None))
        self._guide.show_guide()

    # ── theme follow-up ───────────────────────────────────────────
    def apply_theme(self):
        """Re-skin after an appearance change in the main window (this window
        carries its own stylesheet, so the app-wide restyle does not reach
        it)."""
        self.c = self.ctx.theme_tokens()
        self._apply_qss()
        for b, name, primary in self._tb_icons:
            col = self.c["accent_fg"] if primary else self.c["text_2"]
            b.setIcon(icons.icon(name, col, 16))
        self.editor._c = self.c
        self.editor.gutter.update()
        self.empty.apply_theme(self.c)

    def stop_and_wait(self):
        """Stop a running macro and wait for its thread (app shutdown)."""
        if self._runner is not None and self._runner.isRunning():
            self._runner.request_stop()
            self._runner.wait(3000)

    # ── lifecycle ─────────────────────────────────────────────────
    @property
    def running(self) -> bool:
        return bool(self._runner and self._runner.isRunning())

    def closeEvent(self, event):
        if not self.confirm_close():
            event.ignore()
            return
        self.shutdown()
        super().closeEvent(event)

    def shutdown(self):
        """Stop a running macro and keep the script (window / app closing)."""
        if self.running:
            self._runner.request_stop()
            self._runner.wait(3000)
        self._persist(self.editor.toPlainText())

    def confirm_close(self) -> bool:
        """Ask before abandoning a running macro or unexported results.
        True = go ahead and close."""
        running = self.running

        # Warn before closing while a macro is still computing — otherwise the
        # run is silently aborted and any in-progress measurement is lost.
        theme_name = self.settings.get("theme", "Dark")
        if running:
            choice = themed_message(
                self, theme_name, "warning",
                self.L("Макрос выполняется", "Macro is running"),
                self.L(
                    "Сейчас выполняется макрос. Если закрыть окно, выполнение "
                    "будет прервано, а несохранённые результаты потеряны. "
                    "Закрыть и остановить макрос?",
                    "A macro is currently running. Closing the window will abort "
                    "it and any unsaved results will be lost. "
                    "Close and stop the macro?"),
                [(self.L("Закрыть", "Close"),
                  QMessageBox.ButtonRole.AcceptRole, False),
                 (self.L("Отмена", "Cancel"),
                  QMessageBox.ButtonRole.RejectRole, True)])
            if choice != 0:
                return False
        # Not running, but results are sitting in the table unexported.
        elif self._records:
            choice = themed_message(
                self, theme_name, "question",
                self.L("Несохранённые результаты", "Unsaved results"),
                self.L(
                    f"В таблице есть {len(self._records)} строк результатов, "
                    "которые не были экспортированы. Закрыть окно?",
                    f"The results table holds {len(self._records)} rows that "
                    "have not been exported. Close the window?"),
                [(self.L("Закрыть", "Close"),
                  QMessageBox.ButtonRole.AcceptRole, False),
                 (self.L("Отмена", "Cancel"),
                  QMessageBox.ButtonRole.RejectRole, True)])
            if choice != 0:
                return False
        return True


# ════════════════════════════════════════════════════════════════════
#  MACRO HELP / API REFERENCE
# ════════════════════════════════════════════════════════════════════
# Each entry: (signature, RU description, EN description).
_MACRO_API = [
    ("read(name)",
     "Прочитать один регистр по имени из профиля или по адресу "
     "(<code>read(0x10)</code>; coil, дискретный вход или input-регистр — "
     "<code>read(\"CO 0x05\")</code>, <code>\"DI 3\"</code>, "
     "<code>\"IR 0x10\"</code>). Возвращает число.",
     "Read one register by its profile name or by address "
     "(<code>read(0x10)</code>; a coil / discrete / input register — "
     "<code>read(\"CO 0x05\")</code>, <code>\"DI 3\"</code>, "
     "<code>\"IR 0x10\"</code>). Returns a number."),
    ("write(name, value)",
     "Записать значение в регистр. Регистр должен быть RW.",
     "Write a value to a register. The register must be RW."),
    ("read_all()",
     "Прочитать все регистры профиля и вернуть словарь "
     "<code>{имя: значение}</code>.",
     "Read every register in the profile and return a "
     "<code>{name: value}</code> dict."),
    ("reg(name)",
     "Получить объект регистра с методами <code>.read()</code> / "
     "<code>.write(v)</code> — удобно при многократном обращении.",
     "Get a register object with <code>.read()</code> / "
     "<code>.write(v)</code> methods — handy for repeated access."),
    ("wait(seconds)  ·  sleep(seconds)",
     "Пауза на заданное число секунд (можно дробное).",
     "Pause for the given number of seconds (fractions allowed)."),
    ("record(row)",
     "Добавить строку в таблицу результатов. <code>row</code> — словарь "
     "<code>{колонка: значение}</code>; колонки создаются автоматически.",
     "Append a row to the results table. <code>row</code> is a "
     "<code>{column: value}</code> dict; columns are created automatically."),
    ("log(*args)  ·  print(*args)",
     "Вывести сообщение в журнал внизу окна.",
     "Print a message to the log pane at the bottom of the window."),
    ("now()",
     "Текущее время в секундах (Unix-время, дробное) — для замеров "
     "длительности.",
     "Current time in seconds (Unix time, float) — for measuring durations."),
    ("timestamp()",
     "Текущие дата и время строкой <code>ГГГГ-ММ-ДД ЧЧ:ММ:СС</code> — удобно "
     "как колонка.",
     "Current date and time as a <code>YYYY-MM-DD HH:MM:SS</code> string — "
     "handy as a column."),
]


class _MacroHelpDialog(QDialog):
    """Read-only reference card listing the macro API + a tour launcher."""

    tour_requested = pyqtSignal()

    def __init__(self, colors: dict, lang: str, parent=None):
        super().__init__(parent)
        self.c = colors
        self.lang = lang
        L = lambda r, e: r if lang == "ru" else e
        self.setWindowTitle(L("Справка по макросам", "Macro help"))
        self.resize(560, 640)

        lo = QVBoxLayout(self)
        lo.setContentsMargins(0, 0, 0, 0)
        lo.setSpacing(0)

        browser = QTextBrowser()
        browser.setOpenExternalLinks(False)
        browser.setHtml(self._build_html(L))
        lo.addWidget(browser, 1)

        foot = QHBoxLayout()
        foot.setContentsMargins(16, 12, 16, 12)
        foot.setSpacing(10)
        btn_tour = QPushButton(L("Тур по интерфейсу", "Interface tour"))
        btn_tour.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_tour.clicked.connect(self._launch_tour)
        btn_close = QPushButton(L("Закрыть", "Close"))
        btn_close.setObjectName("mPrimary")
        btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_close.clicked.connect(self.accept)
        foot.addWidget(btn_tour)
        foot.addStretch()
        foot.addWidget(btn_close)
        lo.addLayout(foot)

        c = colors
        self.setStyleSheet(f"""
            QDialog {{ background: {c['bg_0']}; }}
            QTextBrowser {{ background: {c['bg_0']}; color: {c['text_1']};
                border: none; padding: 4px 8px; }}
            QPushButton {{ border: 1px solid {c['line']}; border-radius: 6px;
                padding: 6px 16px; color: {c['text_2']}; background: {c['bg_2']};
                font-size: 9pt; font-weight: 500; }}
            QPushButton:hover {{ background: {c['bg_3']}; color: {c['text_1']}; }}
            QPushButton#mPrimary {{ background: {c['accent']};
                color: {c['accent_fg']}; border: none; }}
        """)

    def _launch_tour(self):
        self.accept()
        self.tour_requested.emit()

    def _build_html(self, L) -> str:
        c = self.c
        rows = []
        for sig, ru, en in _MACRO_API:
            desc = ru if self.lang == "ru" else en
            rows.append(
                f"<div style='margin:0 0 14px 0;'>"
                f"<div style='font-family:{MONO_CSS};"
                f"font-size:11pt;color:{c['accent']};font-weight:600;'>{sig}</div>"
                f"<div style='color:{c['text_2']};font-size:10pt;"
                f"margin-top:2px;'>{desc}</div></div>")
        example = (
            "for i in range(10):\n"
            "    write(\"Setpoint\", i)\n"
            "    wait(0.5)\n"
            "    row = {\"#\": i, \"t\": timestamp()}\n"
            "    row.update(read_all())\n"
            "    record(row)\n"
            "    log(\"step\", i, \"done\")")
        intro = L(
            "Скрипт — это обычный Python. Доступны перечисленные ниже команды "
            "плюс безопасный набор встроенных функций (range, len, round, "
            "int, float, abs, min, max, sum, enumerate, zip…). Регистры "
            "адресуются по имени из профиля или по числовому адресу.",
            "A macro is plain Python. The commands below are available, plus a "
            "safe set of builtins (range, len, round, int, float, abs, min, "
            "max, sum, enumerate, zip…). Registers are addressed by their "
            "profile name or by a numeric address.")
        return (
            f"<body style='font-family:Inter,Segoe UI,sans-serif;'>"
            f"<h2 style='color:{c['text_1']};margin:14px 12px 4px;'>"
            f"{L('Команды макросов', 'Macro commands')}</h2>"
            f"<p style='color:{c['text_3']};font-size:10pt;margin:0 12px 16px;'>"
            f"{intro}</p>"
            f"<div style='margin:0 12px;'>{''.join(rows)}</div>"
            f"<h3 style='color:{c['text_1']};margin:8px 12px 4px;'>"
            f"{L('Пример', 'Example')}</h3>"
            f"<pre style='background:{c['bg_1']};color:{c['text_1']};"
            f"border-radius:8px;padding:12px;margin:0 12px 16px;"
            f"font-family:{MONO_CSS};font-size:10pt;"
            f"white-space:pre-wrap;'>{example}</pre>"
            f"</body>")
