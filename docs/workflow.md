# Workflow

The six phases, what each produces, and the gate at the end of it. Companion to
[`architecture.md`](architecture.md), which explains why the
pipeline is shaped this way.

`SKILL.md` is the operational version of this document; this one has the
reasoning.

---

## Modes and phase coverage

| Mode | Phases | Cost | Use it when |
|---|---|---|---|
| `scan` | 0-2 | Cheap | Always first. Produces the service list and the graph model, no diagrams. |
| `master` | 0-5 | Moderate | You want the whole-system picture. |
| `micro <service>` | 0-5 | Cheap | You want one service's integration surface. |
| `all` | 0-5 | Proportional to service count | Small or mid-size systems. Ask first above ~25 services. |
| `refresh` | 1-5 | Same as the original | Code changed; re-render and report what moved. |

Default is `scan`, and it never escalates on its own. The service list it
produces is the thing that tells a human which micro topology is worth the next
few minutes.

---

## Phase 0 - Scope and service boundaries

Establish what counts as a service before extracting anything, because every
edge is a statement about services and a wrong boundary makes every edge wrong.

```bash
python3 scripts/scan_repository.py <repo> --format summary
```

Read the service list against the repository's own structure. Then emit one of:

```text
PROCEED | PROCEED_WITH_SCOPE | BOUNDARIES_UNCLEAR
```

**Gate.** `BOUNDARIES_UNCLEAR` stops the run. A modular monolith whose internal
modules each carry a manifest, or a system whose deployables are defined only in
Helm, needs a human to say which directories are services. Guessing produces a
diagram that is confidently wrong, which is worse than no diagram - a reader has
no way to detect it.

See
[`service-boundary-heuristics.md`](../skills/topology-cartographer/references/service-boundary-heuristics.md).

---

## Phase 1 - Extraction

```bash
python3 scripts/scan_repository.py <repo> [--scope path,...] -o scan.json
```

Every binding the extractors can trace to a `file:line`, tagged `[CODE]` or
`[INFERENCE]`. Five Kafka ecosystems, four HTTP client families, gRPC in two
phases, OpenAPI specs, connection strings, and the config files that hold the
values code refers to by key.

**Delegate on a large repository.** The `topology-extractor` subagent scans one
subtree and returns a shard. Three thousand files never enter one context
window, and the shards merge in phase 2.

**Check for absence, not just presence.** A service with `KafkaTemplate` on its
classpath and no `produces` edge is a signal. So is an HTTP client import with
no `calls` edge. Each is either a real absence or an extractor gap; say which
you think it is and cite what made you think so. A silent gap is the one failure
mode a reader cannot see.

---

## Phase 2 - Graph model

```bash
python3 scripts/build_graph_model.py --input scan.json \
    -o service-topology/graph-model.json \
    --evidence-out service-topology/evidence/sources.md
```

Merges shards, collapses duplicate sightings into one edge with several
citations, keeps the strongest evidence tag per fact, sorts everything, and
writes the evidence report. The merge is order-independent: the same shards in
any order produce the same bytes.

**Gate (`scan` mode ends here).** Report the service list with edge counts, the
`[CODE]`/`[INFERENCE]` split, and which micro topology looks most worth
generating.

---

## Phase 3 - Layout

```bash
python3 scripts/layout_graph.py service-topology/graph-model.json \
    -o service-topology/graph-model.laid-out.json
```

Cycle-breaking, layering, barycentre ordering, placement, and routing - all
deterministic, all in the standard library.

`--theme` is chosen at this step rather than at render time, because a theme
fixes how big each node is drawn as well as how it is styled: `streams` (the
default) places fixed-size circles and diamonds in wide columns, `classic`
places boxes fitted to their labels. The chosen theme is stamped into the
layout block and the renderers follow it. Do not compute a coordinate
yourself, and do not adjust one the script produced: the determinism is what
makes two runs diffable, and a single hand-placed node destroys it.

See
[`layout-algorithm.md`](../skills/topology-cartographer/references/layout-algorithm.md).

---

## Phase 4 - Render

```bash
python3 scripts/render_drawio.py service-topology/graph-model.laid-out.json \
    --mode all --output-dir service-topology
python3 scripts/render_mermaid.py service-topology/graph-model.laid-out.json \
    --mode all --output-dir service-topology
```

`--mode all` is the widest option, not the default one. Render what the user
asked for: `--mode master`, `--mode micro --service <name>`, or `--mode all
--no-master` for every micro topology and no whole-system diagram. Handing back
a master topology nobody asked for buries the diagram they wanted.

Two artefacts per diagram. The `.drawio` is the deliverable; the `.mmd` is the
fallback that needs nothing installed and renders in a pull request, a Markdown
preview, or a chat window.

Both carry the same evidence distinction: solid means `[CODE]`, dashed grey
means it is not confirmed - and both draw the same shapes, so the `.mmd` and the
`.drawio` read as one diagram rather than two.

Labels come from the renderers. A node's name is wrapped to what its shape can
hold, and drawn under the shape when it cannot hold it; an arrow gets a short
relationship name with anything that merely repeats an adjacent node's name
dropped, and the layout has already slid it clear of the other labels. The
untrimmed string is on the cell as `fullLabel`, in its tooltip, and in
`evidence/sources.md`.

Passing `--theme` here overrides the stamped theme and re-runs the layout, so
the shapes and the coordinates can never disagree.

---

## Phase 5 - Validation and handover

```bash
python3 scripts/validate_graph_model.py service-topology/graph-model.json \
    --repo <repo>
```

`--repo` re-reads every cited location and confirms the file exists and is long
enough for the line number. That is the check that catches a model rendered
against code that has since moved.

Warnings are not failures but each is a claim the summary must acknowledge: a
topic with producers and no consumers, a service with no edges, the count of
unconfirmed edges.

**Gate.** Tell the user the exact path to open, name the extension that renders
it, and mention the Mermaid fallback in the same breath.

---

## Stage gates

| Gate | Question | Who answers |
|---|---|---|
| Boundaries | Are these the right services? | The user, at the end of phase 0 |
| Cost | Large repository - which subsystems, how many micro topologies? | The user, before phase 1 |
| Accuracy | Does this match how the system actually behaves? | The user, after phase 5 |
| Sharing | Is this safe to circulate? | The user, before they share it |

The accuracy gate carries the most weight. The tool reads code; the user knows
production. Ask them to spot-check the edges around one service they know well,
and to read the "inferred, not confirmed" list before trusting the picture.

---

## The human workflow around the run

1. **Run `scan` first.** It is cheap and its output is a decision aid, not a
   deliverable.
2. **Look at the service list before anything else.** If it is wrong, stop.
3. **Generate the micro topology for a service you know well.** Check it against
   what you know. That calibrates how much to trust the rest.
4. **Then generate the master.** By now you know the extraction's error rate.
5. **Read `evidence/sources.md`, inferred section first.** It is short by
   design, and it is the only part that needs a decision.
6. **Re-run after code changes rather than editing the diagram.** `refresh` mode
   exists because code drifts faster than diagrams do, and a hand-edited diagram
   silently stops matching its evidence.
