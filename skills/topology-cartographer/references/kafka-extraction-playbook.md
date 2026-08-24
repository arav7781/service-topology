# Kafka Extraction Playbook

How a producer or consumer binding is recognised, per ecosystem, and where each
one usually hides. `scripts/scan_repository.py` implements all of this; read
this file when a binding you expected is missing, or when one you did not
expect turned up.

---

## The shape of the problem

A Kafka binding is three facts: **which service**, **which topic**, **which
direction**. Extraction is easy when all three are literal on one line and hard
the moment any of them moves:

| Where it moves to | Example | How it is resolved |
|---|---|---|
| The next line | `kafkaTemplate.send(\n  "orders.created", key, payload)` | A multi-line window around the anchor line |
| A constant | `producer.send(TOPIC, ...)` | The file-local symbol table |
| Config | `topics = "${app.topics.orders}"` | The config index - `application.yml`, `.env`, compose, Helm |
| Terraform | `resource "kafka_topic" "orders" { name = "orders.created" }` | Read as a declaration; the topic exists even with no code referencing it |
| Runtime | `producer.send(topicFor(tenant), ...)` | **Unresolvable.** Do not guess a topic name from a function name |

The last row is the important one. An unresolved binding becomes an
`[INFERENCE]` edge to a topic node labelled with the symbol and marked
unresolved, never a `[CODE]` edge to a name we invented.

---

## JVM - Spring Kafka, Kafka Streams, plain client

Gated on the file mentioning Kafka at all. Without that gate a bare
`.send(...)` in an unrelated class becomes a phantom topic.

| Pattern | Direction | Notes |
|---|---|---|
| `@KafkaListener(topics = "...")` | consumes | `topics = {...}` braced lists and `topicPattern` both handled; `groupId` becomes the edge label |
| `@StreamListener("input")` | consumes | Legacy Spring Cloud Stream |
| `kafkaTemplate.send(topic, key, value)` | produces | Three arguments means the middle one is the message key, and it becomes the label |
| `new ProducerRecord<>("topic", ...)` | produces | |
| `@SendTo("topic")` | produces | |
| `consumer.subscribe(List.of("a", "b"))` | consumes | Every literal in the call |
| `builder.stream("topic")` / `.to("topic")` | consumes / produces | Kafka Streams sources and sinks |

**Field-declared templates.** `private final KafkaTemplate<String, Order>
events;` followed by `events.send(...)` is recognised: the extractor looks back
for a `KafkaTemplate`/`KafkaProducer` declaration of that identifier before
treating a bare `.send(` as a producer.

**Spring Cloud Stream bindings** live in config, not code:

```yaml
spring.cloud.stream.bindings.orderEvents-out-0.destination: orders.created
```

Direction comes from the binding name - `-out-`, `output`, `producer`,
`supplier`, `source` mean produces; `-in-`, `input`, `consumer`, `sink`,
`listener` mean consumes. **A binding name matching neither is skipped**, not
guessed at.

---

## Python - kafka-python, confluent-kafka, aiokafka, faust

| Pattern | Direction | Notes |
|---|---|---|
| `KafkaConsumer("topic", group_id=...)` | consumes | Positional arguments only; keyword arguments are skipped |
| `AIOKafkaConsumer("topic")` | consumes | |
| `producer.send("topic", key=...)` | produces | `key=` becomes the label |
| `p.produce("topic", ...)` | produces | confluent-kafka; `produce` is unambiguous, so no identifier check is needed |
| `consumer.subscribe(["topic"])` | consumes | |
| `app.topic("t")` + `@app.agent(t)` | consumes | faust; the topic variable is followed from its assignment |

**The producer check.** A bare `x.send(...)` is only a producer when `x` looks
like one - the name contains `produc`/`kafka`, or the file assigns
`x = KafkaProducer(...)`. `requests.Session().send()` must not become a topic.

---

## Node - kafkajs, node-rdkafka, NestJS

kafkajs passes an options object, so the topic is a property rather than an
argument:

| Pattern | Direction |
|---|---|
| `producer.send({ topic: 'orders.created', messages: [...] })` | produces |
| `producer.sendBatch({ topicMessages: [{ topic: '...' }] })` | produces |
| `consumer.subscribe({ topic: 'orders.created' })` | consumes |
| `consumer.subscribe({ topics: ['a', 'b'] })` | consumes |
| `client.emit('orders.created', payload)` | produces (NestJS) |
| `@EventPattern('orders.created')` | consumes (NestJS) |

