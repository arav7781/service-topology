#!/usr/bin/env python3
"""MCP server exposing Topology Cartographer to any MCP-capable host.

The Claude Code skill and the GitHub Copilot skill invoke the scripts in
`skills/topology-cartographer/scripts/` directly. Cursor, VS Code, and
Antigravity reach the same code through this server instead, so no host needs a
skill format it does not understand and no logic is duplicated: this file is
argument handling and JSON-RPC framing over `topology_lib`, nothing more.

Transport
---------
JSON-RPC 2.0 over stdio, one message per line - the MCP stdio transport.
Standard library only, like everything else in this repository. Nothing is
written to stdout except protocol messages; diagnostics go to stderr, because a
stray print on stdout corrupts the stream and the host sees a dead server.

Tools
-----
    scan_repository(path, scope?, output_dir?)
    list_detected_services(graph_model_path)
    generate_master_topology(graph_model_path, output_dir?, theme?)
    generate_micro_topology(graph_model_path, service_name, output_dir?, theme?)

Safety
------
The same posture as the skill: the analysed repository is read-only, and every
write goes through `SafeWriter`, which refuses any path outside the output
directory. A host cannot use this server to edit a repository even if it asks.

Run it
------
    python3 mcp-server/topology_mcp_server.py

Configuration for each host lives beside this file in mcp-server/README.md.
"""

from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

SCRIPTS = (Path(__file__).resolve().parent.parent
           / "skills" / "topology-cartographer" / "scripts")
sys.path.insert(0, str(SCRIPTS))

from topology_lib import VERSION  # noqa: E402
from topology_lib.discovery import scan_repository as walk_repository  # noqa: E402
from topology_lib.extract import build_model  # noqa: E402
from topology_lib.layout import layout_all, layout_diagram  # noqa: E402
from topology_lib.model import (  # noqa: E402
    GraphModel,
    OutsideOutputRoot,
    SafeWriter,
    subgraph_for_service,
    validate,
)
from topology_lib.render import render_drawio, render_evidence, render_mermaid  # noqa: E402
from topology_lib.theme import DEFAULT_THEME, THEME_NAMES  # noqa: E402
from topology_lib.textutil import safe_filename  # noqa: E402

SERVER_NAME = "topology-cartographer"
DEFAULT_OUTPUT_DIRNAME = "service-topology"

# Newest first. The client's requested version is echoed back when we know it.
SUPPORTED_PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")

# JSON-RPC error codes.
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


# --------------------------------------------------------------------------- #
# Tool definitions
# --------------------------------------------------------------------------- #

