# Safety Model

What Topology Cartographer is allowed to do, what it refuses, and how each rule
is actually enforced rather than merely stated.

The whole posture reduces to one sentence: **it reads the repository and writes
diagrams of it, and it does nothing else.**

---

## The three layers

| Layer | Mechanism | Covers |
|---|---|---|
| **Instructions** | §2 of `SKILL.md`, and the hard-constraints block in each agent | What the model will and will not attempt |
| **Code** | `SafeWriter` in `topology_lib/model.py` | Every byte written, on every path, in every host |
| **Hook** *(optional)* | [`hooks/topology_guard.py`](../hooks/topology_guard.py) | Tool calls, before they run |

They overlap deliberately. Instructions alone rely on compliance. The code layer
cannot be talked out of its rule, but only governs what the pipeline writes. The
hook governs everything the session does, and is opt-in because it applies to
the whole session, not just this skill.

---

## Permission classes

### Normally safe

- Reading any file in the analysed repository.
- Searching it - `grep`, `rg`, `find`, `git ls-files`.
- Reading configuration: `application.yml`, `.properties`, `.env*`,
  `docker-compose.yml`, Helm values, Terraform.
- Running the six bundled scripts. They need no network, no broker, no package
  manager, and no interpreter beyond Python 3.8.
- Writing under `service-topology/`.

### Requires approval

- Anything in the analysed repository's own build or tooling. If you believe a
  code-generation step is needed to resolve a binding, ask first and record what
  you ran.
- Scanning a repository the user has not pointed at.
- Sharing the output beyond the machine it was produced on.

### Denied during mapping

| Denied | Why |
|---|---|
| Writing outside `service-topology/` | The analysed repository is read-only, including its `.gitignore` |
| Hand-editing a generated `.drawio`, `.mmd`, or `evidence/sources.md` | It decouples the diagram from the evidence that justifies it. Fix extraction and re-run |
| Hand-writing mxGraph XML anywhere | The failure mode this design exists to prevent |
| `git commit`, `push`, `add`, `checkout`, `reset --hard`, branch or tag creation | Mapping does not change history |
| `docker compose up`, `kubectl apply`, `terraform apply` | The system is mapped by reading it, not running it |
| `kafka-topics`, `kcat`, `psql`, `mysql`, `redis-cli`, `mongosh` | A live broker or database is not evidence you can cite, and is an environment nobody authorised this run to touch |
| `pip install`, `npm install`, and friends | The scripts are standard-library only. There is nothing to install |
| Running the repository's test suite | Nothing here requires the analysed code to execute |
| `rm -rf`, `mkfs`, `dd of=`, `curl \| sh` | Destructive, and unrelated to mapping |

---

## Untrusted repository handling

You are reading code you did not write, which may be hostile. The design keeps
that boring:

- **Nothing is executed.** Not the build, not the tests, not a container, not a
  generated script. The extractors read text and apply regular expressions.
- **Symlinks are not followed** during the walk, so a link out of the repository
  cannot pull an unrelated file into the scan.
- **File size and type are bounded** - files over 2 MB and anything outside a
  known source or config extension are skipped, so a crafted 4 GB `.yml` cannot
  exhaust memory.
- **A failing extractor is contained.** Each runs inside a try/except that
  records a warning against the file; one malformed file cannot sink a
  whole-repository scan or, more importantly, hide the failure.
- **Config values are not interpolated into commands.** A topic name is a label
  in a diagram; it is never passed to a shell.
- **The YAML parser is a documented subset** rather than a full loader. There is
  no code-execution surface in it at all - no tags, no object construction.

---

## Output confinement

Every write in the pipeline, the scripts, and the MCP server goes through
`SafeWriter`:

```python
writer = SafeWriter("service-topology")
writer.write_text("master-topology.drawio", xml)      # fine
writer.write_text("../../etc/passwd", xml)            # OutsideOutputRoot
```

It normalises `..` before comparing, then resolves symlinks on both sides, so
neither traversal nor a symlink planted inside the output directory escapes. The
resolution happens on both the root and the target, which is what makes it
correct on macOS where `/tmp` is itself a symlink.

There is no code path that writes a file without it. That is the property worth
preserving in any change to this project.

---

## Enabling the hook

[`hooks/topology_guard.py`](../hooks/topology_guard.py) turns the table above
into a technical control. It is **not installed automatically** - no file in this
project registers it - and it accepts all four hosts' payload shapes, emitting a
deny in all four spellings at once.

Before enabling it, read the trade-off in [`hooks/README.md`](../hooks/README.md):
it applies to **every** tool call in the session, not just this skill's. Enabling
it in your user settings blocks ordinary development everywhere. Enable it in the
analysed repository for the duration of the run, or use a session dedicated to
mapping.

It fails open. A malformed payload is allowed through rather than wedging the
session, because a safety net that breaks your session gets disabled, and a
disabled safety net protects nothing.

---

## What this model does not protect against

- **A creative shell command.** The Bash rules inspect command text. Indirection
  through a variable or a wrapper script can evade them. The hook is defence in
  depth, not a sandbox.
- **A wrong diagram.** Nothing here makes extraction correct. It makes extraction
  *auditable*: every arrow cites a line, and every unconfirmed arrow says so.
  The accuracy gate is a human reading it.
- **Over-trust.** The most likely harm from this tool is someone treating a
  generated diagram as authoritative because it looks authoritative. The dashed
  grey edges, the "inferred, not confirmed" section, and the "what this diagram
  does not show" block in the summary template all exist to fight that, and none
  of them works if the summary is skipped.
- **Disclosure by sharing.** A topology diagram maps internal structure. The
  tool cannot know your disclosure rules; the sharing gate asks.

---

## Human approval gates

| Gate | Question | Where |
|---|---|---|
| Boundaries | Are these the right services? | End of phase 0 |
| Cost | Large repository - which subsystems? | Before phase 1 |
| Accuracy | Does this match how the system behaves? | After phase 5 |
| Sharing | Is this safe to circulate? | Before the user shares it |

No gate is passed by the tool on its own.
