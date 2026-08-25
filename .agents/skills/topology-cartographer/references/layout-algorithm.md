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

## The six steps

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

Layer index becomes a column, position within the layer becomes a row. Each
column is centred vertically against the tallest column, so the arrows between
adjacent columns run roughly horizontal.

What is reserved for a node is its **footprint**, not its shape. Those differ
whenever a label is drawn outside the shape it names: a topic in `streams` is an
80x80 circle, but `payrx-core-refund-request-topic-local` written under it needs
about 130 units of width and two more lines of height. Reserving 80 is how a
name ends up written across the node below it, which is the single most common
cause of an unreadable diagram.

Node size, wrap width and column spacing come from the theme, not from this
module. Under `streams` (the default) every node has a fixed size per kind, a
topic's name is wrapped at 22 characters and drawn below the circle, and the
columns are spaced 240 units apart. Under `classic` there are no fixed sizes, so
each box is fitted to its *wrapped* label at eight units per character, clamped
to 160-280 wide, in 160-unit columns.

This is why the theme is chosen at layout time and stamped into the layout
block: a renderer that styled these coordinates with the other theme's shapes
would draw every node at the wrong size, and one that wrapped labels at a
different width would draw them at the wrong height.

### 5. Route

| Span | Route |
|---|---|
| One layer | Straight. Under `classic`, pinned to the right edge of the source and the left edge of the target; under `streams` left floating, so the line lands on the perimeter point of a circle or a diamond rather than its bounding box |
| More than one layer | Up into a channel above the diagram, across, and back down. Three lanes, rotating. Drawn straight it would run through every box between its two ends - and so would its label |
| Zero or negative (a back edge) | Down into a channel below the diagram, across, and back up. Three lanes, rotating, so parallel back edges do not overlap |

The channel above is only reserved when something actually spans more than one
column. An ordinary producer-topic-consumer chain moves one column at a time and
would otherwise gain a band of white space at the top for nothing.

### 6. Place the arrow labels

draw.io centres every edge label, so four arrows crossing one column gap write
four labels in the same place, and a long arrow writes its label on top of
whatever it flies over. Each label is therefore slid along its own arrow to the
first position that is clear of every node, every node label, and every label
already placed. Candidates are tried nearest-the-middle first, so a label only
moves as far as it has to; a crowded diagram where nothing is free keeps the
position with the fewest collisions rather than dropping back onto the pile.

Only the label moves. The arrow, and both things it connects, stay exactly where
step 4 put them.

The label's size is taken as its worst case - `edge_label_chars` wide - because
the text is not written until render time. That is deliberate: `render.py` owns
the wording, the layout owns the geometry, and neither reaches into the other.

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

## Why labels are short

A diagram label is a *relationship name*: `produces`, `group=refund`,
`POST /.../claims`. It is not a restatement of the diagram. Both ends of an
arrow are already drawn and named, so `render.py` drops any part of a label that
merely repeats the name of the shape at either end, and elides what is left to
the theme's `edge_label_chars`.

Nothing is lost. The full string is on the edge's `fullLabel` and tooltip in the
`.drawio` file - one `Edit > Edit Data` away - and in `evidence/sources.md`,
which is generated with no limit at all because a table has the room.

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
