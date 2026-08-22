#!/usr/bin/env python3
"""Drive the Topology Cartographer MCP server end to end, over real stdio.

An MCP client, not a mock: it spawns `topology_mcp_server.py` as a subprocess,
speaks JSON-RPC 2.0 over its stdin and stdout, and exercises every tool in the
order a host would - initialize, notifications/initialized, tools/list, then
each of the four tools. That is what makes it a genuine integration check
rather than four function calls dressed up as one.

Standard library only, so it runs in CI with nothing installed.

Usage
-----
    python3 mcp-server/test_client.py
    python3 mcp-server/test_client.py --repo examples/fixture-mesh
    python3 mcp-server/test_client.py --keep-output   # leave the artefacts

Exit codes
----------
    0  every check passed
    1  bad arguments
    2  a check failed
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
SERVER = HERE / "topology_mcp_server.py"
DEFAULT_REPO = REPO_ROOT / "examples" / "fixture-mesh"

PROTOCOL_VERSION = "2025-06-18"


class Client(object):
    """The smallest thing that can honestly be called an MCP client."""

    def __init__(self, command: List[str]) -> None:
        self.process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            bufsize=1,
        )
        self.counter = 0

    def request(self, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        self.counter += 1
        message = {"jsonrpc": "2.0", "id": self.counter, "method": method}
        if params is not None:
            message["params"] = params
        self._send(message)
        return self._receive(self.counter)

    def notify(self, method: str, params: Optional[Dict[str, Any]] = None) -> None:
        message = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        self._send(message)

    def call_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        return self.request("tools/call", {"name": name, "arguments": arguments})

    def _send(self, message: Dict[str, Any]) -> None:
        assert self.process.stdin is not None
        self.process.stdin.write(json.dumps(message) + "\n")
        self.process.stdin.flush()

    def _receive(self, expect_id: int) -> Dict[str, Any]:
        assert self.process.stdout is not None
        while True:
            line = self.process.stdout.readline()
            if not line:
                stderr = self.process.stderr.read() if self.process.stderr else ""
                raise RuntimeError(
                    "server closed the stream before answering id {0}\n{1}".format(
                        expect_id, stderr))
            line = line.strip()
            if not line:
                continue
            message = json.loads(line)
            if message.get("id") == expect_id:
                return message

    def close(self) -> str:
        if self.process.stdin:
            self.process.stdin.close()
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:  # pragma: no cover - defensive
            self.process.kill()
        return self.process.stderr.read() if self.process.stderr else ""


class Checks(object):
    def __init__(self) -> None:
        self.failures = []  # type: List[str]

    def ok(self, condition: bool, description: str, detail: str = "") -> None:
        if condition:
            print("  pass  {0}".format(description))
        else:
            print("  FAIL  {0}{1}".format(description, ": " + detail if detail else ""))
            self.failures.append(description)


def text_of(response: Dict[str, Any]) -> str:
    result = response.get("result") or {}
    return "\n".join(block.get("text", "")
                     for block in result.get("content", [])
                     if block.get("type") == "text")


def structured_of(response: Dict[str, Any]) -> Dict[str, Any]:
    return (response.get("result") or {}).get("structuredContent") or {}


def run(repo: Path, output_dir: Path, checks: Checks) -> None:
    client = Client([sys.executable, str(SERVER)])

    print("\ninitialize")
    response = client.request("initialize", {
        "protocolVersion": PROTOCOL_VERSION,
        "capabilities": {},
        "clientInfo": {"name": "topology-cartographer-test-client", "version": "1.0.0"},
    })
    result = response.get("result") or {}
    checks.ok(response.get("jsonrpc") == "2.0", "response is JSON-RPC 2.0")
    checks.ok(result.get("protocolVersion") == PROTOCOL_VERSION,
              "server echoes the requested protocol version",
              str(result.get("protocolVersion")))
    checks.ok("tools" in (result.get("capabilities") or {}),
              "server advertises tool capability")
    checks.ok((result.get("serverInfo") or {}).get("name") == "topology-cartographer",
              "serverInfo names the server")

    client.notify("notifications/initialized")

    print("\ntools/list")
    response = client.request("tools/list")
    tools = (response.get("result") or {}).get("tools") or []
    names = sorted(tool["name"] for tool in tools)
    expected = sorted(["scan_repository", "list_detected_services",
                       "generate_master_topology", "generate_micro_topology"])
    checks.ok(names == expected, "all four tools are advertised", str(names))
    checks.ok(all(tool.get("inputSchema", {}).get("type") == "object" for tool in tools),
              "every tool has an object inputSchema")
    checks.ok(all(tool.get("description") for tool in tools),
              "every tool has a description")

    print("\ntools/call scan_repository")
    response = client.call_tool("scan_repository", {
        "path": str(repo), "output_dir": str(output_dir)})
    checks.ok(not (response.get("result") or {}).get("isError"),
              "scan_repository succeeded", text_of(response)[:300])
    scan = structured_of(response)
    model_path = scan.get("graph_model_path", "")
    checks.ok(bool(model_path) and Path(model_path).is_file(),
              "graph-model.json was written", model_path)
    checks.ok(Path(scan.get("evidence_path", "")).is_file(),
              "evidence/sources.md was written")
    checks.ok(scan.get("stats", {}).get("services", 0) >= 3,
              "at least three services were found",
              str(scan.get("stats")))
    checks.ok(not scan.get("validation_problems"),
              "the model validates", str(scan.get("validation_problems"))[:300])

    print("\ntools/call list_detected_services")
    response = client.call_tool("list_detected_services",
                                {"graph_model_path": model_path})
    services = structured_of(response).get("services") or []
    checks.ok(len(services) >= 3, "services are listed with edge counts",
              str(len(services)))
    checks.ok(all("edges" in service and "declared_at" in service
                  for service in services),
              "every listed service reports its edge count and where it was declared")

    print("\ntools/call generate_master_topology")
    response = client.call_tool("generate_master_topology",
                                {"graph_model_path": model_path})
    master = structured_of(response)
    checks.ok(not (response.get("result") or {}).get("isError"),
              "generate_master_topology succeeded", text_of(response)[:300])
    checks.ok(Path(master.get("drawio_path", "")).is_file(), "master .drawio written")
    checks.ok(Path(master.get("mermaid_path", "")).is_file(), "master .mmd written")
    checks.ok("hediet.vscode-drawio" in text_of(response),
              "the reply tells the user how to view it")

    busiest = sorted(services, key=lambda s: (-s["edges"], s["id"]))[0]["id"]
    print("\ntools/call generate_micro_topology ({0})".format(busiest))
    response = client.call_tool("generate_micro_topology", {
        "graph_model_path": model_path, "service_name": busiest})
    micro = structured_of(response)
    checks.ok(not (response.get("result") or {}).get("isError"),
              "generate_micro_topology succeeded", text_of(response)[:300])
    checks.ok(Path(micro.get("drawio_path", "")).is_file(), "micro .drawio written")
    checks.ok(0 < micro.get("nodes", 0) < master.get("nodes", 0) + 1,
              "micro topology is no larger than the master")
    checks.ok(micro.get("edges", 0) < master.get("edges", 0),
              "micro topology has fewer edges than the master",
              "{0} vs {1}".format(micro.get("edges"), master.get("edges")))

    print("\nerror handling")
    response = client.call_tool("generate_micro_topology", {
        "graph_model_path": model_path, "service_name": "no-such-service"})
    result = response.get("result") or {}
    checks.ok(result.get("isError") is True,
              "an unknown service is reported as a tool error, not a crash")
    checks.ok("no-such-service" in text_of(response),
              "the error names what was wrong")

    response = client.call_tool("no_such_tool", {})
    checks.ok((response.get("result") or {}).get("isError") is True,
              "an unknown tool is reported as a tool error")

    response = client.request("no/such/method")
    checks.ok(response.get("error", {}).get("code") == -32601,
              "an unknown method returns JSON-RPC method-not-found")

    print("\ncontainment")
    response = client.call_tool("generate_master_topology", {
        "graph_model_path": model_path,
        "output_dir": str(output_dir / "nested"),
    })
    checks.ok(not (response.get("result") or {}).get("isError"),
              "a nested output directory is allowed")

    stderr = client.close()
    checks.ok("Traceback" not in stderr,
              "the server logged no tracebacks", stderr[-400:])


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="test_client.py",
        description="Exercise the Topology Cartographer MCP server over real stdio.")
    parser.add_argument("--repo", default=str(DEFAULT_REPO),
                        help="repository to scan (default: examples/fixture-mesh)")
    parser.add_argument("--output-dir",
                        help="where the server should write (default: a temp dir)")
    parser.add_argument("--keep-output", action="store_true",
                        help="do not delete the temp output directory")
    args = parser.parse_args(argv)

    repo = Path(args.repo).expanduser()
    if not repo.is_dir():
        print("error: {0} is not a directory".format(repo), file=sys.stderr)
        return 1
    if not SERVER.is_file():
        print("error: server not found at {0}".format(SERVER), file=sys.stderr)
        return 1

    temporary = args.output_dir is None
    output_dir = Path(args.output_dir) if args.output_dir else Path(
        tempfile.mkdtemp(prefix="topology-mcp-"))

    print("server: {0}".format(SERVER))
    print("repo:   {0}".format(repo))
    print("output: {0}".format(output_dir))

    checks = Checks()
    try:
        run(repo, output_dir, checks)
    finally:
        if temporary and not args.keep_output:
            shutil.rmtree(str(output_dir), ignore_errors=True)

    print("")
    if checks.failures:
        print("{0} check(s) failed:".format(len(checks.failures)))
        for failure in checks.failures:
            print("  - {0}".format(failure))
        return 2
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
