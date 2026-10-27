# Draw the architecture of this repository
`overview` · ledger none · 18 nodes · 20 edges (19 CODE, 1 inferred)

Eight services over four transports. `gateway` fronts `orders-api` and
`catalog` over HTTP. `orders-api` charges through `payments` (Feign), reserves
stock in `catalog` (gRPC) and publishes `orders.placed` and `orders.audit` to
Kafka. `payments` calls Adyen and announces captures on a RabbitMQ exchange.
`fulfillment` reacts to both events and hands shipments to `shipping` through
SQS, and `shipping` tells `notifier` over NATS. `analytics` appears to consume
a Kafka topic whose name is only set at deploy time (unconfirmed).

```mermaid
flowchart LR
  s_gateway["gateway"]
  s_orders_api["orders-api"]
  s_payments["payments"]
  s_catalog["catalog"]
  s_fulfillment["fulfillment"]
  s_shipping["shipping"]
  s_notifier["notifier"]
  s_analytics["analytics"]
  t_orders_placed{{"orders.placed"}}
  t_orders_audit{{"orders.audit"}}
  t_rabbitmq_payments{{"payments (exchange)"}}
  t_shipments[/"shipments"/]
  t_user_notify{{"user.notify"}}
  t_ANALYTICS_TOPIC_{{"ANALYTICS_TOPIC ?"}}
  d_orders_db[("orders-db")]
  d_catalog_cache[("catalog-cache")]
  x_api_adyen_com(["api.adyen.com"])
  x_api_easypost_com(["api.easypost.com"])

  s_gateway -->|"POST /orders"| s_orders_api
  s_gateway -->|"GET /products/{id}"| s_catalog
  s_orders_api -->|"POST /charges"| s_payments
  s_payments -->|"GET /orders/{id}"| s_orders_api
  s_orders_api -->|"Reserve"| s_catalog
  s_orders_api -->|"key=order.id"| t_orders_placed
  s_orders_api -->|"key=order.id"| t_orders_audit
  s_orders_api -->|"sql"| d_orders_db
  s_payments -->|"rk=payment.captured"| t_rabbitmq_payments
  s_payments -->|"POST /v71/payments"| x_api_adyen_com
  t_orders_placed -->|"group=fulfillment"| s_fulfillment
  t_rabbitmq_payments -->|"queue=fulfillment.payments"| s_fulfillment
  s_fulfillment -->|"sql"| d_orders_db
  s_fulfillment --> t_shipments
  t_shipments --> s_shipping
  s_shipping -->|"POST /v2/shipments"| x_api_easypost_com
  s_shipping --> t_user_notify
  t_user_notify --> s_notifier
  t_ANALYTICS_TOPIC_ -.->|"group=analytics"| s_analytics
  s_catalog -->|"redis"| d_catalog_cache

  class s_gateway,s_orders_api,s_payments,s_catalog,s_fulfillment,s_shipping,s_notifier,s_analytics svc
  class t_orders_placed,t_orders_audit,t_rabbitmq_payments,t_shipments,t_user_notify topic
  class t_ANALYTICS_TOPIC_ ref
  class d_orders_db db
  class d_catalog_cache cache
  class x_api_adyen_com,x_api_easypost_com ext
  classDef svc fill:#dbeafe,stroke:#2563eb,color:#0b2545
  classDef topic fill:#ffedd5,stroke:#ea580c,color:#431407
  classDef ref fill:#f8fafc,stroke:#94a3b8,color:#475569,stroke-dasharray:4 3
  classDef db fill:#dcfce7,stroke:#16a34a,color:#052e16
  classDef cache fill:#f3e8ff,stroke:#9333ea,color:#3b0764
  classDef ext fill:#f1f5f9,stroke:#64748b,color:#0f172a
```

| Edge | Tag | Receipts |
|---|---|---|
| gateway → orders-api · POST /orders | CODE | `services/gateway/src/routes.ts:11,5` · `docker-compose.yml:5` |
| gateway → catalog · GET /products/{id} | CODE | `services/gateway/src/routes.ts:16,6` · `docker-compose.yml:6` |
| orders-api → payments · POST /charges | CODE | `…/orders/PaymentsClient.java:6,8` · `docker-compose.yml:10` |
| payments → orders-api · GET /orders/{id} | CODE | `services/payments/main.go:18,9` · `docker-compose.yml:13` |
| orders-api → catalog · Reserve | CODE | `…/orders/InventoryClient.java:13,17,11` · `…/resources/application.yml:7` · `services/catalog/catalog/grpc_server.py:15` |
| orders-api → orders.placed · key=order.id | CODE | `…/orders/OrderEvents.java:15,8` · `…/orders/Topics.java:4` |
| orders-api → orders.audit · key=order.id | CODE | `…/orders/OrderEvents.java:16,8` · `…/orders/Topics.java:5` |
| orders-api → orders-db · sql | CODE | `…/resources/application.yml:5` · `docker-compose.yml:9` |
| payments → payments (exchange) · rk=payment.captured | CODE | `services/payments/events.go:15` |
| payments → api.adyen.com · POST /v71/payments | CODE | `services/payments/events.go:14` |
| orders.placed → fulfillment · group=fulfillment | CODE | `…/fulfillment/main.py:9,6,8` · `…/fulfillment/bus.py:11,8` · `services/fulfillment/.env:2` |
| payments (exchange) → fulfillment · queue=fulfillment.payments | CODE | `…/fulfillment/rabbit.py:13,6` |
| fulfillment → orders-db · sql | CODE | `…/fulfillment/db.py:4` · `docker-compose.yml:18` |
| fulfillment → shipments | CODE | `…/fulfillment/shipments.py:9` · `services/fulfillment/.env:1` |
| shipments → shipping | CODE | `services/shipping/src/poller.ts:7` · `docker-compose.yml:22` |
| shipping → api.easypost.com · POST /v2/shipments | CODE | `services/shipping/src/carrier.ts:4` |
| shipping → user.notify | CODE | `services/shipping/src/notify.ts:7` |
| user.notify → notifier | CODE | `services/notifier/main.go:11` |
| ANALYTICS_TOPIC ? ⇢ analytics · group=analytics | INFERENCE | `services/analytics/analytics/consume.py:5` · `docker-compose.yml:31` - no value in the repository |
| catalog → catalog-cache · redis | CODE | `services/catalog/catalog/app.py:7` · `docker-compose.yml:35` |

**Not shown:** `notifier`'s per-tenant alerts - the subject is built at runtime
(`services/notifier/main.go:19`). Not drawn, by rule: the Express
`res.send`, the RxJS `.subscribe`, the `localhost` health check, the test
consumer in `services/fulfillment/tests/`, and the generated
`inventory_pb2_grpc.py`.