TOOLS = [
    {
        "name": "scan_repository",
        "description": (
            "Scan a repository for Kafka producer/consumer bindings and "
            "synchronous service-to-service calls, and write graph-model.json "
            "plus an evidence report. Read-only: the analysed repository is "
            "never modified. Every edge carries the file:line it was read from "
            "and a CODE or INFERENCE evidence tag. Run this first - the other "
            "tools all take its graph_model_path."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute path to the repository to scan.",
                },
                "scope": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Optional repository-relative subtrees to restrict the "
                        "scan to, e.g. ['services/orders']. Use this on a large "
                        "monorepo."
                    ),
                },
                "output_dir": {
                    "type": "string",
                    "description": (
                        "Where to write output. Defaults to "
                        "<path>/service-topology. Nothing is ever written "
                        "outside this directory."
                    ),
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "list_detected_services",
        "description": (
            "List the services in a graph model with their edge counts, "
            "language, and where each was declared. Use this to decide which "
            "micro topology is worth generating first - the busiest service is "
            "usually the most informative."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "graph_model_path": {
                    "type": "string",
                    "description": "Path to graph-model.json from scan_repository.",
                },
            },
            "required": ["graph_model_path"],
        },
    },
    {
        "name": "generate_master_topology",
        "description": (
            "Render the whole-system diagram: every service, every Kafka topic, "
            "every producer/consumer edge, every synchronous call, and external "
            "systems as leaf nodes. Writes both a .drawio file and a Mermaid "
            ".mmd fallback. Open the .drawio in VS Code, Cursor, or Antigravity "
            "with the hediet.vscode-drawio extension installed - it renders on "
            "open. The .mmd renders in any Markdown preview with nothing "
            "installed."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "graph_model_path": {
                    "type": "string",
                    "description": "Path to graph-model.json from scan_repository.",
                },
                "output_dir": {
                    "type": "string",
                    "description": (
                        "Where to write. Defaults to the directory the graph "
                        "model is in."
                    ),
                },
                "theme": {
                    "type": "string",
                    "enum": list(THEME_NAMES),
                    "description": (
                        "Shape vocabulary. \"streams\" (default) is the Kafka "
                        "Streams dataflow idiom - circle topic, diamond "
                        "service, cylinder store, off-page external - and "
                        "carries kind by shape rather than fill, so it stays "
                        "readable at several hundred nodes. \"classic\" draws "
                        "label-fitted boxes, which is more compact for a small "
                        "graph."
                    ),
                },
            },
            "required": ["graph_model_path"],
        },
    },
    {
        "name": "generate_micro_topology",
        "description": (
            "Render one service's direct neighbourhood: the topics it produces "
            "and consumes, the services it calls and that call it, and its "
            "datastores - with the label detail needed to review it without "
            "opening the code. A strict subset of the master topology, centred "
            "on one service. Writes both .drawio and .mmd."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "graph_model_path": {
                    "type": "string",
                    "description": "Path to graph-model.json from scan_repository.",
                },
                "service_name": {
                    "type": "string",
                    "description": (
                        "Service id, as reported by list_detected_services."
                    ),
                },
                "output_dir": {
                    "type": "string",
                    "description": (
                        "Where to write. Defaults to the directory the graph "
                        "model is in."
                    ),
                },
                "theme": {
                    "type": "string",
                    "enum": list(THEME_NAMES),
                    "description": (
                        "Shape vocabulary. \"streams\" (default) is the Kafka "
                        "Streams dataflow idiom - circle topic, diamond "
                        "service, cylinder store, off-page external - and "
                        "carries kind by shape rather than fill, so it stays "
                        "readable at several hundred nodes. \"classic\" draws "
                        "label-fitted boxes, which is more compact for a small "
                        "graph."
                    ),
                },
            },
            "required": ["graph_model_path", "service_name"],
        },
    },
]


# --------------------------------------------------------------------------- #
# Tool implementations
# --------------------------------------------------------------------------- #

class ToolError(Exception):
    """A problem the caller can fix by changing its arguments."""


def _load_model(path: str) -> GraphModel:
    resolved = Path(path).expanduser()
    if not resolved.is_file():
        raise ToolError("no graph model at {0} - run scan_repository first".format(path))
    try:
        return GraphModel.load(str(resolved))
    except ValueError as error:
        raise ToolError("{0} is not a valid graph model: {1}".format(path, error))


def _theme(arguments: Dict[str, Any]) -> str:
    """The requested theme, rejecting an unknown name rather than guessing.

    The CLIs get this from `argparse` `choices`; an MCP client can send
    anything, and silently drawing the default when a caller asked for
    something else is the kind of quiet substitution that wastes an hour.
    """
    name = arguments.get("theme") or DEFAULT_THEME
    if name not in THEME_NAMES:
        raise ToolError("unknown theme {0!r}. Known themes: {1}".format(
            name, ", ".join(THEME_NAMES)))
    return str(name)


def _output_root(model_path: str, output_dir: Optional[str]) -> Path:
    if output_dir:
        return Path(output_dir).expanduser()
    return Path(model_path).expanduser().resolve().parent


def _viewing_note(paths: List[str]) -> str:
    return (
        "Open the .drawio file in your editor - the hediet.vscode-drawio "
        "extension renders it automatically on open in VS Code, Cursor, and "
        "Antigravity. If it opens as raw XML, that extension is not installed "
        "yet; .vscode/extensions.json recommends it. GitHub Copilot Chat cannot "
        "display a file itself, but it runs inside VS Code, so the same preview "
        "applies once you open the path. The .mmd file is a Mermaid fallback "
        "that renders in any Markdown preview with nothing installed.\n\n"
        + "\n".join("  " + p for p in paths)
    )


