<!--
One coherent change per PR. A new extractor, a bug fix, a doc improvement —
pick one.
-->

## What and why

<!-- What changes, and what observed problem motivates it. Link the issue. -->

Closes #

## Type of change

- [ ] New extractor / ecosystem — **fixture added or extended in `examples/fixture-mesh/`** and the relevant playbook updated
- [ ] Bug fix in an existing extractor — edge that was false/missed, now corrected
- [ ] Graph model / schema change — `docs/output-format.md` and `templates/graph-model-schema.md` updated together
- [ ] Layout / rendering change — `docs/architecture.md` or the relevant reference updated if the algorithm changed
- [ ] Guard hook change — all four payload dialects handled; deny tests extended
- [ ] New host support
- [ ] MCP server change
- [ ] Documentation / examples
- [ ] Repo infrastructure (CI, templates, packaging)

## Verification

- [ ] Edited the **canonical** tree (`skills/topology-cartographer/`, `agents/`), then ran `python3 tools/sync_hosts.py --write`
- [ ] `python3 tools/sync_hosts.py` reports no drift
- [ ] `python3 -m py_compile skills/topology-cartographer/scripts/*.py skills/topology-cartographer/scripts/topology_lib/*.py mcp-server/*.py hooks/*.py tools/*.py` passes
- [ ] The pipeline is still deterministic over `examples/fixture-mesh/` (run twice, `diff -r`)
- [ ] `validate_graph_model.py --repo examples/fixture-mesh` reports no problems
- [ ] `python3 mcp-server/test_client.py` passes (if the MCP server or graph model changed)
- [ ] Guard-hook deny tests pass in all host dialects (if `hooks/topology_guard.py` changed)
- [ ] No edge was added without a `path/to/file:LINE` citation; no `[INFERENCE]` edge without a `note`
- [ ] Documentation updated where behaviour changed (README, docs/, the relevant reference playbook)
