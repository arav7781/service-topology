# Examples

Real output from following the skill, not mockups. Each example keeps its
output where a real run would put it - `<repo>/service-topology/` - and its
ledger is checked in CI: every receipt has to resolve to a line in the files
beside it.

| Example | What it shows |
|---|---|
| [`fixture-mesh/`](fixture-mesh/) | Three services - Go, Python, TypeScript - one Kafka topic, REST callbacks and an unconfirmable gRPC stub. Five views from five questions, plus a draw.io file |
| [`fixture-polyglot/`](fixture-polyglot/) | Eight services over Kafka, RabbitMQ, SQS and NATS, with bindings behind wrappers and constants, a deploy-time-only topic, planted traps, and a review that finds a sync cycle and a shared database |
| [`third-party/online-boutique/`](third-party/online-boutique/) | Google's twelve-service gRPC demo, mapped at a pinned commit. Only the ledger and the view are kept here; CI re-checks the receipts against upstream |

## What to look at

- **Different questions, different diagrams.** Compare
  [lineage](fixture-mesh/service-topology/views/lineage-orders.created.md)
  with [impact](fixture-mesh/service-topology/views/impact-orders-svc.md).
  Both come from the same ledger, but each keeps only what its question needs.
- **Visible uncertainty.** In the
  [overview](fixture-mesh/service-topology/views/overview.md), the arrow to
  `InventoryService` is dashed, and its receipt row says why.
- **Resolution across files.** `billing-svc`'s consumer group is a variable.
  The ledger follows it to its env default and to `docker-compose.yml`, and
  cites all three lines.
- **Review with receipts.** The
  [review](fixture-mesh/service-topology/views/review.md) finds that both
  consumers call the producer back for every event, and proposes the smallest
  fix - drawn separately, labelled PROPOSED.

## Checking an example yourself

```bash
bash tools/check-ledger.sh examples/fixture-mesh \
     examples/fixture-mesh/service-topology/topology.ledger
```

To regenerate one, open the fixture in your agent and ask the question in the
view's title. Expect the same edges and receipts. The prose may differ, since
an LLM wrote it.
