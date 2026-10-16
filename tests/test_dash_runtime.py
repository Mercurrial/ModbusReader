"""Dashboard automation runtime: controls write, wires propagate, and the
edit mode is a hard safety gate (no device writes while arranging)."""
import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from app.app_context import AppContext
from app.settings_manager import DEFAULT_SETTINGS
from gui.dashboard import DashboardView

REGS = [
    {"addr": 0x10, "name": "Пуск", "type": "SHORT", "rw": "RW"},
    {"addr": 0x11, "name": "Ток", "type": "SHORT", "rw": "RW",
     "unit": "А", "scale": 0.01},
    {"addr": 0x12, "name": "Режим", "type": "SHORT", "rw": "RW",
     "enum": {"0": "Стоп", "1": "Работа", "2": "Авария"}},
]


@pytest.fixture()
def view():
    ctx = AppContext(dict(DEFAULT_SETTINGS, dash_widgets=[], dash_links=[]))
    v = DashboardView(ctx, lambda: REGS)
    v.set_edit(False)
    yield v
    v.stop_if_running()
    v.deleteLater()


def _writes(view):
    got = []
    view.write_requested.connect(lambda a, d, val: got.append((a, d, val)))
    return got


def test_button_writes_its_value(view):
    got = _writes(view)
    view._make_card({"uid": "b1", "kind": "button", "reg_id": "0x0010",
                     "reg_type": "SHORT", "value_on": 7, "x": 0, "y": 0})
    view.fire("b1")
    assert got == [(0x10, "SHORT", "7")]


def test_toggle_alternates_values(view):
    got = _writes(view)
    view._make_card({"uid": "t1", "kind": "toggle", "reg_id": "0x0010",
                     "reg_type": "SHORT", "value_on": 1, "value_off": 0,
                     "x": 0, "y": 0})
    view.fire("t1")
    view.fire("t1")
    assert [v for _, _, v in got] == ["1", "0"]


def test_input_sends_typed_payload(view):
    got = _writes(view)
    view._make_card({"uid": "i1", "kind": "input", "reg_id": "0x0010",
                     "reg_type": "SHORT", "x": 0, "y": 0})
    view.cards["i1"].editor.setText("42")
    view.fire("i1")
    assert got == [(0x10, "SHORT", "42")]


def test_dashboard_write_applies_scaling(view):
    """Register 0x11 has scale 0.01 — the operator's 12.34 A must reach the
    device as the RAW 1234, exactly like a write from the register table."""
    got = _writes(view)
    view._make_card({"uid": "b2", "kind": "button", "reg_id": "0x0011",
                     "reg_type": "SHORT", "value_on": 12.34, "x": 0, "y": 0})
    view.fire("b2")
    addr, dtype, text = got[0]
    assert addr == 0x11 and abs(float(text) - 1234) < 1e-6


def test_wire_timer_to_button_fires_write(view):
    """The headline scenario: a 1 s timer 'presses' a button that writes."""
    got = _writes(view)
    view._make_card({"uid": "tm", "kind": "timer", "interval": 1000,
                     "x": 0, "y": 0})
    view._make_card({"uid": "bt", "kind": "button", "reg_id": "0x0010",
                     "reg_type": "SHORT", "value_on": 5, "x": 300, "y": 0})
    view.graph.add("tm", "bt")
    view._on_tick("tm")                      # simulate one tick
    assert got == [(0x10, "SHORT", "5")]


def test_wire_chain_propagates(view):
    got = _writes(view)
    for i, uid in enumerate(("a", "b", "c")):
        view._make_card({"uid": uid, "kind": "button", "reg_id": "0x0010",
                         "reg_type": "SHORT", "value_on": i, "x": i * 60, "y": 0})
    view.graph.add("a", "b")
    view.graph.add("b", "c")
    view.fire("a")
    assert [v for _, _, v in got] == ["0", "1", "2"]


def test_edit_mode_blocks_all_writes(view):
    got = _writes(view)
    view._make_card({"uid": "b1", "kind": "button", "reg_id": "0x0010",
                     "reg_type": "SHORT", "value_on": 1, "x": 0, "y": 0})
    view.set_edit(True)
    view.fire("b1")
    view._on_tick("b1")
    assert got == []                          # nothing reaches the device


def test_edit_mode_stops_timers(view):
    view._make_card({"uid": "tm", "kind": "timer", "interval": 100,
                     "autostart": True, "x": 0, "y": 0})
    view._start_timer("tm")
    assert "tm" in view._timers
    view.set_edit(True)
    assert view._timers == {}                 # stopped while arranging
    view.set_edit(False)                      # autostart resumes on run mode
    assert "tm" in view._timers


