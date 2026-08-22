# Master topology - `<repository name>`

<!--
The written summary that accompanies master-topology.drawio. The diagram shows
the shape; this says what it means and what to distrust. Replace every
<placeholder>. Delete a section only when it is genuinely empty, and say so
rather than leaving a heading with nothing under it.
-->

**Scanned:** `<repo path>` <!-- plus the scope, when the scan was scoped -->
**Files read:** `<n>`
**Open in your editor:** `service-topology/master-topology.drawio`
**No drawio extension?** `service-topology/master-topology.mmd` renders anywhere
Markdown does.

| | |
|---|---|
| Services | `<n>` |
| Kafka topics | `<n>` |
| External systems | `<n>` |
| Edges | `<n>` (`<n>` `[CODE]`, `<n>` `[INFERENCE]`) |

---

## What this system does

<!-- Two or three sentences. What flows through it, and in which direction.
     Not a list of the services - the diagram already lists them. -->

---

## The services

| Service | Language | Produces | Consumes | Calls | Called by |
|---|---|---|---|---|---|
| `<id>` | `<lang>` | `<topics>` | `<topics>` | `<services>` | `<services>` |

<!-- Sorted by edge count, busiest first: that ordering answers "where is the
     centre of this system" without anyone having to ask. -->

---

## The topics

| Topic | Produced by | Consumed by | Message key |
|---|---|---|---|
| `<topic>` | `<services>` | `<services>` | `<key, or "not visible in code">` |

<!-- Call out anything asymmetric: a topic with no consumer, a topic with no
     producer in scope, a topic consumed by four services. Those are the rows a
     reviewer should look at. -->

---

## External systems

| System | Kind | Used by | Read at |
|---|---|---|---|
| `<id>` | datastore / cache / external API | `<services>` | `<file:line>` |

---

## Inferred, not confirmed

<!-- Every non-[CODE] edge, in prose, with what would confirm it. If there are
     none, say "Every edge in this diagram was read directly." and move on. -->

| Edge | Why it is not confirmed | What would confirm it |
|---|---|---|
| `<from>` -> `<to>` | `<reason>` | `<the specific thing to look for>` |

---

## What this diagram does not show

<!-- Be specific and complete. Common entries:
     - bindings resolved at runtime (per-tenant topic routing, service discovery)
     - ecosystems outside the extractor's coverage, named
     - anything skipped by --scope
     - generated code that was not read
     - services that exist only in other repositories
     A reader who knows what is missing can trust what is present. -->

---

## Suggested next step

<!-- Usually: the micro topology most worth generating, and why that one.
     Name the command. -->

```bash
python3 scripts/render_drawio.py service-topology/graph-model.laid-out.json \
    --mode micro --service <id> -o service-topology/micro/<id>.drawio
```
