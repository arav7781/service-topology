# Draw the architecture of this repository
`overview` · ledger none · 9 nodes · 10 edges (9 CODE, 1 inferred)

Three services share one Kafka topic. `orders-svc` writes orders to PostgreSQL,
charges cards through Stripe and publishes `orders.created`. `billing-svc` and
`notifications-svc` both consume it, and both call back into `orders-svc` for
fields the event does not carry. `billing-svc` appears to call an
`InventoryService` over gRPC (unconfirmed: no `.proto` in the repository).

```mermaid
flowchart LR
  s_orders_svc["orders-svc"]
  s_billing_svc["billing-svc"]
  s_notifications_svc["notifications-svc"]
  s_InventoryService["InventoryService ?"]
  t_orders_created{{"orders.created"}}
  t_notifications_sent{{"notifications.sent"}}
  d_orders_db[("orders-db")]
  d_billing_cache[("billing-cache")]
  x_api_stripe_com(["api.stripe.com"])

  s_orders_svc -->|"key=orderID"| t_orders_created
  t_orders_created -->|"group=billing"| s_billing_svc
  t_orders_created -->|"group=notifications"| s_notifications_svc
  s_notifications_svc -->|"key=orderId"| t_notifications_sent
  s_billing_svc -->|"GET /orders/{id}"| s_orders_svc
  s_notifications_svc -->|"GET /orders/{id}"| s_orders_svc
  s_orders_svc -->|"POST /v1/charges"| x_api_stripe_com
  s_orders_svc -->|"sql"| d_orders_db
  s_billing_svc -->|"redis"| d_billing_cache
  s_billing_svc -.->|"Reserve"| s_InventoryService

  class s_orders_svc,s_billing_svc,s_notifications_svc svc
  class s_InventoryService ref
  class t_orders_created,t_notifications_sent topic
  class d_orders_db db
  class d_billing_cache cache
  class x_api_stripe_com ext
  classDef svc fill:#dbeafe,stroke:#2563eb,color:#0b2545
  classDef ref fill:#f8fafc,stroke:#94a3b8,color:#475569,stroke-dasharray:4 3
  classDef topic fill:#ffedd5,stroke:#ea580c,color:#431407
  classDef db fill:#dcfce7,stroke:#16a34a,color:#052e16
  classDef cache fill:#f3e8ff,stroke:#9333ea,color:#3b0764
  classDef ext fill:#f1f5f9,stroke:#64748b,color:#0f172a
```

| Edge | Tag | Receipts |
|---|---|---|
| orders-svc → orders.created · key=orderID | CODE | `services/orders/kafka/producer.go:21,22,14` |
| orders.created → billing-svc · group=billing | CODE | `services/billing/billing/consumers.py:13,14,7` · `docker-compose.yml:19` |
| orders.created → notifications-svc · group=notifications | CODE | `services/notifications/src/consumer.ts:13,8` |
| notifications-svc → notifications.sent · key=orderId | CODE | `services/notifications/src/consumer.ts:25,26` |
| billing-svc → orders-svc · GET /orders/{id} | CODE | `services/billing/billing/orders_client.py:12,7` · `docker-compose.yml:18` · `services/orders/api/openapi.yaml:8` |
| notifications-svc → orders-svc · GET /orders/{id} | CODE | `services/notifications/src/orders.ts:5,1` · `services/orders/api/openapi.yaml:8` |
| orders-svc → api.stripe.com · POST /v1/charges | CODE | `services/orders/payments.go:10` |
| orders-svc → orders-db · sql | CODE | `services/orders/main.go:18,11` · `docker-compose.yml:10,12` |
| billing-svc → billing-cache · redis | CODE | `services/billing/billing/cache.py:5` · `docker-compose.yml:20,22` |
| billing-svc ⇢ InventoryService · Reserve | INFERENCE | `services/billing/billing/inventory.py:14,15` - stub only; no `.proto` or server registration in the repository |

**Not shown:** compose `depends_on` lines, folded into the store edges as
receipts; `ORDERS_TOPIC` at `docker-compose.yml:9`, which is declared but never
read - the code names the topic literally.
