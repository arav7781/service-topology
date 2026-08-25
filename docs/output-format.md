# Output Format

What lands on disk, in what shape, and how to check it. The contract between the
skill, the MCP server, and whoever reads the result.

---

## Directory layout

Everything goes under `service-topology/` at the root of the analysed
repository, or a directory the user names. Nothing is written anywhere else,
ever - see [`safety-model.md`](safety-model.md).

```text
service-topology/
├── master-topology.drawio        the whole system
├── master-topology.mmd           Mermaid fallback, same content
├── graph-model.json              the structured source of truth
├── graph-model.laid-out.json     the model plus diagram coordinates
├── micro/
│   ├── orders-svc.drawio         one service's direct neighbourhood
│   ├── orders-svc.mmd
│   └── ...
└── evidence/
    └── sources.md                every edge's tag and file:line
```

That is the full tree, which is what `all` produces. A narrower mode writes a
subset and leaves the rest absent - `micro <service>` writes no
`master-topology.*` at all, because it was not asked to.

File names are slugs of the service id. Ids are stable across `refresh` runs:
never renamed because a label changed, never renumbered.

Add `service-topology/` to a global gitignore, or exclude it locally. Do **not**
edit the analysed repository's `.gitignore` - it is part of that repository, and
this tool does not modify the repository it maps.

---

## Which file to open

| You want | Open |
|---|---|
| The diagram, in your editor | `master-topology.drawio` |
| The diagram, with nothing installed | `master-topology.mmd` |
| One service's integration surface | `micro/<service>.drawio` |
| To check an arrow | `evidence/sources.md`, then the cited line |
| To build something on top of this | `graph-model.json` |

---

## Evidence tags

| Tag | Meaning | In the diagram |
|---|---|---|
| `[CODE]` | Read directly - a literal at the call site, or a config key followed to a value in a file also read | Solid coloured arrow |
| `[INFERENCE]` | The pattern matched, the target did not resolve | Dashed grey arrow, reason recorded |
| `[UNVERIFIED]` | Asserted, not confirmed by reading a file | Dashed grey arrow, what would verify it recorded |

Nodes are qualified too. A service known only because something calls it, and a
topic whose name is an unresolved config key, both render hollow with a dashed
border.

Full rules in
[`evidence-classification.md`](../skills/topology-cartographer/references/evidence-classification.md).

---

## Machine-readable schemas

### `graph-model.json` - `topology-cartographer/graph-model`

Three node buckets and one edge list. Documented field by field in
[`graph-model-schema.md`](../skills/topology-cartographer/templates/graph-model-schema.md).

```json
{
  "schema": "topology-cartographer/graph-model",
  "schema_version": "1.0.0",
  "repo": "/home/dev/acme-platform",
  "stats": {"services": 3, "topics": 2, "edges": 10, "edges_code": 9,
            "edges_inference": 1},
  "services": [{"id": "orders-svc", "kind": "service", "language": "go",
                "path": "services/orders",
                "source_evidence": ["services/orders/go.mod:1"]}],
  "topics": [{"id": "orders.created", "kind": "topic",
              "source_evidence": ["services/orders/kafka/producer.go:12"]}],
  "external_systems": [{"id": "orders-db", "kind": "datastore",
                        "source_evidence": ["docker-compose.yml:4"]}],
  "edges": [{"from": "orders-svc", "to": "orders.created", "type": "produces",
             "protocol": "kafka", "detail": "key=orderID", "evidence_tag": "CODE",
             "source": "services/orders/kafka/producer.go:20",
             "also_at": ["services/orders/kafka/producer.go:12"],
             "extractor": "kafka-go"}],
  "warnings": []
}
```

No timestamp appears anywhere in it, deliberately: a timestamp would make every
run differ from the last and destroy the determinism check.

### `graph-model.laid-out.json`

The same document with a `layout` block: one entry per diagram, each holding
node geometry, per-edge waypoints, and the canvas size.

### The scan document - `topology-cartographer/scan`

What `scan_repository.py` emits, and what `build_graph_model.py` consumes. Wraps
a graph-model payload in `graph`, alongside a `discovery` block reporting the
file count, the services found, and the config index summary. Distinguishable
from a finished model by its `schema` field, so passing the wrong file is an
error rather than a silent half-result.

### The validation report - `topology-cartographer/validation`

```json
{
  "schema": "topology-cartographer/validation",
  "ok": true,
  "counts": {"services": 3, "topics": 2, "external_systems": 3, "edges": 10},
  "problems": [],
  "warnings": ["notifications.sent: produced but no consumer found"],
  "unresolved_citations": []
}
```

`problems` are blocking. `warnings` are claims the summary must acknowledge.
`unresolved_citations` is populated only with `--repo`, and any entry there
means the model no longer matches the code.

---

## The `.drawio` file

Standard mxGraph, openable at diagrams.net, in draw.io desktop, or by the
`hediet.vscode-drawio` extension. Two things about it are unusual and deliberate:

**Every node and edge is a `UserObject`.** That carries the evidence *inside*
the diagram: select an arrow in draw.io, `Edit > Edit Data`, and see its
`sourceLocation`, `evidenceTag`, and any `inferenceNote`. Someone handed only
the file can audit it without the model, the report, or the repository.

**No `modified` timestamp, and a content-hashed `diagram id`.** Both exist so
that re-rendering unchanged code produces byte-identical XML.

Full detail in
[`drawio-xml-spec.md`](../skills/topology-cartographer/references/drawio-xml-spec.md).

---

## Validation

```bash
# structure, tags, and citation format
python3 scripts/validate_graph_model.py service-topology/graph-model.json

# also re-read every cited file:line in the analysed repository
python3 scripts/validate_graph_model.py service-topology/graph-model.json \
    --repo /path/to/repo

# warnings become failures
python3 scripts/validate_graph_model.py service-topology/graph-model.json \
    --repo /path/to/repo --strict

# machine-readable
python3 scripts/validate_graph_model.py service-topology/graph-model.json \
    --format json
```

XML well-formedness, separately:

```bash
python3 -c "import xml.etree.ElementTree as ET,sys; ET.parse(sys.argv[1])" \
    service-topology/master-topology.drawio
```

Determinism, which is the check most likely to catch a regression:

```bash
# render twice into two directories, then
diff -r run-a/ run-b/ && echo "byte-identical"
```

---

## Sensitive output

A topology diagram is a map of internal structure: which services exist, what
they are called, which hold which data, and which third parties are in the
path. `evidence/sources.md` additionally names file paths and line numbers
throughout the codebase.

None of it contains credentials - connection strings are reduced to a host and a
database name before they become a node, and no value from a `.env` file is
reproduced in the output except a topic name or a base URL. It is still
internal-architecture material. Treat it the way you would treat an internal
design document, and prompt the user before it goes anywhere public.