def test_timer_toggle_by_click(view):
    view._make_card({"uid": "tm", "kind": "timer", "interval": 100,
                     "x": 0, "y": 0})
    view.fire("tm")
    assert "tm" in view._timers and view.cards["tm"].state_on
    view.fire("tm")
    assert "tm" not in view._timers and not view.cards["tm"].state_on


def test_removing_widget_drops_its_wires(view):
    view._make_card({"uid": "a", "kind": "timer", "x": 0, "y": 0})
    view._make_card({"uid": "b", "kind": "button", "reg_id": "0x0010",
                     "x": 100, "y": 0})
    view.graph.add("a", "b")
    view._remove_card("b")
    assert view.graph.as_list() == []
    assert view.ctx.settings["dash_links"] == []


def test_links_persist_in_settings(view):
    view._make_card({"uid": "a", "kind": "timer", "x": 0, "y": 0})
    view._make_card({"uid": "b", "kind": "button", "reg_id": "0x0010",
                     "x": 100, "y": 0})
    view.graph.add("a", "b")
    view._persist()
    assert view.ctx.settings["dash_links"] == [{"from": "a", "to": "b"}]


def test_flash_animation_survives_card_deletion(view):
    """Regression: the activation pulse is a QVariantAnimation whose callback
    touches the card. Deleting the card mid-pulse used to dereference a dead
    C++ object — an access violation that killed the whole process."""
    view._make_card({"uid": "b1", "kind": "button", "reg_id": "0x0010",
                     "reg_type": "SHORT", "value_on": 1, "x": 0, "y": 0})
    view.fire("b1")                       # starts the pulse
    view._remove_card("b1")               # card dies while it animates
    for _ in range(8):
        QApplication.processEvents()      # queued animation steps fire here
    assert "b1" not in view.cards         # reaching here without a crash = pass


def test_dialog_result_creates_a_card(view):
    """Regression: the dialog returned x/y/w/h = None for a NEW widget and
    int(None) blew up inside the click handler — the widget silently never
    appeared. Exercise the real dialog → add path."""
    from gui.dashboard_dialog import WidgetDialog
    dlg = WidgetDialog(view.ctx, REGS, None, view)
    dlg._accept()
    cfg = dlg.result_cfg
    assert cfg and cfg["kind"] == "value"
    assert "w" not in cfg or cfg["w"]          # never a None geometry
    cfg["x"], cfg["y"] = view._free_slot(cfg["kind"])
    card = view._make_card(cfg)                # used to raise TypeError
    assert card.width() > 0 and card.height() > 0
    assert cfg["uid"] in view.cards


def test_dialog_tile_picker_switches_kind(view):
    from gui.dashboard_dialog import WidgetDialog
    from core import dash_model as dm
    dlg = WidgetDialog(view.ctx, REGS, None, view)
    assert set(dlg._tiles) == set(dm.KINDS)     # every kind has a tile
    dlg._select_kind("timer")
    assert dlg.current_kind() == "timer"
    assert not dlg.row_reg.isVisibleTo(dlg)     # logic kinds need no register
    dlg._accept()
    assert dlg.result_cfg["kind"] == "timer"
    assert "reg_id" not in dlg.result_cfg


def test_zoom_scales_cards_but_not_config(view):
    from core import dash_model as dm
    view._make_card({"uid": "z", "kind": "value", "reg_id": "0x0010",
                     "x": 100, "y": 50, "w": 200, "h": 100})
    card = view.cards["z"]
    view.zoom_by(2.0)
    assert view.zoom == pytest.approx(2.0)
    assert (card.x(), card.y()) == (200, 100)   # on-screen doubled
    assert (card.cfg["x"], card.cfg["y"]) == (100, 50)   # model untouched
    view.zoom_reset()
    assert (card.x(), card.y()) == (100, 50)


def test_zoom_is_clamped(view):
    from core import dash_model as dm
    for _ in range(40):
        view.zoom_by(1.5)
    assert view.zoom <= dm.ZOOM_MAX
    for _ in range(60):
        view.zoom_by(1 / 1.5)
    assert view.zoom >= dm.ZOOM_MIN


def test_persist_stores_logical_geometry_while_zoomed(view):
    view._make_card({"uid": "z", "kind": "value", "reg_id": "0x0010",
                     "x": 40, "y": 20, "w": 200, "h": 100})
    view.zoom_by(2.0)
    view._persist()
    saved = view.ctx.settings["dash_widgets"][0]
    assert (saved["x"], saved["y"], saved["w"]) == (40, 20, 200)


