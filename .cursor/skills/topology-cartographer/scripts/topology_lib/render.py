"""Renderers: mxGraph (.drawio), Mermaid (.mmd), and the evidence report.

Rendering is mechanical on purpose. It reads the laid-out graph model and
serialises it; it makes no judgement about what belongs in the diagram, because
by this point every such judgement has already been made and cited. That is the
same division of labour as `calculate_candidate_score.py` in contributor-scout:
the model produces the structured input, a deterministic script produces the
artefact.

The XML is built with `xml.etree.ElementTree` rather than string formatting, so
a service called `Orders & Billing <v2>` cannot produce a file draw.io refuses
to open.

Which shapes and strokes are used comes from `theme.py`, not from here. A
renderer must style the diagram for the theme it was *laid out* under, because
a theme fixes node sizes as well as node styles - so when no theme is named,
these functions read the one `layout_all` stamped into the layout block rather
than falling back to the default.
"""

from __future__ import annotations

import hashlib
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Tuple

from .model import (
    CODE,
    EDGE_CALLS,
    EDGE_CONSUMES,
    EDGE_DEPENDS,
    EDGE_PRODUCES,
    KIND_SERVICE,
    KIND_TOPIC,
    Edge,
    GraphModel,
    Node,
)
from .textutil import compact, echoes
from .theme import DEFAULT_THEME, Theme, get_theme

RENDERER_VERSION = "1.1.0"
DRAWIO_AGENT = "topology-cartographer/" + RENDERER_VERSION

# `<br>`, not `&#10;`: the legend cell is html=1 like every other label, so a
# newline entity collapses and the lines run together.
_LEGEND_EVIDENCE = (
    "solid = [CODE], read directly<br>"
    "dashed grey = [INFERENCE]/[UNVERIFIED], not confirmed"
)

# The evidence half is the same whatever the theme; the shape half is not, and
# a legend naming shapes the diagram does not use is worse than no legend.
LEGEND_TEXT = {
    "streams": (
        "<b>Legend</b><br>"
        "circle = topic&nbsp;&nbsp;diamond = service<br>"
        "cylinder = datastore/cache&nbsp;&nbsp;"
        "off-page = external system<br>"
        + _LEGEND_EVIDENCE
    ),
    "classic": (
        "<b>Legend</b><br>"
        + _LEGEND_EVIDENCE
    ),
}


def legend_text(theme: Theme) -> str:
    return LEGEND_TEXT.get(theme.name, LEGEND_TEXT[DEFAULT_THEME])


# --------------------------------------------------------------------------- #
# Shared label helpers
# --------------------------------------------------------------------------- #

def node_label(node: Node, theme: Optional[Theme] = None) -> str:
    """The node's name, broken into lines the shape can actually hold.

    The break has to happen here rather than in the viewer: draw.io wraps a
    label on spaces, and `payrx-core-refund-request-topic-local` has none, so
    left alone it is drawn as one run three times wider than its circle. The
    layout reserved room for exactly these lines - it asked the same theme.
    """
    active = theme if theme is not None else get_theme(None)
    return "\n".join(active.wrap(node.kind, node.display or node.id))


def node_label_text(model: GraphModel, node_id: str) -> str:
    node = model.node(node_id)
    return (node.display if node is not None else node_id) or node_id


def _relationship(edge: Edge) -> str:
    """The name of the relationship itself, when nothing better is known."""
    if edge.type == EDGE_CALLS:
        return edge.protocol or "calls"
    if edge.type == EDGE_DEPENDS:
        return edge.protocol or "depends on"
    return edge.type


