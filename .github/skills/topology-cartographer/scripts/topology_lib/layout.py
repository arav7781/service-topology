"""Deterministic layered placement.

No graphviz, no external layout engine - a plain layered DAG placement in the
standard library, because adding a dependency would break this repository's
one hard rule about the helper scripts.

Determinism is not a nicety here. The acceptance criterion is that re-running
the pipeline over unchanged code produces byte-identical output, so a diff of
two diagrams shows architectural change and nothing else. Every sort in this
module therefore has an explicit, total tie-break on the node id; nothing
depends on dictionary insertion order or on the order files were walked in.

Algorithm
---------
1. Break cycles with a depth-first search over ids in sorted order, so the same
   back edges are chosen every run. Back edges are still drawn - they are just
   routed below the diagram instead of layered.
2. Assign layers by longest path from the sources.
3. Order within each layer with barycentre sweeps, tie-broken by id.
4. Place: layer -> x, position -> y, then centre each column vertically. Space
   is reserved per node *footprint* - the shape plus whatever of its label is
   drawn outside the shape - not per shape.
5. Route: straight for adjacent layers, a channel above the diagram for arrows
   that span more than one column, and a channel below it for back edges. Every
   arrow's label is then slid along its own line until it sits somewhere free.

How big a node is, how wide its label wraps, and how much air a column needs
come from the theme rather than from constants here - `streams` draws
fixed-size circles and diamonds and writes a long name underneath the shape,
`classic` fits a box to its label. The theme name is stamped into the layout
block so the renderers style what was actually laid out.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from .theme import Theme, get_theme
from .model import (
    EDGE_CONSUMES,
    EDGE_PRODUCES,
    KIND_SERVICE,
    KIND_TOPIC,
    GraphModel,
    Node,
    subgraph_for_service,
)

LAYOUT_VERSION = "1.1.0"

# Geometry, in mxGraph units (1 unit == 1 pixel at 100% zoom). These size a
# box around its label, which is what a theme without fixed node sizes asks
# for; the fixed sizes, the label metrics and the column spacing live on the
# theme itself.
MIN_WIDTH = 160
MAX_WIDTH = 280
MIN_HEIGHT = 50
PADDING_X = 28
PADDING_Y = 26

BARYCENTRE_SWEEPS = 4

# Where an arrow's label may sit, as an offset from the midpoint in draw.io's
# own units: 0 is the middle of the arrow, -1 the source end, +1 the target end.
# Tried in this order, so a label only moves as far as it has to and an arrow
# with room to spare keeps its label in the middle, where it is easiest to read.
LABEL_CANDIDATES = (0.0, 0.2, -0.2, 0.36, -0.36, 0.5, -0.5, 0.62, -0.62)


# --------------------------------------------------------------------------- #
# Node geometry
# --------------------------------------------------------------------------- #

def label_lines(node: Node, theme: Theme) -> List[str]:
    """The lines this node's label is drawn on, per the theme's wrap width."""
    return theme.wrap(node.kind, node.display or node.id)


def node_size(node: Node, theme: Optional[Theme] = None) -> Tuple[int, int]:
    """How big the *shape* is drawn.

    A theme with fixed sizes wins outright: in the `streams` idiom a topic is
    an 80-unit circle whatever its name is. With no fixed size the box is
    fitted to the label - to the *wrapped* label, so a name that takes three
    lines gets a box three lines tall instead of one that its own text spills
    out of - clamped so one long name cannot dominate the diagram.
    """
    active = theme if theme is not None else get_theme(None)
    fixed = active.node_size(node.kind)
    if fixed is not None:
        return fixed
    lines = label_lines(node, active)
    longest = max(len(line) for line in lines)
    width = min(MAX_WIDTH, max(MIN_WIDTH, longest * active.label_char_width + PADDING_X))
    height = max(MIN_HEIGHT, len(lines) * active.label_line_height + PADDING_Y)
    return width, height


def node_footprint(node: Node, theme: Theme) -> Tuple[int, int]:
    """How much room the node needs, shape *and* label.

    This is the number the placement uses, and it is why the diagram stopped
    overlapping itself: an 80-unit circle carrying a 37-character name occupies
    far more than 80 units of the page, and a layout that reserves 80 puts the
    next node underneath the name. A label-fitted box already contains its own
    label, so there the footprint and the shape are the same thing.
    """
    width, height = node_size(node, theme)
    lines = label_lines(node, theme)
    text_width = max(len(line) for line in lines) * theme.label_char_width
    text_height = len(lines) * theme.label_line_height

    if theme.labels_outside(node.kind):
        return max(width, text_width), height + theme.label_gap + text_height
    if theme.node_size(node.kind) is not None:
        # Label inside a fixed shape: it may still need more height than the
        # shape has, and a diamond that spills its name is the same overlap.
        return max(width, text_width), max(height, text_height + theme.label_gap * 2)
    return width, height


# --------------------------------------------------------------------------- #
# Layering
# --------------------------------------------------------------------------- #

def _adjacency(model: GraphModel) -> Tuple[Dict[str, List[str]], Dict[str, List[str]]]:
    successors = dict((node_id, []) for node_id in model.nodes)  # type: Dict[str, List[str]]
    predecessors = dict((node_id, []) for node_id in model.nodes)  # type: Dict[str, List[str]]
    for edge in model.edges:
        if edge.src not in successors or edge.dst not in predecessors:
            continue
        if edge.dst not in successors[edge.src]:
            successors[edge.src].append(edge.dst)
        if edge.src not in predecessors[edge.dst]:
            predecessors[edge.dst].append(edge.src)
    for mapping in (successors, predecessors):
        for key in mapping:
            mapping[key] = sorted(mapping[key])
    return successors, predecessors


def _back_edges(successors: Dict[str, List[str]]) -> Set[Tuple[str, str]]:
    """Depth-first search over sorted ids, so the same edges break every run."""
    WHITE, GREY, BLACK = 0, 1, 2
    colour = dict((node_id, WHITE) for node_id in successors)
    back = set()  # type: Set[Tuple[str, str]]

    for root in sorted(successors):
        if colour[root] != WHITE:
            continue
        # Explicit stack: a deep monorepo graph can outrun the recursion limit.
        stack = [(root, iter(successors[root]))]  # type: List[Tuple[str, Any]]
        colour[root] = GREY
        while stack:
            node, children = stack[-1]
            advanced = False
            for child in children:
                if colour.get(child) == GREY:
                    back.add((node, child))
                elif colour.get(child) == WHITE:
                    colour[child] = GREY
                    stack.append((child, iter(successors[child])))
                    advanced = True
                    break
            if not advanced:
                colour[node] = BLACK
                stack.pop()
    return back


def _layers(model: GraphModel, successors: Dict[str, List[str]],
            predecessors: Dict[str, List[str]],
            back: Set[Tuple[str, str]]) -> Dict[str, int]:
    """Longest path from the sources, ignoring the broken back edges."""
    forward = dict(
        (node_id, [child for child in children if (node_id, child) not in back])
        for node_id, children in successors.items())
    incoming = dict(
        (node_id, [parent for parent in parents if (parent, node_id) not in back])
        for node_id, parents in predecessors.items())

    layer = dict((node_id, 0) for node_id in model.nodes)
    ready = sorted(node_id for node_id in model.nodes if not incoming[node_id])
    remaining = dict((node_id, len(incoming[node_id])) for node_id in model.nodes)
    order = []  # type: List[str]

    while ready:
        node_id = ready.pop(0)
        order.append(node_id)
        for child in forward[node_id]:
            layer[child] = max(layer[child], layer[node_id] + 1)
            remaining[child] -= 1
            if remaining[child] == 0:
                ready.append(child)
                ready.sort()

    # Anything left sits in a knot the cycle-breaker could not fully unpick;
    # place it after its deepest resolved predecessor rather than dropping it.
    for node_id in sorted(model.nodes):
        if node_id not in order:
            parents = [layer[p] for p in incoming[node_id] if p in order]
            layer[node_id] = (max(parents) + 1) if parents else 0
    return layer


def _micro_layers(model: GraphModel, focus: str) -> Dict[str, int]:
    """Five fixed columns, so every micro diagram reads the same way.

        upstream | inbound | FOCUS | outbound | downstream
    """
    layer = {focus: 2}
    inbound = set()   # type: Set[str]
    outbound = set()  # type: Set[str]
    for edge in model.edges:
        if edge.dst == focus:
            inbound.add(edge.src)
        elif edge.src == focus:
            outbound.add(edge.dst)

    for node_id in sorted(inbound):
        layer[node_id] = 1
    for node_id in sorted(outbound):
        layer[node_id] = 3

    for edge in model.edges:
        # A producer feeding a topic this service consumes sits upstream of it.
        if edge.dst in inbound and edge.src not in layer:
            layer[edge.src] = 0
        # A consumer of a topic this service produces sits downstream of it.
        if edge.src in outbound and edge.dst not in layer:
            layer[edge.dst] = 4

    for node_id in sorted(model.nodes):
        layer.setdefault(node_id, 2 if node_id == focus else 4)
    return layer


# --------------------------------------------------------------------------- #
# Ordering
# --------------------------------------------------------------------------- #

def _order_within_layers(model: GraphModel, layer: Dict[str, int],
                         successors: Dict[str, List[str]],
                         predecessors: Dict[str, List[str]]) -> Dict[str, int]:
    columns = {}  # type: Dict[int, List[str]]
    for node_id in sorted(model.nodes):
        columns.setdefault(layer[node_id], []).append(node_id)

    # Seed deterministically: group a column by kind, then by id.
    kind_rank = {KIND_TOPIC: 0, KIND_SERVICE: 1}
    for index in sorted(columns):
        columns[index].sort(key=lambda n: (kind_rank.get(model.nodes[n].kind, 2), n))

    position = {}  # type: Dict[str, int]
    for index in sorted(columns):
        for slot, node_id in enumerate(columns[index]):
            position[node_id] = slot

    for sweep in range(BARYCENTRE_SWEEPS):
        indices = sorted(columns)
        if sweep % 2:
            indices = list(reversed(indices))
        for index in indices:
            neighbours = predecessors if sweep % 2 == 0 else successors
            scored = []  # type: List[Tuple[float, str, str]]
            for node_id in columns[index]:
                related = [position[other] for other in neighbours[node_id]
                           if other in position and layer[other] != index]
                barycentre = (sum(related) / float(len(related))
                              if related else float(position[node_id]))
                scored.append((barycentre, node_id, node_id))
            # The id is the final tie-break, so equal barycentres never flip.
            scored.sort(key=lambda item: (item[0], item[1]))
            columns[index] = [item[1] for item in scored]
            for slot, node_id in enumerate(columns[index]):
                position[node_id] = slot

    return position


# --------------------------------------------------------------------------- #
# Placement and routing
# --------------------------------------------------------------------------- #

def _place(model: GraphModel, layer: Dict[str, int], position: Dict[str, int],
           theme: Theme, top_channel: int = 0) -> Tuple[Dict[str, Dict[str, int]], int, int]:
    columns = {}  # type: Dict[int, List[str]]
    for node_id in sorted(model.nodes, key=lambda n: (layer[n], position[n], n)):
        columns.setdefault(layer[node_id], []).append(node_id)

    sizes = dict((node_id, node_size(node, theme))
                 for node_id, node in model.nodes.items())
    # Spacing is done on footprints, drawing on sizes. Where a label sits
    # outside its shape the two differ, and using the shape for both is exactly
    # how a name ends up written across the node below it.
    footprints = dict((node_id, node_footprint(node, theme))
                      for node_id, node in model.nodes.items())

    column_x = {}  # type: Dict[int, int]
    cursor = theme.margin_x
    for index in sorted(columns):
        width = max(footprints[node_id][0] for node_id in columns[index])
        column_x[index] = cursor
        cursor += width + theme.column_gap

    column_height = {}  # type: Dict[int, int]
    for index in sorted(columns):
        total = sum(footprints[node_id][1] for node_id in columns[index])
        column_height[index] = total + theme.row_gap * max(0, len(columns[index]) - 1)
    tallest = max(column_height.values()) if column_height else 0

    placed = {}  # type: Dict[str, Dict[str, int]]
    for index in sorted(columns):
        column_width = max(footprints[node_id][0] for node_id in columns[index])
        y = theme.margin_y + top_channel + (tallest - column_height[index]) // 2
        for node_id in columns[index]:
            width, height = sizes[node_id]
            placed[node_id] = {
                # Centre the shape in its column so the arrows line up; the
                # label is centred on the shape, so it lands centred too.
                "x": column_x[index] + (column_width - width) // 2,
                # Top of the slot: an outside label hangs into the rest of it.
                "y": y,
                "width": width,
                "height": height,
                "layer": index,
                "order": columns[index].index(node_id),
            }
            y += footprints[node_id][1] + theme.row_gap

    total_width = (cursor - theme.column_gap + theme.margin_x
                   if columns else 2 * theme.margin_x)
    total_height = tallest + 2 * theme.margin_y + top_channel
    return placed, total_width, total_height


def _point_at(points: List[Tuple[float, float]], fraction: float) -> Tuple[float, float]:
    """The point `fraction` of the way along a polyline, by arc length."""
    total = 0.0
    lengths = []  # type: List[float]
    for index in range(len(points) - 1):
        (x0, y0), (x1, y1) = points[index], points[index + 1]
        length = ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5
        lengths.append(length)
        total += length
    if total <= 0:
        return points[0]

    want, walked = fraction * total, 0.0
    for index, length in enumerate(lengths):
        if walked + length >= want and length > 0:
            step = (want - walked) / length
            (x0, y0), (x1, y1) = points[index], points[index + 1]
            return (x0 + (x1 - x0) * step, y0 + (y1 - y0) * step)
        walked += length
    return points[-1]


def _overlaps(a: Tuple[float, float, float, float],
              b: Tuple[float, float, float, float]) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _assign_label_offsets(model: GraphModel, placed: Dict[str, Dict[str, int]],
                          routed: List[Dict[str, Any]], theme: Theme) -> None:
    """Slide each arrow's label along its own line until it sits somewhere free.

    draw.io centres every edge label, so several arrows crossing one column gap
    write their labels on top of each other in the middle of it - and on top of
    whatever node the middle of a long arrow happens to fly over. Nothing but
    the label moves: the arrow, and both things it connects, stay exactly where
    the placement put them.

    The label is treated as its worst case - `theme.edge_label_chars` wide -
    because at this point the text has not been written yet; `render.py` owns
    the wording, this owns the geometry. Candidates are tried in a fixed order
    and edges are visited in model order, so the same graph always resolves the
    same way.
    """
    box_width = theme.edge_label_chars * max(1, theme.label_char_width - 1)
    box_height = theme.label_line_height + 4

    obstacles = []  # type: List[Tuple[float, float, float, float]]
    for node_id in sorted(placed):
        geometry = placed[node_id]
        node = model.node(node_id)
        left = float(geometry["x"])
        top = float(geometry["y"])
        right = left + geometry["width"]
        bottom = top + geometry["height"]
        if node is not None and theme.labels_outside(node.kind):
            lines = label_lines(node, theme)
            text_width = max(len(line) for line in lines) * theme.label_char_width
            centre = (left + right) / 2.0
            left = min(left, centre - text_width / 2.0)
            right = max(right, centre + text_width / 2.0)
            bottom += theme.label_gap + len(lines) * theme.label_line_height
        obstacles.append((left, top, right, bottom))

    taken = []  # type: List[Tuple[float, float, float, float]]
    for entry in routed:
        source = placed.get(entry["from"])
        target = placed.get(entry["to"])
        if source is None or target is None:
            continue
        points = [(float(source["x"] + source["width"] // 2),
                   float(source["y"] + source["height"] // 2))]
        points.extend((float(x), float(y)) for x, y in entry["waypoints"])
        points.append((float(target["x"] + target["width"] // 2),
                       float(target["y"] + target["height"] // 2)))

        # A crowded diagram can leave no free spot at all, so score every
        # candidate and keep the least bad one rather than giving up and
        # dropping the label back onto the pile in the middle.
        best = None  # type: Optional[Tuple[int, float, Tuple[float, float, float, float]]]
        for candidate in LABEL_CANDIDATES:
            x, y = _point_at(points, 0.5 + candidate / 2.0)
            box = (x - box_width / 2.0, y - box_height / 2.0,
                   x + box_width / 2.0, y + box_height / 2.0)
            score = sum(1 for other in obstacles + taken if _overlaps(box, other))
            if best is None or score < best[0]:
                best = (score, candidate, box)
            if score == 0:
                break
        if best is None:
            continue
        entry["label_x"] = best[1]
        taken.append(best[2])


def _route(model: GraphModel, placed: Dict[str, Dict[str, int]],
           total_height: int, theme: Theme,
           top_channel: int = 0) -> List[Dict[str, Any]]:
    """Waypoints and a label position per edge, indexed against `model.edges`."""
    routed = []  # type: List[Dict[str, Any]]
    channel = total_height - theme.back_edge_channel // 2
    back_lane = 0
    long_lane = 0

    for index, edge in enumerate(model.edges):
        source = placed.get(edge.src)
        target = placed.get(edge.dst)
        entry = {"index": index, "from": edge.src, "to": edge.dst,
                 "waypoints": [], "label_x": 0.0}  # type: Dict[str, Any]
        if source is None or target is None:
            routed.append(entry)
            continue

        span = target["layer"] - source["layer"]
        source_mid = source["y"] + source["height"] // 2
        target_mid = target["y"] + target["height"] // 2

        if span <= 0:
            # A back edge, or two nodes in the same column: drop below the
            # diagram so the arrow never runs backwards through a box.
            back_lane += 1
            lane_y = channel + (back_lane % 3) * (theme.row_gap // 2)
            entry["waypoints"] = [
                [source["x"] + source["width"] // 2, lane_y],
                [target["x"] + target["width"] // 2, lane_y],
            ]
        elif span > 1 and top_channel:
            # Long edge: up into the channel above the diagram, across, and back
            # down. Drawn straight it would run through every box between its
            # two ends - and so would its label.
            long_lane += 1
            lane_y = (theme.margin_y
                      + (long_lane % 3) * (top_channel // 4)
                      + top_channel // 8)
            entry["waypoints"] = [
                [source["x"] + source["width"] // 2, lane_y],
                [target["x"] + target["width"] // 2, lane_y],
            ]
        elif span > 1:
            # No channel reserved (nothing here spans more than one column in
            # the usual case): jog at the midpoint instead.
            mid_x = (source["x"] + source["width"] + target["x"]) // 2
            entry["waypoints"] = [[mid_x, source_mid], [mid_x, target_mid]]

        routed.append(entry)

    # Labels last: where one can sit depends on where every arrow ended up.
    _assign_label_offsets(model, placed, routed, theme)
    return routed


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #

def layout_diagram(model: GraphModel, title: str,
                   focus: Optional[str] = None,
                   theme: Optional[str] = None) -> Dict[str, Any]:
    """Lay out one diagram. Same model in, same coordinates out, always."""
    active = get_theme(theme)
    if not model.nodes:
        return {"title": title, "focus": focus, "width": 400, "height": 200,
                "theme": active.name, "nodes": {}, "edges": [], "edge_count": 0}

    successors, predecessors = _adjacency(model)
    if focus is not None and focus in model.nodes:
        layer = _micro_layers(model, focus)
    else:
        layer = _layers(model, successors, predecessors, _back_edges(successors))

    position = _order_within_layers(model, layer, successors, predecessors)
    # Only reserve the channel if something actually needs it; an ordinary
    # producer-topic-consumer chain spans one column at a time and would just
    # gain a band of white space at the top.
    top_channel = active.long_edge_channel if any(
        layer.get(edge.dst, 0) - layer.get(edge.src, 0) > 1
        for edge in model.edges) else 0
    placed, width, height = _place(model, layer, position, active, top_channel)
    edges = _route(model, placed, height, active, top_channel)

    return {
        "title": title,
        "focus": focus,
        "width": width,
        "height": height + active.back_edge_channel,
        # Stamped so a renderer handed only the laid-out model styles it for
        # the sizes it was actually placed at.
        "theme": active.name,
        "nodes": placed,
        "edges": edges,
        "edge_count": len(model.edges),
    }


def layout_all(model: GraphModel, services: Optional[Sequence[str]] = None,
               theme: Optional[str] = None,
               include_master: bool = True) -> Dict[str, Any]:
    """Lay out the master topology and one micro topology per service.

    `include_master=False` leaves the master out. Someone who asked for one
    service's micro topology asked for one diagram, and laying out - then
    rendering, then handing over - a whole-system diagram they did not ask for
    is not a bonus, it is the wrong deliverable.
    """
    active = get_theme(theme)
    diagrams = {}  # type: Dict[str, Any]
    if include_master:
        diagrams["master"] = layout_diagram(
            model, "Master topology", theme=active.name)

    if services is not None:
        names = sorted(services)
    else:
        # A service we know only because something calls it has no inside to
        # draw - its micro topology would be the one arrow that named it.
        names = sorted(
            service_id for service_id, node in model.services.items()
            if dict(node.attributes).get("origin") != "referenced-only")
    for service_id in names:
        if service_id not in model.services:
            continue
        subgraph = subgraph_for_service(model, service_id)
        diagrams["micro/" + service_id] = layout_diagram(
            subgraph,
            "Micro topology - {0}".format(model.services[service_id].display),
            focus=service_id,
            theme=active.name,
        )

    return {"layout_version": LAYOUT_VERSION, "theme": active.name,
            "diagrams": diagrams}