def test_nudge_moves_selected_widget(view):
    from core import dash_model as dm
    view._make_card({"uid": "n", "kind": "value", "reg_id": "0x0010",
                     "x": 100, "y": 100})
    view._nudge("n", dm.NUDGE_BIG, 0)
    assert view.cards["n"].cfg["x"] == 100 + dm.NUDGE_BIG


def test_wire_drag_marks_candidates_and_connects(view):
    from PyQt6.QtCore import QPoint
    view._make_card({"uid": "tm", "kind": "timer", "x": 0, "y": 0,
                     "w": 180, "h": 100})
    view._make_card({"uid": "bt", "kind": "button", "reg_id": "0x0010",
                     "x": 300, "y": 0, "w": 180, "h": 100})
    view.set_edit(True)
    view._on_wire_started("tm")
    assert view.cards["bt"].wire_candidate      # legal target lights up
    assert not view.cards["tm"].wire_candidate  # never itself
    target = view.cards["bt"]
    g = view.canvas.mapToGlobal(target.pos() + QPoint(20, 40))
    view._on_wire_moved(g)
    assert view._wire_hover == "bt"             # hover detected
    view._on_wire_finished(g)
    assert view.graph.as_list() == [{"from": "tm", "to": "bt"}]
    assert not view.cards["bt"].wire_candidate  # highlight cleared


def test_legacy_single_dashboard_is_migrated():
    """Pre-1.6 settings kept ONE dashboard in dash_widgets/dash_links — it must
    come back as board #1, not vanish."""
    ctx = AppContext(dict(
        DEFAULT_SETTINGS, dashboards=[],
        dash_widgets=[{"uid": "a", "kind": "value", "reg_id": "0x0010",
                       "x": 10, "y": 10}],
        dash_links=[]))
    v = DashboardView(ctx, lambda: REGS)
    assert len(v.boards) == 1
    assert "a" in v.cards
    assert v.boards[0]["name"]                    # auto-named, never blank
    v.deleteLater()


def test_add_and_switch_boards(view):
    view._make_card({"uid": "one", "kind": "value", "reg_id": "0x0010",
                     "x": 10, "y": 10})
    view.add_board("Наладка")
    assert len(view.boards) == 2 and view.index == 1
    assert view.cards == {}                       # the new board is empty
    view._make_card({"uid": "two", "kind": "button", "reg_id": "0x0010",
                     "x": 20, "y": 20})
    view._persist()
    view.switch_board(0)
    assert set(view.cards) == {"one"}             # first board restored
    view.switch_board(1)
    assert set(view.cards) == {"two"}


def test_boards_keep_their_own_wires(view):
    view._make_card({"uid": "t", "kind": "timer", "x": 0, "y": 0})
    view._make_card({"uid": "b", "kind": "button", "reg_id": "0x0010",
                     "x": 200, "y": 0})
    view.graph.add("t", "b")
    view.add_board("Второй")
    assert view.graph.as_list() == []             # fresh board, no wires
    view.switch_board(0)
    assert view.graph.as_list() == [{"from": "t", "to": "b"}]


def test_delete_board_keeps_at_least_one(view):
    view.add_board("B2")
    view._delete_board()
    assert len(view.boards) == 1
    view._delete_board()                          # refuses to remove the last
    assert len(view.boards) == 1


def test_all_boards_captures_live_screen(view):
    view._make_card({"uid": "x", "kind": "value", "reg_id": "0x0010",
                     "x": 5, "y": 5})
    boards = view.all_boards()
    assert boards[0]["widgets"][0]["uid"] == "x"


def test_load_boards_replaces_everything(view):
    view._make_card({"uid": "old", "kind": "value", "reg_id": "0x0010"})
    view.load_boards([
        {"name": "A", "widgets": [{"uid": "n1", "kind": "label", "x": 0, "y": 0}],
         "links": []},
        {"name": "B", "widgets": [], "links": []}])
    assert [b["name"] for b in view.boards] == ["A", "B"]
    assert set(view.cards) == {"n1"}
    assert "old" not in view.cards


