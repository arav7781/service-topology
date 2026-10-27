<!--
One coherent change per PR: a new signature row, a lens fix, a doc
improvement - pick one.
-->

## What and why

<!-- What changes, and what observed problem motivates it. Link the issue. -->

Closes #

## Type of change

- [ ] New ecosystem / signature row - fixture snippet and expected ledger lines added
- [ ] Fix to an existing signature or the resolution ladder - a false or missed edge, now correct
- [ ] Ledger grammar or evidence rules - `SKILL.md` §5, README and example ledgers updated together
- [ ] Lens or diagram conventions
- [ ] Review checks (`smells.md`)
- [ ] New host support
- [ ] Documentation / examples
- [ ] Repository tooling (CI, `tools/`, templates)

## Verification

- [ ] Edited the canonical tree (`skills/topology-cartographer/`, `agents/`), then ran `bash tools/sync-hosts.sh`
- [ ] `bash tools/sync-hosts.sh --check` reports no drift
- [ ] `bash tools/token-budget.sh` passes, and no budget was raised without a reason in this PR
- [ ] `bash tools/check-ledger.sh` passes for every example ledger I touched
- [ ] I opened every receipt I added and it shows the binding its edge claims
- [ ] No edge without a receipt; no `INFERENCE` edge without a reason
- [ ] Any Mermaid I changed renders (GitHub preview or mermaid.live)
