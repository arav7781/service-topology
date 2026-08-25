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
    and in either draw.io colour scheme. Shapes are fixed-size and small, so a
    name too long to sit inside one is wrapped and drawn underneath it, in
    space `layout.py` reserves from the same numbers.

``classic``
    The label-fitted boxes this skill emitted before themes existed. Kept
    because it is more compact for a small graph, and because changing what an
    existing pipeline renders is not something a version bump should do
    silently.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .textutil import wrap_label
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

THEME_VERSION = "1.1.0"

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

    # --- labels ---
    # How many characters fit on one line of a node label, per kind. draw.io
    # will not break `payrx-core-refund-request-topic-local` for us - there is
    # no space in it to break on - so the renderer inserts the breaks itself and
    # the layout counts the lines they produce. Both read these numbers.
    label_chars: Dict[str, int] = field(default_factory=dict)
    label_chars_default: int = 24
    label_line_height: int = 13
    label_char_width: int = 6
    # Kinds whose label is drawn *below* the shape rather than inside it. A
    # 37-character topic name has no business inside an 80-unit circle.
    label_outside: Tuple[str, ...] = ()
    label_gap: int = 6
    # Longest arrow label, in characters. Past this the label is elided and the
    # full text moves to the tooltip: an arrow label wider than the gap it sits
    # in lands on the next arrow's label.
    edge_label_chars: int = 28

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
    # A band above the diagram for arrows that span more than one column. They
    # used to be drawn straight, which on a wide diagram means straight through
    # whatever boxes happen to sit between the two ends.
    long_edge_channel: int = 70

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

    def wrap(self, kind: str, text: str) -> List[str]:
        """The lines a node label is drawn on. The single source of both truths.

        `layout.py` calls this to work out how much room to reserve and
        `render.py` calls it to write the label; calling it twice is what keeps
        the reserved space and the drawn text the same size.
        """
        return wrap_label(text, self.label_chars.get(kind, self.label_chars_default))

    def labels_outside(self, kind: str) -> bool:
        return kind in self.label_outside


# --------------------------------------------------------------------------- #
# streams - the Kafka Streams dataflow idiom
# --------------------------------------------------------------------------- #

# Fill and stroke are deliberately left unset on most shapes. draw.io then uses
# its own defaults, which follow the viewer's light/dark setting - a diagram
# that hard-codes #ffffff is a white rectangle in a dark canvas.
_STREAMS_LABEL = "verticalAlign=middle;align=center;"
# A name too long for the shape it names goes *under* it. Inside an 80-unit
# circle, `payrx-core-refund-request-topic-local` is drawn as one unbroken run
# that overhangs the circle by a factor of three and lands on whatever is next
# to it; underneath, wrapped, it is centred in space the layout reserved for it.
_STREAMS_OUTSIDE_LABEL = (
    "verticalLabelPosition=bottom;verticalAlign=top;labelPosition=center;"
    "align=center;")
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
            + _MONO + "fontSize=9;" + _STREAMS_OUTSIDE_LABEL
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
            "fontSize=9;" + _STREAMS_OUTSIDE_LABEL
        ),
    },
    unresolved_topic_style=(
        "ellipse;whiteSpace=wrap;html=1;aspect=fixed;dashed=1;"
        "fillColor=none;strokeColor=#999999;fontColor=#666666;"
        + _MONO + "fontSize=9;" + _STREAMS_OUTSIDE_LABEL
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
    # A diamond and a cylinder hold their own name; a circle does not, so a
    # topic gets the wider line and is drawn underneath the shape instead.
    label_chars={
        KIND_SERVICE: 14,
        KIND_TOPIC: 22,
        KIND_DATASTORE: 13,
        KIND_CACHE: 13,
        KIND_EXTERNAL_API: 22,
    },
    label_chars_default=22,
    label_line_height=12,
    label_char_width=6,
    label_outside=(KIND_TOPIC, KIND_EXTERNAL_API),
    label_gap=6,
    edge_label_chars=26,
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
    long_edge_channel=90,
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
    # No fixed sizes: the box is fitted to the label, so the wrap width is what
    # decides how wide the box gets. 30 characters at 8 units lands just inside
    # the 280-unit clamp in `layout.py`.
    label_chars_default=30,
    label_line_height=18,
    label_char_width=8,
    edge_label_chars=20,
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
    # Wide enough for an arrow label to sit between two boxes rather than on
    # one of them. A 20-character label is about 140 units at this font size.
    column_gap=160,
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
