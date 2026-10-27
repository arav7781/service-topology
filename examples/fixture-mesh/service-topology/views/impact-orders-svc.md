# What breaks if I change orders-svc's API or its events?
`impact orders-svc` · ledger none · 4 nodes · 5 edges (5 CODE)

Two services break on a contract change, and they break twice over:
`billing-svc` and `notifications-svc` each consume `orders.created` **and**
call `GET /orders/{id}`. A change to the event schema or to that endpoint hits
both. Nothing depends on either of them in turn, so the blast radius stops at
ring 1. `orders-db` and `api.stripe.com` are things orders-svc depends on, not
dependents, so they are outside the blast radius.

```mermaid
flowchart LR
  s_orders_svc["orders-svc"]
  t_orders_created{{"orders.created"}}
  s_billing_svc["billing-svc"]
  s_notifications_svc["notifications-svc"]

  s_orders_svc -->|"key=orderID"| t_orders_created
  t_orders_created -->|"group=billing"| s_billing_svc
  t_orders_created -->|"group=notifications"| s_notifications_svc
  s_billing_svc -->|"GET /orders/{id}"| s_orders_svc
  s_notifications_svc -->|"GET /orders/{id}"| s_orders_svc

  class s_orders_svc svc
  class s_orders_svc focus
  class s_billing_svc,s_notifications_svc hit1
  class t_orders_created topic
  classDef svc fill:#dbeafe,stroke:#2563eb,color:#0b2545
  classDef focus stroke-width:4px
  classDef hit1 fill:#fee2e2,stroke:#dc2626,color:#450a0a
  classDef topic fill:#ffedd5,stroke:#ea580c,color:#431407
```

| Ring | Service | Breaks because | Receipts |
|---|---|---|---|
| 1 | billing-svc | consumes `orders.created` · calls `GET /orders/{id}` | `services/billing/billing/consumers.py:13` · `services/billing/billing/orders_client.py:12` |
| 1 | notifications-svc | consumes `orders.created` · calls `GET /orders/{id}` | `services/notifications/src/consumer.ts:13` · `services/notifications/src/orders.ts:5` |

**Not shown:** consumers outside this repository. `orders.created` may have
readers elsewhere that no static scan can see.
