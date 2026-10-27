# Architecture

Topology Cartographer v2 is an agent skill with no runtime. This document
explains why v1's design was replaced, what v2 is made of, and which decisions
hold it together.

## What was wrong with v1

v1 (up to 1.2.1) was a deterministic Python pipeline - scan, build model,
layout, render, validate - wrapped in a skill that told the agent to run it.
It was careful and well tested. It also had structural limits that no amount
of tuning could fix:

| Area | Gap or bottleneck | Consequence |
|---|---|---|
| Runtime | Every phase needed `python3` | On Windows `python3` is often absent or opens the Store stub; locked-down agent sandboxes can't run scripts. The skill did nothing. |
| Bootstrap | Outside Claude Code, `CLAUDE_PLUGIN_ROOT` is unset, so the skill fell back to `find / -name scan_repository.py` | A filesystem-wide crawl before the first useful step |
| Tokens | SKILL.md was ~23 KB, and a normal run also loaded five playbooks | ~13k tokens of instructions per run, before reading any code |
| Intelligence | Rules forbade the agent from resolving anything itself; extraction was file-local regex | Wrapped clients, cross-file constants and addresses set in Kubernetes were missed, though the agent reading the code could have followed them |
| Output shape | Fixed master and micro diagrams | Every question became the same picture; no lineage, path, impact, diff or review |
| Reuse | Every run started from zero | Follow-up questions paid the full cost again; no incremental refresh |
| Packaging | ~1 MB of Python mirrored into four host trees, kept in sync by another Python tool | Every fix had to be made four times, and drift was a CI concern |
| MCP | Configs pointed at `${workspaceFolder}/mcp-server/…` | Worked only when this repository was the open workspace - never the real use case |
| Safety | A Python pre-tool-use hook, opt-in | Another runtime dependency, and it blocked ordinary work in the session |

The fix wasn't a faster pipeline. It was to stop needing one.

## What v2 is

```text
skills/topology-cartographer/
├── SKILL.md                rules, token budget, routing, workflow, ledger grammar   ~2.5k tokens
└── references/
    ├── signatures.md       search recipes per ecosystem + resolution ladder          loaded to scan
    ├── lenses.md           question → subgraph → Mermaid conventions                 loaded to draw
    ├── smells.md           twelve topology checks + to-be rules                      review only
    └── drawio.md           grid layout and XML skeleton                              draw.io only
agents/
├── topology-extractor.md   shard helper for big monorepos: returns ledger lines only
└── topology-verifier.md    skeptical second pass before a diagram is shared
```

The agent supplies the runtime: its own search tool runs the sweeps, its read
tool opens windows, and its write tool writes the ledger and the views.

## Five decisions

### 1. The ledger is the interface

Everything the agent learns becomes one line in `service-topology/topology.ledger`:

```text
N <id> <kind> <tech> | <receipts>
E <actor> <rel> <object> | <label> | <TAG> | <receipts> | <note>
G <subject> | <what is unresolved, and what would resolve it> | <receipts>
```

Why this format rather than JSON:

- **Cheap.** About 150 bytes per edge, receipts and notes included, with no
  key names, quoting or indentation around each fact.
- **Diffable.** One fact per line, sorted byte-wise, so `git diff` of two
  ledgers is the architecture change. That one property gives the `diff` lens
  and PR review for free.
- **A cache.** A follow-up question reads the ledger, not the repository. A
  stale ledger is repaired by deleting the lines whose primary receipt sits in
  a file git says changed, then re-sweeping only those files.
- **Checkable without a runtime.** [`tools/check-ledger.sh`](../tools/check-ledger.sh)
  is awk and coreutils.

### 2. The question picks the view

v1 had two outputs. v2 has lenses: `focus`, `lineage`, `path`, `impact`,
`deps`, `data`, `overview`, `diff`, `review`, plus custom selections. Each
lens defines a subgraph rule and a diagram form, so the same ledger yields a
lineage chain for one question and a ringed blast radius for the next. The lens
also bounds the scan: a `focus` question reads the subject and one echo search,
not the whole repository.

`impact` and `deps` follow **dependency**, not data flow. A consumer depends on
its topic, and the topic depends on its producer, so "what breaks if X
changes" walks those links backwards and treats channels as conduits rather
than victims.

### 3. Search, don't read

Each ecosystem family is one combined regex, built only from the rows whose
gate matched. Results come back as `file:line: text`. A file is opened only as
a window of 30 lines or fewer, and only when the target isn't on the hit line.
Two sweeps do most of the work:

- **The address sweep** over deploy config (`*_ADDR`, `*_URL`, `*_TOPIC`…). In
  a twelve-factor system the deployment declares who talks to whom, so one
  search often recovers the whole wiring. Every edge still needs its client
  call in code as well.
- **The echo search** for every name found so far. It catches what patterns
  can't: wrappers, constants files, a topic named in a test helper's sibling.

### 4. Receipts make an LLM auditable

Because the agent now resolves things itself, the rules around evidence are
stricter than v1's:

- Every receipt is a `path:line` copied from a search hit or a window the agent
  saw. Line numbers are never estimated.
- A `CODE` edge reached through a symbol lists every file on the chain.
- Anything weaker is `INFERENCE` with a written reason, drawn dashed.
- A target that can't be named isn't drawn; it becomes a `G` line.
- `topology-verifier` re-opens receipts and checks that each line holds the
  binding its edge claims.

### 5. Budget the instructions

The skill is paid for on every run, so its size is a released property.
`SKILL.md` holds only what every question needs. References load by phase,
and [`tools/token-budget.sh`](../tools/token-budget.sh) fails CI when a file
outgrows its budget. The chat reply is ten lines or fewer, because the diagram
lives in a file.

## Hosts

The canonical skill and agents live in `skills/` and `agents/`. Mirrors for
Copilot (`.github/`), Cursor (`.cursor/`) and Antigravity (`.agents/`) keep
their own frontmatter, and everything below it is copied by
[`tools/sync-hosts.sh`](../tools/sync-hosts.sh). CI runs it with `--check`.
Because the payload is now a few small Markdown files, the mirrors cost
kilobytes, not megabytes.

## What v2 gave up, and why it's worth it

v1 rendered byte-identical output on every run, and v2 can't promise that: an
agent may find more or less in a hard case. v2 narrows the variance with fixed
search recipes, a fixed resolution ladder, a canonical ledger order and
deterministic layout rules, and it makes every claim checkable. In exchange it
runs anywhere an agent runs, resolves what regexes couldn't, answers the
question actually asked, and costs about half as many instruction tokens.

The v1 design document is kept, unchanged, at
[`history/v1-mapping-plan.md`](history/v1-mapping-plan.md).
