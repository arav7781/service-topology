# draw.io output - on request only

Write `views/<name>.drawio` beside the `.md`, from the same subgraph. The limit
is 30 nodes: past it, say so and keep the Mermaid view.

## Layout - compute it, no tool needed

1. **Rank.** Rank over the `pub`, `sub`, `uses` and `dep` edges, plus each
   sync edge (in ledger order) whose target cannot already reach its source -
   a callback against the event flow is drawn, but does not rank. A node with
   no remaining incoming edge has rank 0; otherwise rank = 1 + the highest
   rank among its predecessors.
2. **Columns.** x = 40 + rank × 240. Within a column, order nodes by the mean
   row of their predecessors, ties by id; y = 40 + row × 140.
3. **Sizes.** svc and ref 160×60 · topic, queue and ext 140×60 · db, cache and
   store 120×80. Centre each in its column: add (160 − width) / 2 to x.

## Document

```xml
<mxfile host="topology-cartographer">
  <diagram id="LENS-SUBJECT" name="TITLE">
    <mxGraphModel grid="1" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" page="0">
      <root>
        <mxCell id="0"/>
        <mxCell id="1" parent="0"/>
        <UserObject id="n1" label="orders-svc" kind="svc" receipts="services/orders/go.mod:1">
          <mxCell style="NODE_STYLE" vertex="1" parent="1">
            <mxGeometry x="40" y="40" width="160" height="60" as="geometry"/>
          </mxCell>
        </UserObject>
        <UserObject id="e1" label="key=orderID" tag="CODE" receipts="services/orders/kafka/producer.go:21" tooltip="CODE · services/orders/kafka/producer.go:21">
          <mxCell style="EDGE_STYLE" edge="1" parent="1" source="n1" target="n2">
            <mxGeometry relative="1" as="geometry"/>
          </mxCell>
        </UserObject>
      </root>
    </mxGraphModel>
  </diagram>
</mxfile>
```

Cells `0` and `1` are mandatory - without them draw.io opens a blank page.
Node ids are `n1…`, edge ids `e1…`, in ledger order. In every attribute escape
`&` `<` `>` `"` as `&amp;` `&lt;` `&gt;` `&quot;`. Line breaks in a label are
`&lt;br&gt;`, never a raw newline. Receipts travel inside the cell, so anyone
holding only the `.drawio` can select an arrow and read where it came from
(`Edit > Edit Data`).

## Styles

Every node style starts `whiteSpace=wrap;html=1;`.

| Kind | Style |
|---|---|
| svc | `rounded=1;fillColor=#dbeafe;strokeColor=#2563eb;` |
| ref | `rounded=1;dashed=1;fillColor=none;strokeColor=#94a3b8;fontColor=#475569;` |
| topic | `shape=hexagon;perimeter=hexagonPerimeter2;size=0.15;fillColor=#ffedd5;strokeColor=#ea580c;fontFamily=monospace;` |
| queue | `shape=parallelogram;perimeter=parallelogramPerimeter;fillColor=#ffedd5;strokeColor=#ea580c;` |
| db, store | `shape=cylinder3;size=12;fillColor=#dcfce7;strokeColor=#16a34a;` |
| cache | `shape=cylinder3;size=12;fillColor=#f3e8ff;strokeColor=#9333ea;` |
| ext | `shape=cloud;fillColor=#f1f5f9;strokeColor=#64748b;` |
| proposed node | add `dashed=1;dashPattern=6 3;` |
| lens subject (`focus`, `impact`) | add `strokeWidth=3;` |

Edges: `html=1;rounded=1;endArrow=block;edgeStyle=orthogonalEdgeStyle;` plus a
stroke per rel - pub `#ea580c`, sub `#16a34a`, http `#2563eb`, grpc `#9333ea`,
gql and ws `#0891b2`, uses `#64748b`, dep `#94a3b8`. Not `CODE`:
`dashed=1;strokeColor=#94a3b8;`. Proposed: `strokeWidth=3;strokeColor=#16a34a;`.
Removed: `dashed=1;strokeColor=#dc2626;endArrow=cross;`.

## Check before handing over

Ids are unique, every edge's `source` and `target` is a node id, every
attribute is escaped, and the edge count matches the Mermaid view.
