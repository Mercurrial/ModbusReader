# dash_model.py
"""Dashboard model — widget kinds, layout snapping and the automation graph.

PURE module (no Qt, no I/O) so the tricky parts are unit-testable:

  * **Kind registry** — one ``WidgetKind`` descriptor per widget type
    (Descriptor+Registry style, like datatypes.py). Adding a widget kind is
    one entry here plus a paint branch in gui_dash.
  * **Snapping** — PowerPoint-style alignment: while dragging, a widget's
    edges/centers snap to its neighbours' edges/centers and to the canvas
    center, and the matching guide lines are returned so the view can draw
    them. Falls back to a fine grid so free placement still looks tidy.
  * **Automation graph** — widgets are nodes with ONE input and ONE output
    port; wires carry pulses (optionally with a payload). ``propagate()``
    walks the links breadth-first with a depth guard, so a loop
    (timer → button → timer) can never hang the UI.
"""

from dataclasses import dataclass, field

# ── layout constants ────────────────────────────────────────────────────
GRID = 4                 # invisible fine grid: free placement, tidy result
SNAP_THRESHOLD = 7       # px distance at which an alignment guide grabs
CANVAS_MARGIN = 8
ZOOM_MIN, ZOOM_MAX = 0.4, 2.5
NUDGE, NUDGE_BIG = 1, 10        # arrow-key movement (Shift = big step)


# ═══════════════════════════════════════════════════════════════════════
#  WIDGET KIND REGISTRY
# ═══════════════════════════════════════════════════════════════════════
@dataclass(frozen=True)
class WidgetKind:
    """One dashboard widget type.

    key        stable id stored in the config
    label_key  i18n key for the picker
    group      picker section AND semantics: display / control / logic
    bound      needs a register (display/control/gate) vs standalone
    writes     writes to the device when activated
    has_in     accepts a wire (an incoming pulse activates it)
    has_out    emits a pulse (button click, timer tick, gate pass…)
    """
    key: str
    label_key: str
    icon: str = "num"          # icons.py name, used by the tile picker
    group: str = "display"
    bound: bool = True
    writes: bool = False
    has_in: bool = False
    has_out: bool = False
    default_w: int = 250
    default_h: int = 150
    min_w: int = 120
    min_h: int = 70


KINDS: dict[str, WidgetKind] = {k.key: k for k in [
    # ── display (read a register) ──
    WidgetKind("value", "dashKindValue", icon="num", has_out=True),
    WidgetKind("led",   "dashKindLed",   icon="focus", has_out=True,
               default_w=170, default_h=150),
    WidgetKind("bar",   "dashKindBar",   icon="bars", has_out=True),
    WidgetKind("gauge", "dashKindGauge", icon="gauge", has_out=True),
    WidgetKind("bits",  "dashKindBits",  icon="bits", has_out=True,
               default_w=300, default_h=130, min_w=180, min_h=90),
    WidgetKind("chart", "dashKindChart", icon="chart", has_out=True,
               default_w=330, default_h=190, min_w=180, min_h=110),
    # ── controls (write a register) ──
    WidgetKind("button", "dashKindButton", icon="btn", group="control",
               writes=True, has_in=True, has_out=True,
               default_w=180, default_h=90, min_h=60),
    WidgetKind("input",  "dashKindInput",  icon="field", group="control",
               writes=True, has_in=True, has_out=True,
               default_w=250, default_h=110, min_h=90),
    WidgetKind("toggle", "dashKindToggle", icon="switch", group="control",
               writes=True, has_in=True, has_out=True,
               default_w=180, default_h=100, min_h=70),
    WidgetKind("slider", "dashKindSlider", icon="sliders", group="control",
               writes=True, has_in=True, has_out=True,
               default_w=280, default_h=115, min_w=170, min_h=95),
    WidgetKind("select", "dashKindSelect", icon="list", group="control",
               writes=True, has_in=True, has_out=True,
               default_w=250, default_h=115, min_h=95),
    # ── logic / decoration ──
    WidgetKind("timer", "dashKindTimer", icon="clock", group="logic",
               bound=False, has_in=True, has_out=True,
               default_w=180, default_h=100, min_h=80),
    WidgetKind("gate",  "dashKindGate",  icon="gate", group="logic",
               has_in=True, has_out=True,
               default_w=230, default_h=110, min_h=85),
    WidgetKind("label", "dashKindLabel", icon="text", group="logic",
               bound=False, default_w=200, default_h=70, min_h=40),
]}

