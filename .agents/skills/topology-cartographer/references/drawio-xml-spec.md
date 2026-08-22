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

Node styles, all core mxGraph shapes - nothing here needs a shape library:

| Kind | Style | Reads as |
|---|---|---|
| service | `rounded=1` blue | a deployable |
| service, referenced-only | `rounded=1;dashed=1;fillColor=none` grey | something we only know is called |
| topic | `shape=hexagon` orange | a Kafka topic |
| topic, unresolved name | `shape=hexagon;dashed=1;fillColor=none` grey | a config key we could not resolve |
| datastore | `shape=cylinder3` green | a database |
| cache | `shape=cylinder3` purple | a cache |
| external API | `shape=cloud` grey | something outside the system |

A topic is a hexagon rather than the more conventional horizontal cylinder
precisely because datastores are cylinders here. Two shapes that differ only by
rotation are two shapes a reader has to think about.

Edge colours carry the relationship, and the dash carries the evidence:

| Edge | Colour |
|---|---|
| `produces` | orange |
| `consumes` | green |
| `calls`, http | blue |
| `calls`, grpc | purple |
| `depends_on` | grey |
| anything not `[CODE]` | overridden to dashed grey, whatever its type |

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

Edges between adjacent columns carry none, and instead pin their exit and entry
to the facing sides of the boxes (`exitX=1`, `entryX=0`), which is what makes a
left-to-right diagram read as left-to-right flow.

---

## Verifying output

```bash
python3 -c "import xml.etree.ElementTree as ET, sys; ET.parse(sys.argv[1])" \
    service-topology/master-topology.drawio
```

Well-formedness is necessary and not sufficient. The real check is opening the
file - in the `hediet.vscode-drawio` extension or at diagrams.net - and
confirming the boxes, the shapes, and the labels are all there.