def edge_label(edge: Edge, model: GraphModel, limit: int = 0) -> str:
    """What the arrow says. Every edge gets a label; none is left bare.

    A label is a *relationship name*, not a restatement of the diagram. Both
    ends of the arrow are already drawn and named, so a part that only repeats
    the name of the shape it points at is dropped, and what is left is elided to
    `limit` characters. That is what stops a micro topology writing
    `payrx-core-refund-detail-request-topic-local` across the arrow that already
    ends at the circle of that name, four times, in the same column gap.

    `limit=0` keeps everything: the evidence report is a table, it has the room,
    and it is where a reader goes for the exact string. The full text also
    survives on the diagram itself, in the tooltip and in `fullLabel`.
    """
    if edge.type == EDGE_DEPENDS:
        # The database name is already on the box it points at; repeating it
        # next to the arrow costs a label and says nothing. The protocol does.
        return edge.protocol or edge.type

    ends = [node_label_text(model, edge.src), node_label_text(model, edge.dst)]
    parts = []  # type: List[str]
    for part in (edge.method, edge.detail):
        if not part:
            continue
        if limit > 0 and any(echoes(part, end) for end in ends):
            continue
        parts.append(compact(part, limit))
    if not parts:
        parts.append(_relationship(edge))
    return "\n".join(parts)


def edge_style(edge: Edge, theme: Optional[Theme] = None,
               flow_animation: Optional[bool] = None) -> str:
    active = theme if theme is not None else get_theme(None)
    style = active.edge_base
    animate = active.flow_animation if flow_animation is None else flow_animation
    if animate:
        style += "flowAnimation=1;"
    if edge.confirmed:
        colour = (active.edge_colours.get((edge.type, edge.protocol))
                  or active.edge_colours.get((edge.type, ""))
                  or active.edge_fallback_colour)
        return style + "strokeColor={0};".format(colour)
    # Unconfirmed edges lose their protocol colour entirely rather than
    # carrying two strokeColor declarations and relying on the last one winning.
    return style + active.inferred_edge_extra


def node_style(node: Node, theme: Optional[Theme] = None) -> str:
    active = theme if theme is not None else get_theme(None)
    attributes = dict(node.attributes)
    if node.kind == KIND_TOPIC and attributes.get("unresolved") == "true":
        return active.unresolved_topic_style
    if node.kind == KIND_SERVICE and attributes.get("origin") == "referenced-only":
        return active.referenced_only_service_style
    return active.node_styles.get(node.kind, active.node_styles[KIND_SERVICE])


def _html(text: str) -> str:
    """draw.io labels are HTML when html=1, so a newline must be a <br>.

    ElementTree escapes the angle brackets on write; draw.io unescapes them and
    renders the break. Putting a raw newline here would silently collapse.
    """
    return text.replace("\n", "<br>")


def _tooltip(citations: List[str], note: str = "") -> str:
    lines = list(citations)
    if note:
        lines.append(note)
    return " | ".join(line for line in lines if line)


# --------------------------------------------------------------------------- #
# mxGraph / .drawio
# --------------------------------------------------------------------------- #

