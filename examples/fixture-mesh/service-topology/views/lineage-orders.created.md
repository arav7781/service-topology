# Where does orders.created go?
`lineage orders.created` · ledger none · 5 nodes · 6 edges (6 CODE)

`orders-svc` publishes `orders.created`, keyed by order id. Two groups read it:
`billing` and `notifications`. Each consumer then calls back to `orders-svc`
for the full order, so the event alone is not enough to act on.
`notifications-svc` emits `notifications.sent`, and the trail ends there - no
consumer of it exists in this repository.

```mermaid
flowchart LR
  s_orders_svc["orders-svc"]
  t_orders_created{{"orders.created"}}
  s_billing_svc["billing-svc"]
  s_notifications_svc["notifications-svc"]
  t_notifications_sent{{"notifications.sent"}}

  s_orders_svc -->|"key=orderID"| t_orders_created
  t_orders_created -->|"group=billing"| s_billing_svc
  t_orders_created -->|"group=notifications"| s_notifications_svc
  s_notifications_svc -->|"key=orderId"| t_notifications_sent
  s_billing_svc -->|"GET /orders/{id}"| s_orders_svc
  s_notifications_svc -->|"GET /orders/{id}"| s_orders_svc

  class s_orders_svc,s_billing_svc,s_notifications_svc svc
  class t_orders_created,t_notifications_sent topic
  classDef svc fill:#dbeafe,stroke:#2563eb,color:#0b2545
  classDef topic fill:#ffedd5,stroke:#ea580c,color:#431407
```

| Edge | Tag | Receipts |
|---|---|---|
| orders-svc → orders.created · key=orderID | CODE | `services/orders/kafka/producer.go:21,22,14` |
| orders.created → billing-svc · group=billing | CODE | `services/billing/billing/consumers.py:13,14,7` · `docker-compose.yml:19` |
| orders.created → notifications-svc · group=notifications | CODE | `services/notifications/src/consumer.ts:13,8` |
| notifications-svc → notifications.sent · key=orderId | CODE | `services/notifications/src/consumer.ts:25,26` |
| billing-svc → orders-svc · GET /orders/{id} | CODE | `services/billing/billing/orders_client.py:12,7` · `docker-compose.yml:18` |
| notifications-svc → orders-svc · GET /orders/{id} | CODE | `services/notifications/src/orders.ts:5,1` |

**Not shown:** the consumers' own stores and calls (`billing-cache`,
`InventoryService`), which are not part of the event's path.
