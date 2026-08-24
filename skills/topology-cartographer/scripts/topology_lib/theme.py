"""Diagram themes - the shape, size and stroke vocabulary of the output.

`layout.py` and `render.py` both read a theme, and they must read the *same*
one: a theme fixes how big a node is drawn as well as how it is styled, so a
diagram laid out under one theme and rendered under another places boxes for
sizes it never drew. `layout_all` therefore stamps the theme name into the
layout block, and the renderers default to whatever is stamped there.

A theme is presentation only. It cannot add a node, drop an edge, or change an
evidence tag - by the time anything here runs, every such judgement has already
been made and cited. What a theme decides is which shape says "topic" and how
much room a column needs.

Two are shipped:

``streams``
    The dataflow idiom used for Kafka Streams topologies in draw.io: circles
    for topics, diamonds for the processors between them, cylinders for state,
    off-page connectors for anything outside the system. Kind is carried by
    *shape*, not fill, so the diagram stays readable at several hundred nodes
    and in either draw.io colour scheme. Shapes are fixed-size and small, and
    the columns are spaced wide enough for a long topic name to overhang.

``classic``
    The label-fitted boxes this skill emitted before themes existed. Kept
    because it is more compact for a small graph, and because changing what an
    existing pipeline renders is not something a version bump should do
    silently.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

from .model import (
    EDGE_CALLS,
    EDGE_CONSUMES,
    EDGE_DEPENDS,
    EDGE_PRODUCES,
    KIND_CACHE,
    KIND_DATASTORE,
    KIND_EXTERNAL_API,
    KIND_SERVICE,
    KIND_TOPIC,
)

THEME_VERSION = "1.0.0"

DEFAULT_THEME = "streams"


@dataclass(frozen=True)
class Theme:
    """Everything about how a diagram looks, in one place.

    Frozen so a theme cannot be edited in flight - two diagrams rendered in one
    process must not be able to disagree about what a topic looks like.
    """

    name: str
    description: str

    # --- nodes ---
    node_styles: Dict[str, str] = field(default_factory=dict)
    unresolved_topic_style: str = ""
    referenced_only_service_style: str = ""

    # Fixed drawn size per kind. `None` sizes the box to its label instead,
    # which is what `classic` does.
    node_sizes: Optional[Dict[str, Tuple[int, int]]] = None

    # --- edges ---
    edge_base: str = ""
    edge_colours: Dict[Tuple[str, str], str] = field(default_factory=dict)
    edge_fallback_colour: str = "#6c8ebf"
    inferred_edge_extra: str = ""
    # Pin an adjacent-column arrow to the facing sides of the two boxes. Right
    # for rectangles; wrong for circles and diamonds, where a floating
    # connection finds the perimeter point that actually faces the other node.
    pin_adjacent_edges: bool = True
    # draw.io's marching-ants animation. Off by default: it is a fine touch on
    # a twenty-node dataflow and unreadable on a three-hundred-node master.
    flow_animation: bool = False

    # --- spacing, in mxGraph units ---
    column_gap: int = 120
    row_gap: int = 40
    margin_x: int = 40
    margin_y: int = 40
    back_edge_channel: int = 60

    # --- legend ---
    legend_style: str = ""
    legend_width: int = 300
    legend_height: int = 56

    # --- Mermaid ---
    mermaid_shapes: Dict[str, str] = field(default_factory=dict)
    mermaid_classes: Tuple[str, ...] = ()

    def node_size(self, kind: str) -> Optional[Tuple[int, int]]:
        if self.node_sizes is None:
            return None
        return self.node_sizes.get(kind) or self.node_sizes.get(KIND_SERVICE)


# --------------------------------------------------------------------------- #
# streams - the Kafka Streams dataflow idiom
# --------------------------------------------------------------------------- #

# Fill and stroke are deliberately left unset on most shapes. draw.io then uses
# its own defaults, which follow the viewer's light/dark setting - a diagram
# that hard-codes #ffffff is a white rectangle in a dark canvas.
_STREAMS_LABEL = "verticalAlign=middle;align=center;"
_MONO = "fontFamily=Consolas, Courier New, monospace;"

_STREAMS = Theme(
    name="streams",
    description="Kafka Streams dataflow: circles, diamonds, cylinders.",
    node_styles={
        # A processor: the thing between two topics, drawn as a decision
        # diamond because that is what it is - it reads, decides, and emits.
        KIND_SERVICE: (
            "rhombus;whiteSpace=wrap;html=1;"
            "fontSize=11;fontStyle=1;" + _STREAMS_LABEL
        ),
        # `aspect=fixed` keeps it a circle when a long name would otherwise
        # stretch it into an oval.
        KIND_TOPIC: (
            "ellipse;whiteSpace=wrap;html=1;aspect=fixed;"
            + _MONO + "fontSize=9;" + _STREAMS_LABEL
        ),
        KIND_DATASTORE: (
            "shape=cylinder3;whiteSpace=wrap;html=1;boundedLbl=1;"
            "backgroundOutline=1;size=15;fontSize=10;" + _STREAMS_LABEL
        ),
        # The one place this theme spends colour: a cache and a database are
        # both cylinders, so nothing but fill can separate them.
        KIND_CACHE: (
            "shape=cylinder3;whiteSpace=wrap;html=1;boundedLbl=1;"
            "backgroundOutline=1;size=15;fillColor=#e1d5e7;strokeColor=#9673a6;"
            "fontColor=#3b2a45;fontSize=10;" + _STREAMS_LABEL
        ),
        # Off-page connector: the standard mark for "the flow continues
        # somewhere this diagram does not cover".
        KIND_EXTERNAL_API: (
            "shape=offPageConnector;whiteSpace=wrap;html=1;"
            "fontSize=9;" + _STREAMS_LABEL
        ),
    },
    unresolved_topic_style=(
        "ellipse;whiteSpace=wrap;html=1;aspect=fixed;dashed=1;"
        "fillColor=none;strokeColor=#999999;fontColor=#666666;"
        + _MONO + "fontSize=9;" + _STREAMS_LABEL
    ),
    referenced_only_service_style=(
        "rhombus;whiteSpace=wrap;html=1;dashed=1;"
        "fillColor=none;strokeColor=#999999;fontColor=#777777;"
        "fontSize=11;fontStyle=2;" + _STREAMS_LABEL
    ),
    node_sizes={
        KIND_SERVICE: (120, 115),
        KIND_TOPIC: (80, 80),
        KIND_DATASTORE: (110, 95),
        KIND_CACHE: (110, 95),
        KIND_EXTERNAL_API: (80, 80),
    },
    # No `edgeStyle`, so draw.io draws the direct line between two perimeter
    # points rather than an elbow. With circles and diamonds that is what makes
    # the flow read as flow.
    edge_base=("rounded=0;orthogonalLoop=1;jettySize=auto;html=1;fontSize=9;"),
    edge_colours={
        (EDGE_PRODUCES, ""): "#d79b00",
        (EDGE_CONSUMES, ""): "#82b366",
        (EDGE_CALLS, "http"): "#6c8ebf",
        (EDGE_CALLS, "grpc"): "#9673a6",
        (EDGE_CALLS, ""): "#6c8ebf",
        (EDGE_DEPENDS, ""): "#666666",
    },
    inferred_edge_extra=("strokeColor=#999999;fontColor=#8c8c8c;"
                         "dashed=1;dashPattern=6 6;"),
    pin_adjacent_edges=False,
    # Wide enough that a 45-character topic name overhanging an 80-unit circle
    # still clears the next column.
    column_gap=240,
    row_gap=90,
    margin_x=60,
    margin_y=60,
    back_edge_channel=80,
    legend_style=("text;html=1;align=left;verticalAlign=top;whiteSpace=wrap;"
                  "rounded=1;fillColor=#ffffff;strokeColor=#b3b3b3;"
                  "fontSize=10;fontColor=#555555;"),
    legend_width=330,
    legend_height=86,
    mermaid_shapes={
        KIND_SERVICE: '{0}{{"{1}"}}',
        KIND_TOPIC: '{0}(("{1}"))',
        KIND_DATASTORE: '{0}[("{1}")]',
        KIND_CACHE: '{0}[("{1}")]',
        KIND_EXTERNAL_API: '{0}[["{1}"]]',
    },
    # Only stroke width, so fill and text colour stay with whatever Mermaid
    # theme the page renders under - pinning them to white-on-black here would
    # make every diagram unreadable in a dark Markdown preview, which is the
    # same reason the draw.io shapes leave fill unset.
    mermaid_classes=(
        "  classDef service stroke-width:1px;",
        "  classDef topic stroke-width:1px;",
        "  classDef datastore stroke-width:1px;",
        "  classDef cache fill:#e1d5e7,stroke:#9673a6,color:#3b2a45;",
        "  classDef external_api stroke-width:1px;",
        "  classDef referenced_only fill:none,stroke:#999999,color:#777777,"
        "stroke-dasharray:5 5;",
    ),
)


# --------------------------------------------------------------------------- #
# classic - label-fitted boxes
# --------------------------------------------------------------------------- #

_CLASSIC = Theme(
    name="classic",
    description="Label-fitted boxes: blue services, orange topic hexagons.",
    node_styles={
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
    },
    unresolved_topic_style=(
        "shape=hexagon;perimeter=hexagonPerimeter2;whiteSpace=wrap;html=1;"
        "fixedSize=1;fillColor=#f5f5f5;strokeColor=#999999;dashed=1;"
        "fontColor=#666666;fontSize=11;verticalAlign=middle;align=center;"
    ),
    referenced_only_service_style=(
        "rounded=1;whiteSpace=wrap;html=1;arcSize=12;dashed=1;"
        "fillColor=none;strokeColor=#999999;fontColor=#777777;"
        "fontSize=12;fontStyle=2;verticalAlign=middle;align=center;"
    ),
    node_sizes=None,
    edge_base=("edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;jettySize=auto;"
               "orthogonalLoop=1;endArrow=blockThin;endFill=1;fontSize=10;"),
    edge_colours={
        (EDGE_PRODUCES, ""): "#d79b00",
        (EDGE_CONSUMES, ""): "#82b366",
        (EDGE_CALLS, "http"): "#6c8ebf",
        (EDGE_CALLS, "grpc"): "#9673a6",
        (EDGE_CALLS, ""): "#6c8ebf",
        (EDGE_DEPENDS, ""): "#666666",
    },
    inferred_edge_extra=("strokeColor=#999999;fontColor=#8c8c8c;"
                         "dashed=1;dashPattern=6 6;"),
    pin_adjacent_edges=True,
    column_gap=120,
    row_gap=40,
    margin_x=40,
    margin_y=40,
    back_edge_channel=60,
    legend_style=("text;html=1;align=left;verticalAlign=top;whiteSpace=wrap;"
                  "rounded=1;fillColor=#ffffff;strokeColor=#b3b3b3;"
                  "fontSize=10;fontColor=#555555;"),
    legend_width=300,
    legend_height=56,
    mermaid_shapes={
        KIND_SERVICE: '{0}["{1}"]',
        KIND_TOPIC: '{0}{{{{"{1}"}}}}',
        KIND_DATASTORE: '{0}[("{1}")]',
        KIND_CACHE: '{0}[("{1}")]',
        KIND_EXTERNAL_API: '{0}(["{1}"])',
    },
    mermaid_classes=(
        "  classDef service fill:#dae8fc,stroke:#6c8ebf,color:#10314f;",
        "  classDef topic fill:#ffe6cc,stroke:#d79b00,color:#653700;",
        "  classDef datastore fill:#d5e8d4,stroke:#82b366,color:#1f3d18;",
        "  classDef cache fill:#e1d5e7,stroke:#9673a6,color:#3b2a45;",
        "  classDef external_api fill:#f5f5f5,stroke:#666666,color:#333333;",
        "  classDef referenced_only fill:none,stroke:#999999,color:#777777,"
        "stroke-dasharray:5 5;",
    ),
)


THEMES = {
    _STREAMS.name: _STREAMS,
    _CLASSIC.name: _CLASSIC,
}

THEME_NAMES = tuple(sorted(THEMES))


def get_theme(name=None) -> Theme:
    """Resolve a theme by name. Unknown names fall back to the default.

    Falling back rather than raising is deliberate: a model laid out by a newer
    version of this skill can name a theme this one has never heard of, and a
    diagram in the wrong shapes beats no diagram at all. Callers that want to
    reject an unknown name check `name in THEMES` first - the CLIs do, through
    `argparse` `choices`.
    """
    if not name:
        return THEMES[DEFAULT_THEME]
    return THEMES.get(str(name), THEMES[DEFAULT_THEME])
