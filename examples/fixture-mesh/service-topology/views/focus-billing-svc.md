# What does billing-svc talk to?
`focus billing-svc` · ledger none · 5 nodes · 5 edges (4 CODE, 1 inferred)

`billing-svc` consumes `orders.created` (group `billing`) and, for each order,
calls `orders-svc` `GET /orders/{id}` for the fields the event leaves out. It
keeps a Redis cache, `billing-cache`. It also appears to call an
`InventoryService` over gRPC (`Reserve`) - unconfirmed, because neither the
`.proto` nor a server registration is in this repository.

```mermaid
flowchart LR
  s_orders_svc["orders-svc"]
  t_orders_created{{"orders.created"}}
  s_billing_svc["billing-svc"]
  d_billing_cache[("billing-cache")]
  s_InventoryService["InventoryService ?"]

  s_orders_svc -->|"key=orderID"| t_orders_created
  t_orders_created -->|"group=billing"| s_billing_svc
  s_billing_svc -->|"GET /orders/{id}"| s_orders_svc
  s_billing_svc -->|"redis"| d_billing_cache
  s_billing_svc -.->|"Reserve"| s_InventoryService

  class s_orders_svc,s_billing_svc svc
  class s_billing_svc focus
  class s_InventoryService ref
  class t_orders_created topic
  class d_billing_cache cache
  classDef svc fill:#dbeafe,stroke:#2563eb,color:#0b2545
  classDef focus stroke-width:4px
  classDef ref fill:#f8fafc,stroke:#94a3b8,color:#475569,stroke-dasharray:4 3
  classDef topic fill:#ffedd5,stroke:#ea580c,color:#431407
  classDef cache fill:#f3e8ff,stroke:#9333ea,color:#3b0764
```

| Edge | Tag | Receipts |
|---|---|---|
| orders-svc → orders.created · key=orderID | CODE | `services/orders/kafka/producer.go:21,22,14` |
| orders.created → billing-svc · group=billing | CODE | `services/billing/billing/consumers.py:13,14,7` · `docker-compose.yml:19` |
| billing-svc → orders-svc · GET /orders/{id} | CODE | `services/billing/billing/orders_client.py:12,7` · `docker-compose.yml:18` · `services/orders/api/openapi.yaml:8` |
| billing-svc → billing-cache · redis | CODE | `services/billing/billing/cache.py:5` · `docker-compose.yml:20,22` |
| billing-svc ⇢ InventoryService · Reserve | INFERENCE | `services/billing/billing/inventory.py:14,15` - stub only |

**Not shown:** the other consumer of `orders.created` (`notifications-svc`),
which is a sibling, not a neighbour. The owner of `InventoryService` is
unknown - its `.proto` is generated at deploy time from another repository
(`services/billing/billing/inventory.py:3`).
