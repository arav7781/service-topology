# Changelog

## 2.0.0

A rewrite. The skill no longer runs any code.

### Added

- **Zero runtime.** The skill is Markdown only. The agent's own search and read
  tools do the extraction; there is no Python, Node or MCP server to install.
- **Lenses.** Diagrams are shaped by the question: `focus`, `lineage`, `path`,
  `impact`, `deps`, `data`, `overview`, `diff`, `review`, or a custom selection.
- **The topology ledger.** `service-topology/topology.ledger` stores one cited
  line per fact, sorted so a `git diff` is an architecture diff. It also acts as
  the cache for follow-up questions and incremental refresh.
- **Review lens.** Twelve topology checks, each proven by ledger lines, plus an
  optional to-be diagram that stays separate from the as-is view.
- **Address sweep.** One search over compose, Kubernetes and Helm config
  recovers declared wiring (`*_ADDR`, `*_URL`, `*_TOPIC`…).
- **Signatures for RabbitMQ, SQS/SNS/EventBridge/Kinesis, GCP Pub/Sub, NATS,
  Azure Service Bus, Redis streams, Celery, BullMQ and Sidekiq**, as well as
  Kafka. Also GraphQL, WebSocket and vendor SDKs.
- `topology-verifier` helper agent.
- `tools/check-ledger.sh`, `tools/token-budget.sh`, `tools/sync-hosts.sh` - all
  POSIX shell, used only by CI and contributors.

### Changed

- `SKILL.md` went from ~23 KB to ~10 KB. A first question loads ~7k tokens of
  instructions (v1: ~13k); a follow-up loads ~3.8k.
- `topology-extractor` returns ledger lines instead of scan JSON.
- Mermaid is the default output; draw.io is written only on request, using a
  grid layout the agent computes.
- Resolution follows cross-file constants, project wrappers and deploy config
  when every file on the chain is cited. v1 stopped at file boundaries.

### Removed

- `scripts/` and `topology_lib/` - the Python scan, model, layout, render and
  validate pipeline.
- `templates/`.
- `mcp-server/` and the `.cursor/mcp.json`, `.agents/mcp_config.json` and
  `.vscode/mcp.json` registrations.
- `hooks/topology_guard.py` and the hook examples. They are replaced by
  host permission rules; see [docs/safety-model.md](docs/safety-model.md).
- `graph-layout-validator` agent, replaced by `topology-verifier`.
- Fixed `master-topology.*` and `micro/*` outputs.

### Migrating from 1.x

| 1.x | 2.0 |
|---|---|
| `scan` mode | Ask a question; the ledger is written as a side effect |
| `master` | "Map this repo" → `views/overview.md` |
| `micro <svc>` | "What does `<svc>` talk to?" → `views/focus-<svc>.md` |
| `all` | Ask for the views you need; nothing is rendered unasked |
| `refresh` | Automatic - a stale ledger is refreshed from `git diff` |
| `graph-model.json` | `topology.ledger` |
| `evidence/sources.md` | The receipts table in each view, and the ledger itself |
| `--theme`, `--flow-animation` | Not needed; Mermaid lays out itself. draw.io styling is in `references/drawio.md` |
| MCP tools | Not needed; the skill works through the host's own tools |

## 1.2.1

Last Python release. Available at commit
[`63b28d5`](https://github.com/arav7781/service-topology/tree/63b28d5).
