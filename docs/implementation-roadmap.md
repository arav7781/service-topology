# Implementation Roadmap

Where Topology Cartographer is, what it does not do yet, and the order those
gaps get closed. Companion to
[`architecture.md`](architecture.md).

---

## V1 - Evidence-backed diagrams (this release)

Kafka and synchronous calls, one layout algorithm, four hosts.

| Area | Shipped |
|---|---|
| Kafka | Spring Kafka, Kafka Streams, the plain Java client, kafka-python, confluent-kafka, aiokafka, faust, kafkajs, node-rdkafka, NestJS, segmentio/kafka-go, sarama, Spring Cloud Stream bindings |
| Sync calls | OpenAPI specs, `.proto` plus generated-stub usage, requests/httpx, axios/fetch/got, RestTemplate/WebClient/OkHttp/Feign, net/http, resty |
| Config resolution | `application.yml`, `.properties`, `bootstrap.*`, `.env*`, docker-compose, Helm values, Terraform topic resources |
| External systems | Datastores, caches, and third-party APIs as leaf nodes, from connection strings and compose containers |
| Output | `.drawio` master and per-service micro topologies, Mermaid fallback, `graph-model.json`, evidence report |
| Hosts | Claude Code and GitHub Copilot as skills; Cursor and Antigravity as skills plus an MCP server |
| Safety | `SafeWriter` containment in code, optional dual-payload guard hook |

### V1 exit criteria

- [x] `scan_repository.py` runs on this repository and on a synthetic
      multi-service fixture with zero dependencies beyond the Python standard
      library.
- [x] Generated `.drawio` files are well-formed mxGraph, with every edge
      endpoint resolving to a declared cell.
- [x] Master and micro topologies are distinguishable, and each micro topology
      is a strict subset of the master centred on one service.
- [x] Every edge in `graph-model.json` carries a `file:line` that
      `validate_graph_model.py --repo` can re-read in the analysed repository.
- [x] Re-running the pipeline on unchanged code produces byte-identical
      `graph-model.json` and `.drawio` output.
- [x] The four MCP tools are callable end to end by a real MCP client over
      stdio.
- [x] The Claude Code skill and the GitHub Copilot skill produce identical
      output on the same fixture - both call the same scripts.
- [x] No file is written outside `service-topology/` at any point.
- [x] `tools/sync_hosts.py` reports the four host trees in sync, and CI enforces
      it.

---

## V2 - Schema awareness and staleness

The two things that most limit V1's usefulness on a real system.

| Item | Why it matters |
|---|---|
| Avro, Protobuf, and JSON Schema registry lookup | The message *shape* is the part of a topic contract that breaks consumers; right now an edge can say the key but not the payload |
| Stale-diagram detection | `refresh` re-renders, but does not yet say *what moved*. A diff of two graph models, reported as added, removed, and changed edges |
| Consumer-group topology | Several services in one group is a very different picture from several groups on one topic, and V1 draws them the same |
| Dead-letter and retry topics | Recognising `*.dlq`, `*.retry`, `*-dlt` as a class, drawn as a subordinate lane rather than a peer topic |
| Per-environment overlays | A topic name that differs between staging and production is currently one unresolved node |

---

## V3 - Language and ecosystem depth

| Item | Notes |
|---|---|
| .NET | Confluent.Kafka, MassTransit, `HttpClient`, gRPC - the largest uncovered ecosystem |
| Ruby, PHP, Rust | `ruby-kafka`, `rdkafka`, `rdkafka-rs`; Faraday, Guzzle, reqwest |
| Framework abstractions | Spring Integration, Micronaut, Quarkus/SmallRye Reactive Messaging, Akka Streams |
| Service mesh and gateway config | Istio `VirtualService`, Envoy routes, Kong, an API gateway's declared upstreams - all of which name edges the code does not |
| Kubernetes as a boundary source | Deployments and Services as the service list, for repositories where code layout does not match deployment |
| Call-graph depth | Following a base URL constant across module boundaries, safely - V1 deliberately stays file-local because doing this by name alone produces confident nonsense |

---

## V4 - Beyond Kafka

| Item | Notes |
|---|---|
| RabbitMQ | Exchanges, queues, and bindings - a genuinely different topology shape, not a rename of Kafka's |
| AWS SNS/SQS and EventBridge | Frequently defined entirely in Terraform, where V1 already reads topic declarations |
| Google Pub/Sub, Azure Service Bus | Same pattern |
| NATS, Pulsar, Redis Streams | Lower priority; smaller installed base in the systems this targets |
| Scheduled and batch edges | A cron job that reads one datastore and writes another is a real dependency the current model cannot express |

---

## Success metrics

What "working" means, measured on a real repository rather than the fixture:

| Metric | Target |
|---|---|
| Edges found that a service owner recognises | The overwhelming majority |
| Edges drawn that turn out not to exist | Approximately none - this is the metric that matters most, and the reason unresolved calls are dropped |
| Share of edges tagged `[CODE]` rather than `[INFERENCE]` | High, and honestly reported when it is not |
| Time from "point at repository" to "diagram open in editor" | Minutes |
| Re-run after a code change | Byte-identical where nothing changed |

A missing edge is a gap a reader can detect. A fabricated edge is not. The
targets are asymmetric on purpose.

---

## Quality review questions

Before any change to extraction ships, ask:

1. Can this produce an edge with no citation? If yes, it does not ship.
2. Can it produce a `[CODE]` edge from something not directly read?
3. Does it introduce a source of run-to-run variation - a timestamp, an
   unsorted set, a dictionary ordered by filesystem walk?
4. Does it make a false positive more likely than the false negative it removes?
5. Does the playbook in `references/` still describe what the code does?
6. Does `tools/sync_hosts.py` still report the host trees in sync?

---

## Operating model

- **The graph model is the interface.** Any new extractor emits nodes and edges
  in the existing shape. No renderer changes to accommodate an extractor.
- **A new ecosystem is a new function plus a playbook section**, not a new
  module tree, until there is enough of it to justify one.
- **Determinism is a released guarantee.** A change that breaks byte-identical
  re-runs is a breaking change, regardless of how much better the diagram looks.
- **Coverage gaps are documented, not hidden.** An ecosystem the extractors do
  not cover belongs in the playbook's "when a binding is genuinely missing"
  section and in the run's final summary.

---

## Pilot selection

The best first real target has: three to ten services in one repository, at
least one Kafka topic with more than one consumer, per-service manifests,
service names that match their hostnames, and someone available who can look at
the result and say which arrows are wrong.

The worst first target is a forty-service monorepo nobody fully understands -
which is, unhelpfully, exactly where the tool would be most valuable. Get the
error rate calibrated on something knowable first.
