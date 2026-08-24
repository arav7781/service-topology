---
name: topology-cartographer
description: >-
  Map a repository's Kafka producer/consumer relationships and synchronous
  service-to-service calls into architecture diagrams. Extracts every binding it
  can trace to a file and line, builds a structured graph model, and renders
  valid .drawio (mxGraph) diagrams plus a Mermaid fallback under
  service-topology/ - one master topology for the whole system and one micro
  topology per service. Discovery and diagramming only - never modifies the
  analysed repository, never commits, never runs the application. Use when the
  user asks what talks to what, which services produce or consume a Kafka topic,
  what a service depends on, wants an architecture diagram of a codebase, or
  wants to see the blast radius of changing a topic or an endpoint.
---

# Topology Cartographer

Evidence-first architecture diagrams for a codebase you did not write.

Topology Cartographer answers one question: **what actually talks to what in
this system, and where in the code does each of those connections live?** It
produces diagrams. It never produces application code, and it never draws an
arrow it cannot cite.

Full design rationale lives in the project's planning document,
`Service_Topology_Mapping_Plan.md`.

---

## 1. Activation context

Use this skill when the user is standing in (or points at) a repository - their
own or a third party's - and wants to know:

- which services produce and consume a given Kafka topic;
- which services call which, over REST or gRPC, and on what endpoint;
- what a single service touches, in and out, without reading its code;
- what the blast radius of renaming a topic or changing an endpoint would be;
- what the system looks like, as a diagram they can open in their editor.

Do **not** use this skill to design a *new* architecture, to review code for
defects (that is a code review task), or to implement anything. It reports what
is there.

---

## 2. Hard constraints (non-negotiable)

During mapping you **MUST NOT**:

- modify application source code, configuration, tests, or documentation of the
  analysed repository;
- write anywhere outside `service-topology/` in the analysed repository (or an
  output directory the user names) - this includes the repository's own
  `.gitignore`;
- edit a generated `.drawio` file by hand, or hand-write mxGraph XML anywhere:
  XML comes from `scripts/render_drawio.py` and from nowhere else;
- invent an edge. Every arrow traces to a `path/to/file:LINE` you read in this
  run. A call whose target you cannot resolve is **left out**, not guessed at;
- present an `[INFERENCE]` as a fact, or quietly upgrade one to `[CODE]`
  because it would make the diagram look more complete;
- create branches, stage files, create commits, amend, rebase, or push;
- run the analysed application, its containers, its migrations, or its test
  suite - nothing here needs the code to execute;
- connect to a Kafka broker, a database, a service registry, or any other live
  system to "confirm" a binding;
- install dependencies, create virtualenvs, or run Docker builds;
- run destructive commands (`git reset --hard`, `git clean -fd`, `git checkout`
  over dirty files, `rm -rf`, deployment or release commands).

You **MAY**:

- read code, search files, and follow references across the repository;
- read configuration - `application.yml`, `.properties`, `.env`,
  docker-compose, Helm values, Terraform - to resolve a topic name or a base URL;
- run the bundled scripts in `scripts/`;
- delegate per-directory extraction to the `topology-extractor` subagent;
- write diagrams, the graph model, and the evidence report under the output
  directory;
- ask the user which service boundary is correct when the repository is
  ambiguous about it.

> If the user asks you to change the architecture the diagram reveals, that is a
> **different** task. Stop this skill, hand over the diagram and the evidence,
> and begin that work as separate, explicitly authorised work.

### Sandbox check before running anything

The scripts in `scripts/` read files and write to the output directory; they
need no network, no broker, and no package manager. Anything beyond them - a
repository's own build, a code-generation step, a container - is **not** part of
this skill. If you think you need it to resolve a binding, **ask first**, and
record what you ran and why in `evidence/sources.md`.

---

## 3. Modes