def render_drawio(model: GraphModel, diagram: Dict[str, Any],
                  include_legend: bool = True,
                  theme: Optional[str] = None,
                  flow_animation: Optional[bool] = None) -> str:
    """Serialise one laid-out diagram as an mxGraph document.

    `theme` defaults to the one the diagram was laid out under, because node
    sizes come from the theme too: styling a `streams` layout with `classic`
    shapes draws label-fitted boxes at 80x80 and hides half of every name.

    No `modified` timestamp is written. That attribute is optional, and leaving
    it out is what lets an unchanged repository re-render byte-identically.
    """
    placed = diagram.get("nodes") or {}
    routed = diagram.get("edges") or []
    title = diagram.get("title") or "Topology"
    active = get_theme(theme or diagram.get("theme"))

    mxfile = ET.Element("mxfile", {
        "host": "topology-cartographer",
        "agent": DRAWIO_AGENT,
        "version": "24.7.17",
        "type": "device",
    })
    page = ET.SubElement(mxfile, "diagram", {
        "id": _diagram_id(title, model),
        "name": title,
    })
    graph = ET.SubElement(page, "mxGraphModel", {
        "dx": str(max(800, int(diagram.get("width", 800)))),
        "dy": str(max(600, int(diagram.get("height", 600)))),
        "grid": "1", "gridSize": "10", "guides": "1", "tooltips": "1",
        "connect": "1", "arrows": "1", "fold": "1",
        "page": "1", "pageScale": "1", "pageWidth": "1169", "pageHeight": "826",
        "math": "0", "shadow": "0",
    })
    root = ET.SubElement(graph, "root")
    ET.SubElement(root, "mxCell", {"id": "0"})
    ET.SubElement(root, "mxCell", {"id": "1", "parent": "0"})

    cell_ids = {}  # type: Dict[str, str]
    for index, node_id in enumerate(sorted(placed)):
        node = model.node(node_id)
        if node is None:
            continue
        cell_ids[node_id] = "node-{0}".format(index)

    for node_id in sorted(placed):
        node = model.node(node_id)
        if node is None:
            continue
        geometry = placed[node_id]
        holder = ET.SubElement(root, "UserObject", {
            "label": _html(node_label(node, active)),
            "tooltip": _tooltip(list(node.source_evidence)),
            "topologyKind": node.kind,
            "topologyId": node.id,
            "sourceEvidence": "; ".join(node.source_evidence),
            "id": cell_ids[node_id],
        })
        cell = ET.SubElement(holder, "mxCell", {
            "style": node_style(node, active), "vertex": "1", "parent": "1",
        })
        ET.SubElement(cell, "mxGeometry", {
            "x": str(geometry["x"]), "y": str(geometry["y"]),
            "width": str(geometry["width"]), "height": str(geometry["height"]),
            "as": "geometry",
        })

    for entry in routed:
        index = int(entry.get("index", -1))
        if index < 0 or index >= len(model.edges):
            continue
        edge = model.edges[index]
        source_cell = cell_ids.get(edge.src)
        target_cell = cell_ids.get(edge.dst)
        if source_cell is None or target_cell is None:
            continue

        label = edge_label(edge, model, active.edge_label_chars)
        full = edge_label(edge, model)
        shortened = full.replace("\n", " ") if full != label else ""
        holder = ET.SubElement(root, "UserObject", {
            "label": _html(label),
            "tooltip": _tooltip([edge.source], edge.note or shortened),
            "evidenceTag": edge.evidence_tag,
            "sourceLocation": edge.source,
            "alsoAt": "; ".join(edge.also_at),
            "edgeType": edge.type,
            "id": "edge-{0}".format(index),
        })
        if shortened:
            # Nothing is lost by shortening the drawn label: the whole string is
            # one `Edit > Edit Data` away, and it is in `evidence/sources.md`.
            holder.set("fullLabel", shortened)
        if edge.note:
            holder.set(
                "inferenceNote" if not edge.confirmed else "resolutionNote",
                edge.note)
        if edge.extractor:
            holder.set("extractor", edge.extractor)

        style = edge_style(edge, active, flow_animation)
        waypoints = entry.get("waypoints") or []
        if not waypoints and active.pin_adjacent_edges:
            # Adjacent columns: pin the arrow to the facing edges of the boxes
            # so a left-to-right diagram reads as a left-to-right flow. Only
            # right for rectangles - on a circle or a diamond a floating
            # connection finds the perimeter point that faces the other node,
            # and a pinned one leaves the arrow hanging off the bounding box.
            style += ("exitX=1;exitY=0.5;exitDx=0;exitDy=0;"
                      "entryX=0;entryY=0.5;entryDx=0;entryDy=0;")
        cell = ET.SubElement(holder, "mxCell", {
            "style": style, "edge": "1", "parent": "1",
            "source": source_cell, "target": target_cell,
        })
        attributes = {"relative": "1", "as": "geometry"}
        # Slide the label along its own arrow, away from the midpoint every
        # other arrow in this column gap also wants. The layout computed the
        # offsets; this only writes them down.
        label_x = float(entry.get("label_x") or 0.0)
        if label_x:
            attributes["x"] = "{0:g}".format(label_x)
            attributes["y"] = "0"
        geometry = ET.SubElement(cell, "mxGeometry", attributes)
        if waypoints:
            points = ET.SubElement(geometry, "Array", {"as": "points"})
            for point in waypoints:
                ET.SubElement(points, "mxPoint",
                              {"x": str(int(point[0])), "y": str(int(point[1]))})

    if include_legend:
        _append_legend(root, diagram, active)

    _indent(mxfile)
    return ET.tostring(mxfile, encoding="unicode") + "\n"


