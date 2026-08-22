# IDE Rendering Playbook

Where the diagram shows up, per host, and what to tell the user. "Where is my
diagram?" is the most common question this skill produces, and it is always
answerable in one sentence.

---

## The one-line answer

**Open the `.drawio` file.** The `hediet.vscode-drawio` extension renders it
automatically on open - no command, no palette entry, no export step - in every
VS Code-compatible editor.

---

## Per host

| Host | Extension source | What to say |
|---|---|---|
| **VS Code** | Marketplace: `hediet.vscode-drawio` | "Open `service-topology/master-topology.drawio`. If you see XML instead of a diagram, install the Draw.io Integration extension and reopen." |
| **Cursor** | Cursor's marketplace, or OpenVSX | Same. Cursor is a VS Code-compatible extension host. |
| **Antigravity** | Its extension marketplace, or OpenVSX | Same. Also a VS Code-compatible extension host. Confirm the extension is installed before promising a preview - the marketplace backing it can differ from VS Code's. |
| **GitHub Copilot Chat** | n/a - see below | "Copilot Chat cannot render a file. It runs inside VS Code, so the file is already on disk: open `service-topology/master-topology.drawio` in the editor and the same extension previews it." |
| **Any chat with no file view** | n/a | "Paste `service-topology/master-topology.mmd` - it is Mermaid, and renders anywhere Markdown does." |

---

## Recommend, never install

`.vscode/extensions.json` in this project contains:

```json
{ "recommendations": ["hediet.vscode-drawio"] }
```

All three VS Code-family hosts read that file and prompt the user to install
what it names. That prompt is the whole mechanism.

**Do not attempt to install the extension.** Extensions do not uniformly have
permission to install other extensions across these hosts, the attempt fails
noisily, and it is not the kind of change to make on someone's editor without
asking. Recommending is the supported path; take it.

---

## The Mermaid fallback is not a consolation prize

`master-topology.mmd` carries the same content as the `.drawio`, from the same
graph model, with the same evidence distinction - a solid arrow is `[CODE]`, a
dotted arrow is not. It renders in a Markdown preview, in a GitHub pull-request
description, in an issue comment, and in most chat surfaces, with nothing
installed.

Mention it every time. For a reader who just wants to see the shape of the
system, it is often the faster answer, and it is the only answer in a surface
with no filesystem view.

```bash
# ready to paste into a chat window
python3 scripts/render_mermaid.py service-topology/graph-model.json --fenced
```

---

## Sharing a diagram outside the editor

- **diagrams.net** - `File > Open from > Device` at <https://app.diagrams.net>.
  Nothing is uploaded; the app runs client-side.
- **draw.io desktop** - opens the file directly.
- **PNG or SVG for a document** - the user exports from either app. This skill
  does not rasterise anything.
- **A pull request** - paste the Mermaid. GitHub renders it inline.

Before any of these, prompt the sharing gate from SKILL.md section 8: a topology
diagram is a map of internal structure, including which services hold which
data. That is usually fine to share internally and worth a moment's thought
before it goes anywhere else.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| The file opens as raw XML | Extension not installed, or the editor is not a VS Code-family host | Install `hediet.vscode-drawio`, reopen the file |
| The diagram is blank | The model had no nodes | Re-run `scan` and check the service list |
| Shapes render as plain rectangles | A very old draw.io build not recognising a shape name | Cosmetic only; colours and labels still carry the meaning |
| Boxes overlap after editing | Manual edits in draw.io, then a re-run overwrote them | Save a renamed copy before hand-editing; the pipeline owns the generated path |
| Mermaid block will not render | A label containing a quote or a pipe | Already escaped by `render_mermaid.py`; if it recurs, that is a bug worth reporting |