def tool_scan_repository(arguments: Dict[str, Any]) -> Dict[str, Any]:
    path = arguments.get("path")
    if not path:
        raise ToolError("`path` is required")
    repo = Path(path).expanduser()
    if not repo.is_dir():
        raise ToolError("{0} is not a directory".format(path))

    scope = tuple(arguments.get("scope") or ())
    output_dir = arguments.get("output_dir") or str(repo.resolve() / DEFAULT_OUTPUT_DIRNAME)

    scan = walk_repository(str(repo), scope)
    model = build_model(scan)
    model.scope = scope

    writer = SafeWriter(output_dir)
    model_path = writer.write_text("graph-model.json", model.dumps())
    evidence_path = writer.write_text("evidence/sources.md", render_evidence(model))

    problems = validate(model)
    counts = model.edge_count_by_service()
    summary = {
        "repo": str(scan.root),
        "scope": list(scope),
        "files_scanned": len(scan.files),
        "graph_model_path": str(model_path),
        "evidence_path": str(evidence_path),
        "stats": model.stats,
        "services": [
            {
                "id": service_id,
                "language": node.language,
                "path": node.path,
                "edges": counts.get(service_id, 0),
                "declared_at": (node.source_evidence[0]
                                if node.source_evidence else ""),
            }
            for service_id, node in sorted(model.services.items())
        ],
        "validation_problems": problems,
        "warnings": model.warnings[:20],
    }

    lines = [
        "Scanned {0} ({1} files).".format(scan.root, len(scan.files)),
        "",
        "{0} service(s), {1} topic(s), {2} external system(s), {3} edge(s) "
        "- [CODE] {4}, [INFERENCE] {5}.".format(
            model.stats.get("services", 0), model.stats.get("topics", 0),
            model.stats.get("external_systems", 0), model.stats.get("edges", 0),
            model.stats.get("edges_code", 0), model.stats.get("edges_inference", 0)),
        "",
        "Graph model: {0}".format(model_path),
        "Evidence:    {0}".format(evidence_path),
        "",
        "Services (by edge count):",
    ]
    for service in sorted(summary["services"], key=lambda s: (-s["edges"], s["id"])):
        lines.append("  {0:<28} {1:<12} {2} edge(s)  {3}".format(
            service["id"], service["language"] or "-", service["edges"],
            service["declared_at"]))
    if problems:
        lines += ["", "Validation problems ({0}) - do not render until fixed:".format(
            len(problems))]
        lines += ["  " + problem for problem in problems[:10]]
    lines += ["", "Next: generate_master_topology, or generate_micro_topology for "
              "the busiest service."]
    return {"text": "\n".join(lines), "structured": summary}


def tool_list_detected_services(arguments: Dict[str, Any]) -> Dict[str, Any]:
    model = _load_model(arguments.get("graph_model_path") or "")
    counts = model.edge_count_by_service()

    services = []
    for service_id, node in sorted(model.services.items()):
        touching = model.edges_touching(service_id)
        services.append({
            "id": service_id,
            "label": node.display,
            "language": node.language,
            "path": node.path,
            "edges": counts.get(service_id, 0),
            "produces": sorted(set(e.dst for e in touching if e.type == "produces")),
            "consumes": sorted(set(e.src for e in touching if e.type == "consumes")),
            "calls": sorted(set(e.dst for e in touching
                                if e.type in ("calls", "depends_on") and e.src == service_id)),
            "called_by": sorted(set(e.src for e in touching
                                    if e.type == "calls" and e.dst == service_id)),
            "declared_at": node.source_evidence[0] if node.source_evidence else "",
            "origin": dict(node.attributes).get("origin", "declared"),
        })

    lines = ["{0} service(s), busiest first:".format(len(services)), ""]
    for service in sorted(services, key=lambda s: (-s["edges"], s["id"])):
        marker = " (referenced only)" if service["origin"] == "referenced-only" else ""
        lines.append("  {0:<28} {1:>3} edge(s)  produces={2} consumes={3} calls={4}{5}".format(
            service["id"], service["edges"], len(service["produces"]),
            len(service["consumes"]), len(service["calls"]), marker))
    return {"text": "\n".join(lines), "structured": {"services": services}}


