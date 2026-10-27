# Lenses

How to cut the ledger into the view a question needs, and how to draw it.

## Dependency direction

Lenses that ask "who is affected" or "what is needed" follow **dependency**,
not data flow. `A depends on B` when:

- `A http|grpc|gql|ws|uses|dep B` - the caller depends on the callee or store;
- `A sub T` - the consumer depends on the channel;
- `A pub T` - the channel depends on its producer.

Topics and queues are conduits: they appear in the view but are never counted
as an affected party.

## Subgraph rules

| Lens | Nodes and edges | Form |
|---|---|---|
| `focus X` | X, every node one edge from X, the producers of each channel X consumes and the consumers of each channel X produces (their other edges hidden) | `flowchart LR`, X in class `focus` |
| `lineage T` | producers → T → consumers, then each consumer's `pub` edges onward until a sink, a repeat or 4 hops; include sync calls a consumer makes back to an upstream producer | `flowchart LR` |
| `path A B` | every simple path from A to B, ≤ 6 hops, following data flow (sync and async) | sync-only → `sequenceDiagram`; mixed → `flowchart LR` with labels prefixed `1.` `2.` along the path |
| `impact X` | everything that depends on X: ring 1 directly (a contract change breaks it), rings 2-3 transitively (availability and latency risk) | `flowchart LR`, classes `hit1`, `hit2` |
| `deps X` | everything X depends on, transitively, ≤ 3 hops | `flowchart TB` |
| `data` | services, `db`/`cache`/`store` nodes and `uses` edges; stores with ≥ 2 users in class `warn` | `flowchart LR` |
| `overview` | everything except `dep` edges; over 30 nodes → one `subgraph` per top-level directory or domain prefix, and `ext` nodes collapsed to one per subgraph (`3 external APIs`) | `flowchart LR` |
| `diff [ref]` | edges added, removed or relabelled since ref, plus their endpoints. Old ledger: `git show <ref>:service-topology/topology.ledger`; if it was never committed, sweep the files changed since ref at both versions | `flowchart LR`, added `==>` with endpoints in class `add`, removed `-.-x` |
| `review` | see `smells.md` | as-is with findings in class `warn`; to-be only if asked |

A path is reachability over cited edges, not a proven call chain. Say so when
a path has two or more sync hops: one handler calling the next has to be read
in the handler code, and that read is not in the ledger.

## Mermaid

**Ids** are a kind prefix plus the name with every non-alphanumeric character
replaced by `_`: `s_` service or ref, `t_` topic or queue, `d_` db, cache or
store, `x_` external. The prefix keeps a topic `orders` apart from a service
`orders`, and keeps reserved words like `end` out of ids. Labels are always quoted.

| Kind | Node |
|---|---|
| svc | `s_orders_svc["orders-svc"]` |
| ref | `s_inventory["InventoryService ?"]` |
| topic | `t_orders_created{{"orders.created"}}` |
| queue | `t_jobs[/"jobs"/]` |
| db, store | `d_orders_db[("orders-db")]` |
| cache | `d_cache[("billing-cache")]` |
| ext | `x_api_stripe_com(["api.stripe.com"])` |

**Edges** run in data-flow direction. `CODE` `a -->|"label"| b` ·
`INFERENCE`/`UNVERIFIED` `a -.->|"label"| b` · proposed `a ==>|"label"| b` ·
removed `a -.-x|"label"| b`. Drop `|…|` when the label is `-`. Keep labels
≤ 28 characters by eliding the middle (`POST /…/claims`); the full label is in
the receipts table.

**Classes.** Assign with one `class a,b,c name` line per class, and declare only
the classes the diagram uses:

```text
classDef svc fill:#dbeafe,stroke:#2563eb,color:#0b2545
classDef ref fill:#f8fafc,stroke:#94a3b8,color:#475569,stroke-dasharray:4 3
classDef topic fill:#ffedd5,stroke:#ea580c,color:#431407
classDef db fill:#dcfce7,stroke:#16a34a,color:#052e16
classDef cache fill:#f3e8ff,stroke:#9333ea,color:#3b0764
classDef ext fill:#f1f5f9,stroke:#64748b,color:#0f172a
classDef focus stroke-width:4px
classDef hit1 fill:#fee2e2,stroke:#dc2626,color:#450a0a
classDef hit2 fill:#fef3c7,stroke:#d97706,color:#451a03
classDef warn stroke:#dc2626,stroke-width:3px
classDef add stroke:#16a34a,stroke-width:3px
classDef prop fill:#dcfce7,stroke:#16a34a,color:#052e16,stroke-dasharray:6 3
```

`queue` nodes take `topic`; `store` nodes take `db`.

**Sequence form** (`path`, sync only): one `participant` per service in path
order; `A->>B: GET /orders/{id}` for `CODE`, `A-->>B: …` for inferred, `A-)T:
orders.created` for an async hop. Responses are not drawn.

## View file

````markdown
# <the question, as asked>
`<lens>` · ledger <commit> · <n> nodes · <e> edges (<c> CODE, <i> inferred)

<the answer in 1-5 sentences; every inferred edge hedged>

```mermaid
<diagram>
```

| Edge | Tag | Receipts |
|---|---|---|
| billing-svc → orders-svc · GET /orders/{id} | CODE | `services/billing/billing/orders_client.py:12` · `docker-compose.yml:18` |

**Not shown:** <gaps relevant to this view, scope limits, hidden edges>
````

The table lists only the edges drawn. A custom lens states its selection rule
on the second line, in place of the lens name.
