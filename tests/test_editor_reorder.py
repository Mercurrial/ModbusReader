"""Live WYSIWYG drag-reorder regression (v3: grab-anywhere + visual sections).

A row is dragged from ANY item cell. During the drag only the vertical
header's visual sections move (zero widget churn — this was the lag), plus a
ghost pixmap follows the cursor. The DATA is permuted once on release
(reorderCommitted -> dialog applies visual_order()); Esc just resets the
visual order because the model was never touched mid-drag.

All tests drive the REAL mouse path (events routed through the viewport) —
handler-only tests previously missed a broken-in-practice drag.
"""
import pytest
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt, QPointF, QEvent
from PyQt6.QtGui import QMouseEvent, QKeyEvent

from app.app_context import AppContext
from app.settings_manager import DEFAULT_SETTINGS
from gui.map_editor import ProfileEditorDialog, COL_GRIP, COL_RU


@pytest.fixture()
def editor():
    ctx = AppContext(dict(DEFAULT_SETTINGS))
    prof = [{"addr": 0, "name": f"R{i}", "type": "SHORT"} for i in range(4)]
    ed = ProfileEditorDialog(None, prof, ctx)
    ed.table.resize(900, 300)
    ed.table.doItemsLayout()
    yield ed
    ed.close()


def _names(ed):
    return [r["name"] for r in ed.profile_data]


def _send(vp, etype, x, y, btn, btns):
    QApplication.sendEvent(
        vp, QMouseEvent(etype, QPointF(x, y), QPointF(x, y), btn, btns,
                        Qt.KeyboardModifier.NoModifier))


def _drag(ed, from_row, to_row, col=COL_GRIP, release=True):
    """Simulate press on (from_row, col), move through rows, then release."""
    t = ed.table
    vp = t.viewport()
    x = t.columnViewportPosition(col) + 20

    def yc(logical):
        return t.rowViewportPosition(logical) + max(1, t.rowHeight(logical) // 2)

    _send(vp, QEvent.Type.MouseButtonPress, x, yc(from_row),
          Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton)
    step = 1 if to_row >= from_row else -1
    for r in range(from_row, to_row + step, step):
        _send(vp, QEvent.Type.MouseMove, x, yc(r),
              Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton)
    if release:
        _send(vp, QEvent.Type.MouseButtonRelease, x, yc(to_row),
              Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton)


def test_drag_first_to_last(editor):
    _drag(editor, 0, 3)
    assert _names(editor) == ["R1", "R2", "R3", "R0"]
    assert editor.table.rowCount() == 4              # nothing vanished


def test_drag_last_to_first(editor):
    _drag(editor, 3, 0)
    assert _names(editor) == ["R3", "R0", "R1", "R2"]
    assert editor.table.rowCount() == 4


def test_grab_anywhere_not_only_grip(editor):
    _drag(editor, 0, 2, col=COL_RU)                  # dragged by the NAME cell
    assert _names(editor) == ["R1", "R2", "R0", "R3"]


def test_visual_moves_live_but_data_waits_for_release(editor):
    _drag(editor, 0, 2, release=False)               # still holding the button
    assert _names(editor) == ["R0", "R1", "R2", "R3"]        # data untouched
    assert editor.table.visual_order() == [1, 2, 0, 3]       # view moved live
    t = editor.table
    vp = t.viewport()
    x = t.columnViewportPosition(COL_GRIP) + 20
    y = t.rowViewportPosition(2) + 10
    _send(vp, QEvent.Type.MouseButtonRelease, x, y,
          Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton)
    assert _names(editor) == ["R1", "R2", "R0", "R3"]        # applied on drop


def test_ghost_and_slot_appear_during_drag_and_go_away(editor):
    _drag(editor, 0, 2, release=False)
    assert editor.table._ghost is not None           # floating row snapshot
    assert editor.table._slot is not None            # dashed landing slot
    t = editor.table
    _send(t.viewport(), QEvent.Type.MouseButtonRelease,
          t.columnViewportPosition(COL_GRIP) + 20,
          t.rowViewportPosition(2) + 10,
          Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton)
    assert editor.table._ghost is None
    assert editor.table._slot is None
    assert not editor.table._anims                   # animations cleaned up


def test_esc_cancels_whole_drag(editor):
    before = _names(editor)
    _drag(editor, 0, 3, release=False)
    assert editor.table.visual_order() != [0, 1, 2, 3]
    QApplication.sendEvent(editor.table, QKeyEvent(
        QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))
    assert editor.table.visual_order() == [0, 1, 2, 3]       # view restored
    assert _names(editor) == before                          # data untouched
    assert editor.table._grabbed is False


def test_noop_drag_is_not_modified(editor):
    editor.is_modified = False
    t = editor.table
    vp = t.viewport()
    vh = t.verticalHeader()
    x = t.columnViewportPosition(COL_GRIP) + 20

    def y_visual(v):
        # Y of the row currently shown at VISUAL position v (sections move
        # during the drag, so logical positions shift under the cursor).
        logical = vh.logicalIndex(v)
        return t.rowViewportPosition(logical) + max(1, t.rowHeight(logical) // 2)

    _send(vp, QEvent.Type.MouseButtonPress, x, y_visual(1),
          Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton)
    for v in (2, 1):                                  # down one and back
        _send(vp, QEvent.Type.MouseMove, x, y_visual(v),
              Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton)
    _send(vp, QEvent.Type.MouseButtonRelease, x, y_visual(1),
          Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton)
    assert _names(editor) == ["R0", "R1", "R2", "R3"]
    assert editor.is_modified is False               # net-unchanged -> no dirty


def test_commit_pushes_single_undo_step(editor):
    depth_before = len(editor.history)
    _drag(editor, 0, 3)
    assert len(editor.history) == depth_before + 1   # ONE undo entry per drag
    editor._undo()
    assert _names(editor) == ["R0", "R1", "R2", "R3"]


def test_addresses_recomputed_after_drag(editor):
    _drag(editor, 2, 0)
    assert [r["addr"] for r in editor.profile_data] == [0, 1, 2, 3]


def test_grab_released_on_drop(editor):
    _drag(editor, 0, 3)
    assert editor.table._grabbed is False
    assert editor.is_modified is True


def test_a_fast_drag_leaves_no_row_snapshots_behind(editor):
    """Displaced rows glide as snapshot labels. A release before their 140 ms
    animation finished STOPPED it — and stop() does not emit finished(), the
    only place the snapshot was deleted. The stale row pictures stayed over
    the table for good (rows drawn on top of each other)."""
    from PyQt6.QtWidgets import QLabel
    editor.show()
    QApplication.processEvents()
    try:
        _drag(editor, 0, 2)                  # release at once: anims running
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
        QApplication.processEvents()
        left = [w for w in editor.table.viewport().findChildren(QLabel)
                if not w.isHidden()]
        names = _names(editor)
    finally:
        editor.is_modified = False           # no "save changes?" on close
    assert left == []
    assert names == ["R1", "R2", "R0", "R3"]
