# Security Policy

Topology Cartographer reads untrusted repositories by design, and it ships an
optional enforcement hook. If you find a security problem in this project,
please report it privately first.

## Supported versions

| Version | Supported |
|---|---|
| Latest release / `main` | ✅ |
| Anything older | ❌ — please reproduce on `main` |

## What counts as a vulnerability here

This is a set of prompts, Markdown playbooks, standard-library Python scripts,
an optional enforcement hook, and an MCP server. Its interesting attack
surface is unusual but real:

- **`SafeWriter` bypass.** Any path that resolves outside the declared output
  root (`service-topology/` by default) and still gets written — via symlink,
  `..` traversal, or a crafted `output_dir`/`output_root` argument — in any of
  `build_graph_model.py`, `layout_graph.py`, `render_drawio.py`,
  `render_mermaid.py`, or the MCP server's tool handlers.
- **Guard-hook bypass.** Any input that gets a write outside
  `service-topology/`, a git-state mutation, or a command that runs/reaches
  the analysed system past [`hooks/topology_guard.py`](hooks/topology_guard.py)
  when the hook is enabled — in any of the four host payload dialects.
- **Prompt injection via the analysed repository.** The skill reads untrusted
  repositories by design. Content in an analysed repository (a README, a code
  comment, a config value) that reliably induces the assistant to violate the
  hard constraints in `SKILL.md` §2 — writing outside `service-topology/`,
  running the analysed system, connecting to a live broker or database — is in
  scope. We know instruction-layer defences are probabilistic; reports that
  demonstrate a *reliable* bypass, especially one the hook then fails to
  catch, are valuable.
- **Script vulnerabilities.** Command injection, path traversal, or unsafe
  deserialisation through repository content the scripts parse (YAML,
  properties files, `.proto`, OpenAPI specs, docker-compose files).
- **MCP server vulnerabilities.** The JSON-RPC handler in
  `mcp-server/topology_mcp_server.py` accepting a malformed or adversarial
  request in a way that escapes its declared tool schema or writes outside the
  output root.

> Found a vulnerability **in a repository you mapped** with this tool? That is
> not ours to receive — report it through that project's own security policy.

## What is out of scope

- The diagrams themselves being wrong (a missed or false edge). That's a real
  bug, but it's an [extraction issue](https://github.com/arav7781/service-topology/issues/new?template=20-extraction-issue.yml),
  not a security report.
- Vulnerabilities in a repository this tool was pointed at and mapped.
- Theoretical prompt-injection concerns with no demonstrated reliable bypass.

## Reporting

Use [GitHub's private vulnerability reporting](https://github.com/arav7781/service-topology/security/advisories/new)
for this repository. Include:

- the payload or repository content that triggers it,
- which host and component (script, hook, or MCP server),
- what you expected instead.

Please do not open a public issue for a security report.
