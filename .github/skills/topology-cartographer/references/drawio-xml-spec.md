# draw.io / mxGraph XML Spec

What `scripts/render_drawio.py` emits, and why each part is shaped the way it
is. **Read this to understand the output. Never use it to write XML yourself** -
hand-written mxGraph going straight into a rendered diagram is exactly the
failure mode this design exists to prevent.

---

## Document shape

```xml
<mxfile host="topology-cartographer" agent="topology-cartographer/1.0.0"
        version="24.7.17" type="device">
  <diagram id="<stable hash>" name="Master topology">
    <mxGraphModel dx="..." dy="..." grid="1" gridSize="10" guides="1"
                  tooltips="1" connect="1" arrows="1" fold="1" page="1"
                  pageScale="1" pageWidth="1169" pageHeight="826"
                  math="0" shadow="0">
      <root>
        <mxCell id="0" />
        <mxCell id="1" parent="0" />
        <!-- nodes and edges, each wrapped in a UserObject -->
      </root>
    </mxGraphModel>
  </diagram>
</mxfile>
```

Cells `0` and `1` are mandatory: `0` is the model root and `1` is the default
layer every visible cell parents to. Omitting either produces a file draw.io
opens as blank.

**No `modified` attribute.** It is optional, and leaving it out is what lets an
unchanged repository re-render byte-identically. The `diagram id` is a SHA-1 of
the title and the node and edge ids - stable across runs, distinct per diagram,
never a random UUID.

---

## Why UserObject rather than plain mxCell

Every node and edge is wrapped:

```xml
<UserObject label="key=order_id"
            tooltip="services/orders/kafka/producer.go:20"
            evidenceTag="CODE"
            sourceLocation="services/orders/kafka/producer.go:20"
            edgeType="produces"
            extractor="kafka-go"
            id="edge-3">
  <mxCell style="..." edge="1" parent="1" source="node-4" target="node-7">
    <mxGeometry relative="1" as="geometry" />
  </mxCell>
</UserObject>
```

A `UserObject` carries arbitrary attributes that draw.io surfaces under
`Edit > Edit Data`, and shows as a tooltip on hover. That means the evidence
travels *inside* the diagram: someone handed only the `.drawio` file can select
any arrow and see the `file:line` that justifies it, without the graph model,
the evidence report, or the repository.

The `id` belongs on the `UserObject`, not on the inner `mxCell`. Edge `source`
and `target` reference those ids.

---

## Styles

Every style comes from `scripts/topology_lib/theme.py`, never from a literal in
the renderer. Two themes ship, chosen with `--theme` on `layout_graph.py` and
`render_drawio.py`. All shapes in both are core mxGraph - nothing needs a shape
library.

### `streams` (default)

The Kafka Streams dataflow idiom: **kind is carried by shape, not by fill.** At
three hundred nodes a reader stops distinguishing seven pastel fills and never
stops distinguishing a circle from a diamond, and leaving fill unset means the
diagram follows draw.io's own light/dark setting instead of being a white
rectangle on a dark canvas.

| Kind | Style | Drawn at | Reads as |
|---|---|---|---|
| topic | `ellipse;aspect=fixed` | 80x80 | a Kafka topic |
| topic, unresolved name | `ellipse;dashed=1;fillColor=none` grey | 80x80 | a config key we could not resolve |
| service | `rhombus` | 120x115 | the processor between two topics |
| service, referenced-only | `rhombus;dashed=1;fillColor=none` grey | 120x115 | something we only know is called |
| datastore | `shape=cylinder3;size=15` | 110x95 | a database |
| cache | `shape=cylinder3;size=15` purple | 110x95 | a cache |
| external API | `shape=offPageConnector` | 80x80 | the flow continues outside this diagram |

Cache is the one place this theme spends colour, because a cache and a database
are both cylinders and nothing but fill can separate them.

Shapes are fixed-size and small, so a long topic name overhangs its circle -
that is the idiom, not a defect, and it is why this theme also asks for a
240-unit column gap. Topic labels are set in a monospace stack, which is what
makes `orders.created.v2` and `orders_created_v2` distinguishable at 9px.

Edges carry no `edgeStyle`, so draw.io draws the direct line between two
perimeter points rather than an elbow, and adjacent-column arrows are *not*
pinned with `exitX`/`entryX`: on a circle or a diamond a floating connection
finds the perimeter point that actually faces the other node, where a pinned one
leaves the arrow hanging off the bounding box.

### `classic`

The label-fitted boxes this skill emitted before themes existed - blue rounded
service, orange topic hexagon, green datastore cylinder, purple cache cylinder,
grey external cloud, orthogonal elbow edges pinned to the facing sides. More
compact for a small graph, and still selectable so that upgrading this skill
does not silently redraw an existing pipeline's output.

### Both themes

Edge colours carry the relationship, and the dash carries the evidence:

| Edge | Colour |
|---|---|
| `produces` | orange |
| `consumes` | green |
| `calls`, http | blue |
| `calls`, grpc | purple |
| `depends_on` | grey |
| anything not `[CODE]` | overridden to dashed grey, whatever its type |

### A theme fixes sizes, not just styles

`streams` draws a topic at 80x80 whatever its name is; `classic` fits the box to
the label and can reach 280 wide. So the layout and the render must agree on one
theme, or boxes are placed for sizes they were never drawn at. `layout_all`
stamps its theme name into the layout block, the renderers default to whatever
is stamped there, and passing a different `--theme` to `render_drawio.py`
re-runs the layout rather than styling one layout with another theme's shapes.

`--flow-animation` adds draw.io's marching-ants `flowAnimation=1` to every edge.
Good on a twenty-node dataflow, unreadable on a large master topology, so it is
off unless asked for.

---

## Labels are HTML

`html=1` is set on every cell, so the label is parsed as HTML and a raw newline
collapses. Multi-line labels use `<br>`, which ElementTree escapes to `&lt;br&gt;`
on write and draw.io un-escapes on read. Putting a literal `\n` in a label
silently produces a single run-on line.

---

## Why ElementTree, not string formatting

A service called `Orders & Billing <v2>` is a legal service name and an illegal
XML attribute value. `xml.etree.ElementTree` escapes attributes on write, which
means no input can produce a file draw.io refuses to open. String-formatted XML
gets this wrong the first time a name contains an ampersand.

`ET.indent` only arrived in Python 3.9, and this repository supports 3.8, so
`render.py` carries its own small indenter.

---

## Waypoints

Routed edges carry explicit points:

```xml
<mxGeometry relative="1" as="geometry">
  <Array as="points">
    <mxPoint x="640" y="420" />
    <mxPoint x="200" y="420" />
  </Array>
</mxGeometry>
```

Edges between adjacent columns carry none. Under `classic` they instead pin
their exit and entry to the facing sides of the boxes (`exitX=1`, `entryX=0`),
which is what makes a left-to-right diagram of rectangles read as left-to-right
flow. Under `streams` they are left floating, because a pin computed for a
bounding box leaves the arrow hanging in the corner of a circle or a diamond
while a floating connection lands on the perimeter point that faces the other
node.

---

## Verifying output

```bash
python3 -c "import xml.etree.ElementTree as ET, sys; ET.parse(sys.argv[1])" \
    service-topology/master-topology.drawio
```

Well-formedness is necessary and not sufficient. The real check is opening the
file - in the `hediet.vscode-drawio` extension or at diagrams.net - and
confirming the boxes, the shapes, and the labels are all there.