def _drag_card(view, card, grab, delta, zoom_hint=1.0):
    """Drive a real mouse drag with FIXED global positions (the card moves
    under the cursor, so local coordinates would compound)."""
    from PyQt6.QtCore import QPointF, QEvent
    from PyQt6.QtGui import QMouseEvent
    g0 = card.mapToGlobal(QPointF(grab))
    QApplication.sendEvent(card, QMouseEvent(
        QEvent.Type.MouseButtonPress, QPointF(grab), g0,
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier))
    for f in (0.2, 0.6, 1.0):
        g = g0 + QPointF(delta[0] * f, delta[1] * f)
        QApplication.sendEvent(card, QMouseEvent(
            QEvent.Type.MouseMove, QPointF(card.mapFromGlobal(g)), g,
            Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier))
    QApplication.sendEvent(card, QMouseEvent(
        QEvent.Type.MouseButtonRelease, QPointF(0, 0),
        g0 + QPointF(*delta), Qt.MouseButton.LeftButton,
        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier))


def test_drag_keeps_the_grabbed_point_under_the_cursor(view):
    """Regression: the card used to teleport so the cursor sat at its top
    centre. A drag must translate the card by the cursor delta, no jump."""
    from PyQt6.QtCore import QPoint
    view._make_card({"uid": "d", "kind": "value", "reg_id": "0x0010",
                     "x": 50, "y": 50, "w": 250, "h": 150})
    view.set_edit(True)
    card = view.cards["d"]
    _drag_card(view, card, QPoint(100, 70), (80, 80))
    # +80 px, then snapped to the 4 px grid — never a jump to the cursor.
    assert abs(card.cfg["x"] - 130) <= 4
    assert abs(card.cfg["y"] - 130) <= 4


def test_drag_is_zoom_aware(view):
    from PyQt6.QtCore import QPoint
    view._make_card({"uid": "z", "kind": "value", "reg_id": "0x0010",
                     "x": 50, "y": 50, "w": 250, "h": 150})
    view.set_edit(True)
    view.zoom_by(2.0)
    card = view.cards["z"]
    _drag_card(view, card, QPoint(60, 40), (60, 0))
    # 60 screen px at 2× zoom == 30 logical px
    assert abs(card.cfg["x"] - 80) <= 4


# ── v6 kinds: slider / select / gate / bits / chart ─────────────────────
def test_slider_writes_on_release_not_while_dragging(view):
    """A setpoint slider must not spray writes at the device on every mouse
    move — one write when the operator lets go."""
    from PyQt6.QtCore import QPoint
    got = _writes(view)
    view._make_card({"uid": "s", "kind": "slider", "reg_id": "0x0010",
                     "reg_type": "SHORT", "vmin": 0, "vmax": 100, "step": 1,
                     "x": 0, "y": 0, "w": 280, "h": 115})
    card = view.cards["s"]
    track = card.slider_track()
    _drag_card(view, card, QPoint(int(track.left()), int(track.center().y())),
               (int(track.width() / 2), 0))
    assert len(got) == 1                       # exactly one write, on release
    assert abs(float(got[0][2]) - 50) <= 2     # ~half way along the track
    assert card._slider_frac is None           # follows the register again


def test_slider_live_mode_writes_while_dragging(view):
    from PyQt6.QtCore import QPoint
    got = _writes(view)
    view._make_card({"uid": "s", "kind": "slider", "reg_id": "0x0010",
                     "reg_type": "SHORT", "vmin": 0, "vmax": 100, "step": 1,
                     "live": True, "x": 0, "y": 0, "w": 280, "h": 115})
    card = view.cards["s"]
    track = card.slider_track()
    _drag_card(view, card, QPoint(int(track.left()), int(track.center().y())),
               (int(track.width()), 0))
    assert len(got) > 1                        # opted in to continuous writes


def test_slider_snaps_to_its_step(view):
    view._make_card({"uid": "s", "kind": "slider", "reg_id": "0x0010",
                     "vmin": 0, "vmax": 100, "step": 25,
                     "x": 0, "y": 0, "w": 280, "h": 115})
    card = view.cards["s"]
    card.slider_set_from_x(card.slider_track().center().x())
    assert card.slider_value() in (50.0, 50)


def test_slider_is_inert_in_edit_mode(view):
    """Edit mode is the safety gate: dragging a slider arranges it, never
    writes to the device."""
    from PyQt6.QtCore import QPoint
    got = _writes(view)
    view._make_card({"uid": "s", "kind": "slider", "reg_id": "0x0010",
                     "vmin": 0, "vmax": 100, "x": 0, "y": 0, "w": 280, "h": 115})
    view.set_edit(True)
    card = view.cards["s"]
    _drag_card(view, card, QPoint(40, 60), (90, 0))
    assert got == []
    assert card.cfg["x"] != 0                  # it moved instead


