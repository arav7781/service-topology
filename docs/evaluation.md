# Evaluation

v2 hands extraction to the agent, so the question that matters is whether an
agent following `SKILL.md` - with only search, read and write tools - finds
the real topology and nothing else. This is the record of the first test.

## Method

The skill was followed step by step, as an IDE agent would: route the
question, find services, run each sweep exactly as written in
`signatures.md`, resolve hits with the ladder, write the ledger, draw the view.
No Python was run. Every edge was then checked three ways:

1. `tools/check-ledger.sh` - every receipt's file exists and its line is inside it.
2. The primary receipt line of every edge was printed and read - it must hold
   the binding the edge claims.
3. Every Mermaid block was parsed with Mermaid 11.4.1, and the draw.io file
   was parsed as XML and checked for unique ids and resolvable edge endpoints.

**Caveat:** the agent that ran the test is the one that wrote v2, so this is
not a blind test. A cold run by a fresh agent with nothing but the skill
loaded is the next one worth doing, and contributions of that kind are welcome.

## Results

| Repository | Services | Ground truth | Edges found | False edges | Inferred | Gaps |
|---|---|---|---|---|---|---|
| [`fixture-mesh`](../examples/fixture-mesh/) | 3 + 1 referenced | 10 edges, v1's reference output | 10 / 10 | 0 | 1 | 1 |
| [`fixture-polyglot`](../examples/fixture-polyglot/) | 8 | 20 planted edges, 5 traps | 20 / 20 | 0 - no trap fired | 1 | 2 |
| [Online Boutique](../examples/third-party/online-boutique/) @ `38e7348` | 12 | 16 edges in the upstream [architecture diagram](https://github.com/GoogleCloudPlatform/microservices-demo/blob/38e7348eb289eb5b87c0c6e8cb19ced0449dc389/docs/img/architecture-diagram.png) | 16 / 16, plus 6 real code paths the diagram omits | 0 | 0 | 3 |

All 52 primary receipts land on the line holding their binding, and all 10
diagrams parse.

The 6 Online Boutique edges outside its diagram are real: the opt-in shopping
assistant (frontend → assistant, assistant → Gemini, assistant → AlloyDB) and
optional cart and catalog backends (AlloyDB, Spanner). The ones that config
switches on are labelled `optional:` in the ledger.

### What v2 resolved that v1 could not

On `fixture-mesh`, v1's output said `billing-svc`'s consumer group was "not
visible", because the code passes a variable. v2 follows it to an env default
and to `docker-compose.yml`, and records `group=billing` as `CODE` with all
three lines cited. v1 labelled the billing → orders call `GET /orders` because
the URL is concatenated. v2 records `GET /orders/{id}`, confirmed by the
service's OpenAPI spec.

On `fixture-polyglot`, four edges need a second file - a Java constants class,
a Python wrapper class, an `.env` value, a gRPC address in `application.yml` -
and all four resolve to `CODE` with the chain cited. v1's file-local resolver
stopped at the first file boundary.

## What the test changed in the skill

The first pass over Online Boutique exposed real gaps in `signatures.md`. Each
was fixed before the results above were recorded:

| Found | Fix |
|---|---|
| Go stubs built from a struct field (`pb.NewCartServiceClient(cs.cartSvcConn)`) slipped past `New\w+Client\(\s*\w*[cC]onn` | Pattern allows dotted receivers |
| Node's `server.addService(…)` registration wasn't recognised, so currency and payment had no server | Added `\.addService\(` and Node client credentials |
| 82 of 134 gRPC hits came from generated `*_pb2_grpc.py` / `*_grpc.pb.go`, and 36 from four copies of one `.proto` | Exclusions passed as one negated glob; contracts searched separately, copies counted once |
| `baseUrl` matched route prefixes, and `Spanner` matched every parameter type | Tightened both to client-construction forms |
| The messaging gate fired on `go.sum` and `package-lock.json`, which list transitive dependencies | Lock files excluded from gates |
| `cartservice → redis-cart` has no URL scheme anywhere (`REDIS_ADDR=redis-cart:6379`) | New **address sweep** over deploy config; Redis client patterns for .NET, Go and Java |
| The build name of `adservice` is `hipstershop`, and of `currencyservice` is `grpc-currency-service` | Service id is now the deployable name others use, ahead of build manifests |
| Python services had only a `Dockerfile` and `requirements.txt` | `requirements.txt` added to the manifest glob |
| Gemini is reached through an SDK, with no URL | Vendor SDK clients become `ext` nodes |
| AlloyDB and Spanner are switched on by env flags | Optional backends are edges labelled `optional: FLAG` |
| A RabbitMQ exchange and a service were both named `payments` | Ids are unique across kinds; a clashing channel takes a `<tech>:` prefix |

Two lessons apply beyond this repository. Deploy config is the cheapest source
of truth for who talks to whom: one search over Online Boutique's Kubernetes
manifests returned the whole service wiring. And generated code is the
largest source of noise, so exclusions have to be passed to the search tool,
not left for the agent to filter afterwards.

## Search cost on Online Boutique

Hit lines returned by each sweep, before and after the fixes above:

| Sweep | Before | After |
|---|---|---|
| gRPC (code) | 134 | 49 |
| HTTP | 33 | 9 |
| Datastores | 35 | 10 |
| Address sweep (with 1 line of context) | - | 46 |

That's about 115 lines of `file:line: text` for twelve services, before
`.proto` contracts and windows. Exact token counts depend on the host's path
format and output framing, so they aren't claimed here.

## Reproducing

```bash
bash tools/check-ledger.sh examples/fixture-mesh examples/fixture-mesh/service-topology/topology.ledger
bash tools/check-ledger.sh examples/fixture-polyglot examples/fixture-polyglot/service-topology/topology.ledger

git clone https://github.com/GoogleCloudPlatform/microservices-demo /tmp/boutique
git -C /tmp/boutique checkout 38e7348eb289eb5b87c0c6e8cb19ced0449dc389
bash tools/check-ledger.sh /tmp/boutique examples/third-party/online-boutique/topology.ledger
```

To rerun the extraction itself, open a fixture in your agent, install the
skill, and ask the question in a view's title. The edges and receipts should
match; the prose will differ.
