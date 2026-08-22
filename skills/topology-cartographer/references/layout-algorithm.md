# Layout Algorithm

What `scripts/layout_graph.py` does, and why it does it that way. Read this when
a diagram reads badly. Do not read it in order to place a node yourself - the
script owns placement, and hand-placing one node breaks the determinism the rest
of the pipeline depends on.

---

## Why determinism is a requirement, not a nicety

Re-running the pipeline on unchanged code must produce byte-identical output.
That is what makes two diagrams diffable: a change in the file means a change in
the architecture, not a change in the weather. Every sort in the layout has an
explicit total tie-break on the node id; nothing depends on dictionary insertion
order, on filesystem walk order, or on a random seed.

The same requirement rules out a force-directed layout, which would be prettier
and would move every node whenever one edge changed.

---

## The five steps

### 1. Break cycles

Services call each other in both directions, so the graph is not a DAG. A
depth-first search over node ids **in sorted order** finds the back edges. Sorted
order is what makes the choice reproducible: the same graph always yields the
same set of back edges.

The search uses an explicit stack rather than recursion - a large monorepo graph
will outrun Python's recursion limit.

Back edges are not discarded. They are drawn, routed through a channel below the
diagram so an arrow never runs backwards through a box.

### 2. Assign layers

Longest path from the sources, ignoring back edges. A node with no remaining
predecessors starts at layer 0; every child sits at least one layer right of its
deepest parent. Anything still unplaced afterwards - a knot the cycle-breaker
could not fully unpick - is placed one layer right of its deepest resolved
predecessor rather than dropped.

For a Kafka topology this produces the shape you want without being told to:
producers left, topics centre, consumers right, datastores at the far right
because nothing flows out of them.

### 3. Order within a layer

Four barycentre sweeps, alternating direction. Each node moves toward the
average position of its neighbours in the adjacent layer, which is the standard
way to reduce edge crossings. Ties break on node id, so equal barycentres never
flip between runs.

The seed order groups a column by kind before id, which keeps topics from being
interleaved with services in the same column.

### 4. Place

Layer index becomes a column, position within the layer becomes a row. Each box
is sized around its label - eight units per character, clamped to 160-280 wide -
and each column is centred vertically against the tallest column, so the arrows
between adjacent columns run roughly horizontal.

### 5. Route

| Span | Route |
|---|---|
| One layer | Straight, pinned to the right edge of the source and the left edge of the target |
| More than one layer | A jog at the horizontal midpoint, so the arrow does not clip the columns it flies over |
| Zero or negative (a back edge) | Down into a channel below the diagram, across, and back up. Three lanes, rotating, so parallel back edges do not overlap |

---

## The micro layout is different

A micro topology uses five fixed columns rather than computed layers:

```text
upstream | inbound | FOCUS | outbound | downstream
```

- **inbound**: anything with an edge into the focus service - topics it
  consumes, services that call it.
- **outbound**: anything with an edge out of it - topics it produces, services
  it calls, datastores it uses.
- **upstream**: producers into the topics it consumes.
- **downstream**: consumers of the topics it produces.

Fixed columns mean every micro topology reads the same way, so a reader who has
seen one knows where to look in the next. It also makes the two-hop Kafka
context legible: you can see who else is on the other end of your topic without
that being confused with a direct call.

---

## When a diagram still reads badly

Options, in order of preference:

1. **Narrow the scope.** `--scope services/orders,services/billing` produces a
   readable diagram of the part that matters. A 40-service master topology is
   honest and unreadable; two 8-service ones are honest and useful.
2. **Use micro topologies.** They are the answer to "this is too dense", and
   they are why the mode exists.
3. **Open it in draw.io and move things.** The file is a normal `.drawio`
   document; the user can rearrange it freely. Warn them that re-running the
   pipeline overwrites the file - they should save a copy under a different name
   first.

Never hand-edit coordinates in `graph-model.laid-out.json`. If the layout is
wrong for a whole class of diagram, that is a change to `layout.py`.
