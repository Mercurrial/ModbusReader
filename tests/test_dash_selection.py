"""Multi-select, rubber band and clipboard on the dashboard canvas.

These drive real mouse events through the real widgets rather than poking the
selection list, because every bug this feature can have lives in the gesture:
a click that collapses a group, a band that selects nothing, a paste whose
wires still point at the originals.
"""
import pytest
from PyQt6.QtCore import Qt, QPoint, QPointF, QEvent
from PyQt6.QtGui import QMouseEvent, QKeyEvent

from app_context import AppContext
from settings_manager import DEFAULT_SETTINGS
from gui_dash import DashboardView

REGS = [{"addr": 0x10, "name": "Пуск", "type": "SHORT", "rw": "RW"}]

NO_MOD = Qt.KeyboardModifier.NoModifier
CTRL = Qt.KeyboardModifier.ControlModifier


@pytest.fixture()
def view():
    ctx = AppContext(dict(DEFAULT_SETTINGS, dash_widgets=[], dash_links=[]))
    v = DashboardView(ctx, lambda: REGS)
    v.resize(900, 700)
    v.set_edit(True)
    yield v
    v.stop_if_running()
    v.deleteLater()


def _card(view, uid, x, y, w=100, h=60, kind="value"):
    view._make_card({"uid": uid, "kind": kind, "reg_id": "0x0010",
                     "reg_type": "SHORT", "name": uid,
                     "x": x, "y": y, "w": w, "h": h})
    return view.cards[uid]


def _click(widget, pos, mods=NO_MOD, button=Qt.MouseButton.LeftButton):
    for kind, buttons in ((QEvent.Type.MouseButtonPress, button),
                          (QEvent.Type.MouseButtonRelease, Qt.MouseButton.NoButton)):
        widget.mousePressEvent(QMouseEvent(
            kind, QPointF(pos), button, buttons, mods)) \
            if kind == QEvent.Type.MouseButtonPress else \
            widget.mouseReleaseEvent(QMouseEvent(
                kind, QPointF(pos), button, buttons, mods))


def _press(widget, pos, mods=NO_MOD):
    widget.mousePressEvent(QMouseEvent(
        QEvent.Type.MouseButtonPress, QPointF(pos), Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton, mods))


def _move(widget, pos, mods=NO_MOD):
    widget.mouseMoveEvent(QMouseEvent(
        QEvent.Type.MouseMove, QPointF(pos), Qt.MouseButton.NoButton,
        Qt.MouseButton.LeftButton, mods))


def _release(widget, pos, mods=NO_MOD):
    widget.mouseReleaseEvent(QMouseEvent(
        QEvent.Type.MouseButtonRelease, QPointF(pos), Qt.MouseButton.LeftButton,
        Qt.MouseButton.NoButton, mods))


def _key(view, key, mods=NO_MOD):
    view.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, key, mods))


# ═══════════════ clicking ═══════════════
def test_a_plain_click_selects_only_that_widget(view):
    a, b = _card(view, "a", 0, 0), _card(view, "b", 200, 0)
    _press(a, QPoint(10, 10))
    assert view.sel_uids == ("a",)
    _press(b, QPoint(10, 10))
    assert view.sel_uids == ("b",)


def test_ctrl_click_adds_and_removes(view):
    a, b = _card(view, "a", 0, 0), _card(view, "b", 200, 0)
    _press(a, QPoint(10, 10))
    _press(b, QPoint(10, 10), CTRL)
    assert set(view.sel_uids) == {"a", "b"}
    _press(b, QPoint(10, 10), CTRL)             # toggles back off
    assert view.sel_uids == ("a",)


def test_clicking_a_member_keeps_the_group(view):
    """Grabbing a group to drag it must not collapse the selection to the one
    card under the cursor — that made multi-move impossible to perform."""
    a, b = _card(view, "a", 0, 0), _card(view, "b", 200, 0)
    view._select(["a", "b"])
    _press(a, QPoint(10, 10))
    assert set(view.sel_uids) == {"a", "b"}


def test_selected_cards_know_they_are_selected(view):
    _card(view, "a", 0, 0), _card(view, "b", 200, 0)
    view._select(["a", "b"])
    assert all(view.cards[u].is_selected for u in ("a", "b"))
    view.clear_selection()
    assert not any(view.cards[u].is_selected for u in ("a", "b"))


# ═══════════════ rubber band ═══════════════
def test_band_selects_every_widget_it_touches(view):
    _card(view, "a", 10, 10)
    _card(view, "b", 150, 10)
    _card(view, "far", 600, 500)
    _drag_band(view, (5, 5), (400, 200))
    assert set(view.sel_uids) == {"a", "b"}


def test_band_only_needs_to_touch_a_widget_not_swallow_it(view):
    """Requiring full containment means you cannot band a row of widgets
    without also enclosing everything under them."""
    _card(view, "a", 100, 100, w=200, h=200)
    cv = view.canvas
    _press(cv, QPoint(90, 90))
    _move(cv, QPoint(120, 120))                  # clips one corner only
    _release(cv, QPoint(120, 120))
    assert view.sel_uids == ("a",)


