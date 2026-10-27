# fixture-mesh

A small, deliberately fake three-service system for testing Topology
Cartographer end to end. It isn't a runnable application: there are no
dependencies, no build and no tests. Every file exists to give the sweeps
something real to read.

| Path | Language | Exercises |
|---|---|---|
| `services/orders` | Go | `segmentio/kafka-go` producer, PostgreSQL connection string, third-party HTTPS call, OpenAPI spec |
| `services/billing` | Python | `kafka-python` consumer with its group in an env default, `requests` call through a config base URL, Redis, an unconfirmable gRPC stub |
| `services/notifications` | TypeScript | `kafkajs` consumer and producer, `fetch` through a file constant |
| `docker-compose.yml` | - | Hostnames, env values, `depends_on`, infrastructure images |

Expected result: 3 services and 1 referenced-only service, 2 topics, 3 stores
and externals, 10 edges - exactly one of them `INFERENCE` (the gRPC stub in
`services/billing/billing/inventory.py`, which has no `.proto` anywhere) - and
1 gap.

The output in [`service-topology/`](service-topology/) came from following the
skill against this directory. Check its receipts with:

```bash
bash tools/check-ledger.sh examples/fixture-mesh \
     examples/fixture-mesh/service-topology/topology.ledger
```
