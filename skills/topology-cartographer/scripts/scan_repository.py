#!/usr/bin/env python3
"""Extract Kafka bindings and service-to-service calls from a repository.

Part of the Topology Cartographer skill (Phase 1: extraction).

Walks a repository read-only, discovers service boundaries, indexes the config
that topic names and base URLs actually live in, and records every producer,
consumer, and synchronous call it can trace to a `path/to/file:LINE`. Nothing
is written to the analysed repository - output goes to stdout or to `--output`.

What is covered
---------------
    Kafka   Spring Kafka, Kafka Streams, the plain Java client, kafka-python,
            confluent-kafka, aiokafka, faust, kafkajs, node-rdkafka, NestJS,
            segmentio/kafka-go, sarama, and Spring Cloud Stream bindings
    Sync    OpenAPI/Swagger specs, .proto services and generated stubs,
            requests/httpx, axios/fetch, RestTemplate/WebClient/Feign,
            net/http, resty
    Config  application.yml/.properties, .env, docker-compose, Helm values,
            Terraform topic resources

Every fact is tagged `[CODE]` or `[INFERENCE]`; see
references/evidence-classification.md. A call whose target cannot be resolved
is dropped, not guessed at.

Usage
-----
    python3 scan_repository.py /path/to/repo
    python3 scan_repository.py /path/to/repo -o scan.json
    python3 scan_repository.py /path/to/repo --scope services/orders,services/billing
    python3 scan_repository.py /path/to/repo --format summary
    python3 scan_repository.py --example

Sharding a monorepo
-------------------
Run once per subtree with `--scope`, then merge the shards:

    python3 scan_repository.py . --scope services/orders  -o orders.json
    python3 scan_repository.py . --scope services/billing -o billing.json
    python3 build_graph_model.py --input orders.json --input billing.json \
        -o service-topology/graph-model.json

Exit codes
----------
    0  scan completed
    1  bad arguments, or the path is not a readable directory
    2  scan completed but found no services at all
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
from topology_lib.discovery import scan_repository  # noqa: E402
from topology_lib.extract import build_model  # noqa: E402

SCHEMA = "topology-cartographer/scan"
SCHEMA_VERSION = "1.0.0"

EXAMPLE = {
    "schema": SCHEMA,
    "schema_version": SCHEMA_VERSION,
    "scanner_version": VERSION,
    "repo": "/home/dev/acme-platform",
    "scope": [],
    "discovery": {
        "files_scanned": 34,
        "services": [
            {"id": "orders-svc", "label": "orders-svc", "path": "services/orders",
             "language": "go", "evidence": "services/orders/go.mod:1", "files": 9},
        ],
        "config_index": {"config_keys": 12, "env_vars": 6, "declared_topics": 1,
                         "service_hosts": 4, "infrastructure_containers": 2},
    },
    "graph": {
        "schema": "topology-cartographer/graph-model",
        "schema_version": "1.0.0",
        "services": [{"id": "orders-svc", "kind": "service",
                      "source_evidence": ["services/orders/go.mod:1"]}],
        "topics": [{"id": "orders.created", "kind": "topic",
                    "source_evidence": ["services/orders/kafka/producer.go:42"]}],
        "external_systems": [],
        "edges": [
            {"from": "orders-svc", "to": "orders.created", "type": "produces",
             "protocol": "kafka", "detail": "key=order_id", "evidence_tag": "CODE",
             "source": "services/orders/kafka/producer.go:42",
             "extractor": "kafka-go"},
        ],
    },
}


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="scan_repository.py",
        description="Extract Kafka and service-call topology facts from a repository.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="The analysed repository is never modified. Output is a scan\n"
               "document; feed it to build_graph_model.py to produce\n"
               "graph-model.json.\n",
    )
    parser.add_argument("repo", nargs="?", help="path to the repository to scan")
    parser.add_argument("-o", "--output", help="write to this file instead of stdout")
    parser.add_argument(
        "--scope",
        help="comma-separated subtrees to restrict the scan to, "
             "e.g. services/orders,services/billing")
    parser.add_argument(
        "--format", choices=("json", "summary"), default="json",
        help="json (default) for the machine-readable scan document, "
             "summary for a short human-readable report")
    parser.add_argument("--indent", type=int, default=2, help="JSON indent (default 2)")
    parser.add_argument(
        "--example", action="store_true",
        help="print an example scan document and exit")
    return parser.parse_args(argv)


def summarise(document: Dict[str, Any]) -> str:
    graph = document["graph"]
    stats = graph.get("stats", {})
    lines = [
        "Repository: {0}".format(document["repo"]),
        "Files scanned: {0}".format(document["discovery"]["files_scanned"]),
        "",
        "Services ........... {0}".format(stats.get("services", 0)),
        "Topics ............. {0}".format(stats.get("topics", 0)),
        "External systems ... {0}".format(stats.get("external_systems", 0)),
        "Edges .............. {0}  ([CODE] {1}, [INFERENCE] {2})".format(
            stats.get("edges", 0), stats.get("edges_code", 0),
            stats.get("edges_inference", 0)),
        "",
        "Services found:",
    ]
    for service in document["discovery"]["services"]:
        lines.append("  {0:<28} {1:<12} {2}".format(
            service["id"], service["language"] or "-", service["evidence"]))

    warnings = graph.get("warnings") or []
    if warnings:
        lines.extend(["", "Warnings ({0}):".format(len(warnings))])
        for warning in warnings[:20]:
            lines.append("  - {0}".format(warning))
        if len(warnings) > 20:
            lines.append("  ... and {0} more".format(len(warnings) - 20))
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)

    if args.example:
        print(json.dumps(EXAMPLE, indent=args.indent))
        return 0
    if not args.repo:
        print("error: a repository path is required (or use --example)",
              file=sys.stderr)
        return 1

    root = Path(args.repo).expanduser()
    if not root.is_dir():
        print("error: {0} is not a directory".format(root), file=sys.stderr)
        return 1

    scope = tuple(part.strip() for part in (args.scope or "").split(",") if part.strip())

    scan = scan_repository(str(root), scope)
    model = build_model(scan)
    model.scope = scope

    document = {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "scanner_version": VERSION,
        "repo": str(scan.root),
        "scope": list(scope),
        "discovery": {
            "files_scanned": len(scan.files),
            "services": [
                {
                    "id": service.id,
                    "label": service.label,
                    "path": service.rel,
                    "language": service.language,
                    "evidence": service.evidence,
                    "files": service.files,
                }
                for service in scan.services.values()
            ],
            "config_index": scan.config.summary(),
        },
        "graph": model.to_json(),
    }

    if args.format == "summary":
        payload = summarise(document) + "\n"
    else:
        payload = json.dumps(document, indent=args.indent, ensure_ascii=False) + "\n"

    if args.output:
        target = Path(args.output).expanduser()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(payload, encoding="utf-8")
        print("wrote {0}".format(target))
    else:
        sys.stdout.write(payload)

    if not scan.services:
        print("\nwarning: no services were discovered - check --scope, or the "
              "repository may have no recognised manifests", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