def _append_legend(root: ET.Element, diagram: Dict[str, Any],
                   theme: Theme) -> None:
    cell = ET.SubElement(root, "mxCell", {
        "id": "legend",
        "value": legend_text(theme),
        "style": theme.legend_style,
        "vertex": "1", "parent": "1",
    })
    ET.SubElement(cell, "mxGeometry", {
        "x": str(theme.margin_x),
        "y": str(int(diagram.get("height", 600)) + 20),
        "width": str(theme.legend_width),
        "height": str(theme.legend_height), "as": "geometry",
    })


def _diagram_id(title: str, model: GraphModel) -> str:
    """Stable across runs, distinct per diagram - never a random UUID."""
    digest = hashlib.sha1()
    digest.update(title.encode("utf-8"))
    for node_id in sorted(model.nodes):
        digest.update(node_id.encode("utf-8"))
    for edge in model.edges:
        digest.update("|".join(edge.sort_key).encode("utf-8"))
    return digest.hexdigest()[:20]


def _indent(element: ET.Element, level: int = 0) -> None:
    """`ET.indent` only arrived in Python 3.9; this repository supports 3.8."""
    padding = "\n" + "  " * level
    if len(element):
        if not (element.text or "").strip():
            element.text = padding + "  "
        for child in element:
            _indent(child, level + 1)
        if not (child.tail or "").strip():
            child.tail = padding
    if level and not (element.tail or "").strip():
        element.tail = padding


# --------------------------------------------------------------------------- #
# Mermaid
# --------------------------------------------------------------------------- #

def _mermaid_class(node: Node) -> str:
    attributes = dict(node.attributes)
    if node.kind == KIND_SERVICE and attributes.get("origin") == "referenced-only":
        return "referenced_only"
    if node.kind == KIND_TOPIC and attributes.get("unresolved") == "true":
        return "referenced_only"
    return node.kind


def render_mermaid(model: GraphModel, title: str = "Master topology",
                   theme: Optional[str] = None) -> str:
    """A Mermaid `flowchart` carrying the same content as the .drawio file.

    Cheap, and it renders inline in any Markdown preview or chat surface, which
    matters for hosts that cannot show a file from disk. The theme picks the
    node shapes, so the two renderings of one topology stay recognisably the
    same diagram - a topic is a circle in both, or a hexagon in both.
    """
    active = get_theme(theme if theme is not None
                       else (model.layout or {}).get("theme"))
    lines = [
        "%% {0}".format(title),
        "%% Generated by topology-cartographer {0} - do not edit by hand.".format(
            RENDERER_VERSION),
        "%% Solid arrow = [CODE] (read directly). "
        "Dotted arrow = [INFERENCE]/[UNVERIFIED] (not confirmed).",
        "flowchart LR",
    ]

    aliases = {}  # type: Dict[str, str]
    for index, node_id in enumerate(sorted(model.nodes)):
        aliases[node_id] = "n{0}".format(index)

    by_kind = {}  # type: Dict[str, List[str]]
    for node_id in sorted(model.nodes):
        node = model.nodes[node_id]
        shape = active.mermaid_shapes.get(
            node.kind, active.mermaid_shapes[KIND_SERVICE])
        label = _mermaid_text(node_label(node, active))
        lines.append("  " + shape.format(aliases[node_id], label))
        by_kind.setdefault(_mermaid_class(node), []).append(aliases[node_id])

    if model.edges:
        lines.append("")
    for edge in model.edges:
        source = aliases.get(edge.src)
        target = aliases.get(edge.dst)
        if source is None or target is None:
            continue
        arrow = "-->" if edge.confirmed else "-.->"
        label = _mermaid_text(edge_label(edge, model, active.edge_label_chars))
        lines.append('  {0} {1}|"{2}"| {3}'.format(source, arrow, label, target))

    lines.append("")
    lines.extend(active.mermaid_classes)
    for kind in sorted(by_kind):
        lines.append("  class {0} {1};".format(",".join(sorted(by_kind[kind])), kind))

    return "\n".join(lines) + "\n"


def _mermaid_text(text: str) -> str:
    """Mermaid labels are quoted, so quotes and pipes must not survive raw."""
    cleaned = text.replace('"', "'").replace("|", "/").replace("`", "'")
    return cleaned.replace("\n", "<br/>")


# --------------------------------------------------------------------------- #
# Evidence report
# --------------------------------------------------------------------------- #

