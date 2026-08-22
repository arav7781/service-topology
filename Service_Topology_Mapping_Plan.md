**TOPOLOGY CARTOGRAPHER**

**Evidence-First Service Topology Mapping**

A structured framework for deriving architecture diagrams from a codebase, where every arrow is traceable to a line of source and every uncertainty is visible in the picture.

| **EXTRACT** | **MODEL** | **RENDER** |
|---|---|---|
| Read Kafka bindings and service calls out of the code and the config that feeds it. | Normalise them into one cited, deduplicated, deterministic graph. | Draw it as `.drawio` and Mermaid, with unconfirmed edges visibly different. |

**Prepared for**

Internal Team Review and Implementation Planning

**Prepared by**

Vaibhav Vanage

**Document date**

22 August 2026

# Document Purpose and Control

This document defines the proposed design, governance model, workflows, outputs, and delivery roadmap for Topology Cartographer, the second skill in this repository. It is the design source of truth: once agreed, it is kept unchanged, and the implementation is expected to follow it or to explain where it diverged and why.

It is a companion to `AI_Assisted_Open_Source_Contribution_Discovery_Plan.md`, not a replacement. The two skills share a repository, a safety posture, an evidence-tag vocabulary, and a packaging model; they answer different questions.

# Contents

1. Executive Summary
2. Background and Problem Statement
3. Vision, Objectives, and Non-Goals
4. Design Principles
5. Proposed Architecture
6. End-to-End Operating Workflow
7. Service Boundary Determination
8. Kafka Binding Extraction
9. Synchronous Call Extraction
10. Evidence Model
11. Layout and Rendering
12. Output Contract
13. Host Packaging and the MCP Layer
14. Safety and Governance
15. Delivery Roadmap
16. Risks and Mitigations

# 1. Executive Summary

Engineering teams working on event-driven systems routinely lack an accurate picture of what talks to what. Architecture diagrams exist, are drawn once, and drift. The knowledge that replaces them lives in the heads of the three people who have been there longest.

Topology Cartographer derives the diagram from the code instead. It scans a repository for Kafka producer and consumer bindings and for synchronous service-to-service calls, resolves the config that topic names and base URLs actually live in, and renders two levels of detail: one master topology of the whole system, and one micro topology per service.

## Expected outcome

A diagram a reviewer can trust, because every arrow in it cites a `path/to/file:LINE` they can open, and because the arrows that could not be fully resolved are drawn differently and listed separately.

## Proposed delivery model

A skill in this repository, packaged for four hosts, backed by six standard-library-only scripts and an MCP server. No new dependencies, no service to run, no data leaving the machine.

## Recommended initial decision

Ship V1 covering Kafka and REST/gRPC with a single layout algorithm. Defer schema-registry awareness, staleness diffing, and non-Kafka brokers to later versions rather than shipping a broader but less trustworthy V1.

# 2. Background and Problem Statement

## Why service topology is hard to see

An event-driven system's structure is distributed across the thing it describes. A topic name appears in a producer in Go, a consumer in Python, an `application.yml` in a third service, and a Terraform resource in a fourth repository. No single file states the relationship. The relationship is what matters.

Three failure modes follow. Diagrams are drawn by hand and drift within weeks. Tribal knowledge substitutes for documentation and leaves with the person. And a change to a topic or an endpoint carries an unknown blast radius, which makes teams either too cautious or not cautious enough.

## Opportunity created by coding agents

An agent can read a whole repository quickly and can be given per-ecosystem extraction knowledge. What it cannot be trusted to do is draw the result: asked for a diagram, a model will produce a plausible one, partly invented, with no way for the reader to tell which parts.

## Problem statement

Produce architecture diagrams from a codebase such that a reader can verify any individual claim in seconds, and can see at a glance which claims are not verified. Do it without executing the system, without contacting a live environment, and without modifying the repository being mapped.

# 3. Vision, Objectives, and Non-Goals

## Vision

The diagram is generated, not drawn. It is regenerated when the code changes. A diff between two generations is a diff between two architectures.

## Primary objectives

1. **Traceability.** Every edge carries a `path/to/file:LINE` read during the run.
2. **Visible uncertainty.** An unconfirmed edge is dashed and grey and listed separately. Evidence quality is legible from the picture.
3. **Determinism.** The same code produces the same bytes, so two runs are diffable.
4. **Two levels of detail.** A master topology for the system, a micro topology per service with enough label detail to review without opening code.
5. **Read-only.** The analysed repository is never modified, and the analysed system is never contacted.
6. **Host reach.** Usable from Claude Code, GitHub Copilot, Cursor, and Antigravity without duplicating extraction logic.

