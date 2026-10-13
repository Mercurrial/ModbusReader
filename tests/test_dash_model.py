"""Dashboard model: kind registry, alignment snapping, automation graph."""
import pytest

import dash_model as dm


# ── kind registry ───────────────────────────────────────────────────────
def test_kind_registry_shape():
    assert set(dm.DISPLAY_KINDS) == {"value", "led", "bar", "gauge", "bits", "chart"}
    assert set(dm.CONTROL_KINDS) == {"button", "input", "toggle", "slider", "select"}
    assert set(dm.LOGIC_KINDS) == {"timer", "gate", "label"}
    # every control writes and accepts a wire
    for k in dm.CONTROL_KINDS:
        assert dm.kind(k).writes and dm.kind(k).has_in
    # displays never write — a readout must not be able to touch the device
    for k in dm.DISPLAY_KINDS:
        assert dm.kind(k).bound and not dm.kind(k).writes
    assert dm.kind("nonsense").key == "value"          # safe fallback


def test_groups_cover_every_kind_exactly_once():
    """The picker is derived from the descriptors: a new kind must appear in
    exactly one section, otherwise it is unreachable in the UI."""
    listed = [k for _, keys in dm.KIND_GROUPS for k in keys]
    assert sorted(listed) == sorted(dm.KINDS)
    assert len(listed) == len(set(listed))


def test_default_and_min_sizes():
    w, h = dm.default_size("gauge")
    mw, mh = dm.min_size("gauge")
    assert w >= mw and h >= mh


# ── snapping ────────────────────────────────────────────────────────────
def test_snap_to_grid():
    assert dm.snap_to_grid(13) == 12                    # GRID = 4
    assert dm.snap_to_grid(14) == 16


def test_snap_aligns_left_edges():
    other = (100, 100, 200, 100)                        # x=100
    moving = (104, 300, 200, 100)                       # 4 px off -> snaps
    r = dm.compute_snap(moving, [other])
    assert r.x == 100
    assert 100 in r.v_guides


def test_snap_aligns_centers():
    other = (100, 100, 200, 100)                        # center x = 200
    moving = (98, 400, 204, 100)                        # center 200 -> lock
    r = dm.compute_snap(moving, [other])
    assert r.x + 204 / 2 == 200


def test_snap_aligns_top_and_bottom():
    other = (0, 200, 100, 100)                          # top 200, bottom 300
    r = dm.compute_snap((500, 203, 100, 100), [other])
    assert r.y == 200 and 200 in r.h_guides
    r2 = dm.compute_snap((500, 298, 100, 50), [other])  # top near other bottom
    assert r2.y == 300


def test_snap_beyond_threshold_falls_back_to_grid():
    other = (100, 100, 200, 100)
    r = dm.compute_snap((131, 500, 200, 100), [other])  # 31 px away
    assert r.x == 132 and r.v_guides == []              # grid, no guide


def test_snap_disabled_returns_raw():
    r = dm.compute_snap((103, 207, 200, 100), [(100, 200, 200, 100)],
                        enabled=False)
    assert (r.x, r.y) == (103, 207) and not r.v_guides


def test_snap_to_canvas_center():
    r = dm.compute_snap((398, 10, 200, 100), [], canvas=(1000, 800))
    assert r.x + 100 == 500                              # centered on canvas


def test_clamp_rect_keeps_widget_inside():
    x, y = dm.clamp_rect(-50, -50, 100, 100)
    assert x >= dm.CANVAS_MARGIN and y >= dm.CANVAS_MARGIN
    x, y = dm.clamp_rect(950, 10, 200, 100, canvas=(1000, 800))
    assert x + 200 <= 1000


def test_flow_positions_matches_old_grid():
    pos = dm.flow_positions(5, canvas_w=800, w=250, h=150, gap=12)
    assert len(pos) == 5
    assert pos[0][1] == pos[1][1]                        # same row
    assert pos[3][1] > pos[0][1]                         # wrapped to next row


# ── automation graph ────────────────────────────────────────────────────
def test_graph_add_rules():
    g = dm.Graph()
    assert g.add("a", "b")
    assert not g.add("a", "b")                           # duplicate
    assert not g.add("a", "a")                           # self-link
    assert not g.add("a", None)
    assert g.as_list() == [{"from": "a", "to": "b"}]


def test_graph_remove_and_widget_cleanup():
    g = dm.Graph([{"from": "a", "to": "b"}, {"from": "b", "to": "c"}])
    assert g.remove("a", "b")
    assert not g.remove("a", "b")
    g.add("a", "c")
    g.remove_widget("c")
    assert g.as_list() == []


def test_graph_propagation_chain():
    g = dm.Graph([{"from": "timer", "to": "btn"},
                  {"from": "btn", "to": "led"}])
    assert g.propagate("timer") == ["btn", "led"]


def test_graph_fanout():
    g = dm.Graph([{"from": "t", "to": "a"}, {"from": "t", "to": "b"}])
    assert sorted(g.propagate("t")) == ["a", "b"]


def test_graph_cycle_terminates():
    g = dm.Graph([{"from": "a", "to": "b"}, {"from": "b", "to": "a"}])
    order = g.propagate("a")
    assert order == ["b"]                                # 'a' not re-fired
    # deep loop also terminates
    g2 = dm.Graph([{"from": "a", "to": "b"}, {"from": "b", "to": "c"},
                   {"from": "c", "to": "a"}])
    assert g2.propagate("a") == ["b", "c"]


def test_graph_sources_and_targets():
    g = dm.Graph([{"from": "a", "to": "c"}, {"from": "b", "to": "c"}])
    assert sorted(g.sources_of("c")) == ["a", "b"]
    assert g.targets_of("a") == ["c"]
