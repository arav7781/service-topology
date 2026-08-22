#!/usr/bin/env python3
"""Render a laid-out graph model as a valid mxGraph (.drawio) document.

Part of the Topology Cartographer skill (Phase 4: render).

The model never hand-writes mxGraph XML. It produces graph-model.json; this
script turns that into the diagram. XML is built with `xml.etree.ElementTree`
rather than string formatting, so a service called `Orders & Billing <v2>`
cannot produce a file draw.io refuses to open.

What the styles mean
--------------------
    rounded blue box    service
    orange hexagon      Kafka topic
    grey dashed hexagon topic whose name is an unresolved config reference
    green cylinder      datastore
    purple cylinder     cache
    grey cloud          external API
    solid arrow         [CODE] - read directly
    dashed grey arrow   [INFERENCE]/[UNVERIFIED] - not confirmed

Every node and edge is emitted as a `UserObject`, so the `path/to/file:LINE`
that justifies it travels inside the diagram: select any arrow in draw.io and
`Edit > Edit Data` shows its source location and, for an inference, the reason
it is not confirmed.

Usage
-----
    python3 render_drawio.py service-topology/graph-model.laid-out.json \
        --mode master -o service-topology/master-topology.drawio
    python3 render_drawio.py service-topology/graph-model.laid-out.json \
        --mode micro --service orders-svc \
        -o service-topology/micro/orders-svc.drawio
    python3 render_drawio.py graph-model.laid-out.json --mode all \
        --output-dir service-topology
    python3 render_drawio.py --example

Open the result directly in VS Code, Cursor, or Antigravity with the
hediet.vscode-drawio extension installed; it renders .drawio files on open.

Exit codes
----------
    0  diagram(s) written
    1  bad arguments or unreadable input
    2  the model has no layout block, or the named service is not in it
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from topology_lib.layout import layout_all  # noqa: E402
from topology_lib.model import (  # noqa: E402
    GraphModel,
    OutsideOutputRoot,
    SafeWriter,
    subgraph_for_service,
    user_path,
)
from topology_lib.render import render_drawio  # noqa: E402
from topology_lib.textutil import safe_filename  # noqa: E402

EXAMPLE = """\
<mxfile host="topology-cartographer" agent="topology-cartographer/1.0.0" \
version="24.7.17" type="device">
  <diagram id="8f14e45fceea167a5a36" name="Master topology">
    <mxGraphModel dx="940" dy="600" grid="1" gridSize="10" guides="1" \
tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" \
pageWidth="1169" pageHeight="826" math="0" shadow="0">
      <root>
        <mxCell id="0" />
        <mxCell id="1" parent="0" />
        <UserObject label="orders-svc" tooltip="services/orders/go.mod:1" \
topologyKind="service" topologyId="orders-svc" \
sourceEvidence="services/orders/go.mod:1" id="node-0">
          <mxCell style="rounded=1;whiteSpace=wrap;html=1;fillColor=#dae8fc;\
strokeColor=#6c8ebf;" vertex="1" parent="1">
            <mxGeometry x="40" y="40" width="160" height="50" as="geometry" />
          </mxCell>
        </UserObject>
        <UserObject label="key=order_id" \
tooltip="services/orders/kafka/producer.go:42" evidenceTag="CODE" \
sourceLocation="services/orders/kafka/producer.go:42" edgeType="produces" \
id="edge-0">
          <mxCell style="edgeStyle=orthogonalEdgeStyle;html=1;\
strokeColor=#d79b00;" edge="1" parent="1" source="node-0" target="node-1">
            <mxGeometry relative="1" as="geometry" />
          </mxCell>
        </UserObject>
      </root>
    </mxGraphModel>
  </diagram>
</mxfile>
"""


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="render_drawio.py",
        description="Render a laid-out graph model as mxGraph .drawio XML.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="If the model has no `layout` block, one is computed on the fly,\n"
               "so render_drawio.py can be run straight after build_graph_model.py.\n",
    )
    parser.add_argument("model", nargs="?", help="path to graph-model.laid-out.json")
    parser.add_argument(
        "--mode", choices=("master", "micro", "all"), default="master",
        help="master (default), micro (needs --service), or all")
    parser.add_argument("--service", help="service id, required for --mode micro")
    parser.add_argument("-o", "--output", help="output file for master/micro mode")
    parser.add_argument(
        "--output-dir", default="service-topology",
        help="directory for --mode all (default: service-topology)")
    parser.add_argument(
        "--output-root", default="service-topology",
        help="containment root; nothing is written outside it")
    parser.add_argument(
        "--no-legend", action="store_true",
        help="omit the evidence legend box from the diagram")
    parser.add_argument(
        "--example", action="store_true",
        help="print an abbreviated example .drawio document and exit")
    return parser.parse_args(argv)


def ensure_layout(model: GraphModel) -> Dict[str, Any]:
    if not model.layout or not model.layout.get("diagrams"):
        model.layout = layout_all(model)
    return model.layout["diagrams"]


def render_one(model: GraphModel, diagrams: Dict[str, Any], key: str,
               no_legend: bool) -> Optional[str]:
    diagram = diagrams.get(key)
    if diagram is None:
        return None
    focus = diagram.get("focus")
    if focus:
        # The subgraph is derived deterministically, so it matches the layout
        # that was computed from the same model - edge indices line up.
        target_model = subgraph_for_service(model, focus)
    else:
        target_model = model
    return render_drawio(target_model, diagram,
                         include_topic_labels=bool(focus),
                         include_legend=not no_legend)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)

    if args.example:
        sys.stdout.write(EXAMPLE)
        return 0
    if not args.model:
        print("error: a graph model path is required (or use --example)",
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

    diagrams = ensure_layout(model)
    writer = SafeWriter(user_path(args.output_root))

    try:
        if args.mode == "all":
            written = 0
            for key in sorted(diagrams):
                xml = render_one(model, diagrams, key, args.no_legend)
                if xml is None:
                    continue
                if key == "master":
                    relative = "master-topology.drawio"
                else:
                    relative = "micro/{0}.drawio".format(
                        safe_filename(key.split("/", 1)[1]))
                target = writer.write_text(
                    user_path(str(Path(args.output_dir) / relative)), xml)
                print("wrote {0}".format(target))
                written += 1
            if not written:
                print("error: nothing to render", file=sys.stderr)
                return 2
            return 0

        if args.mode == "micro":
            if not args.service:
                print("error: --mode micro requires --service", file=sys.stderr)
                return 1
            key = "micro/{0}".format(args.service)
            if key not in diagrams:
                available = sorted(
                    name.split("/", 1)[1] for name in diagrams if name != "master")
                print("error: no micro topology for {0!r}. Known services: {1}".format(
                    args.service, ", ".join(available) or "(none)"), file=sys.stderr)
                return 2
            default_name = "micro/{0}.drawio".format(safe_filename(args.service))
        else:
            key = "master"
            default_name = "master-topology.drawio"

        xml = render_one(model, diagrams, key, args.no_legend)
        if xml is None:
            print("error: the model has no {0} diagram".format(key), file=sys.stderr)
            return 2

        if args.output:
            target = writer.write_text(user_path(args.output), xml)
            print("wrote {0}".format(target))
        else:
            sys.stdout.write(xml)
            print("(pass -o {0} to write a file)".format(default_name),
                  file=sys.stderr)
    except OutsideOutputRoot as error:
        print("error: {0}".format(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