def test_select_takes_its_options_from_the_register_enum(view):
    """The dialog snapshots the enum, so labels survive opening the dashboard
    without that profile loaded."""
    from gui.dashboard_dialog import WidgetDialog
    dlg = WidgetDialog(view.ctx, REGS, None, view)
    dlg._select_kind("select")
    dlg.combo_reg.setCurrentIndex(2)           # 0x0012 has the enum
    dlg._accept()
    cfg = dlg.result_cfg
    assert cfg["options"] == [[0, "Стоп"], [1, "Работа"], [2, "Авария"]]
    cfg["x"], cfg["y"] = 0, 0
    card = view._make_card(cfg)
    card.value = 1
    assert card.select_label() == "Работа"


def test_select_writes_the_picked_value(view):
    got = _writes(view)
    view._make_card({"uid": "sel", "kind": "select", "reg_id": "0x0012",
                     "reg_type": "SHORT", "options": [[0, "Стоп"], [2, "Авария"]],
                     "x": 0, "y": 0})
    view.fire("sel", 2)
    assert got == [(0x12, "SHORT", "2")]


def test_gate_blocks_the_pulse_until_its_condition_holds(view):
    """timer → gate(temp > 80) → button: the button only fires while the
    watched register is over the limit."""
    got = _writes(view)
    view._make_card({"uid": "tm", "kind": "timer", "interval": 1000,
                     "x": 0, "y": 0})
    view._make_card({"uid": "g", "kind": "gate", "reg_id": "0x0011",
                     "cond": "gt", "cmp": 80, "x": 200, "y": 0})
    view._make_card({"uid": "bt", "kind": "button", "reg_id": "0x0010",
                     "reg_type": "SHORT", "value_on": 1, "x": 400, "y": 0})
    view.graph.add("tm", "g")
    view.graph.add("g", "bt")

    view.cards["g"].update_value(20)
    view._on_tick("tm")
    assert got == []                           # gate closed: nothing written

    view.cards["g"].update_value(95)
    view._on_tick("tm")
    assert got == [(0x10, "SHORT", "1")]       # gate open: chain completes


def test_gate_with_no_value_fails_closed(view):
    """A gate that cannot read its register must NOT pass — a disconnected
    device would otherwise keep firing writes."""
    got = _writes(view)
    view._make_card({"uid": "tm", "kind": "timer", "x": 0, "y": 0})
    view._make_card({"uid": "g", "kind": "gate", "reg_id": "0x0011",
                     "cond": "gt", "cmp": 0, "x": 200, "y": 0})
    view._make_card({"uid": "bt", "kind": "button", "reg_id": "0x0010",
                     "value_on": 1, "x": 400, "y": 0})
    view.graph.add("tm", "g")
    view.graph.add("g", "bt")
    view._on_tick("tm")                        # gate never got a sample
    assert got == []


def test_gate_still_flashes_when_it_blocks(view):
    """The gate is reached (so the operator sees where the chain stopped) even
    though the pulse goes no further."""
    view._make_card({"uid": "tm", "kind": "timer", "x": 0, "y": 0})
    view._make_card({"uid": "g", "kind": "gate", "reg_id": "0x0011",
                     "cond": "gt", "cmp": 80, "x": 200, "y": 0})
    view.graph.add("tm", "g")
    view.cards["g"].update_value(10)
    view._on_tick("tm")
    assert view.cards["g"].pulse > 0


def test_pulse_lights_only_the_wires_it_travelled(view):
    """A blocked branch must stay dark — that highlight is how the operator
    reads where the automation actually went."""
    view._make_card({"uid": "tm", "kind": "timer", "x": 0, "y": 0})
    view._make_card({"uid": "g", "kind": "gate", "reg_id": "0x0011",
                     "cond": "gt", "cmp": 80, "x": 200, "y": 0})
    view._make_card({"uid": "bt", "kind": "button", "reg_id": "0x0010",
                     "value_on": 1, "x": 400, "y": 0})
    view.graph.add("tm", "g")
    view.graph.add("g", "bt")

    view.cards["g"].update_value(10)           # gate closed
    view._on_tick("tm")
    assert ("tm", "g") in view._hot_links      # reached the gate
    assert ("g", "bt") not in view._hot_links  # …and stopped there

    view._hot_links.clear()
    view.cards["g"].update_value(99)           # gate open
    view._on_tick("tm")
    assert {("tm", "g"), ("g", "bt")} <= set(view._hot_links)


def test_bits_and_chart_are_read_only(view):
    """Clicking a readout must never write, whatever the kind."""
    got = _writes(view)
    for i, k in enumerate(("bits", "chart", "value", "led", "bar", "gauge")):
        view._make_card({"uid": f"d{i}", "kind": k, "reg_id": "0x0010",
                         "x": i * 20, "y": 0})
        view.fire(f"d{i}")
    assert got == []