## Non-goals for V1

- No custom diagram renderer or webview. `.drawio` is already rendered by an extension that works in every VS Code-family editor.
- No LLM-authored mxGraph XML. Generation is a script, from a structured input.
- No runtime observation: no broker connection, no service registry, no distributed trace.
- No modification of the analysed repository, including its `.gitignore`.
- No guessed edges. A call whose target does not resolve is dropped.
- No non-Kafka brokers, no schema-registry lookup, no staleness diffing. Those are V2 and V4.

# 4. Design Principles

1. **A missing arrow beats a wrong arrow.** Under-reporting is detectable by a reader who knows the system; mis-reporting is not. Every ambiguous case resolves toward dropping the edge.
2. **The model owns judgement, scripts own everything mechanical.** Coordinates, XML, deduplication, and the evidence report are arithmetic. The same division as `calculate_candidate_score.py` in contributor-scout.
3. **The graph model is the only interface.** Nothing downstream of it re-reads source. A wrong edge is fixed by fixing extraction, never by editing output.
4. **Two files can make one direct claim.** Reading a config key at a call site and reading its value in a config file is still reading. Config-resolved bindings are `[CODE]`.
5. **Evidence is visible, not just recorded.** The dashed grey arrow is the feature. A footnote nobody reads is not.
6. **Determinism is a released guarantee.** Breaking byte-identical re-runs is a breaking change, however much better the diagram looks.
7. **Standard library only.** The constraint that makes the scripts runnable anywhere, and that ruled out PyYAML and graphviz.

# 5. Proposed Architecture

## Logical architecture

Four layers, each with one job:

| Layer | Contents | Owns |
|---|---|---|
| Host packaging | `skills/`, `agents/`, and their three mirrors | When to run this, what to ask, what to refuse |
| Compatibility | `mcp-server/` | Making the same library callable from hosts with no skill format |
| Entry points | `scripts/*.py` | Argument handling, exit codes, `--help`, `--example` |
| Library | `scripts/topology_lib/` | Discovery, config indexing, extraction, the model, layout, rendering |

## Why a pipeline rather than an agent loop

Because the guarantees are pipeline guarantees. Determinism, containment, and citation integrity are properties of a fixed sequence of transformations over a structured artefact. An agent deciding at each step what to do next cannot offer any of the three.

## Core components

`discovery` walks and attributes files. `configindex` parses the subset of YAML, properties, dotenv, compose, Helm, and Terraform that config lives in. `extract_kafka` and `extract_sync` produce cited edges. `model` normalises, deduplicates, validates, and enforces write containment. `layout` places. `render` serialises.

# 6. End-to-End Operating Workflow

Six phases, each with an artefact and a gate:

| Phase | Produces | Gate |
|---|---|---|
| 0 Scope and boundaries | Service list, one of three decisions | Are these the right services? |
| 1 Extraction | Scan document with cited facts | Large repository - which subsystems? |
| 2 Graph model | `graph-model.json`, `evidence/sources.md` | `scan` mode ends here |
| 3 Layout | `graph-model.laid-out.json` | - |
| 4 Render | `.drawio`, `.mmd` | - |
| 5 Validation | Pass/fail plus warnings | Does this match how the system behaves? |

## Stage gates

Boundaries, cost, accuracy, sharing. None is passed by the tool alone. The accuracy gate carries the most weight: the tool reads code, the user knows production, and the calibration step is asking them to check one service they know well.

# 7. Service Boundary Determination

Service identity is the one judgement the pipeline must make before any edge means anything. It is made from declared names, in precedence order: `spring.application.name`, then `artifactId`, `rootProject.name`, package.json `name`, the go.mod module, `pyproject.toml` name, `Cargo.toml` name, `Chart.yaml` name, then the directory name.

Each file is attributed to the deepest service root above it. A file under no service root belongs to no service and is skipped by the extractors - which is what stops a repository-root `docker-compose.yml` from hanging every connection string in it off whichever service sorts first.

Where boundaries are genuinely ambiguous - a modular monolith, deployables defined only in Helm, more than twenty-five services - the run stops and asks.

# 8. Kafka Binding Extraction

Five ecosystems: Spring Kafka and the JVM client, kafka-python and its relatives, kafkajs and NestJS, segmentio/kafka-go and sarama, and Spring Cloud Stream bindings in config.

The hard part is not the call sites, it is that the topic name has usually moved: to the next line, to a constant, to `application.yml`, to an environment variable, or to Terraform. The resolution ladder tries the literal, then a placeholder default, then the config index across four key spellings, and only then gives up - producing an `[INFERENCE]` edge to a topic node labelled with the unresolved symbol.

