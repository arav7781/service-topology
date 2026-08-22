#!/usr/bin/env python3
"""Merge scan output into the canonical graph-model.json.

Part of the Topology Cartographer skill (Phase 2: graph model).

One scan produces one shard. This script merges any number of shards into the
single structured source of truth every renderer reads, dropping duplicate
sightings, keeping the strongest evidence tag for each fact, sorting everything
so the output is byte-reproducible, and writing the evidence report.

It also refuses to emit a model that would draw an edge it cannot cite. If a
shard contains an edge with no `source`, a target that no node declares, or an
`[INFERENCE]` with no reason, that is a bug in extraction, not something to
paper over at render time.

Usage
-----
    python3 build_graph_model.py --input scan.json -o service-topology/graph-model.json
    python3 build_graph_model.py --input orders.json --input billing.json \
        -o service-topology/graph-model.json \
        --evidence-out service-topology/evidence/sources.md
    cat scan.json | python3 build_graph_model.py --input - -o graph-model.json
    python3 build_graph_model.py --example

Accepts either a scan document (`topology-cartographer/scan`) or an existing
graph model (`topology-cartographer/graph-model`), so a model can be re-merged.

Exit codes
----------
    0  model written and structurally valid
    1  bad arguments or unreadable input
    2  the merged model has validation problems (it is still written, so the
       problems can be inspected, but do not render from it)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from topology_lib import VERSION  # noqa: E402
from topology_lib.model import (  # noqa: E402
    GraphModel,
    OutsideOutputRoot,
    SafeWriter,
    user_path,
    validate,
)
from topology_lib.render import render_evidence  # noqa: E402

EXAMPLE = {
    "schema": "topology-cartographer/graph-model",
    "schema_version": "1.0.0",
    "repo": "/home/dev/acme-platform",
    "stats": {"services": 3, "topics": 1, "external_systems": 1, "edges": 4,
              "edges_code": 3, "edges_inference": 1},
    "services": [
        {"id": "orders-svc", "kind": "service", "label": "orders-svc",
         "language": "go", "path": "services/orders",
         "source_evidence": ["services/orders/go.mod:1"]},
        {"id": "billing-svc", "kind": "service", "label": "billing-svc",
         "language": "python", "path": "services/billing",
         "source_evidence": ["services/billing/pyproject.toml:2"]},
    ],
    "topics": [
        {"id": "orders.created", "kind": "topic", "label": "orders.created",
         "source_evidence": ["services/orders/kafka/producer.go:42"]},
    ],
    "external_systems": [
        {"id": "postgresql-orders", "kind": "datastore", "label": "PostgreSQL\norders",
         "source_evidence": ["services/orders/config.go:12"]},
    ],
    "edges": [
        {"from": "orders-svc", "to": "orders.created", "type": "produces",
         "protocol": "kafka", "detail": "key=order_id", "evidence_tag": "CODE",
         "source": "services/orders/kafka/producer.go:42", "extractor": "kafka-go"},
        {"from": "orders.created", "to": "billing-svc", "type": "consumes",
         "protocol": "kafka", "detail": "group=billing", "evidence_tag": "CODE",
         "source": "services/billing/consumers.py:18", "extractor": "kafka-python"},
        {"from": "billing-svc", "to": "orders-svc", "type": "calls",
         "protocol": "grpc", "method": "GetOrder", "evidence_tag": "INFERENCE",
         "source": "services/billing/client.py:9",
         "note": "gRPC stub `OrderServiceStub` is used here, but no .proto "
                 "declaring it was found in scope", "extractor": "grpc"},
        {"from": "orders-svc", "to": "postgresql-orders", "type": "depends_on",
         "protocol": "sql", "detail": "orders", "evidence_tag": "CODE",
         "source": "services/orders/config.go:12", "extractor": "datastore"},
    ],
    "warnings": [],
}


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="build_graph_model.py",
        description="Merge scan shards into the canonical graph-model.json.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Pass --input once per shard. Use - to read one document from\n"
               "stdin. The merge is order-independent: the same shards in any\n"
               "order produce the same bytes.\n",
    )
    parser.add_argument(
        "--input", action="append", default=[], metavar="PATH",
        help="a scan document or graph model; repeatable, - for stdin")
    parser.add_argument("-o", "--output", help="write the model here")
    parser.add_argument(
        "--evidence-out", metavar="PATH",
        help="also write the evidence report, normally "
             "service-topology/evidence/sources.md")
    parser.add_argument(
        "--output-root", default="service-topology",
        help="containment root; nothing is written outside it (default: "
             "service-topology)")
    parser.add_argument("--indent", type=int, default=2, help="JSON indent (default 2)")
    parser.add_argument(
        "--example", action="store_true",
        help="print an example graph model and exit")
    return parser.parse_args(argv)


def load_document(path: str) -> Dict[str, Any]:
    if path == "-":
        return json.loads(sys.stdin.read())
    with open(Path(path).expanduser(), "r", encoding="utf-8") as handle:
        return json.load(handle)


def graph_payload(document: Dict[str, Any]) -> Dict[str, Any]:
    """Accept a scan document or a bare graph model."""
    if isinstance(document.get("graph"), dict):
        return document["graph"]
    return document


def merge(models: List[GraphModel]) -> GraphModel:
    """Union of nodes and edges. `finalize()` does the deduplication."""
    merged = GraphModel()
    scopes = []  # type: List[str]
    for model in models:
        merged.repo = merged.repo or model.repo
        scopes.extend(model.scope)
        for bucket in (model.services, model.topics, model.external_systems):
            for node in bucket.values():
                merged.add_node(node)
        for edge in model.edges:
            merged.add_edge(edge)
        merged.warnings.extend(model.warnings)
        for key, value in model.stats.items():
            if key.startswith("files"):
                merged.stats[key] = merged.stats.get(key, 0) + int(value or 0)
    merged.scope = tuple(sorted(set(scopes)))
    return merged.finalize()


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)

    if args.example:
        print(json.dumps(EXAMPLE, indent=args.indent))
        return 0
    if not args.input:
        print("error: --input is required (or use --example)", file=sys.stderr)
        return 1

    models = []  # type: List[GraphModel]
    for path in args.input:
        try:
            document = load_document(path)
        except (OSError, IOError) as error:
            print("error: {0}".format(error), file=sys.stderr)
            return 1
        except ValueError as error:
            print("error: {0} is not valid JSON: {1}".format(path, error),
                  file=sys.stderr)
            return 1
        models.append(GraphModel.from_json(graph_payload(document)))

    model = merge(models)
    problems = validate(model)

    payload = model.dumps(indent=args.indent)
    if args.output:
        writer = SafeWriter(user_path(args.output_root))
        try:
            target = writer.write_text(user_path(args.output), payload)
        except OutsideOutputRoot as error:
            print("error: {0}".format(error), file=sys.stderr)
            return 1
        print("wrote {0}".format(target))

        if args.evidence_out:
            try:
                evidence = writer.write_text(
                    user_path(args.evidence_out), render_evidence(model))
            except OutsideOutputRoot as error:
                print("error: {0}".format(error), file=sys.stderr)
                return 1
            print("wrote {0}".format(evidence))
    else:
        sys.stdout.write(payload)

    stats = model.stats
    print("{0} service(s), {1} topic(s), {2} external system(s), {3} edge(s) "
          "([CODE] {4}, [INFERENCE] {5})".format(
              stats.get("services", 0), stats.get("topics", 0),
              stats.get("external_systems", 0), stats.get("edges", 0),
              stats.get("edges_code", 0), stats.get("edges_inference", 0)),
          file=sys.stderr)

    if problems:
        print("\n{0} validation problem(s) - do not render from this model "
              "until they are fixed:".format(len(problems)), file=sys.stderr)
        for problem in problems[:40]:
            print("  {0}".format(problem), file=sys.stderr)
        if len(problems) > 40:
            print("  ... and {0} more".format(len(problems) - 40), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
