# Optional guard hook

This directory contains an **optional, opt-in** enforcement layer that turns
the skill's mapping-only principle into a technical control rather than relying
on prompt compliance alone.

> **Nothing here is installed or activated automatically.** No file in this
> project registers the hook. You must add it to a settings file yourself.

## What it enforces

[`topology_guard.py`](topology_guard.py) is a pre-tool-use hook, usable with
all four supported hosts. It reads the tool-call payload on stdin - Claude
Code's, GitHub Copilot's, Cursor's, or Antigravity's shape - and denies:

| Category | Examples |
|---|---|
| Writes outside the output directory | `Write`/`Edit`/`NotebookEdit`, Copilot's file-edit tools, Antigravity's `replace_file_content` - to any path not under `service-topology/` |
| Hand-editing a generated artefact | A write to a `.drawio`, a `.mmd`, or `evidence/sources.md` even inside `service-topology/` - those come from the render scripts, and editing one silently decouples the diagram from the evidence that justifies it |
| Git state mutation | `git commit`, `git push`, `git reset --hard`, `git clean -fd`, `git checkout`, `git rebase`, `git merge`, `git stash`, `git add`, branch/tag creation |
| Running or reaching the analysed system | `docker compose up`, `kubectl apply`, `terraform apply`, `kafka-topics`, `kcat`, `psql`, `mysql`, `redis-cli`, `mongosh`, and the repository's own test suite |
| Dependency installs | `pip install`, `npm install`, and friends - the scripts are standard-library only |
| Destructive shell | `rm -rf`, `mkfs`, `dd of=`, writes to block devices, `chmod 777`, `curl \| sh` |
| Shell redirection | `>` or `>>` to a path outside `service-topology/` |

Everything else falls through to the host tool's normal permission handling.

One script covers every host. A deny response carries all four spellings at
once - Claude Code and Copilot read `hookSpecificOutput.permissionDecision`,
Cursor reads `permission`, Antigravity reads `decision` - and each host ignores
the keys it does not recognise.

## Trade-off before you enable it

The hook applies to **every** tool call in the session, not just this skill's.
If you enable it in your user settings, ordinary development in any project
will be blocked from committing, pushing, running builds, and editing files.
That is usually not what you want.

**Recommended:** enable it in the *analysed repository's* settings for the
duration of the mapping run, then remove it. Or start a session dedicated to
mapping.

## Installing it - Claude Code

1. Note the absolute path to your checkout.
2. Open (or create) `.claude/settings.json` in the repository you are mapping.
3. Copy the `hooks` block from
   [`topology-settings.example.json`](topology-settings.example.json),
   replacing `/ABSOLUTE/PATH/TO/service-topology` with the real path.
4. Optionally copy the `permissions` block too - it allowlists the read-only
   commands the skill needs, marks builds and installs as `ask`, and denies the
   write commands outright.
5. Restart Claude Code, or run `/hooks` to confirm registration.

## Installing it - GitHub Copilot

1. Note the absolute path to your checkout.
2. Create `.github/hooks/topology-guard.json` in the repository you are mapping.
3. Copy the contents of
   [`topology-copilot-hooks.example.json`](topology-copilot-hooks.example.json),
   replacing `/ABSOLUTE/PATH/TO/service-topology` with the real path.
4. Reload the window, or check the Copilot hooks output for confirmation.

> Do not place a real (non-placeholder) copy of this file at `.github/hooks/`
> inside **this checkout itself** - Copilot auto-loads any `*.json` file it
> finds there for that workspace.

## Installing it - Cursor

1. Note the absolute path to your checkout.
2. Open (or create) `.cursor/hooks.json` in the repository you are mapping.
3. Copy the contents of
   [`topology-cursor-hooks.example.json`](topology-cursor-hooks.example.json),
   replacing `/ABSOLUTE/PATH/TO/service-topology` with the real path.
4. Reload the window. Cursor reports hook registration in its output panel.

