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
    KIND_CACHE,
    KIND_DATASTORE,
    KIND_EXTERNAL_API,
    KIND_SERVICE,
    KIND_TOPIC,
    Edge,
    GraphModel,
    Node,
)

RENDERER_VERSION = "1.0.0"
DRAWIO_AGENT = "topology-cartographer/" + RENDERER_VERSION

# draw.io reads this to decide which shape library rendered the file. Anything
# unrecognised falls back to a rectangle rather than failing to open, but these
# are all core mxGraph shapes, so nothing here depends on an extension.
NODE_STYLES = {
    KIND_SERVICE: (
        "rounded=1;whiteSpace=wrap;html=1;arcSize=12;"
        "fillColor=#dae8fc;strokeColor=#6c8ebf;fontColor=#10314f;"
        "fontSize=12;fontStyle=1;verticalAlign=middle;align=center;"
    ),
    KIND_TOPIC: (
        "shape=hexagon;perimeter=hexagonPerimeter2;whiteSpace=wrap;html=1;"
        "fixedSize=1;fillColor=#ffe6cc;strokeColor=#d79b00;fontColor=#653700;"
        "fontSize=11;verticalAlign=middle;align=center;"
    ),
    KIND_DATASTORE: (
        "shape=cylinder3;whiteSpace=wrap;html=1;boundedLbl=1;backgroundOutline=1;"
        "size=12;fillColor=#d5e8d4;strokeColor=#82b366;fontColor=#1f3d18;"
        "fontSize=11;verticalAlign=middle;align=center;"
    ),
    KIND_CACHE: (
        "shape=cylinder3;whiteSpace=wrap;html=1;boundedLbl=1;backgroundOutline=1;"
        "size=12;fillColor=#e1d5e7;strokeColor=#9673a6;fontColor=#3b2a45;"
        "fontSize=11;verticalAlign=middle;align=center;"
    ),
    KIND_EXTERNAL_API: (
        "ellipse;shape=cloud;whiteSpace=wrap;html=1;"
        "fillColor=#f5f5f5;strokeColor=#666666;fontColor=#333333;"
        "fontSize=11;verticalAlign=middle;align=center;"
    ),
}
UNRESOLVED_TOPIC_STYLE = (
    "shape=hexagon;perimeter=hexagonPerimeter2;whiteSpace=wrap;html=1;"
    "fixedSize=1;fillColor=#f5f5f5;strokeColor=#999999;dashed=1;"
    "fontColor=#666666;fontSize=11;verticalAlign=middle;align=center;"
)

# A service nothing in this repository declares - we know it only because
# something calls it. Drawn hollow so it never reads as a mapped service.
REFERENCED_ONLY_SERVICE_STYLE = (
    "rounded=1;whiteSpace=wrap;html=1;arcSize=12;dashed=1;"
    "fillColor=none;strokeColor=#999999;fontColor=#777777;"
    "fontSize=12;fontStyle=2;verticalAlign=middle;align=center;"
)

_EDGE_BASE = ("edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;jettySize=auto;"
              "orthogonalLoop=1;endArrow=blockThin;endFill=1;fontSize=10;")

EDGE_COLOURS = {
    (EDGE_PRODUCES, ""): "#d79b00",
    (EDGE_CONSUMES, ""): "#82b366",
    (EDGE_CALLS, "http"): "#6c8ebf",
    (EDGE_CALLS, "grpc"): "#9673a6",
    (EDGE_CALLS, ""): "#6c8ebf",
    (EDGE_DEPENDS, ""): "#666666",
}

# Anything not [CODE] is drawn dashed and grey, and listed separately. This is
# the visual half of the rule that an inference never passes for a fact.
INFERRED_EDGE_EXTRA = ("strokeColor=#999999;fontColor=#8c8c8c;"
                       "dashed=1;dashPattern=6 6;")

# `<br>`, not `&#10;`: the legend cell is html=1 like every other label, so a
# newline entity collapses and the three lines run together.
LEGEND_TEXT = (
    "<b>Legend</b><br>"
    "solid = [CODE], read directly<br>"
    "dashed grey = [INFERENCE]/[UNVERIFIED], not confirmed"
)


# --------------------------------------------------------------------------- #
# Shared label helpers
# --------------------------------------------------------------------------- #

def node_label(node: Node) -> str:
    return node.display or node.id


def edge_label(edge: Edge, model: GraphModel, include_topic: bool = False) -> str:
    """What the arrow says. Every edge gets a label; none is left bare."""
    parts = []  # type: List[str]
    if include_topic and edge.type in (EDGE_PRODUCES, EDGE_CONSUMES):
        topic_id = edge.dst if edge.type == EDGE_PRODUCES else edge.src
        topic = model.topics.get(topic_id)
        if topic is not None:
            parts.append(node_label(topic).split("\n")[0])
    if edge.type == EDGE_DEPENDS:
        # The database name is already on the box it points at; repeating it
        # next to the arrow costs a label and says nothing. The protocol does.
        return edge.protocol or edge.type
    if edge.method:
        parts.append(edge.method)
    if edge.detail:
        parts.append(edge.detail)
    if not parts:
        parts.append(edge.type if edge.type != EDGE_CALLS else (edge.protocol or "calls"))
    return "\n".join(parts)


def edge_style(edge: Edge) -> str:
    if edge.confirmed:
        colour = (EDGE_COLOURS.get((edge.type, edge.protocol))
                  or EDGE_COLOURS.get((edge.type, ""))
                  or "#6c8ebf")
        return _EDGE_BASE + "strokeColor={0};".format(colour)
    # Unconfirmed edges lose their protocol colour entirely rather than
    # carrying two strokeColor declarations and relying on the last one winning.
    return _EDGE_BASE + INFERRED_EDGE_EXTRA


