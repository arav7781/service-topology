# Micro topology - `<service id>`

<!--
Accompanies micro/<service>.drawio. The point of a micro topology is that
someone can review a service's integration surface without opening its code, so
this document must carry the detail the diagram cannot: message keys, endpoint
shapes, consumer groups, and what is uncertain.
-->

**Service root:** `<services/orders>`
**Language:** `<go>`
**Declared in:** `<services/orders/go.mod:1>`
**Open in your editor:** `service-topology/micro/<service>.drawio`

| | |
|---|---|
| Inbound edges | `<n>` |
| Outbound edges | `<n>` |
| Confirmed `[CODE]` | `<n>` |
| Inferred | `<n>` |

---

## Inbound

### Topics it consumes

| Topic | Consumer group | Also produced by | Read at |
|---|---|---|---|
| `<topic>` | `<group>` | `<services>` | `<file:line>` |

### Services that call it

| Caller | Protocol | Endpoint | Evidence | Read at |
|---|---|---|---|---|
| `<service>` | http / grpc | `<GET /orders/{id}>` | `[CODE]` | `<file:line>` |

---

## Outbound

### Topics it produces

| Topic | Message key | Also consumed by | Read at |
|---|---|---|---|
| `<topic>` | `<key=order_id>` | `<services>` | `<file:line>` |

### Services it calls

| Target | Protocol | Endpoint | Evidence | Read at |
|---|---|---|---|---|
| `<service>` | http / grpc | `<POST /invoices>` | `[CODE]` | `<file:line>` |

### External systems

| System | Kind | Protocol | Read at |
|---|---|---|---|
| `<id>` | datastore / cache / external API | `<sql>` | `<file:line>` |

---

## Blast radius

<!-- The question this diagram exists to answer. For each topic this service
     produces and each endpoint it exposes: who breaks if it changes shape?
     Name them. This is the section a reviewer actually reads. -->

| If this changes | These break | Confidence |
|---|---|---|
| `<topic or endpoint>` | `<services>` | `<[CODE] / [INFERENCE]>` |

---

## Inferred, not confirmed

<!-- The non-[CODE] edges touching this service. If none: "Every edge touching
     this service was read directly." -->

| Edge | Why | What would confirm it |
|---|---|---|

---

## What this diagram does not show

<!-- Two hops only, by design: the topics this service touches and who else is
     on the other end of them. It is not a transitive dependency graph - a
     change three hops away will not appear here. Name anything else specific to
     this service: runtime-resolved targets, unread generated code, bindings in
     an ecosystem the extractors do not cover. -->