def test_chart_keeps_a_longer_history_than_the_sparkline(view):
    from gui import dashboard as gui_dash
    view._make_card({"uid": "c", "kind": "chart", "reg_id": "0x0010",
                     "x": 0, "y": 0})
    view._make_card({"uid": "v", "kind": "value", "reg_id": "0x0010",
                     "x": 300, "y": 0})
    assert view.cards["c"].history.maxlen == gui_dash.CHART_LEN
    assert view.cards["v"].history.maxlen == gui_dash.SPARK_LEN


def test_every_kind_can_be_added_through_the_dialog(view):
    """Real path: pick each tile, accept, build the card. Guards against a new
    kind that the dialog can produce but the view cannot render."""
    from gui.dashboard_dialog import WidgetDialog
    from core import dash_model as dm
    for k in dm.KINDS:
        dlg = WidgetDialog(view.ctx, REGS, None, view)
        dlg._select_kind(k)
        dlg._accept()
        cfg = dlg.result_cfg
        assert cfg is not None and cfg["kind"] == k
        cfg["x"], cfg["y"] = view._free_slot(k)
        card = view._make_card(cfg)
        assert card.width() > 0
        dlg.deleteLater()


def _send(widget, typ, local, button=Qt.MouseButton.NoButton,
          buttons=Qt.MouseButton.NoButton, global_pos=None):
    from PyQt6.QtCore import QPointF, QEvent
    from PyQt6.QtGui import QMouseEvent
    g = global_pos if global_pos is not None else widget.mapToGlobal(QPointF(local))
    QApplication.sendEvent(widget, QMouseEvent(
        typ, QPointF(local), g, button, buttons, Qt.KeyboardModifier.NoModifier))


def test_double_click_to_edit_does_not_leave_the_card_glued_to_the_cursor(view):
    """Regression: the press before a double-click armed a move, the modal edit
    dialog swallowed the release, and afterwards the card followed the mouse
    with no button held. Qt's default double-click handler re-forwards to
    mousePressEvent, so the handler must NOT call super() either."""
    from PyQt6.QtCore import QPoint, QPointF, QEvent
    view._make_card({"uid": "d", "kind": "value", "reg_id": "0x0010",
                     "x": 50, "y": 50, "w": 250, "h": 150})
    view.set_edit(True)
    card = view.cards["d"]
    edited = []
    # The view opens a MODAL dialog on this signal — swap in a recorder so the
    # test exercises the gesture, not the dialog.
    card.edit_requested.disconnect()
    card.edit_requested.connect(edited.append)

    _send(card, QEvent.Type.MouseButtonPress, QPoint(120, 80),
          Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton)
    _send(card, QEvent.Type.MouseButtonDblClick, QPoint(120, 80),
          Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton)
    assert edited == ["d"]                      # the dialog was requested
    assert card._mode is None and card._press is None

    # …now the user moves the mouse away with NO button held
    far = card.mapToGlobal(QPointF(400, 300))
    _send(card, QEvent.Type.MouseMove, card.mapFromGlobal(far), global_pos=far)
    assert (card.cfg["x"], card.cfg["y"]) == (50, 50)


def test_a_lost_release_cancels_the_drag(view):
    """Any gesture whose release goes missing (menu, dialog, focus loss) must
    end the moment a move arrives with the button up."""
    from PyQt6.QtCore import QPoint, QPointF, QEvent
    view._make_card({"uid": "d", "kind": "value", "reg_id": "0x0010",
                     "x": 50, "y": 50, "w": 250, "h": 150})
    view.set_edit(True)
    card = view.cards["d"]
    _send(card, QEvent.Type.MouseButtonPress, QPoint(60, 60),
          Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton)
    g = card.mapToGlobal(QPointF(90, 90))
    _send(card, QEvent.Type.MouseMove, card.mapFromGlobal(g),
          buttons=Qt.MouseButton.LeftButton, global_pos=g)   # real drag
    moved_to = (card.cfg["x"], card.cfg["y"])
    assert moved_to != (50, 50)

    g2 = card.mapToGlobal(QPointF(300, 300))
    _send(card, QEvent.Type.MouseMove, card.mapFromGlobal(g2), global_pos=g2)
    assert (card.cfg["x"], card.cfg["y"]) == moved_to        # frozen
    assert card._mode is None


