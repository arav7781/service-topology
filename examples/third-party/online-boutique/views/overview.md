# Draw the architecture of Online Boutique
`overview` · ledger 38e7348 · 16 nodes · 22 edges (22 CODE)

A gRPC mesh behind one HTTP frontend. `frontend` calls seven services and
places orders through `checkoutservice`, which fans out to six more.
`recommendationservice` reads the product catalog, and `cartservice` keeps
carts in Redis. The opt-in shopping assistant adds an HTTP hop to a Python
service that talks to Gemini and AlloyDB. Three edges are optional backends
that config switches on (`optional:` labels), not the default deployment.

```mermaid
flowchart LR
  s_loadgenerator["loadgenerator"]
  s_frontend["frontend"]
  s_checkoutservice["checkoutservice"]
  s_cartservice["cartservice"]
  s_productcatalogservice["productcatalogservice"]
  s_currencyservice["currencyservice"]
  s_shippingservice["shippingservice"]
  s_paymentservice["paymentservice"]
  s_emailservice["emailservice"]
  s_recommendationservice["recommendationservice"]
  s_adservice["adservice"]
  s_shoppingassistantservice["shoppingassistantservice"]
  d_redis_cart[("redis-cart")]
  d_alloydb[("alloydb")]
  d_spanner[("spanner")]
  x_gemini(["gemini"])

  s_loadgenerator -->|"locust"| s_frontend
  s_frontend -->|"GetAds"| s_adservice
  s_frontend -->|"GetCart, EmptyCart, AddItem"| s_cartservice
  s_frontend -->|"PlaceOrder"| s_checkoutservice
  s_frontend -->|"GetSupportedCurr…, Convert"| s_currencyservice
  s_frontend -->|"ListProducts, GetProduct"| s_productcatalogservice
  s_frontend -->|"ListRecommendations"| s_recommendationservice
  s_frontend -->|"GetQuote"| s_shippingservice
  s_frontend -->|"POST /"| s_shoppingassistantservice
  s_checkoutservice -->|"GetCart, EmptyCart"| s_cartservice
  s_checkoutservice -->|"Convert"| s_currencyservice
  s_checkoutservice -->|"SendOrderConfirmation"| s_emailservice
  s_checkoutservice -->|"Charge"| s_paymentservice
  s_checkoutservice -->|"ProductCatalogService"| s_productcatalogservice
  s_checkoutservice -->|"GetQuote, ShipOrder"| s_shippingservice
  s_recommendationservice -->|"ListProducts"| s_productcatalogservice
  s_cartservice -->|"redis"| d_redis_cart
  s_cartservice -->|"optional"| d_alloydb
  s_cartservice -->|"optional"| d_spanner
  s_productcatalogservice -->|"optional"| d_alloydb
  s_shoppingassistantservice -->|"vector store"| d_alloydb
  s_shoppingassistantservice -->|"gemini-1.5-flash"| x_gemini

  class s_loadgenerator,s_frontend,s_checkoutservice,s_cartservice,s_productcatalogservice,s_currencyservice,s_shippingservice,s_paymentservice,s_emailservice,s_recommendationservice,s_adservice,s_shoppingassistantservice svc
  class d_redis_cart cache
  class d_alloydb,d_spanner db
  class x_gemini ext
  classDef svc fill:#dbeafe,stroke:#2563eb,color:#0b2545
  classDef cache fill:#f3e8ff,stroke:#9333ea,color:#3b0764
  classDef db fill:#dcfce7,stroke:#16a34a,color:#052e16
  classDef ext fill:#f1f5f9,stroke:#64748b,color:#0f172a
```

Receipts for every edge are in [`../topology.ledger`](../topology.ledger).
Each one resolves at
[`38e7348`](https://github.com/GoogleCloudPlatform/microservices-demo/tree/38e7348eb289eb5b87c0c6e8cb19ced0449dc389).
A few to spot-check:

| Edge | Primary receipt |
|---|---|
| frontend → checkoutservice · PlaceOrder | [`src/frontend/handlers.go:354`](https://github.com/GoogleCloudPlatform/microservices-demo/blob/38e7348eb289eb5b87c0c6e8cb19ced0449dc389/src/frontend/handlers.go#L354) |
| checkoutservice → paymentservice · Charge | [`src/checkoutservice/main.go:370`](https://github.com/GoogleCloudPlatform/microservices-demo/blob/38e7348eb289eb5b87c0c6e8cb19ced0449dc389/src/checkoutservice/main.go#L370) |
| cartservice → redis-cart | [`src/cartservice/src/Startup.cs:36`](https://github.com/GoogleCloudPlatform/microservices-demo/blob/38e7348eb289eb5b87c0c6e8cb19ced0449dc389/src/cartservice/src/Startup.cs#L36) · [`kubernetes-manifests/cartservice.yaml:51`](https://github.com/GoogleCloudPlatform/microservices-demo/blob/38e7348eb289eb5b87c0c6e8cb19ced0449dc389/kubernetes-manifests/cartservice.yaml#L51) |
| recommendationservice → productcatalogservice · ListProducts | [`src/recommendationservice/recommendation_server.py:73`](https://github.com/GoogleCloudPlatform/microservices-demo/blob/38e7348eb289eb5b87c0c6e8cb19ced0449dc389/src/recommendationservice/recommendation_server.py#L73) |

**Not shown:** the packaging-info call (`PACKAGING_SERVICE_URL` has no value in
any manifest), OpenTelemetry export (optional, no default collector), and
whether the three AlloyDB users share one cluster - that is decided at deploy
time.