# Picker sections, derived from the descriptors so a new kind shows up in the
# picker by adding ONE entry above (order follows KINDS insertion order).
GROUP_LABELS = (("display", "dashGroupDisplay"),
                ("control", "dashGroupControl"),
                ("logic",   "dashGroupLogic"))


def _of_group(g: str) -> tuple:
    return tuple(k for k, d in KINDS.items() if d.group == g)


KIND_GROUPS = tuple((label, _of_group(g)) for g, label in GROUP_LABELS)

DISPLAY_KINDS = _of_group("display")
CONTROL_KINDS = _of_group("control")
LOGIC_KINDS = _of_group("logic")
RANGE_KINDS = ("bar", "gauge", "slider", "chart")   # kinds with vmin/vmax


def kind(key: str) -> WidgetKind:
    return KINDS.get(key, KINDS["value"])


# ── gate condition (pure: the view only paints the result) ───────────────
CONDITIONS = ("gt", "ge", "lt", "le", "eq", "ne")
CONDITION_SIGNS = {"gt": ">", "ge": "≥", "lt": "<", "le": "≤",
                   "eq": "=", "ne": "≠"}
_EPS = 1e-9


def gate_pass(cfg: dict, value) -> bool:
    """Does the gate let a pulse through, given the watched register's value?

    An unreadable value never passes — a gate that cannot evaluate must fail
    closed, otherwise a disconnected device would keep firing writes."""
    if value is None:
        return False
    try:
        v = float(value)
        ref = float(cfg.get("cmp", 0))
    except (TypeError, ValueError):
        return False
    cond = str(cfg.get("cond", "gt"))
    if cond == "gt":
        return v > ref
    if cond == "ge":
        return v >= ref
    if cond == "lt":
        return v < ref
    if cond == "le":
        return v <= ref
    if cond == "eq":
        return abs(v - ref) <= _EPS
    if cond == "ne":
        return abs(v - ref) > _EPS
    return False


def default_size(key: str) -> tuple[int, int]:
    k = kind(key)
    return k.default_w, k.default_h


def min_size(key: str) -> tuple[int, int]:
    k = kind(key)
    return k.min_w, k.min_h


# ═══════════════════════════════════════════════════════════════════════
#  LAYOUT: grid + PowerPoint-style alignment guides
# ═══════════════════════════════════════════════════════════════════════
def snap_to_grid(v: int, grid: int = GRID) -> int:
    return int(round(v / grid) * grid)


@dataclass
class SnapResult:
    """Where the dragged widget should land + the guides to draw."""
    x: int
    y: int
    v_guides: list = field(default_factory=list)   # x coords of vertical lines
    h_guides: list = field(default_factory=list)   # y coords of horizontal lines


def _edges_x(rect):
    x, _, w, _ = rect
    return (("left", x), ("center", x + w / 2), ("right", x + w))


def _edges_y(rect):
    _, y, _, h = rect
    return (("top", y), ("middle", y + h / 2), ("bottom", y + h))


def compute_snap(moving, others, canvas=None, threshold: int = SNAP_THRESHOLD,
                 enabled: bool = True) -> SnapResult:
    """Snap the *moving* ``(x, y, w, h)`` rect against *others*.

    Alignment wins over the grid: if any edge/center of the moving rect is
    within *threshold* of a neighbour's (or the canvas centre's) edge/center,
    it locks to it and that guide line is reported. Otherwise the position
    snaps to the fine grid, which keeps free placement visually tidy.
    ``enabled=False`` (Alt held) returns the raw position untouched."""
    x, y, w, h = moving
    if not enabled:
        return SnapResult(int(x), int(y))

    targets_x, targets_y = [], []
    for o in others:
        targets_x += [v for _, v in _edges_x(o)]
        targets_y += [v for _, v in _edges_y(o)]
    if canvas:
        cw, ch = canvas
        targets_x.append(cw / 2)
        targets_y.append(ch / 2)

    best_dx, best_v = None, []
    for _, mv in _edges_x((x, y, w, h)):
        for tv in targets_x:
            d = tv - mv
            if abs(d) <= threshold and (best_dx is None or abs(d) < abs(best_dx)):
                best_dx, best_v = d, [tv]
            elif abs(d) <= threshold and best_dx is not None \
                    and abs(d) == abs(best_dx) and tv not in best_v:
                best_v.append(tv)

    best_dy, best_h = None, []
    for _, mv in _edges_y((x, y, w, h)):
        for tv in targets_y:
            d = tv - mv
            if abs(d) <= threshold and (best_dy is None or abs(d) < abs(best_dy)):
                best_dy, best_h = d, [tv]
            elif abs(d) <= threshold and best_dy is not None \
                    and abs(d) == abs(best_dy) and tv not in best_h:
                best_h.append(tv)

    nx = int(round(x + best_dx)) if best_dx is not None else snap_to_grid(int(x))
    ny = int(round(y + best_dy)) if best_dy is not None else snap_to_grid(int(y))
    return SnapResult(nx, ny,
                      [int(round(v)) for v in best_v] if best_dx is not None else [],
                      [int(round(v)) for v in best_h] if best_dy is not None else [])