def test_zoom_scales_content_not_just_the_box(view):
    """Cards paint in LOGICAL pixels under a scaled painter, so a card at 200 %
    is the same card twice the size — fonts and ports included. The invariant:
    every logical measurement is identical at any zoom."""
    from PyQt6.QtCore import QPoint
    view._make_card({"uid": "z", "kind": "gauge", "reg_id": "0x0010",
                     "x": 10, "y": 10, "w": 250, "h": 150})
    card = view.cards["z"]
    at1 = (card.pw, card.ph, card._fit_pt(24),
           card.in_port_pos(), card.out_port_pos(), card._handle_rect())
    view.zoom_by(2.0)
    assert card.width() == 500 and card.height() == 300      # box doubled
    at2 = (card.pw, card.ph, card._fit_pt(24),
           card.in_port_pos(), card.out_port_pos(), card._handle_rect())
    assert at1 == at2                                        # logic unchanged
    # …and the mouse maps back: a click at the far corner is the far corner
    assert card.to_logical(QPoint(500, 300)) == QPoint(250, 150)


def test_drag_tracks_the_cursor_exactly_when_zoomed(view):
    """The grab offset is logical now; a mis-matched unit here shows up as the
    card sliding away from the pointer as you drag."""
    from PyQt6.QtCore import QPoint
    view._make_card({"uid": "z", "kind": "value", "reg_id": "0x0010",
                     "x": 40, "y": 40, "w": 250, "h": 150})
    view.set_edit(True)
    view.zoom_by(2.0)
    card = view.cards["z"]
    _drag_card(view, card, QPoint(120, 80), (100, 0))   # 100 screen px
    assert abs(card.cfg["x"] - (40 + 50)) <= 4          # == 50 logical px


def test_canvas_always_has_room_to_pan(view):
    """pan_by moves the scrollbars; a canvas exactly the size of its viewport
    has zero range, so panning silently did nothing."""
    from PyQt6.QtCore import QPoint
    view.resize(900, 600)
    view.show()
    QApplication.processEvents()
    view._grow_canvas()
    h = view.scroll.horizontalScrollBar()
    v = view.scroll.verticalScrollBar()
    assert h.maximum() > 0 and v.maximum() > 0
    before = (h.value(), v.value())
    view.pan_by(QPoint(80, 60))
    assert (h.value(), v.value()) != before


def test_right_drag_over_a_widget_pans_instead_of_dying(view):
    """The gesture used to be swallowed by whatever card sat under the cursor."""
    from PyQt6.QtCore import QPoint, QPointF, QEvent
    view.resize(900, 600)
    view.show()
    QApplication.processEvents()
    view._make_card({"uid": "d", "kind": "value", "reg_id": "0x0010",
                     "x": 40, "y": 40, "w": 250, "h": 150})
    view.set_edit(True)
    card = view.cards["d"]
    h = view.scroll.horizontalScrollBar()
    h.setValue(80)
    start = h.value()
    _send(card, QEvent.Type.MouseButtonPress, QPoint(100, 60),
          Qt.MouseButton.RightButton, Qt.MouseButton.RightButton)
    g = card.mapToGlobal(QPointF(40, 60))          # drag left by 60 px
    _send(card, QEvent.Type.MouseMove, card.mapFromGlobal(g),
          buttons=Qt.MouseButton.RightButton, global_pos=g)
    assert h.value() != start
    assert (card.cfg["x"], card.cfg["y"]) == (40, 40)   # the card never moved


def test_value_index_follows_card_edits(view):
    """update_value uses a reg_id index; a stale index would silently freeze a
    widget after its register was changed or the card removed."""
    view._make_card({"uid": "a", "kind": "value", "reg_id": "0x0010", "x": 0, "y": 0})
    view._make_card({"uid": "b", "kind": "value", "reg_id": "0x0010", "x": 300, "y": 0})
    view.update_value("0x0010", 7)
    assert view.cards["a"].value == 7 and view.cards["b"].value == 7

    view.cards["b"].cfg["reg_id"] = "0x0011"     # as _edit_widget does
    view._invalidate_index()
    view.update_value("0x0010", 9)
    assert view.cards["a"].value == 9
    assert view.cards["b"].value == 7            # no longer bound to 0x0010
    view.update_value("0x0011", 11)
    assert view.cards["b"].value == 11

    view._remove_card("a")
    view.update_value("0x0010", 13)              # must not touch a dead card


