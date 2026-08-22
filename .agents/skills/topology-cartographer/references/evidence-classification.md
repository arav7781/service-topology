# Evidence Classification

Every edge in every generated diagram carries an evidence tag. The tag states
*how you know*, so a human reviewer can audit the arrow without re-deriving it -
and so the diagram can show, visually, which parts of itself to trust.

Contributor Scout's tag set, minus the four tags that do not apply to topology
extraction. There is no `[TEST]` here because nothing is executed, no
`[HISTORY]` because a topology is a statement about the present, and no
`[MAINTAINER]` or `[DOCS]` because an architecture document describing an
integration is not evidence the integration exists.

---

## Tags

| Tag | Meaning | Minimum requirement to use it |
|---|---|---|
| `[CODE]` | Directly verified. | You read the binding in this run and cite `path:line`. A config key you followed to a concrete value in a config file you also read counts: both ends were read. |
| `[INFERENCE]` | The pattern matched but the target did not resolve. | The edge records *why* it did not resolve, in words a reviewer can act on. |
| `[UNVERIFIED]` | Asserted but not confirmed by reading a file. | The edge says what would verify it. Never produced silently. |

---

## Rules

1. **One tag per edge, at the strongest level you can actually support.**
   Not the strongest level that would make the diagram look complete.
2. **Never upgrade.** If a hostname *looks* like a service you found, but the
   only thing connecting them is that the strings are similar, that is
   `[INFERENCE]`, not `[CODE]`.
3. **Line numbers are facts.** Cite only lines you read in this run.
   `validate_graph_model.py --repo` re-reads every one of them; a citation past
   the end of a file is a hard failure, not a warning.
4. **Two files can make one `[CODE]`.** `@KafkaListener(topics =
   "${app.topics.orders}")` plus `app.topics.orders: orders.created` in
   `application.yml` is a directly evidenced binding. The edge cites the call
   site and its note names the config file the value came from.
5. **An unresolved target is not an edge.** If a call's destination cannot be
   resolved to a service, an external host, or a declared API, the edge is
   **dropped**. A wrong arrow reads as a fact; a missing arrow reads as a gap.
   Gaps are honest, wrong arrows are not.
6. **Absence is a finding.** "A topic with producers and no consumers" and "a
   service with a Kafka client on its classpath and no topic edges" are both
   worth reporting. `validate_graph_model.py` surfaces them as warnings.

---

## What the reader sees

The tag is not just metadata - it changes the picture:

| Tag | In the `.drawio` | In the `.mmd` | In `evidence/sources.md` |
|---|---|---|---|
| `[CODE]` | Solid coloured arrow | `-->` | "Confirmed edges" table |
| `[INFERENCE]` | Dashed grey arrow | `-.->` | "Inferred, not confirmed", with the reason |
| `[UNVERIFIED]` | Dashed grey arrow | `-.->` | "Inferred, not confirmed", with what would verify it |

A node can be qualified too. A service nothing in the repository declares -
known only because something calls it - is drawn hollow with a dashed border,
and a topic whose name is an unresolved config reference is drawn the same way.

---

## Consequences for what a diagram may claim

Evidence quality gates what the accompanying summary is allowed to say:

| Edge evidence | Strongest permitted claim |
|---|---|
| `[CODE]` at both ends of a producer/consumer pair | "`orders-svc` publishes to `orders.created`; `billing-svc` consumes it." |
| `[CODE]` producer, no consumer found | "`orders-svc` publishes to `orders.created`. No consumer was found in the scanned scope." |
| `[INFERENCE]` | "`billing-svc` appears to call `orders-svc` over gRPC - stub usage at `billing/client.py:9`, but no `.proto` declaring the service was found. Unconfirmed." |
| `[UNVERIFIED]` | "Reported, not confirmed by this run." |

Never write "`billing-svc` calls `orders-svc`" for an `[INFERENCE]` edge. The
hedge is the content.

---

## Worked examples

Weak, and why:

```text
billing-svc consumes orders.created.
```

No tag, no location. Which file? Which consumer group? Is the topic name a
literal, or a config key that might be different per environment?

Strong:

```json
{
  "from": "orders.created",
  "to": "billing-svc",
  "type": "consumes",
  "protocol": "kafka",
  "detail": "group=billing",
  "evidence_tag": "CODE",
  "source": "services/billing/billing/consumers.py:12",
  "extractor": "kafka-python"
}
```

Strong, and honest about its limits:

```json
{
  "from": "billing-svc",
  "to": "inventory",
  "type": "calls",
  "protocol": "grpc",
  "method": "InventoryService",
  "evidence_tag": "INFERENCE",
  "source": "services/billing/billing/inventory.py:14",
  "note": "gRPC stub `InventoryServiceStub` is used here, but no .proto declaring it was found in scope",
  "extractor": "grpc"
}
```

A reviewer can act on the second one: find the `.proto`, or confirm which
service answers, and the edge becomes `[CODE]` on the next run.

---

## Where evidence lives

| Artefact | Contents |
|---|---|
| `graph-model.json` | Every node and edge, each with `source_evidence` or `source`, and `also_at` for repeat sightings of the same binding. |
| `evidence/sources.md` | The same, rendered for humans: confirmed edges, inferred edges with reasons, node origins, and scan warnings. |
| The `.drawio` file itself | Each node and edge is a `UserObject` carrying `sourceLocation`, `evidenceTag`, and any `inferenceNote`. Select an arrow in draw.io and `Edit > Edit Data` shows where it came from. |

An arrow that is not traceable to one of these is not finished.