The example registers two events on purpose: `preToolUse` covers every tool
including file writes, and `beforeShellExecution` is the dedicated terminal
gate that also runs for cloud agents. Shell commands are checked twice; the
guard is idempotent, so that costs nothing but a few milliseconds.

> Do not place a real copy at `.cursor/hooks.json` inside **this checkout
> itself** - Cursor auto-loads project hooks from there.

## Installing it - Antigravity

1. Note the absolute path to your checkout.
2. Create `.agents/hooks.json` in the repository you are mapping.
3. Copy the contents of
   [`topology-antigravity-hooks.example.json`](topology-antigravity-hooks.example.json),
   replacing `/ABSOLUTE/PATH/TO/service-topology` with the real path.
4. Reload the window.

> Do not place a real copy at `.agents/hooks.json` inside **this checkout
> itself** - Antigravity auto-loads workspace hooks from there.

Verify it is working:

```bash
echo '{"tool_name":"Bash","tool_input":{"command":"docker compose up -d"},"cwd":"'"$PWD"'"}' \
  | python3 hooks/topology_guard.py | python3 -m json.tool
```

Expected output - one deny, spelled for every host:

```json
{
    "hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": "Topology Cartographer is mapping-only: the analysed system is mapped by reading it, not by running it. Blocked command: docker compose up -d"
    },
    "permission": "deny",
    "user_message": "Topology Cartographer is mapping-only: the analysed system is mapped by reading it, not by running it. Blocked command: docker compose up -d",
    "agent_message": "Topology Cartographer is mapping-only: the analysed system is mapped by reading it, not by running it. Blocked command: docker compose up -d",
    "decision": "deny",
    "reason": "Topology Cartographer is mapping-only: the analysed system is mapped by reading it, not by running it. Blocked command: docker compose up -d"
}
```

An allowed call produces no output at all:

```bash
echo '{"tool_name":"Bash","tool_input":{"command":"grep -rn KafkaTemplate services/"},"cwd":"'"$PWD"'"}' \
  | python3 hooks/topology_guard.py
```

To check the host dialect you actually run under, send that host's payload
shape instead:

```bash
# Cursor - beforeShellExecution puts the command at the top level
echo '{"hook_event_name":"beforeShellExecution","command":"git push","cwd":"'"$PWD"'"}' \
  | python3 hooks/topology_guard.py

# Antigravity - everything is nested under toolCall
echo '{"toolCall":{"name":"run_command","args":{"CommandLine":"kafka-topics --list","Cwd":"'"$PWD"'"}}}' \
  | python3 hooks/topology_guard.py
```

## Removing it

Delete the block or file you added - `.claude/settings.json` `hooks`,
`.github/hooks/topology-guard.json`, `.cursor/hooks.json`, or
`.agents/hooks.json` - and restart/reload. The hook keeps no state and writes
nothing.

## Limitations - read these

- **It is defence in depth, not a sandbox.** The Bash rules inspect command
  text. A sufficiently creative command string (unusual quoting, indirection
  through a variable, a wrapper script) can evade it. It complements the
  skill's instructions and the host tool's permission rules; it does not
  replace either.
- **It fails open.** A malformed payload is allowed through rather than
  wedging the session. A safety net that breaks your session gets disabled,
  and a disabled safety net protects nothing.
- **It does not stop reads.** Reading source and config is exactly what
  mapping needs.
- **It cannot tell mapping work from ordinary work.** See the trade-off above.
- **Path checks resolve symlinks.** A symlink from inside `service-topology/`
  pointing elsewhere will be denied, which is intended.

## Related

- [`docs/safety-model.md`](../docs/safety-model.md) - the full permission model
- §2 of each host's `SKILL.md` - the hard constraints this hook mirrors:
  [Claude Code](../skills/topology-cartographer/SKILL.md),
  [Copilot](../.github/skills/topology-cartographer/SKILL.md),
  [Cursor](../.cursor/skills/topology-cartographer/SKILL.md),
  [Antigravity](../.agents/skills/topology-cartographer/SKILL.md)
