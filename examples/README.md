# Examples

Worked output from Topology Cartographer.

> **These are real output, not mockups.** Both documents were produced by
> running the pipeline against [`fixture-mesh/`](fixture-mesh/), a small
> synthetic three-service system that lives in this repository. Every file path
> and line number in them resolves to a file you can open, and each document
> ends with the commands that regenerate it.

| File | Demonstrates |
|---|---|
| [sample-master-topology.md](sample-master-topology.md) | The whole-system diagram: services, Kafka topics, REST and gRPC calls, external systems as leaves, and one `[INFERENCE]` edge rendered visibly differently from the nine `[CODE]` ones |
| [sample-micro-topology.md](sample-micro-topology.md) | One service's neighbourhood as a strict subset of the master, the two-hop Kafka context, blast-radius analysis, and a base URL resolved across two files |
| [fixture-mesh/](fixture-mesh/) | The synthetic repository both were generated from - Go, Python, and TypeScript services with a shared topic and a deliberately unresolvable gRPC stub |

## What to look at

**Visible uncertainty.** In `sample-master-topology.md`, the arrow to
`Inventory` is dotted and its box is hollow before you read a word of prose. The
one unconfirmed edge out of ten is legible from the picture alone, which is the
property the whole evidence system exists to produce.

**One node, several citations.** `orders-db` was seen three times - a container
image, a `depends_on`, and a connection string in Go. It is one box with three
citations, not three near-duplicate boxes.

**Honest gaps.** Both documents end with "what this diagram does not show",
naming the consumer group read from a variable, the URL assembled by
concatenation, and the `.proto` that lives elsewhere. A reader who knows what is
missing can trust what is present.

## Regenerating the examples

```bash
S=skills/topology-cartographer/scripts
OUT=/tmp/topology-example

python3 $S/scan_repository.py examples/fixture-mesh -o /tmp/scan.json
python3 $S/build_graph_model.py --input /tmp/scan.json \
    --output-root $OUT -o $OUT/graph-model.json \
    --evidence-out $OUT/evidence/sources.md
python3 $S/layout_graph.py $OUT/graph-model.json \
    --output-root $OUT -o $OUT/graph-model.laid-out.json
python3 $S/render_drawio.py $OUT/graph-model.laid-out.json \
    --mode all --output-dir $OUT --output-root $OUT
python3 $S/render_mermaid.py $OUT/graph-model.laid-out.json \
    --mode all --output-dir $OUT --output-root $OUT
python3 $S/validate_graph_model.py $OUT/graph-model.json \
    --repo examples/fixture-mesh
```

Run the full pipeline twice into two directories and `diff -r` them: the output
is byte-identical, which is the property that makes a diff between two runs a
diff between two architectures.
