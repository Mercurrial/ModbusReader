"""The macro editor's keys (gui/macros.py CodeEditor) — the ones a code
editor has: indent / dedent of the selected lines, auto-indent, comment
toggle, duplicate, and Ctrl+S that saves the script, not the project."""
import pytest
from PyQt6.QtCore import Qt, QEvent
from PyQt6.QtGui import QKeyEvent, QTextCursor

from gui.macros import CodeEditor
from gui.theme_manager import get_theme

NO = Qt.KeyboardModifier.NoModifier
CTRL = Qt.KeyboardModifier.ControlModifier
SHIFT = Qt.KeyboardModifier.ShiftModifier


@pytest.fixture()
def ed():
    e = CodeEditor(get_theme("Dark"))
    yield e
    e.deleteLater()


def _key(ed, key, mods=NO, text=""):
    ed.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, key, mods, text))


def _select_lines(ed, first, last):
    doc = ed.document()
    c = QTextCursor(doc.findBlockByNumber(first))
    end = doc.findBlockByNumber(last)
    c.setPosition(end.position() + end.length() - 1, QTextCursor.MoveMode.KeepAnchor)
    ed.setTextCursor(c)


def test_tab_and_shift_tab_move_the_selected_lines(ed):
    ed.setPlainText("a = 1\nb = 2\nc = 3")
    _select_lines(ed, 0, 1)
    _key(ed, Qt.Key.Key_Tab)
    assert ed.toPlainText() == "    a = 1\n    b = 2\nc = 3"
    assert ed.textCursor().hasSelection()       # still selected: Tab again works
    _key(ed, Qt.Key.Key_Backtab, SHIFT)
    _key(ed, Qt.Key.Key_Backtab, SHIFT)         # nothing left to take: no harm
    assert ed.toPlainText() == "a = 1\nb = 2\nc = 3"
    ed.undo()
    assert ed.toPlainText() == "    a = 1\n    b = 2\nc = 3"   # one step per press


def test_enter_keeps_the_indent_and_adds_one_after_a_colon(ed):
    ed.setPlainText("for i in range(3):")
    ed.moveCursor(QTextCursor.MoveOperation.End)
    _key(ed, Qt.Key.Key_Return)
    ed.insertPlainText("x = read('T')")
    _key(ed, Qt.Key.Key_Return)
    assert ed.toPlainText() == "for i in range(3):\n    x = read('T')\n    "


def test_ctrl_slash_comments_the_lines_out_and_back(ed):
    ed.setPlainText("if x:\n    a()\n\n    b()")
    _select_lines(ed, 0, 3)
    _key(ed, Qt.Key.Key_Slash, CTRL)
    assert ed.toPlainText() == "# if x:\n#     a()\n\n#     b()"
    _key(ed, Qt.Key.Key_Slash, CTRL)
    assert ed.toPlainText() == "if x:\n    a()\n\n    b()"


def test_ctrl_d_duplicates_the_line(ed):
    ed.setPlainText("wait(0.05)\nlog(1)")
    _key(ed, Qt.Key.Key_D, CTRL)
    assert ed.toPlainText() == "wait(0.05)\nwait(0.05)\nlog(1)"
    assert ed.textCursor().blockNumber() == 1


def test_ctrl_s_saves_the_script_not_the_project(ed):
    saved = []
    ed.save_requested.connect(lambda: saved.append(1))
    over = QKeyEvent(QEvent.Type.ShortcutOverride, Qt.Key.Key_S, CTRL)
    ed.event(over)
    assert over.isAccepted()                    # the window's Ctrl+S stays out of it
    _key(ed, Qt.Key.Key_S, CTRL)
    assert saved == [1]


def test_ctrl_s_writes_the_open_file_without_asking(tmp_path, monkeypatch):
    from PyQt6.QtWidgets import QFileDialog
    from app.app_context import AppContext
    from app.settings_manager import DEFAULT_SETTINGS
    from gui.macros import MacroWindow
    ctx = AppContext(dict(DEFAULT_SETTINGS))
    mw = MacroWindow(ctx, lambda: [], embedded=True)
    try:
        asked = []
        target = tmp_path / "m.py"
        monkeypatch.setattr(QFileDialog, "getSaveFileName",
                            lambda *a, **k: (asked.append(1), (str(target), ""))[1])
        mw.editor.setPlainText("log(1)")
        mw.editor.save_requested.emit()          # first time: where to?
        mw.editor.setPlainText("log(2)")
        mw.editor.save_requested.emit()          # then: the same file
        assert asked == [1]
        assert target.read_text(encoding="utf-8") == "log(2)"
    finally:
        mw.deleteLater()
