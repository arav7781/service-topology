#!/usr/bin/env python3
"""Check that a graph model is complete, cited, and safe to render.

Part of the Topology Cartographer skill (Phase 5: completion check).

This is the gate that stops an unciteable diagram from being produced. It
enforces the rules the skill promises:

  * every edge has a `path/to/file:LINE` source, and it is well formed;
  * every edge endpoint is a node the model actually declares;
  * every edge carries a valid evidence tag;
  * every edge weaker than `[CODE]` explains why, so it can be listed as
    "inferred, not confirmed" rather than passing for a fact;
  * `produces` points at a topic and `consumes` starts at one.

With `--repo` it goes further and re-reads every cited location, confirming the
file exists and is long enough for the line number. That is the check that
catches a stale model rendered against moved code.

Usage
-----
    python3 validate_graph_model.py service-topology/graph-model.json
    python3 validate_graph_model.py graph-model.json --repo /path/to/repo
    python3 validate_graph_model.py graph-model.json --strict
    python3 validate_graph_model.py graph-model.json --format json
    python3 validate_graph_model.py --example

Exit codes
----------
    0  no problems (with --strict, also no warnings)
    1  bad arguments or unreadable input
    2  at least one problem found
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from topology_lib.model import GraphModel, validate  # noqa: E402

EXAMPLE = {
    "schema": "topology-cartographer/validation",
    "schema_version": "1.0.0",
    "model": "service-topology/graph-model.json",
    "ok": False,
    "counts": {"services": 3, "topics": 1, "external_systems": 1, "edges": 4},
    "problems": [
        "edge billing-svc -calls-> orders-svc: tagged INFERENCE without a note "
        "explaining why",
    ],
    "warnings": [
        "orders-svc: no edges - the service was discovered but nothing "
        "connects it to the rest of the system",
    ],
    "unresolved_citations": [],
}


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="validate_graph_model.py",
        description="Check a graph model for completeness and citation integrity.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Run this before rendering, and again before sharing a diagram.\n"
               "With --repo every cited file:line is re-read and confirmed.\n",
    )
    parser.add_argument("model", nargs="?", help="path to graph-model.json")
    parser.add_argument(
        "--repo", help="repository root, to verify every cited file:line exists")
    parser.add_argument(
        "--strict", action="store_true",
        help="treat warnings as failures")
    parser.add_argument(
        "--format", choices=("text", "json"), default="text",
        help="text (default) or json")
    parser.add_argument(
        "--example", action="store_true",
        help="print an example validation report and exit")
    return parser.parse_args(argv)


def soft_warnings(model: GraphModel) -> List[str]:
    """Things that are not errors but usually mean the diagram is incomplete."""
    warnings = []  # type: List[str]
    counts = model.edge_count_by_service()
    for service_id in sorted(model.services):
        if counts.get(service_id, 0) == 0:
            warnings.append(
                "{0}: no edges - the service was discovered but nothing connects "
                "it to the rest of the system".format(service_id))

    for topic_id in sorted(model.topics):
        touching = model.edges_touching(topic_id)
        producers = [e for e in touching if e.dst == topic_id]
        consumers = [e for e in touching if e.src == topic_id]
        if not producers and consumers:
            warnings.append(
                "{0}: consumed but no producer found - the producer may be "
                "outside the scanned scope".format(topic_id))
        if producers and not consumers:
            warnings.append(
                "{0}: produced but no consumer found - either a genuine dead "
                "topic or a consumer outside the scanned scope".format(topic_id))
        if not producers and not consumers:
            warnings.append(
                "{0}: declared but neither produced nor consumed".format(topic_id))

    inferred = model.inferred_edges()
    if inferred:
        warnings.append(
            "{0} of {1} edges are not confirmed - they render dashed and grey "
            "and are listed in evidence/sources.md".format(
                len(inferred), len(model.edges)))
    return warnings


def check_citations(model: GraphModel, repo: str) -> List[str]:
    """Re-read every cited location. Catches a model rendered against old code."""
    root = Path(repo).expanduser().resolve()
    problems = []  # type: List[str]
    cache = {}  # type: Dict[str, int]

    def line_count(relative: str) -> int:
        if relative not in cache:
            path = root / relative
            try:
                with open(str(path), "r", encoding="utf-8", errors="replace") as handle:
                    cache[relative] = sum(1 for _ in handle)
            except (OSError, IOError):
                cache[relative] = -1
        return cache[relative]

    def check(citation: str, owner: str) -> None:
        if ":" not in citation:
            problems.append("{0}: citation {1!r} has no line number".format(
                owner, citation))
            return
        relative, _, line_part = citation.rpartition(":")
        try:
            line = int(line_part.split("-")[0])
        except ValueError:
            problems.append("{0}: citation {1!r} has a non-numeric line".format(
                owner, citation))
            return
        total = line_count(relative)
        if total < 0:
            problems.append("{0}: cited file {1} does not exist under {2}".format(
                owner, relative, root))
        elif line > max(total, 1):
            problems.append("{0}: {1} has {2} lines but the citation is line {3}".format(
                owner, relative, total, line))

    for node_id in sorted(model.nodes):
        for citation in model.nodes[node_id].source_evidence:
            check(citation, "node {0}".format(node_id))
    for edge in model.edges:
        owner = "edge {0} -{1}-> {2}".format(edge.src, edge.type, edge.dst)
        for citation in edge.citations:
            check(citation, owner)
    return sorted(set(problems))


def render_text(report: Dict[str, Any]) -> str:
    counts = report["counts"]
    lines = [
        "model: {0}".format(report["model"]),
        "{0} service(s), {1} topic(s), {2} external system(s), {3} edge(s)".format(
            counts["services"], counts["topics"], counts["external_systems"],
            counts["edges"]),
        "",
    ]
    for key, heading in (("problems", "problems"),
                         ("unresolved_citations", "unresolved citations"),
                         ("warnings", "warnings")):
        entries = report[key]
        if entries:
            lines.append("{0} ({1}):".format(heading, len(entries)))
            for entry in entries:
                lines.append("  {0}".format(entry))
            lines.append("")
    if report["ok"]:
        lines.append("OK - every edge is declared, tagged, and cited.")
    else:
        lines.append("NOT OK - fix the problems above before rendering.")
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)

    if args.example:
        print(json.dumps(EXAMPLE, indent=2))
        return 0
    if not args.model:
        print("error: a graph-model.json path is required (or use --example)",
              file=sys.stderr)
        return 1

    try:
        model = GraphModel.load(str(Path(args.model).expanduser()))
    except (OSError, IOError) as error:
        print("error: {0}".format(error), file=sys.stderr)
        return 1
    except ValueError as error:
        print("error: {0} is not valid JSON: {1}".format(args.model, error),
              file=sys.stderr)
        return 1

    problems = validate(model)
    warnings = soft_warnings(model)
    unresolved = check_citations(model, args.repo) if args.repo else []

    ok = not problems and not unresolved and (not args.strict or not warnings)
    report = {
        "schema": "topology-cartographer/validation",
        "schema_version": "1.0.0",
        "model": args.model,
        "ok": ok,
        "counts": {
            "services": len(model.services),
            "topics": len(model.topics),
            "external_systems": len(model.external_systems),
            "edges": len(model.edges),
        },
        "problems": problems,
        "warnings": warnings,
        "unresolved_citations": unresolved,
    }

    if args.format == "json":
        print(json.dumps(report, indent=2))
    else:
        print(render_text(report))
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
