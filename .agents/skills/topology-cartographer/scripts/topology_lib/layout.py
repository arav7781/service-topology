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
4. Place: layer -> x, position -> y, then centre each column vertically.
5. Route: straight for adjacent layers, a jog for longer spans, and a channel
   below the diagram for back edges.

How big a node is, and how much air a column needs, come from the theme rather
than from constants here - `streams` draws fixed-size circles and diamonds and
needs wide columns for the names that overhang them, `classic` fits a box to
its label and does not. The theme name is stamped into the layout block so the
renderers style what was actually laid out.
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

LAYOUT_VERSION = "1.0.0"

# Geometry, in mxGraph units (1 unit == 1 pixel at 100% zoom). These size a
# box around its label, which is what a theme without fixed node sizes asks
# for; the fixed sizes and the column spacing live on the theme itself.
MIN_WIDTH = 160
MAX_WIDTH = 280
MIN_HEIGHT = 50
CHAR_WIDTH = 8
LINE_HEIGHT = 18
PADDING_X = 28
PADDING_Y = 26

BARYCENTRE_SWEEPS = 4


# --------------------------------------------------------------------------- #
# Node geometry
# --------------------------------------------------------------------------- #

def node_size(node: Node, theme: Optional[Theme] = None) -> Tuple[int, int]:
    """How big this node is drawn.

    A theme with fixed sizes wins outright: in the `streams` idiom a topic is
    an 80-unit circle whatever its name is, and a name that overhangs it is the
    look, not a bug - which is why that theme also asks for wide columns. With
    no fixed size the box is fitted to the label, clamped so one long name
    cannot dominate the diagram.
    """
    fixed = (theme if theme is not None else get_theme(None)).node_size(node.kind)
    if fixed is not None:
        return fixed
    lines = (node.display or node.id).split("\n")
    longest = max(len(line) for line in lines) if lines else len(node.id)
    width = min(MAX_WIDTH, max(MIN_WIDTH, longest * CHAR_WIDTH + PADDING_X))
    height = max(MIN_HEIGHT, len(lines) * LINE_HEIGHT + PADDING_Y)
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
           theme: Theme) -> Tuple[Dict[str, Dict[str, int]], int, int]:
    columns = {}  # type: Dict[int, List[str]]
    for node_id in sorted(model.nodes, key=lambda n: (layer[n], position[n], n)):
        columns.setdefault(layer[node_id], []).append(node_id)

    sizes = dict((node_id, node_size(node, theme))
                 for node_id, node in model.nodes.items())

    column_x = {}  # type: Dict[int, int]
    cursor = theme.margin_x
    for index in sorted(columns):
        width = max(sizes[node_id][0] for node_id in columns[index])
        column_x[index] = cursor
        cursor += width + theme.column_gap

    column_height = {}  # type: Dict[int, int]
    for index in sorted(columns):
        total = sum(sizes[node_id][1] for node_id in columns[index])
        column_height[index] = total + theme.row_gap * max(0, len(columns[index]) - 1)
    tallest = max(column_height.values()) if column_height else 0

    placed = {}  # type: Dict[str, Dict[str, int]]
    for index in sorted(columns):
        column_width = max(sizes[node_id][0] for node_id in columns[index])
        y = theme.margin_y + (tallest - column_height[index]) // 2
        for node_id in columns[index]:
            width, height = sizes[node_id]
            placed[node_id] = {
                # Centre each box in its column so the arrows line up.
                "x": column_x[index] + (column_width - width) // 2,
                "y": y,
                "width": width,
                "height": height,
                "layer": index,
                "order": columns[index].index(node_id),
            }
            y += height + theme.row_gap

    total_width = (cursor - theme.column_gap + theme.margin_x
                   if columns else 2 * theme.margin_x)
    total_height = tallest + 2 * theme.margin_y
    return placed, total_width, total_height


def _route(model: GraphModel, placed: Dict[str, Dict[str, int]],
           total_height: int, theme: Theme) -> List[Dict[str, Any]]:
    """Waypoints per edge, indexed against `model.edges`."""
    routed = []  # type: List[Dict[str, Any]]
    channel = total_height - theme.back_edge_channel // 2
    back_lane = 0

    for index, edge in enumerate(model.edges):
        source = placed.get(edge.src)
        target = placed.get(edge.dst)
        entry = {"index": index, "from": edge.src, "to": edge.dst,
                 "waypoints": []}  # type: Dict[str, Any]
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
        elif span > 1:
            # Long edge: jog at the midpoint so it does not clip the columns
            # it flies over.
            mid_x = (source["x"] + source["width"] + target["x"]) // 2
            entry["waypoints"] = [[mid_x, source_mid], [mid_x, target_mid]]

        routed.append(entry)
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
    placed, width, height = _place(model, layer, position, active)
    edges = _route(model, placed, height, active)

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
               theme: Optional[str] = None) -> Dict[str, Any]:
    """Lay out the master topology and one micro topology per service."""
    active = get_theme(theme)
    diagrams = {
        "master": layout_diagram(model, "Master topology", theme=active.name),
    }  # type: Dict[str, Any]

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
