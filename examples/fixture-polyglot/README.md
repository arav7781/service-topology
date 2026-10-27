# fixture-polyglot

A fake eight-service shop built to stress the parts of the skill that
`fixture-mesh` doesn't reach: four brokers, five languages, bindings hidden
behind wrappers and constants, a topic only the deployment knows, and traps
that a careless sweep would draw as edges. It doesn't run; every file exists
to be read.

## What it plants

| Service | Language | Exercises |
|---|---|---|
| `gateway` | TypeScript | `axios.create({ baseURL })` from env; `fetch` through a constant; **traps:** Express `res.send`, RxJS `.subscribe`, a `localhost` call |
| `orders-api` | Java / Spring | `KafkaTemplate` field with topics from a **constants class in another file**; Feign client by name; gRPC stub whose address is in `application.yml`; JDBC URL |
| `payments` | Go | HTTP callback into its own caller through an env base URL; RabbitMQ publish with a routing key; hard-wired Adyen URL |
| `fulfillment` | Python | Kafka consumed through a **project wrapper** (`EventBus`); RabbitMQ queue bound to an exchange; **direct reads of orders-api's database**; SQS send with the queue URL in `.env`; **trap:** a test-only consumer |
| `shipping` | TypeScript | SQS receive; NATS publish; hard-wired EasyPost URL |
| `notifier` | Go | NATS subscribe; a **subject computed per tenant at runtime** |
| `analytics` | Python | Kafka consumer whose topic is **only set at deploy time** |
| `catalog` | Python | FastAPI routes; Redis; gRPC server registration; **trap:** a generated `*_pb2_grpc.py` |

## Expected result

18 nodes, 20 edges, 2 gaps:

- **19 `CODE` edges**, including the ones that need a second file: the
  constants class, the wrapper, `.env`, `application.yml`, compose.
- **1 `INFERENCE` edge:** `analytics` consumes `ANALYTICS_TOPIC?`, a topic with
  no value in the repository.
- **2 gaps:** the deploy-time topic name, and `notifier`'s per-tenant subject.
- **0 trap edges:** no `res.send`, RxJS subscription, `localhost`, test consumer
  (`orders.test`) or generated stub appears.

A review should find, with receipts: the sync cycle `orders-api` ⇄
`payments` (T1, high), the shared `orders-db` (T3, high), the three-hop sync
chain to Adyen (T5), `orders-api` as a hub (T6), the unconsumed `orders.audit`
(T4), and the hard-wired vendor URLs (T8).

The output in [`service-topology/`](service-topology/) was produced by
following the skill against this directory. Check its receipts with:

```bash
bash tools/check-ledger.sh examples/fixture-polyglot \
     examples/fixture-polyglot/service-topology/topology.ledger
```
