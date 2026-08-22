# Topology Cartographer MCP server

The universal compatibility layer. Claude Code and GitHub Copilot run
topology-cartographer as a skill; Cursor, VS Code, and Antigravity reach the
same code through this server, so no host needs a skill format it does not
understand and no extraction logic exists twice.

[`topology_mcp_server.py`](topology_mcp_server.py) is argument handling and
JSON-RPC framing over `skills/topology-cartographer/scripts/topology_lib/`. It
is standard library only, like everything else in this project, and speaks
JSON-RPC 2.0 over stdio - one message per line, the MCP stdio transport.

## Tools

| Tool | Arguments | Returns |
|---|---|---|
| `scan_repository` | `path`, `scope?`, `output_dir?` | Service list with edge counts, the `[CODE]`/`[INFERENCE]` split, and the path to `graph-model.json`. Run this first. |
| `list_detected_services` | `graph_model_path` | Every service with its edge count, produced and consumed topics, and where it was declared. Use it to pick which micro topology to generate. |
| `generate_master_topology` | `graph_model_path`, `output_dir?` | Paths to `master-topology.drawio` and `master-topology.mmd`. |
| `generate_micro_topology` | `graph_model_path`, `service_name`, `output_dir?` | Paths to `micro/<service>.drawio` and `.mmd`. |

Every reply that writes a diagram also says how to view it - the extension name,
and the Mermaid fallback for surfaces with no file view. That sentence exists
because "where is my diagram?" is the most common question this tool produces.

## Safety

Identical to the skill's posture, enforced in code rather than in prose:

- the analysed repository is **read-only** - nothing here writes to it;
- every write goes through `SafeWriter`, which resolves symlinks and `..` and
  refuses any path outside the output directory;
- a tool failure is returned as an MCP tool error with a readable message, never
  as a crash - the host stays connected and the model can correct itself;
- nothing is executed in the analysed repository: no build, no test suite, no
  container, no broker or database connection.

## Configuring a host

This repository ships a working registration for each host, pointing at the
server through `${workspaceFolder}`:

| Host | File in this repository |
|---|---|
| VS Code, and GitHub Copilot Chat inside it | [`.vscode/mcp.json`](../.vscode/mcp.json) |
| Cursor | [`.cursor/mcp.json`](../.cursor/mcp.json) |
| Antigravity | [`.agents/mcp_config.json`](../.agents/mcp_config.json) |

Antigravity also reads a global config at `~/.gemini/config/mcp_config.json`,
which the IDE, the `agy` CLI, and the SDK share; the workspace file above
overrides it per project.

### Using it from another repository

Copy the block into the equivalent file in the repository you want to map, and
replace `${workspaceFolder}` with an absolute path to this checkout - the
placeholder expands to the *open* workspace, which will be the other repository:

```json
{
  "mcpServers": {
    "topology-cartographer": {
      "command": "python3",
      "args": ["/ABSOLUTE/PATH/TO/service-topology/mcp-server/topology_mcp_server.py"]
    }
  }
}
```

VS Code uses `"servers"` rather than `"mcpServers"` and takes a `"type": "stdio"`
field; the other two use the shape above. Reload the window after editing, then
ask the assistant to scan the repository - it will call `scan_repository` itself.

## Checking it works

Two self-checks, neither needing a host:

```bash
# schemas are well formed and the tool set is what this README says
python3 mcp-server/topology_mcp_server.py --list-tools

# a real MCP client: spawns the server, speaks JSON-RPC over its stdio, and
# exercises every tool against examples/fixture-mesh
python3 mcp-server/test_client.py
```

[`test_client.py`](test_client.py) is an integration test, not a mock. It runs
`initialize`, `notifications/initialized`, `tools/list`, then all four tools in
the order a host would, and checks the artefacts landed on disk, that the micro
topology is smaller than the master, that an unknown service is reported as a
tool error rather than a crash, and that the server logged no tracebacks. CI
runs it on every push.

## Troubleshooting

<details>
<summary>The host shows the server as failed or disconnected</summary>

Run it by hand - `python3 mcp-server/topology_mcp_server.py --version`. If that
works, the problem is the path in your config: `${workspaceFolder}` only expands
to this checkout when *this* repository is the open workspace. Use an absolute
path otherwise.

Check that `python3` is on the host's `PATH`, which is not always the shell's
`PATH`. Give the full interpreter path if in doubt.
</details>

<details>
<summary>The tools are not offered to the model</summary>

Reload the window after editing the config; most hosts read it once at startup.
Then confirm the server is listed in the host's MCP panel and that its tools are
enabled - several hosts let you disable individual tools per server.
</details>

<details>
<summary>`scan_repository` returns no services</summary>

The repository has no recognised manifests at the paths scanned. Pass `scope`
with the directories the services actually live in, and see
[`service-boundary-heuristics.md`](../skills/topology-cartographer/references/service-boundary-heuristics.md).
</details>

<details>
<summary>A write was refused</summary>

`SafeWriter` refused a path outside the output directory. That is the containment
rule working. Pass an `output_dir` you want written to; do not try to write into
the analysed repository's source tree.
</details>