def tool_generate_master_topology(arguments: Dict[str, Any]) -> Dict[str, Any]:
    model_path = arguments.get("graph_model_path") or ""
    model = _load_model(model_path)
    if not model.nodes:
        raise ToolError("this graph model has no nodes to draw")

    theme = _theme(arguments)
    root = _output_root(model_path, arguments.get("output_dir"))
    writer = SafeWriter(str(root))
    diagram = layout_diagram(model, "Master topology", theme=theme)

    drawio = writer.write_text("master-topology.drawio",
                               render_drawio(model, diagram, theme=theme))
    mermaid = writer.write_text("master-topology.mmd",
                                render_mermaid(model, "Master topology",
                                               theme=theme))

    inferred = model.inferred_edges()
    text = [
        "Master topology: {0} node(s), {1} edge(s).".format(
            len(model.nodes), len(model.edges)),
    ]
    if inferred:
        text.append(
            "{0} edge(s) are drawn dashed and grey - inferred, not confirmed. "
            "They are listed with reasons in evidence/sources.md.".format(len(inferred)))
    else:
        text.append("Every edge was read directly.")
    text += ["", _viewing_note([str(drawio), str(mermaid)])]

    return {
        "text": "\n".join(text),
        "structured": {
            "drawio_path": str(drawio),
            "mermaid_path": str(mermaid),
            "nodes": len(model.nodes),
            "edges": len(model.edges),
            "inferred_edges": len(inferred),
        },
    }


def tool_generate_micro_topology(arguments: Dict[str, Any]) -> Dict[str, Any]:
    model_path = arguments.get("graph_model_path") or ""
    service = arguments.get("service_name") or ""
    if not service:
        raise ToolError("`service_name` is required")
    model = _load_model(model_path)
    if service not in model.services:
        raise ToolError(
            "no service {0!r} in this model. Known services: {1}".format(
                service, ", ".join(sorted(model.services)) or "(none)"))

    theme = _theme(arguments)
    subgraph = subgraph_for_service(model, service)
    title = "Micro topology - {0}".format(model.services[service].display)
    diagram = layout_diagram(subgraph, title, focus=service, theme=theme)

    root = _output_root(model_path, arguments.get("output_dir"))
    writer = SafeWriter(str(root))
    name = safe_filename(service)
    drawio = writer.write_text(
        "micro/{0}.drawio".format(name),
        render_drawio(subgraph, diagram, include_topic_labels=True, theme=theme))
    mermaid = writer.write_text(
        "micro/{0}.mmd".format(name),
        render_mermaid(subgraph, title, include_topic_labels=True, theme=theme))

    inbound = [e for e in subgraph.edges if e.dst == service]
    outbound = [e for e in subgraph.edges if e.src == service]
    text = [
        "Micro topology for {0}: {1} node(s), {2} edge(s) "
        "({3} inbound, {4} outbound).".format(
            service, len(subgraph.nodes), len(subgraph.edges),
            len(inbound), len(outbound)),
        "A strict subset of the master topology, centred on this service.",
        "",
        _viewing_note([str(drawio), str(mermaid)]),
    ]
    return {
        "text": "\n".join(text),
        "structured": {
            "service": service,
            "drawio_path": str(drawio),
            "mermaid_path": str(mermaid),
            "nodes": len(subgraph.nodes),
            "edges": len(subgraph.edges),
            "inbound_edges": len(inbound),
            "outbound_edges": len(outbound),
        },
    }


HANDLERS = {
    "scan_repository": tool_scan_repository,
    "list_detected_services": tool_list_detected_services,
    "generate_master_topology": tool_generate_master_topology,
    "generate_micro_topology": tool_generate_micro_topology,
}  # type: Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]]


# --------------------------------------------------------------------------- #
# JSON-RPC plumbing
# --------------------------------------------------------------------------- #

def _result(request_id: Any, payload: Dict[str, Any]) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": payload}


def _error(request_id: Any, code: int, message: str) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id,
            "error": {"code": code, "message": message}}


