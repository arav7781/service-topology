#!/usr/bin/env python3
"""Compute deterministic node and edge placement for every diagram.

Part of the Topology Cartographer skill (Phase 3: layout).

The model never hand-computes coordinates, exactly as it never hand-computes a
candidate score in contributor-scout. This script owns the arithmetic: it reads
graph-model.json, lays out the master topology plus one micro topology per
service, and writes the same model back with a `layout` block added. Pass
`--no-master` to lay out only the micro topologies - what gets laid out here is
what gets rendered later, so a mode that asked for one service stops here.

Layout is a plain layered DAG placement implemented in the standard library -
no graphviz, no external engine. Cycles are broken by a depth-first search over
ids in sorted order, so the same back edges are chosen on every run and the
same input always produces the same coordinates.

Usage
-----
    python3 layout_graph.py service-topology/graph-model.json \
        -o service-topology/graph-model.laid-out.json
    python3 layout_graph.py graph-model.json --service orders-svc --format summary
    python3 layout_graph.py graph-model.json --service orders-svc --no-master \
        -o service-topology/graph-model.laid-out.json
    python3 layout_graph.py --example

Exit codes
----------
    0  layout written
    1  bad arguments or unreadable input
    2  the model has no nodes to lay out
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from topology_lib.layout import LAYOUT_VERSION, layout_all  # noqa: E402
from topology_lib.theme import DEFAULT_THEME, THEME_NAMES  # noqa: E402
from topology_lib.model import (  # noqa: E402
    GraphModel,
    OutsideOutputRoot,
    SafeWriter,
    user_path,
)

EXAMPLE = {
    "layout_version": LAYOUT_VERSION,
    "diagrams": {
        "master": {
            "title": "Master topology",
            "focus": None,
            "width": 940,
            "height": 320,
            "nodes": {
                "orders-svc": {"x": 40, "y": 40, "width": 160, "height": 50,
                               "layer": 0, "order": 0},
                "orders.created": {"x": 320, "y": 40, "width": 176, "height": 50,
                                   "layer": 1, "order": 0},
                "billing-svc": {"x": 616, "y": 40, "width": 160, "height": 50,
                                "layer": 2, "order": 0},
            },
            "edges": [
                {"index": 0, "from": "orders-svc", "to": "orders.created",
                 "waypoints": [], "label_x": 0.0},
                {"index": 1, "from": "orders.created", "to": "billing-svc",
                 "waypoints": [], "label_x": 0.0},
            ],
            "edge_count": 2,
        },
    },
}


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="layout_graph.py",
        description="Add deterministic diagram coordinates to a graph model.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Output is graph-model.laid-out.json: the same model with a\n"
               "`layout` block. render_drawio.py and render_mermaid.py read it.\n",
    )
    parser.add_argument("model", nargs="?", help="path to graph-model.json")
    parser.add_argument("-o", "--output", help="write the laid-out model here")
    parser.add_argument(
        "--service", action="append", default=[], metavar="NAME",
        help="lay out micro topologies for these services only; repeatable "
             "(default: every service)")
    parser.add_argument(
        "--no-master", action="store_true",
        help="lay out the micro topologies only. Someone who asked for one "
             "service's topology asked for one diagram")
    parser.add_argument(
        "--theme", choices=THEME_NAMES, default=DEFAULT_THEME,
        help="shape and spacing vocabulary; a theme fixes node sizes, so it "
             "is chosen here and stamped into the layout block for the "
             "renderers to follow (default: {0})".format(DEFAULT_THEME))
    parser.add_argument(
        "--format", choices=("json", "summary"), default="json",
        help="json (default) or a short per-diagram summary")
    parser.add_argument(
        "--output-root", default="service-topology",
        help="containment root; nothing is written outside it")
    parser.add_argument("--indent", type=int, default=2, help="JSON indent (default 2)")
    parser.add_argument(
        "--example", action="store_true",
        help="print an example layout block and exit")
    return parser.parse_args(argv)


def summarise(layout: Dict[str, Any]) -> str:
    lines = ["{0:<34} {1:>7} {2:>7} {3:>7} {4:>7}".format(
        "diagram", "nodes", "edges", "width", "height")]
    lines.append("-" * 66)
    for key in sorted(layout["diagrams"]):
        diagram = layout["diagrams"][key]
        lines.append("{0:<34} {1:>7} {2:>7} {3:>7} {4:>7}".format(
            key, len(diagram["nodes"]), diagram["edge_count"],
            diagram["width"], diagram["height"]))
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)

    if args.example:
        print(json.dumps(EXAMPLE, indent=args.indent))
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

    if not model.nodes:
        print("error: the model has no nodes to lay out", file=sys.stderr)
        return 2

    model.layout = layout_all(model, args.service or None, theme=args.theme,
                              include_master=not args.no_master)

    if args.format == "summary":
        payload = summarise(model.layout) + "\n"
    else:
        payload = model.dumps(indent=args.indent)

    if args.output:
        writer = SafeWriter(user_path(args.output_root))
        try:
            target = writer.write_text(user_path(args.output), payload)
        except OutsideOutputRoot as error:
            print("error: {0}".format(error), file=sys.stderr)
            return 1
        print("wrote {0} ({1} diagram(s), {2} theme)".format(
            target, len(model.layout["diagrams"]), args.theme))
    else:
        sys.stdout.write(payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