def clamp_rect(x, y, w, h, canvas=None):
    """Keep a widget inside the canvas (top-left never negative)."""
    x = max(CANVAS_MARGIN, int(x))
    y = max(CANVAS_MARGIN, int(y))
    if canvas:
        cw, ch = canvas
        if cw > w:
            x = min(x, int(cw - w - CANVAS_MARGIN))
        if ch > h:
            y = min(y, int(ch - h - CANVAS_MARGIN))
    return x, y


def flow_positions(count: int, canvas_w: int, w: int = 250, h: int = 150,
                   gap: int = 12) -> list:
    """Grid positions used to place legacy (pre-v3) cards that have no x/y —
    they keep the exact look they had in the old auto-flow layout."""
    cols = max(1, (canvas_w - gap) // (w + gap)) if canvas_w else 4
    return [(CANVAS_MARGIN + (i % cols) * (w + gap),
             CANVAS_MARGIN + (i // cols) * (h + gap)) for i in range(count)]


# ═══════════════════════════════════════════════════════════════════════
#  AUTOMATION GRAPH (wires)
# ═══════════════════════════════════════════════════════════════════════
MAX_DEPTH = 16           # propagation depth guard — kills feedback loops


class Graph:
    """Directed links between widgets: ``{"from": uid, "to": uid}``.

    One output → many inputs is allowed; the same pair twice is not, and a
    self-link is rejected. ``propagate`` returns the activation order so the
    view can fire the target widgets (and tests can assert the chain)."""

    def __init__(self, links=None):
        self.links: list[dict] = []
        for l in (links or []):
            self.add(l.get("from"), l.get("to"))

    # ── editing ──────────────────────────────────────────────────────
    def add(self, src, dst) -> bool:
        if not src or not dst or src == dst:
            return False
        if any(l["from"] == src and l["to"] == dst for l in self.links):
            return False
        self.links.append({"from": src, "to": dst})
        return True

    def remove(self, src, dst) -> bool:
        n = len(self.links)
        self.links = [l for l in self.links
                      if not (l["from"] == src and l["to"] == dst)]
        return len(self.links) != n

    def remove_widget(self, uid):
        """Drop every wire touching a deleted widget."""
        self.links = [l for l in self.links
                      if l["from"] != uid and l["to"] != uid]

    def targets_of(self, uid) -> list:
        return [l["to"] for l in self.links if l["from"] == uid]

    def sources_of(self, uid) -> list:
        return [l["from"] for l in self.links if l["to"] == uid]

    def as_list(self) -> list:
        return [dict(l) for l in self.links]

    # ── runtime ──────────────────────────────────────────────────────
    def propagate(self, uid, max_depth: int = MAX_DEPTH, blocked=None) -> list:
        """Breadth-first activation order downstream of *uid* (excluding it).

        A widget is activated at most once per propagation, so a cycle
        (timer → button → timer) terminates instead of hanging the UI. The
        depth guard is a second belt for deep chains.

        ``blocked(uid) -> bool`` marks a node that still activates (a gate
        flashes to show it was reached) but does NOT pass the pulse on — that
        is exactly what a closed condition gate does."""
        order, seen = [], {uid}
        frontier, depth = self.targets_of(uid), 0
        while frontier and depth < max_depth:
            nxt = []
            for t in frontier:
                if t in seen:
                    continue
                seen.add(t)
                order.append(t)
                if blocked is not None and blocked(t):
                    continue                 # node runs, the chain stops here
                nxt += self.targets_of(t)
            frontier = nxt
            depth += 1
        return order
