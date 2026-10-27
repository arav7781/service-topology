# Contributing

Topology Cartographer is a skill made of Markdown. Most contributions are
edits to that Markdown. The most valuable one isn't code at all: it's a real
repository the skill got wrong, whether a missed binding, a false edge or a
misjudged service boundary.

## Reporting a wrong map

Open an [extraction issue](https://github.com/arav7781/service-topology/issues/new?template=20-extraction-issue.yml) with:

- the framework or library involved ("kafkajs consumer behind a wrapper class");
- a minimal snippet - a few lines, nothing from a real private codebase;
- the ledger line the agent wrote, or the one it should have written;
- whether the correct edge is `CODE` or `INFERENCE`, and why.

A false edge is worse than a missed one, so say which you found.

## Ground rules

- **Never invent an edge.** A target that can't be named is a `G` line, not
  an arrow. Any change to the signatures or the ladder has to keep that rule.
- **Every fact cites `path:line`.** A change that adds a kind of fact adds a
  kind of receipt with it.
- **Stay inside the token budget.** `tools/token-budget.sh` sets a ceiling for
  each file. If you need more room, make the case in the PR; don't quietly
  raise the number. A sentence that helps a human but not the agent belongs in
  `docs/`, not in the skill.
- **No runtime.** Nothing in `skills/` or `agents/` may need an interpreter,
  a package or a server. CI fails if a non-Markdown file appears in a skill tree.
- **Edit the canonical tree** (`skills/topology-cartographer/`, `agents/`),
  then run `bash tools/sync-hosts.sh` to update the Copilot, Cursor and
  Antigravity mirrors. Their frontmatter is host-specific and is kept; the
  body is copied.

## Adding an ecosystem

1. Add a row to the right table in
   [`signatures.md`](skills/topology-cartographer/references/signatures.md):
   the gate token, the produce and consume patterns (or the client pattern),
   and where the target lives.
2. Add a snippet that exercises it to a fixture under `examples/`.
3. Add the lines it should produce to that fixture's
   `service-topology/topology.ledger`, with correct receipts.
4. Run the checks below.

## Checks

CI runs exactly these. Each one needs only bash, coreutils and awk; the
manifest check also needs `jq`.

```bash
bash tools/sync-hosts.sh --check     # mirrors match the canonical skill
bash tools/token-budget.sh           # every instruction file is inside its budget
bash tools/check-ledger.sh examples/fixture-mesh \
     examples/fixture-mesh/service-topology/topology.ledger
```

`check-ledger.sh` proves that receipts exist and fall inside their files. It
can't prove that a cited line says what the edge claims. For a change to
extraction, open the receipts you added and look.

If you change a view, paste its Mermaid into <https://mermaid.live> or a GitHub
comment preview to confirm it renders.

## Pull requests

- One coherent change per PR.
- Imperative commit messages that say what changed and why ("Add NATS
  JetStream pull consumers to the messaging signatures").
- If you change what an edge means or how it's tagged, update `SKILL.md` §5,
  the README's evidence table and any affected example ledger in the same PR.