def node_style(node: Node) -> str:
    attributes = dict(node.attributes)
    if node.kind == KIND_TOPIC and attributes.get("unresolved") == "true":
        return UNRESOLVED_TOPIC_STYLE
    if node.kind == KIND_SERVICE and attributes.get("origin") == "referenced-only":
        return REFERENCED_ONLY_SERVICE_STYLE
    return NODE_STYLES.get(node.kind, NODE_STYLES[KIND_SERVICE])


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
                  include_topic_labels: bool = False,
                  include_legend: bool = True) -> str:
    """Serialise one laid-out diagram as an mxGraph document.

    No `modified` timestamp is written. That attribute is optional, and leaving
    it out is what lets an unchanged repository re-render byte-identically.
    """
    placed = diagram.get("nodes") or {}
    routed = diagram.get("edges") or []
    title = diagram.get("title") or "Topology"

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
            "label": _html(node_label(node)),
            "tooltip": _tooltip(list(node.source_evidence)),
            "topologyKind": node.kind,
            "topologyId": node.id,
            "sourceEvidence": "; ".join(node.source_evidence),
            "id": cell_ids[node_id],
        })
        cell = ET.SubElement(holder, "mxCell", {
            "style": node_style(node), "vertex": "1", "parent": "1",
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

        holder = ET.SubElement(root, "UserObject", {
            "label": _html(edge_label(edge, model, include_topic_labels)),
            "tooltip": _tooltip([edge.source], edge.note),
            "evidenceTag": edge.evidence_tag,
            "sourceLocation": edge.source,
            "alsoAt": "; ".join(edge.also_at),
            "edgeType": edge.type,
            "id": "edge-{0}".format(index),
        })
        if edge.note:
            holder.set(
                "inferenceNote" if not edge.confirmed else "resolutionNote",
                edge.note)
        if edge.extractor:
            holder.set("extractor", edge.extractor)

        style = edge_style(edge)
        waypoints = entry.get("waypoints") or []
        if not waypoints:
            # Adjacent columns: pin the arrow to the facing edges of the boxes
            # so a left-to-right diagram reads as a left-to-right flow.
            style += "exitX=1;exitY=0.5;exitDx=0;exitDy=0;entryX=0;entryY=0.5;entryDx=0;entryDy=0;"
        cell = ET.SubElement(holder, "mxCell", {
            "style": style, "edge": "1", "parent": "1",
            "source": source_cell, "target": target_cell,
        })
        geometry = ET.SubElement(cell, "mxGeometry", {"relative": "1", "as": "geometry"})
        if waypoints:
            points = ET.SubElement(geometry, "Array", {"as": "points"})
            for point in waypoints:
                ET.SubElement(points, "mxPoint",
                              {"x": str(int(point[0])), "y": str(int(point[1]))})

    if include_legend:
        _append_legend(root, diagram)

    _indent(mxfile)
    return ET.tostring(mxfile, encoding="unicode") + "\n"


def _append_legend(root: ET.Element, diagram: Dict[str, Any]) -> None:
    cell = ET.SubElement(root, "mxCell", {
        "id": "legend",
        "value": LEGEND_TEXT,
        "style": ("text;html=1;align=left;verticalAlign=top;whiteSpace=wrap;"
                  "rounded=1;fillColor=#ffffff;strokeColor=#b3b3b3;"
                  "fontSize=10;fontColor=#555555;"),
        "vertex": "1", "parent": "1",
    })
    ET.SubElement(cell, "mxGeometry", {
        "x": "40",
        "y": str(max(0, int(diagram.get("height", 600)) - 70)),
        "width": "300", "height": "56", "as": "geometry",
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

_MERMAID_SHAPES = {
    KIND_SERVICE: '{0}["{1}"]',
    KIND_TOPIC: '{0}{{{{"{1}"}}}}',
    KIND_DATASTORE: '{0}[("{1}")]',
    KIND_CACHE: '{0}[("{1}")]',
    KIND_EXTERNAL_API: '{0}(["{1}"])',
}

_MERMAID_CLASSES = (
    "  classDef service fill:#dae8fc,stroke:#6c8ebf,color:#10314f;",
    "  classDef topic fill:#ffe6cc,stroke:#d79b00,color:#653700;",
    "  classDef datastore fill:#d5e8d4,stroke:#82b366,color:#1f3d18;",
    "  classDef cache fill:#e1d5e7,stroke:#9673a6,color:#3b2a45;",
    "  classDef external_api fill:#f5f5f5,stroke:#666666,color:#333333;",
    "  classDef referenced_only fill:none,stroke:#999999,color:#777777,"
    "stroke-dasharray:5 5;",
)


def _mermaid_class(node: Node) -> str:
    attributes = dict(node.attributes)
    if node.kind == KIND_SERVICE and attributes.get("origin") == "referenced-only":
        return "referenced_only"
    if node.kind == KIND_TOPIC and attributes.get("unresolved") == "true":
        return "referenced_only"
    return node.kind


def render_mermaid(model: GraphModel, title: str = "Master topology",
                   include_topic_labels: bool = False) -> str:
    """A Mermaid `flowchart` carrying the same content as the .drawio file.

    Cheap, and it renders inline in any Markdown preview or chat surface, which
    matters for hosts that cannot show a file from disk.
    """
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
        shape = _MERMAID_SHAPES.get(node.kind, _MERMAID_SHAPES[KIND_SERVICE])
        label = _mermaid_text(node_label(node))
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
        label = _mermaid_text(edge_label(edge, model, include_topic_labels))
        lines.append('  {0} {1}|"{2}"| {3}'.format(source, arrow, label, target))

    lines.append("")
    lines.extend(_MERMAID_CLASSES)
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