def test_band_with_ctrl_extends_instead_of_replacing(view):
    _card(view, "a", 10, 10)
    _card(view, "b", 400, 400)
    view._select(["b"])
    cv = view.canvas
    _press(cv, QPoint(5, 5), CTRL)
    for x in (60, 120, 200):
        _move(cv, QPoint(x, x), CTRL)
    _release(cv, QPoint(200, 200), CTRL)
    assert set(view.sel_uids) == {"a", "b"}


def _drag_band(view, start, end, steps=8):
    """A real drag: many small moves, not one jump.

    This matters. With a single move almost any implementation looks correct;
    the anchor bug only shows up once there is a SECOND move to feed the
    previous rect back into.
    """
    cv = view.canvas
    _press(cv, QPoint(*start))
    for i in range(1, steps + 1):
        _move(cv, QPoint(start[0] + (end[0] - start[0]) * i // steps,
                         start[1] + (end[1] - start[1]) * i // steps))
    _release(cv, QPoint(*end))


@pytest.mark.parametrize("start,end", [
    ((5, 5), (300, 200)),        # down-right
    ((300, 200), (5, 5)),        # up-left
    ((300, 5), (5, 200)),        # down-left
    ((5, 200), (300, 5)),        # up-right
])
def test_the_band_works_in_every_direction(view, start, end):
    """The band must grow from where it was ANCHORED. Measuring it from the
    previous rect's topLeft() means that after normalisation it only ever
    covers the last two cursor positions, so it never selects anything on a
    real drag — and up/left drags collapse it entirely."""
    _card(view, "a", 50, 50)
    _card(view, "b", 180, 60)
    _drag_band(view, start, end)
    assert set(view.sel_uids) == {"a", "b"}, f"{start} -> {end}"


def test_band_disappears_after_release(view):
    cv = view.canvas
    _press(cv, QPoint(5, 5))
    _move(cv, QPoint(200, 200))
    assert view._marquee is not None
    _release(cv, QPoint(200, 200))
    assert view._marquee is None


def test_empty_click_clears_the_selection(view):
    _card(view, "a", 300, 300)
    view._select(["a"])
    _press(view.canvas, QPoint(5, 5))
    assert view.sel_uids == ()


# ═══════════════ moving a group ═══════════════
def test_dragging_one_member_moves_the_whole_group(view):
    a = _card(view, "a", 100, 100)
    _card(view, "b", 300, 100)
    view._select(["a", "b"])
    view._on_move_started("a", QPoint(5, 5))
    g = view.canvas.mapToGlobal(QPoint(155, 175))     # +50, +70 from the grab
    view._on_move_moved("a", g)
    assert view.cards["a"].cfg["x"] != 100
    dx = view.cards["a"].cfg["x"] - 100
    dy = view.cards["a"].cfg["y"] - 100
    assert (view.cards["b"].cfg["x"], view.cards["b"].cfg["y"]) == (300 + dx, 100 + dy)


def test_a_group_does_not_snap_to_its_own_members(view):
    """A group that snaps to itself glues together and stops moving."""
    _card(view, "a", 100, 100)
    _card(view, "b", 104, 100)          # within snap distance of a
    _card(view, "outsider", 600, 600)
    view._select(["a", "b"])
    assert view._others("a") == [(600, 600, 100, 60)]


def test_dragging_a_non_member_leaves_the_group_alone(view):
    _card(view, "a", 100, 100)
    c = _card(view, "c", 500, 100)
    view._select(["a"])
    view._on_move_started("c", QPoint(5, 5))
    view._on_move_moved("c", view.canvas.mapToGlobal(QPoint(600, 300)))
    assert (view.cards["a"].cfg["x"], view.cards["a"].cfg["y"]) == (100, 100)


def test_arrows_nudge_every_selected_widget(view):
    _card(view, "a", 100, 100)
    _card(view, "b", 300, 100)
    view._select(["a", "b"])
    _key(view, Qt.Key.Key_Right, Qt.KeyboardModifier.ShiftModifier)
    assert view.cards["a"].cfg["x"] > 100 and view.cards["b"].cfg["x"] > 300


# ═══════════════ clipboard ═══════════════
def test_copy_paste_makes_independent_copies(view):
    _card(view, "a", 100, 100)
    view._select(["a"])
    assert view.copy_selection() == 1
    assert view.paste_clipboard() == 1
    assert len(view.cards) == 2
    new_uid = [u for u in view.cards if u != "a"][0]
    assert new_uid != "a"
    view.cards[new_uid].cfg["name"] = "changed"
    assert view.cards["a"].cfg.get("name") == "a"


def test_paste_lands_offset_so_the_copy_is_visible(view):
    _card(view, "a", 100, 100)
    view._select(["a"])
    view.copy_selection()
    view.paste_clipboard()
    new = [c for u, c in view.cards.items() if u != "a"][0]
    assert (new.cfg["x"], new.cfg["y"]) != (100, 100)


def test_repeated_paste_does_not_stack_copies_on_top_of_each_other(view):
    _card(view, "a", 100, 100)
    view._select(["a"])
    view.copy_selection()
    view.paste_clipboard()
    view.paste_clipboard()
    spots = {(c.cfg["x"], c.cfg["y"]) for c in view.cards.values()}
    assert len(spots) == 3, "three widgets must occupy three positions"


def test_wires_inside_the_copied_set_are_rebuilt_between_the_copies(view):
    _card(view, "a", 100, 100, kind="button")
    _card(view, "b", 300, 100)
    view.graph.add("a", "b")
    view._select(["a", "b"])
    view.copy_selection()
    view.paste_clipboard()
    new = [u for u in view.cards if u not in ("a", "b")]
    assert len(new) == 2
    assert view.graph.add(new[0], new[1]) is False or \
        view.graph.add(new[1], new[0]) is False, \
        "the copied pair must already be wired to each other"
    # …and the original wire is untouched
    assert {"from": "a", "to": "b"} in view.graph.links


def test_a_half_copied_wire_is_dropped_not_attached_to_the_original(view):
    """Copying only the source must not leave the copy driving the ORIGINAL
    target — silently wiring a duplicate into live equipment."""
    _card(view, "a", 100, 100, kind="button")
    _card(view, "b", 300, 100)
    view.graph.add("a", "b")
    view._select(["a"])                       # only the source
    view.copy_selection()
    view.paste_clipboard()
    new = [u for u in view.cards if u not in ("a", "b")][0]
    assert view.graph.targets_of(new) == []


def test_cut_removes_the_originals_and_paste_brings_them_back(view):
    _card(view, "a", 100, 100)
    _card(view, "b", 300, 100)
    view._select(["a", "b"])
    assert view.cut_selection() == 2
    assert view.cards == {}
    assert view.paste_clipboard() == 2
    assert len(view.cards) == 2


def test_paste_selects_what_it_just_pasted(view):
    _card(view, "a", 100, 100)
    view._select(["a"])
    view.copy_selection()
    view.paste_clipboard()
    assert len(view.sel_uids) == 1 and view.sel_uids[0] != "a"


def test_paste_with_an_empty_clipboard_is_a_no_op(view):
    assert view.paste_clipboard() == 0
    assert view.cards == {}


def test_the_clipboard_survives_switching_dashboards(view):
    """Copying a control block from one screen to another is the main reason
    to have copy at all."""
    _card(view, "a", 100, 100)
    view._select(["a"])
    view.copy_selection()
    view.add_board("second")
    assert view.cards == {}
    assert view.paste_clipboard() == 1


def test_delete_removes_every_selected_widget(view):
    _card(view, "a", 100, 100)
    _card(view, "b", 300, 100)
    view._select(["a", "b"])
    _key(view, Qt.Key.Key_Delete)
    assert view.cards == {}


def test_ctrl_a_selects_everything(view):
    _card(view, "a", 100, 100)
    _card(view, "b", 300, 100)
    _key(view, Qt.Key.Key_A, CTRL)
    assert set(view.sel_uids) == {"a", "b"}


def test_duplicating_a_member_duplicates_the_whole_group(view):
    _card(view, "a", 100, 100)
    _card(view, "b", 300, 100)
    view._select(["a", "b"])
    view._duplicate_widget("a")
    assert len(view.cards) == 4


# ═══════════════ safety ═══════════════
def test_deleting_a_card_drops_it_from_the_selection(view):
    _card(view, "a", 100, 100)
    _card(view, "b", 300, 100)
    view._select(["a", "b"])
    view._remove_card("a")
    assert view.sel_uids == ("b",)


def test_selection_never_holds_a_uid_without_a_card(view):
    _card(view, "a", 100, 100)
    view._select(["a", "ghost"])
    assert view.sel_uids == ("a",)


def test_run_mode_ignores_selection_gestures(view):
    """A stray band-drag or Del on a live dashboard must not rearrange it."""
    _card(view, "a", 100, 100)
    view.set_edit(False)
    _press(view.canvas, QPoint(5, 5))
    _move(view.canvas, QPoint(400, 400))
    assert view.sel_uids == ()
    _key(view, Qt.Key.Key_Delete)
    assert "a" in view.cards


def test_sel_uid_still_reads_and_writes_like_a_single_selection(view):
    """Older code paths (and saved behaviour) address one widget."""
    _card(view, "a", 100, 100)
    _card(view, "b", 300, 100)
    view.sel_uid = "a"
    assert view.sel_uid == "a" and view.sel_uids == ("a",)
    view.sel_uid = None
    assert view.sel_uid is None and view.sel_uids == ()