Invoke with the `/topology-cartographer <mode>` workflow, or in natural language ("use the
topology-cartographer skill in scan mode"). Both are equivalent - the mode is
just an argument that selects which phases run.

| Mode | Phases | Purpose |
|---|---|---|
| `scan` | 0-2 | Extract bindings and build the graph model. No diagrams. Cheap. Run this first. |
| `master` | 0-5 | The whole-system diagram: every service, topic, and edge. |
| `micro <service>` | 0-5 | One service's direct neighbourhood, with full label detail. |
| `all` | 0-5 | Master plus one micro topology per discovered service. |
| `refresh` | 1-5 | Re-scan and re-render after code changes, then report what moved. |

Default when no mode is given: **`scan`**. Never silently escalate to `all` -
`scan` is cheap, and its service list is what tells the user which micro
topology is worth generating first.

If the repository has more than roughly 5,000 source files, or `scan` reports
more than 25 services, ask the user which subsystems to focus on before running
`all`. Twenty-five micro topologies nobody asked for is not a deliverable.

---

## 4. Workflow

Track phases with a todo list. Do not skip phases. Do not reorder them.

### Phase 0 - Scope and service boundaries

Read `references/service-boundary-heuristics.md`.

Establish what counts as a service in this repository before extracting
anything. Run:

```bash
python3 scripts/scan_repository.py <repo> --format summary
```

Check the service list against the repository's own structure. A monorepo with
per-directory manifests usually maps cleanly; a single deployable with internal
modules usually does not, and a repository whose services are named only in
Kubernetes manifests may need `--scope`.

Emit exactly one decision:

```text
PROCEED | PROCEED_WITH_SCOPE | BOUNDARIES_UNCLEAR
```

**Stop condition:** on `BOUNDARIES_UNCLEAR`, show the user the detected list and
ask which boundaries are right before going further. A diagram built on the
wrong service boundaries is worse than no diagram - it is confidently wrong.

### Phase 1 - Extraction

Read `references/kafka-extraction-playbook.md` and
`references/sync-call-extraction-playbook.md`.

```bash
python3 scripts/scan_repository.py <repo> [--scope path,...] -o scan.json
```

For a large monorepo, delegate to the `topology-extractor` custom subagent via `invoke_subagent`
once per subtree and merge the shards in Phase 2. That keeps a 3,000-file repository from
filling the context window with source you only needed to grep.

Confirm the scan found what the repository's own documentation implies it should.
A service with a `KafkaTemplate` on its classpath and no `produces` edge is a
signal that an extractor missed something - say so rather than shipping the gap
silently.

### Phase 2 - Graph model

```bash
python3 scripts/build_graph_model.py --input scan.json \
    -o service-topology/graph-model.json \
    --evidence-out service-topology/evidence/sources.md
```

`graph-model.json` is the source of truth. Everything downstream reads it and
nothing downstream re-derives a fact from source. If an edge is wrong, fix the
extraction and rebuild the model - never edit the rendered diagram.

**Stop condition (`scan` mode):** stop here. Report the service list with edge
counts, the `[CODE]`/`[INFERENCE]` split, and which micro topology looks most
worth generating.

### Phase 3 - Layout

```bash
python3 scripts/layout_graph.py service-topology/graph-model.json \
    -o service-topology/graph-model.laid-out.json

# label-fitted boxes instead of the default dataflow shapes
python3 scripts/layout_graph.py service-topology/graph-model.json \
    --theme classic -o service-topology/graph-model.laid-out.json
```

A theme fixes node *sizes* as well as node styles, so it is chosen here and
stamped into the layout block; the renderers follow what is stamped. `streams`
(the default) draws the Kafka Streams dataflow idiom - circle topic, diamond
service, cylinder store, off-page external - and `classic` draws the
label-fitted boxes. See `references/drawio-xml-spec.md`.

Do not compute coordinates yourself, and do not adjust the ones the script
produces. The script is the authority on placement, exactly as
`calculate_candidate_score.py` is the authority on arithmetic in
contributor-scout. Its determinism is what makes two runs diffable.

### Phase 4 - Render

Read `references/drawio-xml-spec.md` if you need to understand the output; do
not use it to write XML yourself.

```bash
# master
python3 scripts/render_drawio.py service-topology/graph-model.laid-out.json \
    --mode master -o service-topology/master-topology.drawio
python3 scripts/render_mermaid.py service-topology/graph-model.laid-out.json \
    -o service-topology/master-topology.mmd

# one service
python3 scripts/render_drawio.py service-topology/graph-model.laid-out.json \
    --mode micro --service <name> \
    -o service-topology/micro/<name>.drawio

# everything
python3 scripts/render_drawio.py service-topology/graph-model.laid-out.json \
    --mode all --output-dir service-topology
python3 scripts/render_mermaid.py service-topology/graph-model.laid-out.json \
    --mode all --output-dir service-topology
```

Both renderers style the diagram for the theme it was laid out under. Passing
`--theme` here overrides that and re-runs the layout, so the shapes and the
coordinates cannot disagree. `--flow-animation` animates the arrows in draw.io -
worth it on a small dataflow, unreadable on a large master topology.

### Phase 5 - Validation and handover

```bash
python3 scripts/validate_graph_model.py service-topology/graph-model.json \
    --repo <repo>
```

`--repo` re-reads every cited location and confirms the file exists and is long
enough for the line number. Fix every reported problem before declaring
completion. Then tell the user how to view what you made - see section 7.

**A valid, successful outcome is:**

```text
No service-to-service communication was found in this repository.
```

A library, a monolith, and a CLI tool all legitimately produce that. Prefer it
over a diagram padded with inferences.

---

## 5. Output contract

Write everything under `service-topology/` at the repository root (or the
directory the user names). Never write outside it.

```text
service-topology/
├── master-topology.drawio        the whole system
├── master-topology.mmd           Mermaid fallback, same content
├── graph-model.json              the structured source of truth
├── graph-model.laid-out.json     the model plus diagram coordinates
├── micro/
│   ├── <service-name>.drawio     one service's direct neighbourhood
│   └── <service-name>.mmd
└── evidence/
    └── sources.md                every edge's tag and file:line
```

Service file names are slugs of the service id: `orders-svc.drawio`. Ids are
stable across `refresh` runs - never rename a service between runs just because
its label changed.

Use `templates/` for every document you write by hand. The `.drawio`, `.mmd`,
and `sources.md` files are generated - do not hand-edit them.

Add `service-topology/` to the user's global gitignore or tell them to exclude
it - do **not** edit the target repository's `.gitignore`.

---

## 6. Evidence requirements

Read `references/evidence-classification.md`.

Every edge carries a tag:

```text
[CODE] [INFERENCE] [UNVERIFIED]
```

Rules:

- Source locations are `path/to/file.ext:LINE`, verified by reading the file in
  this run. Never cite a line number you did not read.
- `[CODE]` covers a literal at the call site *and* a config key you followed to
  a concrete value in a config file you also read. Both ends were read, so both
  are direct.
- `[INFERENCE]` is the pattern matching but the target not resolving: an
  unresolved `${...}` placeholder, a hostname matching no known service, a gRPC
  stub with no `.proto` in scope. Every `[INFERENCE]` edge states *why* it is
  one.
- `[UNVERIFIED]` is for a binding a human or a subagent asserted that this run
  could not confirm by reading a file. Never produce one silently.
- Anything weaker than `[CODE]` renders **dashed and grey** and is listed under
  "Inferred, not confirmed" in `evidence/sources.md`. That is the whole point:
  a reader can see at a glance which parts of the diagram to trust.
- If you cannot resolve a call's target at all, **drop the edge**. An arrow to a
  guessed target is worse than a missing arrow, because a missing arrow looks
  like a gap and a wrong arrow looks like a fact.

---

## 7. Rendering and viewing

The `.drawio` file is the deliverable; the editor renders it. Do not build a
viewer, and do not install anything on the user's behalf.

| Host | How the user sees it |
|---|---|
| VS Code | Install `hediet.vscode-drawio`, then open the `.drawio` file. It renders on open - no command needed. |
| Cursor | Same extension, same behaviour. Offered from Cursor's marketplace or OpenVSX. |
| Antigravity | Same extension; it is a VS Code-compatible extension host. |
| GitHub Copilot Chat | Copilot Chat does not render files. It runs **inside VS Code**, so once the file is on disk the same extension previews it. Say this explicitly, or the user will wonder where the diagram went. |
| Any chat surface, no file view | Paste `master-topology.mmd` into a Markdown preview or a chat that renders Mermaid. |

`.vscode/extensions.json` in this project recommends the extension. All three
VS Code-family hosts honour that file and prompt to install it. **Recommend,
never auto-install** - extensions do not uniformly have that permission, and
attempting it fails noisily.

Always end a run by telling the user the exact path to open, and mention the
Mermaid fallback in the same breath.

---

## 8. Human approval gates

The skill stops at every gate and asks. It never proceeds through one on its own.

| Gate | Question | Where |
|---|---|---|
| Boundaries | Are these the right services? | End of Phase 0 |
| Cost | Large repository - which subsystems, and how many micro topologies? | Before Phase 1 |
| Accuracy | Does this diagram match how the system actually behaves? | After Phase 5 |
| Sharing | Is this safe to circulate? Topology reveals internal structure. | Before the user shares it |

The accuracy gate is the important one. The tool reads code; the user knows
production. Ask them to spot-check the edges around one service they know well,
and to look at the "inferred, not confirmed" list before trusting the picture.

---

## 9. Completion criteria

A run is complete only when all of these hold:

- [ ] Every phase for the selected mode ran, or was explicitly skipped with a
      recorded reason.
- [ ] `graph-model.json` exists and `validate_graph_model.py --repo` reports no
      problems.
- [ ] Every edge in every rendered diagram has a `source` in
      `graph-model.json` pointing at a real `file:line` in the analysed
      repository.
- [ ] Every `[INFERENCE]` and `[UNVERIFIED]` edge has a note saying why, renders
      dashed and grey, and appears under "Inferred, not confirmed".
- [ ] Every coordinate came from `layout_graph.py`; every byte of XML came from
      `render_drawio.py`.
- [ ] The master topology and at least one micro topology were produced, and the
      micro topology is a strict subset of the master centred on one service.
- [ ] Re-running the pipeline on unchanged code produces byte-identical output.
- [ ] `evidence/sources.md` lists every edge with its tag and location.
- [ ] No file outside `service-topology/` was created or modified.
- [ ] The user was told the exact path to open and which extension renders it.

Report honestly. If an ecosystem was not covered, if a service's bindings live
in generated code you skipped, or if the scan was scoped, say so in the final
summary rather than implying the diagram is complete.

---

## 10. Stop conditions

Stop immediately and report when:

- service boundaries are unclear and the user has not confirmed them;
- the repository has no discoverable services and the user has not named a scope;
- the user asks you to change the architecture rather than map it;
- `validate_graph_model.py` reports problems you cannot fix by re-extracting;
- an extractor would need to run the application, contact a broker, or read a
  live registry to resolve a binding;
- you find yourself about to hand-write mxGraph XML, hand-place a node, or edit
  a generated file;
- you find yourself about to write outside `service-topology/`.

---

## 11. Bundled resources

Load these on demand - do not read them all up front.

**References** (`references/`)

| File | When to read |
|---|---|
| `service-boundary-heuristics.md` | Phase 0 |
| `kafka-extraction-playbook.md` | Phase 1, any Kafka binding |
| `sync-call-extraction-playbook.md` | Phase 1, any REST or gRPC call |
| `evidence-classification.md` | Every phase that records a fact |
| `layout-algorithm.md` | Phase 3, or when a diagram reads badly |
| `drawio-xml-spec.md` | Phase 4, to understand the output - never to write it |
| `ide-rendering-playbook.md` | Phase 5, and any "where is my diagram" question |

**Templates** (`templates/`) - one per document you write by hand; use verbatim
structure.

| File | Purpose |
|---|---|
| `graph-model-schema.md` | The `graph-model.json` contract, field by field |
| `master-topology-summary.md` | The written summary that accompanies the master diagram |
| `micro-topology-summary.md` | The same, for one service |
| `evidence-sources.md` | The shape `evidence/sources.md` is generated in |

**Scripts** (`scripts/`) - run with `python3`; all support `--help` and
`--example`.

| Script | Purpose |
|---|---|
| `scan_repository.py` | Phase 1 extraction, one repository or one subtree |
| `build_graph_model.py` | Phase 2 merge, dedupe, and evidence report |
| `layout_graph.py` | Phase 3 deterministic placement |
| `render_drawio.py` | Phase 4 mxGraph XML |
| `render_mermaid.py` | Phase 4 Mermaid fallback |
| `validate_graph_model.py` | Phase 5 completeness and citation check |

**Custom subagents** (`.agents/agents/` directory): `topology-extractor`,
`graph-layout-validator`.