`groupId` from the `kafka.consumer({ groupId })` call anywhere in the file
becomes the consumer edge's label - kafkajs conventionally declares it once per
module.

**Wrapped clients.** Many teams put kafkajs behind their own service class, so
the call site imports `IPubSubService` and never mentions kafkajs at all:

```ts
const refundTopic = this.configService.get<string>(
    INFRA.KAFKA.TOPICS.REFUND_REQUEST_TOPIC,
);
await this.iPubSubService.subscribe({ topic: refundTopic, ... });
```

Two things make this resolvable, and both are needed - either alone yields
nothing:

1. **The gate accepts wrapper vocabulary**, not just vendor names: `pubsub`,
   `pub-sub`, `topic`, `producer`, `consumer`, case-insensitively. Gating on
   `kafkajs` alone silently skips every repository built this way.
2. **File-local constants are followed.** A `const`/`readonly` whose value is a
   literal, a `process.env.X`, or a `configService.get(...)` call is recorded,
   and the last dotted segment of the key (`INFRA.KAFKA.TOPICS.X` -> `X`) is
   what the config index is asked for. The declaration is matched across
   newlines, because a formatter routinely splits it over three lines.

The config index then resolves `REFUND_REQUEST_TOPIC` against `.env`,
`application.yml`, compose, Helm, or Terraform. A camelCase identifier is also
tried as `SNAKE_CASE`, so `refundCallbackProcessorTopic` finds
`REFUND_CALLBACK_PROCESSOR_TOPIC`. All three ends were read, so the edge is
`[CODE]`; only a key with no value anywhere in the repository degrades to
`[INFERENCE]`.

---

## Go - segmentio/kafka-go, sarama

Go puts the topic in a struct field, often several lines below the anchor, so
the extractor reads the whole composite literal:

| Pattern | Direction |
|---|---|
| `kafka.NewWriter(kafka.WriterConfig{Topic: "..."})` | produces |
| `kafka.Message{Topic: "...", Key: ...}` | produces |
| `kafka.NewReader(kafka.ReaderConfig{Topic: "...", GroupID: "..."})` | consumes |
| `sarama.ProducerMessage{Topic: "..."}` | produces |
| `group.Consume(ctx, []string{"..."}, handler)` | consumes |
| `consumer.ConsumePartition("...", ...)` | consumes |

**The brace must hug the type name.** `func New(...) *kafka.Writer {` is a
return type, not a composite literal; matching it invents a topic-less producer
on every constructor. The patterns require `kafka.Writer{` or
`kafka.WriterConfig{`, never `kafka.Writer {`.

`Key: []byte(orderID)` is unwrapped to `key=orderID` for the label - the
conversion is noise on a diagram.

---

## Resolving a topic name from config

Order of attempts, stopping at the first hit:

1. The literal at the call site → `[CODE]`.
2. `${KEY:-default}` with a default → the default, `[CODE]`.
3. The symbol looked up in the config index - exact key, then dotted-lowercase,
   then `SHOUTY_SNAKE`, then a suffix match on the dotted tail (Spring nests
   under arbitrary prefixes) → `[CODE]`, with the config file named in the note.
4. Nothing found → `[INFERENCE]`, topic node labelled `SYMBOL (unresolved)`.

The config index reads `application.yml`, `application.properties`,
`bootstrap.*`, `.env*`, `docker-compose.yml`, Helm `values.yaml`, and Terraform.
It does **not** read a running environment - `ORDERS_TOPIC` set only in a
deployment pipeline stays unresolved, and that is the correct answer.

---

## Rejecting noise

A candidate topic name is discarded when it is a number, a boolean, a
serialiser class name, a path, a URL, a sentence, or anything not matching
`[A-Za-z0-9][A-Za-z0-9._-]*`. Losing one real edge to over-strict filtering is
cheaper than putting `org.apache.kafka.common.serialization.StringSerializer` in
the middle of an architecture diagram.

---

## When a binding is genuinely missing

Report it rather than working around it:

- **Topic chosen at runtime** - per-tenant or per-partition routing. State the
  routing function's location and that the topic set is not statically knowable.
- **Binding in generated code** - the extractor skips `*_pb2.py`, `*.pb.go` and
  friends. Say so.
- **Binding in a framework abstraction** the playbook does not cover - name the
  library and the file. That is a gap in this playbook, and worth fixing here
  rather than hand-adding an edge to the model.
