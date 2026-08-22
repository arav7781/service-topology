# Contributing

Topology Cartographer scans a codebase and produces evidence-backed
architecture diagrams. Improvements are welcome — the most valuable
contribution is not code, it is a real repository this tool got wrong: a
missed binding, a false edge, a service boundary it misjudged.

## Reporting an extraction problem

Open an issue with:

- the framework/library involved (e.g. "kafkajs consumer with a dynamic topic
  pattern"),
- a minimal snippet that reproduces it — a few lines is enough, you do not need
  to share your real repository,
- what the tool produced (or failed to produce), and what you expected,
- whether the edge that's wrong would have been `[CODE]` or `[INFERENCE]` if
  correct.

A false negative (a real binding the tool missed) and a false positive (an
edge that doesn't exist) are both worth reporting, but they are not equally
serious — see the evidence rule below.

## Ground rules for a change

- **Never invent an edge.** If a call's target cannot be resolved, the edge is
  dropped, not guessed at. Any change to an extractor must preserve this: a
  false negative is acceptable, a false positive is not.
- **Every edge cites a `path/to/file:LINE`.** If your change adds a fact to the
  graph model, it needs a citation the reader can open and verify.
- **`[INFERENCE]` requires a `note`** explaining why the edge isn't confirmed.
  See
  [`references/evidence-classification.md`](skills/topology-cartographer/references/evidence-classification.md).
- **Standard library only.** No PyYAML, no graphviz, no third-party anything in
  `topology_lib/` or the scripts. If you think you need a dependency, open an
  issue first and explain why the standard-library approach doesn't work.
- **Determinism is a released guarantee.** Re-running the pipeline on
  unchanged code must produce byte-identical output. Sort every collection you
  iterate; never rely on dictionary insertion order or filesystem walk order.
- **Python 3.8 is the floor.** CI runs 3.8 and 3.12. Use `.format()` rather
  than f-strings, and `typing.Dict`/`List`/`Optional` rather than builtin
  generics — this keeps the codebase consistent, and it's what the CI matrix
  actually checks.
- **One coherent change per PR.** A new extractor, a bug fix, a doc
  improvement — pick one. Add or update the fixture in
  `examples/fixture-mesh/` when you change extraction behaviour, so the change
  is testable and the worked examples stay honest.
- **The four host trees must stay in sync.** `skills/topology-cartographer/`
  is canonical; `.github/skills/`, `.cursor/skills/`, and `.agents/skills/`
  mirror it. Run `tools/sync_hosts.py --write` after editing anything under
  `references/`, `templates/`, or `scripts/`.

## Adding a new ecosystem (Kafka client, HTTP framework, etc.)

1. Add the extraction function to `topology_lib/extract_kafka.py` or
   `topology_lib/extract_sync.py`, following the existing pattern: gate on the
   file actually referencing the ecosystem, resolve the topic/URL through the
   existing ladder (literal → config index → drop), and tag every edge.
2. Add a fixture file under `examples/fixture-mesh/` exercising it, or add a
   new service if the ecosystem needs its own language/manifest.
3. Document it in the relevant playbook —
   [`kafka-extraction-playbook.md`](skills/topology-cartographer/references/kafka-extraction-playbook.md)
   or
   [`sync-call-extraction-playbook.md`](skills/topology-cartographer/references/sync-call-extraction-playbook.md).
4. Run the verification battery below and confirm the new edge appears with
   the right evidence tag.

## Verifying a change

The full battery — CI runs exactly this:

```bash
# 1. everything compiles
python3 -m py_compile \
  skills/topology-cartographer/scripts/*.py \
  skills/topology-cartographer/scripts/topology_lib/*.py \
  mcp-server/*.py hooks/*.py tools/*.py

# 2. the four host trees agree
python3 tools/sync_hosts.py

# 3. every script answers --help and --example
S=skills/topology-cartographer/scripts
for s in scan_repository build_graph_model layout_graph \
         render_drawio render_mermaid validate_graph_model; do
  python3 "$S/$s.py" --help >/dev/null && python3 "$S/$s.py" --example >/dev/null
done
python3 mcp-server/topology_mcp_server.py --list-tools >/dev/null

# 4. the pipeline is deterministic over the fixture
for out in run-a run-b; do
  mkdir -p "$out"
  python3 $S/scan_repository.py examples/fixture-mesh -o "$out/scan.json"
  python3 $S/build_graph_model.py --input "$out/scan.json" --output-root "$out" \
    -o "$out/graph-model.json" --evidence-out "$out/evidence/sources.md"
  python3 $S/layout_graph.py "$out/graph-model.json" --output-root "$out" \
    -o "$out/laid-out.json"
  python3 $S/render_drawio.py "$out/laid-out.json" --mode all \
    --output-dir "$out" --output-root "$out"
  python3 $S/render_mermaid.py "$out/laid-out.json" --mode all \
    --output-dir "$out" --output-root "$out"
done
diff -r run-a run-b                             # must be byte-identical

# 5. every citation resolves to a real line in the fixture
python3 $S/validate_graph_model.py run-a/graph-model.json \
  --repo examples/fixture-mesh

# 6. the MCP server answers a real client over stdio
python3 mcp-server/test_client.py

# 7. the guard hook still denies what it should, in every host dialect
echo '{"tool_name":"Bash","tool_input":{"command":"git commit -m x"},"cwd":"'"$PWD"'"}' \
  | python3 hooks/topology_guard.py            # must print a deny
echo '{"toolCall":{"name":"run_command","args":{"CommandLine":"kafka-topics --list","Cwd":"'"$PWD"'"}}}' \
  | python3 hooks/topology_guard.py            # must print a deny
echo '{"tool_name":"Write","tool_input":{"file_path":"'"$PWD"'/service-topology/master-topology.drawio"},"cwd":"'"$PWD"'"}' \
  | python3 hooks/topology_guard.py            # must print a deny

rm -rf run-a run-b
```

Step 4 is the one most likely to catch a regression. If it fails, something
introduced run-to-run variation — a timestamp, a set iterated without sorting,
or a dictionary whose order came from a filesystem walk.

## Pull requests

- Write commit messages in the imperative mood, describing the change and the
  reason ("Add faust agent support to the Python Kafka extractor").
- CI must pass. If the sync check fails, run
  `tools/sync_hosts.py --write` and commit the result — `SKILL.md` and agent
  frontmatter are host-specific and merge by hand.
- If your change affects what an edge means or how it's tagged, update
  [`docs/output-format.md`](docs/output-format.md) and the relevant reference
  playbook in the same PR.
