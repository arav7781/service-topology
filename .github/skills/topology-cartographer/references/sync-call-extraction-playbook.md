# Synchronous Call Extraction Playbook

REST and gRPC edges, and the external systems that hang off the leaves. Harder
than Kafka, because a Kafka binding names its topic and an HTTP call names a
URL that may be assembled from three places.

---

## The resolution ladder

Every HTTP call site produces a verb and a URL expression. The expression is
resolved in this order, and the first hit wins:

| Step | Situation | Result |
|---|---|---|
| 1 | Literal URL, host matches a service found in this repository | `[CODE]`, edge to that service |
| 2 | Literal URL, host is a real external domain (`api.stripe.com`) | `[CODE]`, edge to an external-API node |
| 3 | Symbol → config or environment value → host | `[CODE]`, note names the config file |
| 4 | Literal URL, bare hostname matching nothing | `[INFERENCE]`, edge to an external node, note says the host matched nothing |
| 5 | Path only, matching a path declared in an OpenAPI spec | `[INFERENCE]`, note names the spec and the matched path |
| 6 | Anything else | **Dropped** |

Step 6 is not a failure mode, it is the design. A call whose target cannot be
established is left out. The diagram then under-reports, which a reader can
detect, instead of mis-reporting, which they cannot.

`localhost`, `127.0.0.1`, `0.0.0.0`, `host.docker.internal` and `example.com`
are skipped outright - they are development and documentation URLs, not topology.

---

## Recognised HTTP clients

| Language | Patterns |
|---|---|
| Python | `requests.get/post/...`, `requests.request(method, url)`, `httpx.*`, `session.*`, `aiohttp` |
| JavaScript / TypeScript | `axios.get/post/...`, `axios({ method, url })`, `fetch(url, { method })`, `got.*`, `superagent.*`, `ky.*` |
| Java / Kotlin | `restTemplate.getForObject/postForEntity/exchange(...)`, `webClient.get().uri(...)`, `new Request.Builder().url(...)` |
| Go | `http.Get/Post/PostForm`, `http.NewRequest(method, url, body)`, `http.NewRequestWithContext(ctx, method, url, body)`, resty `.R().Get(...)` |

For `restTemplate.exchange(url, HttpMethod.GET, ...)` the verb comes from the
`HttpMethod.` argument, not from the method name.

---

## The file-local symbol table

Base URLs are almost never literal at the call site. Before scanning call sites,
the extractor builds a symbol table from the same file:

```python
ORDERS_BASE_URL = os.environ["ORDERS_SERVICE_URL"]     # -> ORDERS_SERVICE_URL
```
```javascript
const ORDERS_URL = 'http://orders-svc:8080';           # -> the literal
```
```java
@Value("${orders.url:http://orders-svc:8080}")
private String ordersUrl;                              # -> the default
```

A symbol resolving to another symbol is followed up to four times, then given
up on. **File-local on purpose**: chasing a constant across module boundaries by
name alone produces confident nonsense in any repository with more than one
`BASE_URL`.

An environment variable that reaches the config index resolves to `[CODE]` and
the note records which file the value was read from:

```text
base URL read from docker-compose.yml:12 via `ORDERS_SERVICE_URL`
```

---

## Template literals and concatenation

```javascript
fetch(`${ORDERS_URL}/orders/${orderId}`)
```

The head resolves through the symbol table; the tail is taken from the same
literal, after the closing brace. Remaining `${...}` placeholders become `{id}`,
so the edge is labelled `GET /orders/{id}` rather than losing the path entirely.

```python
requests.get(ORDERS_BASE_URL + "/orders/" + str(order_id))
```

Only the literal fragment survives - `GET /orders`. That is what the source
actually contains; the trailing segment is a runtime value and is not invented.

Concrete ids in a path are collapsed: `/orders/42` and `/orders/7` are both
`/orders/{id}`, so one endpoint is one edge rather than one per test fixture.

---

## Feign

```java
@FeignClient(name = "orders-svc")
interface OrdersClient {
    @GetMapping("/orders/{id}")
    Order get(@PathVariable String id);
}
```

Feign names its target outright, which makes it the strongest REST signal
available: `[CODE]` when the name matches a known service, `[INFERENCE]` when it
does not, with a note saying the name matched nothing. Every `@*Mapping` in the
interface body becomes its own labelled edge, capped at twelve so one large
client interface cannot dominate the diagram.

---

## OpenAPI specs

A spec is the **provider** side. It never creates an edge on its own; it does
three things:

1. Registers the paths a service serves, so a path-only client call can be
   matched against them (step 5 of the ladder - always `[INFERENCE]`, because
   matching a path shape is a guess).
2. Registers `servers[].url` hosts as aliases for that service, which upgrades
   later calls to that host to `[CODE]`.
3. Marks the service as having a declared API, recorded in the node's attributes.

---

## gRPC

Two phases, because a `.proto` says a contract exists without saying who serves
it.

**Phase 1** reads every `.proto` for `service X { rpc Y(...) ... }`, recording
the methods and provisionally attributing the service to whichever directory the
`.proto` lives in. It then looks for a server registration, which is the fact
that actually settles ownership:

| Language | Registration |
|---|---|
| Go | `pb.RegisterOrderServiceServer(s, ...)` |
| Python | `add_OrderServiceServicer_to_server(...)` |
| Java | `extends OrderServiceGrpc.OrderServiceImplBase` |

**Phase 2** finds stub construction and turns it into an edge:

| Language | Stub |
|---|---|
| Go | `pb.NewOrderServiceClient(conn)` |
| Python | `order_pb2_grpc.OrderServiceStub(channel)` |
| Java | `OrderServiceGrpc.newBlockingStub(channel)` |
| C# / Node | `new OrderService.OrderServiceClient(channel)` |

The tag depends on what phase 1 found:

- server registration found → `[CODE]`, edge to the registering service;
- `.proto` found but no registration → `[INFERENCE]`, note says the target was
  inferred from where the `.proto` lives;
- no `.proto` at all → `[INFERENCE]`, edge to a service node derived from the
  stub name and marked *referenced-only*, note says no `.proto` was in scope.

Method names come from the `.proto` and are matched against calls in the same
file (both `GetOrder` and `get_order` spellings), so the edge is labelled with
the RPCs actually used rather than every RPC the service offers. A file calling
into its own generated server code produces no edge.

---

## External systems as leaves

Connection strings become datastore, cache, or broker nodes:

```text
postgres:// postgresql:// mysql:// mariadb:// sqlserver:// oracle://
mongodb:// mongodb+srv:// cassandra:// clickhouse://
elasticsearch:// opensearch:// redis:// rediss:// valkey:// memcached://
amqp:// amqps://          and each of these behind jdbc:
```

Two rules keep these from multiplying:

- **A host that names a docker-compose container reuses that container's node.**
  Otherwise `postgres://orders-db/orders` in code and `image: postgres` in
  compose draw the same database twice.
- **A numeric path is an index, not a name.** `redis://cache:6379/0` is the
  `cache` node, not a node called `0`.

`depends_on` in docker-compose is read as a `[CODE]` dependency edge, attributed
to the compose service that declares it - never to whichever service happens to
own the file. A message broker in `depends_on` is skipped: the broker is already
drawn as its topics, and a box labelled "kafka" that every service points at
tells the reader nothing.