def render_evidence(model: GraphModel, output_dir: str = "service-topology") -> str:
    """`evidence/sources.md` - every edge, its tag, and its file:line."""
    confirmed = [edge for edge in model.edges if edge.confirmed]
    inferred = model.inferred_edges()

    lines = [
        "# Topology evidence",
        "",
        "Every edge in every generated diagram, with the location it was read "
        "from. Generated by `build_graph_model.py`; do not edit by hand.",
        "",
        "| | |",
        "|---|---|",
        "| Services | {0} |".format(len(model.services)),
        "| Topics | {0} |".format(len(model.topics)),
        "| External systems | {0} |".format(len(model.external_systems)),
        "| Edges | {0} |".format(len(model.edges)),
        "| `[CODE]` | {0} |".format(len(confirmed)),
        "| `[INFERENCE]` / `[UNVERIFIED]` | {0} |".format(len(inferred)),
        "",
        "---",
        "",
        "## Confirmed edges `[CODE]`",
        "",
        "Read directly from the cited location, or from a config key followed to "
        "a value in a file that was also read.",
        "",
    ]
    lines.extend(_edge_table(confirmed, model))

    lines.extend([
        "",
        "---",
        "",
        "## Inferred, not confirmed",
        "",
    ])
    if inferred:
        lines.extend([
            "These edges are drawn **dashed and grey**. The pattern matched, but "
            "the target never fully resolved. Confirm each one before treating "
            "the diagram as authoritative.",
            "",
        ])
        lines.extend(_edge_table(inferred, model, with_reason=True))
    else:
        lines.append("None - every edge in this topology was read directly.")

    lines.extend(["", "---", "", "## Node origins", ""])
    lines.append("| Node | Kind | First read at |")
    lines.append("|---|---|---|")
    for node_id in sorted(model.nodes):
        node = model.nodes[node_id]
        citation = node.source_evidence[0] if node.source_evidence else "-"
        lines.append("| `{0}` | {1} | `{2}` |".format(
            node_id, node.kind, citation))

    if model.warnings:
        lines.extend(["", "---", "", "## Scan warnings", ""])
        for warning in model.warnings:
            lines.append("- {0}".format(warning))

    lines.extend([
        "",
        "---",
        "",
        "## How to read the tags",
        "",
        "| Tag | Meaning |",
        "|---|---|",
        "| `[CODE]` | The binding was read - a literal at the call site, or a "
        "config key followed to a concrete value in a file also read. |",
        "| `[INFERENCE]` | The pattern matched but the target did not resolve. "
        "The reason is given for every such edge above. |",
        "| `[UNVERIFIED]` | Asserted but not confirmed by reading a file. |",
        "",
        "See `references/evidence-classification.md` for the full rules.",
        "",
    ])
    return "\n".join(lines) + "\n"


def _edge_table(edges: List[Edge], model: GraphModel,
                with_reason: bool = False) -> List[str]:
    if not edges:
        return ["_None._"]
    header = "| From | | To | Label | Source |"
    divider = "|---|---|---|---|---|"
    if with_reason:
        header = "| From | | To | Label | Source | Why it is not confirmed |"
        divider = "|---|---|---|---|---|---|"
    rows = [header, divider]
    for edge in edges:
        label = edge_label(edge, model).replace("\n", " ")
        citations = "`{0}`".format(edge.source)
        if edge.also_at:
            citations += " (also " + ", ".join(
                "`{0}`".format(extra) for extra in edge.also_at) + ")"
        row = "| `{0}` | {1} | `{2}` | {3} | {4} |".format(
            edge.src, _arrow(edge), edge.dst, label or "-", citations)
        if with_reason:
            row += " {0} |".format(edge.note or "-")
        rows.append(row)
    return rows


def _arrow(edge: Edge) -> str:
    if edge.type == EDGE_PRODUCES:
        return "produces&nbsp;&rarr;"
    if edge.type == EDGE_CONSUMES:
        return "&rarr;&nbsp;consumed by"
    if edge.type == EDGE_DEPENDS:
        return "{0}&nbsp;&rarr;".format(edge.protocol or "depends on")
    return "{0}&nbsp;&rarr;".format(edge.protocol or "calls")
