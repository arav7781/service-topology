# fixture-mesh

A deliberately small, deliberately fake three-service system, used to test
Topology Cartographer end to end. It is **not** a runnable application: there
are no dependencies, no build, and no tests. Every file exists to give the
extractors something real to read.

What it contains, and which extractor each part exercises:

| Path | Language | Exercises |
|---|---|---|
| `services/orders` | Go | `segmentio/kafka-go` producer, PostgreSQL connection string, third-party HTTPS call, OpenAPI spec |
| `services/billing` | Python | `kafka-python` consumer, `requests` call resolved through a config base URL, Redis, an unresolvable gRPC stub |
| `services/notifications` | TypeScript | `kafkajs` consumer and producer, `fetch` call |
| `docker-compose.yml` | - | service hostnames, `depends_on`, infrastructure containers, the env var the billing base URL resolves through |

Expected result: 3 services, 2 topics, 3 external systems, and exactly one
`[INFERENCE]` edge - the gRPC stub in `services/billing/billing/inventory.py`,
which has no `.proto` anywhere in the fixture and so cannot be confirmed.

Regenerate the worked examples from it with:

```bash
python3 skills/topology-cartographer/scripts/scan_repository.py \
    examples/fixture-mesh -o /tmp/scan.json
python3 skills/topology-cartographer/scripts/build_graph_model.py \
    --input /tmp/scan.json --output-root /tmp/out -o /tmp/out/graph-model.json
```