def test_picker_fits_every_kind_in_both_languages(view):
    """Layout guard: adding a kind must not push a tile past the dialog card,
    elide its label, or grow the dialog past a 768 px laptop screen."""
    from PyQt6.QtGui import QFontMetrics
    from PyQt6.QtWidgets import QFrame
    from app.app_context import AppContext
    from gui.dashboard_dialog import WidgetDialog
    from core import dash_model as dm
    for lang in ("ru", "en"):
        ctx = AppContext(dict(DEFAULT_SETTINGS, lang=lang))
        dlg = WidgetDialog(ctx, REGS, None, view)
        dlg.show()
        QApplication.processEvents()
        card = dlg.findChild(QFrame, "dlgCard")
        for k, tile in dlg._tiles.items():
            tile.ensurePolished()
            adv = QFontMetrics(tile.font()).horizontalAdvance(tile.text())
            assert adv <= tile.width() - 4, f"{lang}/{k}: label {tile.text()!r} elides"
            assert tile.mapTo(card, tile.rect().topRight()).x() <= card.width() - 8, \
                f"{lang}/{k}: tile sticks out of the dialog"
        # The dialog must be the SAME size for every kind — it used to grow and
        # shrink by ~170 px as rows appeared, which read as random padding.
        heights = set()
        for k in dm.KINDS:
            dlg._select_kind(k)
            QApplication.processEvents()
            heights.add(dlg.sizeHint().height())
        assert len(heights) == 1, f"{lang}: dialog resizes per kind: {sorted(heights)}"
        assert max(heights) <= 720, f"{lang}: dialog too tall ({max(heights)})"
        dlg.close()
        dlg.deleteLater()


def test_control_widgets_only_offer_writable_registers(view):
    """Offering a read-only register to a button/slider is a write that the
    device will refuse — the picker must not show it at all."""
    from app.app_context import AppContext
    from gui.dashboard_dialog import WidgetDialog
    from core import dash_model as dm
    regs = [{"addr": 0x10, "name": "Уставка", "type": "SHORT", "rw": "RW"},
            {"addr": 0x11, "name": "Только чтение", "type": "SHORT", "rw": "R"},
            {"addr": 0x12, "name": "Команда", "type": "SHORT", "rw": "W"}]
    ctx = AppContext(dict(DEFAULT_SETTINGS))
    dlg = WidgetDialog(ctx, regs, None, view)
    for k, spec in dm.KINDS.items():
        dlg._select_kind(k)
        addrs = {r["addr"] for r in dlg._regs}
        if spec.writes:
            assert addrs == {0x10, 0x12}, f"{k} offers a read-only register"
        else:
            assert addrs == {0x10, 0x11, 0x12}, f"{k} hides readable registers"
    dlg.deleteLater()


def test_read_only_map_disables_the_register_picker_for_controls(view, monkeypatch):
    from app.app_context import AppContext
    from gui.dashboard_dialog import WidgetDialog
    from gui import dialogs
    told = []
    monkeypatch.setattr(dialogs, "themed_info",
                        lambda *a, **k: told.append(a[4]))
    ctx = AppContext(dict(DEFAULT_SETTINGS))
    dlg = WidgetDialog(ctx, [{"addr": 1, "name": "RO", "type": "SHORT", "rw": "R"}],
                       None, view)
    dlg._select_kind("button")
    assert dlg._regs == [] and not dlg.combo_reg.isEnabled()
    assert dlg.combo_reg.placeholderText()          # says why, not blank
    dlg._accept()
    assert dlg.result_cfg is None                   # cannot create a broken widget
    # …and it SAYS so instead of the dialog silently closing on «Add».
    assert told == [ctx.t("dashNoWritableReg")]
    dlg.deleteLater()


def test_new_cards_do_not_overlap(view):
    for i in range(3):
        cfg = {"uid": f"u{i}", "kind": "value", "reg_id": "0x0010"}
        cfg["x"], cfg["y"] = view._free_slot("value")
        view._make_card(cfg)
    rects = [(c.x(), c.y()) for c in view.cards.values()]
    assert len(set(rects)) == 3               # every card got its own slot


def test_duplicate_uids_in_a_file_do_not_orphan_a_widget(view):
    """Cards are keyed by uid: with two equal uids the first card stayed on
    screen but dropped out of the board — no values, no selection, not saved."""
    view.load_boards([{"name": "B", "links": [], "widgets": [
        {"uid": "same", "kind": "value", "reg_id": "0x0010", "x": 0, "y": 0},
        {"uid": "same", "kind": "value", "reg_id": "0x0011", "x": 300, "y": 0},
    ]}])
    assert len(view.cards) == 2
    view.update_value("0x0010", 5.0)
    view.update_value("0x0011", 7.0)
    assert sorted(c.value for c in view.cards.values()) == [5.0, 7.0]