def handle_initialize(params: Dict[str, Any]) -> Dict[str, Any]:
    requested = str(params.get("protocolVersion") or "")
    version = requested if requested in SUPPORTED_PROTOCOLS else SUPPORTED_PROTOCOLS[0]
    return {
        "protocolVersion": version,
        "capabilities": {"tools": {"listChanged": False}},
        "serverInfo": {"name": SERVER_NAME, "version": VERSION},
        "instructions": (
            "Call scan_repository first; every other tool takes the "
            "graph_model_path it returns. Diagrams are written as .drawio "
            "files, which render in VS Code, Cursor, and Antigravity with the "
            "hediet.vscode-drawio extension, plus a .mmd Mermaid fallback that "
            "needs nothing installed. Edges tagged INFERENCE are drawn dashed "
            "and grey and should be confirmed before the diagram is trusted."
        ),
    }


def handle_tools_call(params: Dict[str, Any]) -> Dict[str, Any]:
    name = params.get("name")
    arguments = params.get("arguments") or {}
    if not isinstance(arguments, dict):
        raise ToolError("`arguments` must be an object")
    handler = HANDLERS.get(name)
    if handler is None:
        raise ToolError("unknown tool {0!r}. Available: {1}".format(
            name, ", ".join(sorted(HANDLERS))))

    outcome = handler(arguments)
    return {
        "content": [{"type": "text", "text": outcome["text"]}],
        "structuredContent": outcome.get("structured", {}),
        "isError": False,
    }


def dispatch(message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Return the response, or None for a notification."""
    method = message.get("method")
    request_id = message.get("id")
    params = message.get("params") or {}
    is_notification = "id" not in message

    if method == "initialize":
        return _result(request_id, handle_initialize(params))
    if method in ("notifications/initialized", "initialized"):
        return None
    if method == "ping":
        return _result(request_id, {})
    if method == "tools/list":
        return _result(request_id, {"tools": TOOLS})
    if method == "tools/call":
        try:
            return _result(request_id, handle_tools_call(params))
        except ToolError as error:
            # A tool-level failure is a result, not a protocol error: the model
            # should see the message and fix its arguments.
            return _result(request_id, {
                "content": [{"type": "text", "text": "Error: {0}".format(error)}],
                "isError": True,
            })
        except OutsideOutputRoot as error:
            return _result(request_id, {
                "content": [{"type": "text", "text": "Refused: {0}".format(error)}],
                "isError": True,
            })
        except Exception as error:  # noqa: BLE001 - never kill the server
            traceback.print_exc(file=sys.stderr)
            return _result(request_id, {
                "content": [{"type": "text", "text": "Internal error: {0}: {1}".format(
                    type(error).__name__, error)}],
                "isError": True,
            })
    if method in ("shutdown", "exit"):
        return None if is_notification else _result(request_id, {})

    if is_notification:
        return None
    return _error(request_id, METHOD_NOT_FOUND, "unknown method {0!r}".format(method))


def serve(stdin=None, stdout=None) -> int:
    """Read newline-delimited JSON-RPC from stdin until it closes."""
    source = stdin if stdin is not None else sys.stdin
    sink = stdout if stdout is not None else sys.stdout

    for line in source:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except ValueError:
            _write(sink, _error(None, PARSE_ERROR, "invalid JSON"))
            continue
        if not isinstance(message, dict):
            _write(sink, _error(None, INVALID_REQUEST, "expected a JSON-RPC object"))
            continue

        try:
            response = dispatch(message)
        except Exception as error:  # noqa: BLE001 - a crash here kills the session
            traceback.print_exc(file=sys.stderr)
            response = _error(message.get("id"), INTERNAL_ERROR,
                              "{0}: {1}".format(type(error).__name__, error))
        if response is not None:
            _write(sink, response)
    return 0


def _write(sink, payload: Dict[str, Any]) -> None:
    sink.write(json.dumps(payload) + "\n")
    sink.flush()


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--help" in argv or "-h" in argv:
        sys.stdout.write(__doc__ or "")
        return 0
    if "--list-tools" in argv:
        # A self-check that needs no MCP client: prove the schemas are valid
        # JSON and the tool set is what the README says it is.
        print(json.dumps({"tools": [
            {"name": tool["name"],
             "required": tool["inputSchema"].get("required", [])}
            for tool in TOOLS]}, indent=2))
        return 0
    if "--version" in argv:
        print("{0} {1}".format(SERVER_NAME, VERSION))
        return 0
    return serve()


if __name__ == "__main__":
    sys.exit(main())
