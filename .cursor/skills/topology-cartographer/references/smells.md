# Topology review

Only for `review`. Every finding is computed from the ledger and lists the `E`
lines that prove it. A finding resting on `INFERENCE` edges says so. Channel
findings (T4) need `scopes=all`, because a consumer outside the scanned scope
is not an absence.

| Id | Smell | Detect in the ledger | Sev | Why it matters | Typical fix |
|---|---|---|---|---|---|
| T1 | Sync cycle | a cycle using only `http`/`grpc`/`gql` edges | high | the services deploy and fail together - a distributed monolith | turn one direction into an event, or merge |
| T2 | Event then callback | `X sub T`, `P pub T`, and `X http\|grpc P` | med | the event is not self-sufficient; P sits on every consumer's critical path | carry the needed fields in the event, or keep a consumer-side projection |
| T3 | Shared store | one `db` node with `uses` from ≥ 2 services | high | schema coupling with no single owner | one owner; others read through its API or its events |
| T4 | Orphan channel | a channel with `pub` and no `sub`, or `sub` and no `pub` | low | dead traffic, or a party outside the repository | find the owner, then document or delete it |
| T5 | Deep sync chain | longest path over sync edges ≥ 3 hops | med | availability multiplies and latency adds along the chain | async hop, cache, or an aggregating endpoint |
| T6 | Hub | a service on ≥ max(6, 30 % of all edges) | med | a change magnet and the centre of every blast radius | split by capability; put an anti-corruption layer in front |
| T7 | Chatty pair | ≥ 4 distinct sync labels between one pair | low | a boundary in the wrong place, or an API too fine-grained | one coarser endpoint, an event, or merge |
| T8 | Hard-wired endpoint | a literal URL or host at the call site with no config indirection | low | cannot be re-pointed per environment | config value behind a client adapter |
| T9 | Unkeyed event | `pub` with no `key=` on a topic read by ≥ 2 consumers | info | no per-entity ordering | key by the aggregate id |
| T10 | Event ping-pong | `A pub T1`, `B sub T1`, `B pub T2`, `A sub T2` | info | a choreography loop whose termination lives in code | an explicit end state, or an orchestrator |
| T11 | Unowned contract | a `ref` node, or a gRPC/HTTP edge with no `.proto`/spec in scope | info | the contract lives elsewhere and cannot be checked here | vendor the contract or point at its registry |
| T12 | Inference debt | more than 20 % of edges are not `CODE` | info | the diagram is less trustworthy than it looks | list the configs or contracts that would confirm them |

`\|` in the table is a literal `|`.

## The review view

Open with a health line, then the findings, then the as-is diagram with every
node named in a high or medium finding in class `warn`:

```text
services S · edges E · CODE c% · max sync depth d · sync cycles n · shared stores n · findings H high / M med / L low
```

| Id | Finding | Evidence |
|---|---|---|
| T2 | billing-svc consumes `orders.created`, then calls orders-svc for the order | `E billing-svc sub orders.created` · `E billing-svc http orders-svc` |

## To-be design - only when the user asks to improve or redesign

1. Every proposal fixes a named finding. No finding, no proposal.
2. Change as little as possible: fewest edges added or removed, existing names kept.
3. Draw a second diagram titled **PROPOSED - not in the code**: unchanged edges
   as they are, removed edges `-.-x`, added edges `==>`, new nodes in class `prop`.
4. Per proposal: the change, the findings it removes, migration steps (expand →
   migrate → contract), the risks, and the health line after it.
5. Never describe a proposal as current state, and never edit code to apply it.