Every extractor is gated on the file referencing Kafka at all. Without that gate a bare `.send(...)` becomes a phantom topic, and a diagram with phantom topics is worse than no diagram.

# 9. Synchronous Call Extraction

REST is harder than Kafka, because a URL is assembled rather than named. The resolution ladder is: literal URL whose host is a known service; literal URL whose host is a real external domain; a symbol resolved through a file-local table into a config value; a path matched against an OpenAPI spec; and otherwise nothing.

The symbol table is deliberately file-local. Chasing a constant across module boundaries by name alone produces confident nonsense in any repository with more than one `BASE_URL`.

gRPC resolves in two phases, because a `.proto` says a contract exists without saying who serves it. Phase one reads declarations and server registrations; phase two turns stub construction into an edge whose tag depends on whether an implementer was found.

# 10. Evidence Model

Three tags, reused from contributor-scout with the four inapplicable ones dropped: `[CODE]`, `[INFERENCE]`, `[UNVERIFIED]`.

The rule that does the work is the consequence, not the definition: anything weaker than `[CODE]` renders dashed and grey, appears in a separate "inferred, not confirmed" section, and carries a written reason. A tag that changes nothing visible is a tag nobody acts on.

Deduplication is part of the evidence model, not a rendering convenience. Three sightings of one binding become one arrow with three citations. A sighting with no label folds into a labelled sighting of the same relationship.

# 11. Layout and Rendering

A layered DAG placement in the standard library: break cycles by depth-first search over sorted ids, layer by longest path, order by barycentre sweeps with a total tie-break on id, place, then route - straight for adjacent layers, a jog for longer spans, a channel below the diagram for back edges.

Micro topologies use five fixed columns instead, so every one of them reads the same way.

Rendering emits mxGraph via `ElementTree`, so no service name can produce a file draw.io refuses to open, and every node and edge is wrapped in a `UserObject` carrying its citation - which puts the evidence inside the diagram, where someone handed only the file can still audit it.

# 12. Output Contract

Everything under `service-topology/`: the two diagram formats, the graph model, the laid-out model, per-service micro topologies, and the evidence report. Nothing outside it, enforced in code by a containment-checked writer rather than by instruction.

# 13. Host Packaging and the MCP Layer

The same payload four times - Claude Code, GitHub Copilot, Cursor, Antigravity - with per-host frontmatter and byte-identical bodies, checked by `tools/sync_hosts.py` in CI.

Cursor and Antigravity additionally get an MCP server exposing four tools. They need both: the skill tree gives their agent the workflow and the constraints, the server gives it callable tools. A host that can call `scan_repository` but has never read the hard-constraints section will happily be asked to edit the diagram it just made.

# 14. Safety and Governance

Read-only on the analysed repository; no execution of the analysed system; no network; no dependency installation. Enforced in three overlapping layers: instructions in the skill, containment in code, and an optional dual-payload hook that covers the whole session.

The residual risk worth naming is over-trust. The most likely harm from this tool is someone treating a generated diagram as authoritative because it looks authoritative. The dashed edges, the inferred-edge section, and the mandatory "what this diagram does not show" block are all aimed at that, and none of them works if the summary is skipped.

# 15. Delivery Roadmap

V1 covers Kafka, REST, gRPC, and external systems across four hosts. V2 adds schema-registry awareness, staleness diffing, consumer-group topology, and dead-letter recognition. V3 broadens language and framework coverage and adds mesh and gateway configuration as an edge source. V4 goes beyond Kafka to RabbitMQ, SNS/SQS, and Pub/Sub.

Detail in `docs/implementation-roadmap.md`.

# 16. Risks and Mitigations

| Risk | Mitigation |
|---|---|
| A fabricated edge is believed | Unresolvable targets are dropped, not guessed; every edge cites a line; `validate_graph_model.py --repo` re-reads them all |
| The diagram looks complete but is not | Coverage gaps are reported in the run summary and in the playbooks; validation warns on topics with no producer and services with no edges |
| Wrong service boundaries make every edge wrong | Phase 0 stops and asks before anything is extracted |
| Regex extraction produces false positives | File-level gating per ecosystem, noise rejection on candidate topic names, and a bias toward dropping ambiguous matches |
| Output drifts between runs and diffs become useless | Determinism is a released guarantee, checked in CI by rendering twice and diffing |
| Four host copies drift apart | `tools/sync_hosts.py` in CI |
| A user edits the diagram and it silently stops matching the evidence | The optional guard hook denies writes to generated artefacts; the skill says to re-run instead |
