# Security Policy

Topology Cartographer is a set of instructions an AI coding agent follows while
reading repositories, some of them untrusted. If you find a security problem
in this project, please report it privately first.

## Supported versions

| Version | Supported |
|---|---|
| Latest release / `main` | ✅ |
| Anything older | ❌ - please reproduce on `main` |

## What counts as a vulnerability here

- **Prompt injection through the analysed repository.** Content in a mapped
  repository - a README, a comment, a config value, a crafted ledger - that
  reliably makes an agent following this skill break its rules: writing
  outside `service-topology/`, running the analysed code, contacting a live
  system, committing, or installing something. We know instruction-level
  defences are probabilistic. A report showing a *reliable* bypass, especially
  one that also slips past the permission rules in
  [docs/safety-model.md](docs/safety-model.md), is valuable.
- **Credential leakage.** A case where following the skill copies a secret -
  a password in a connection string, a token in a URL - into the ledger or a
  view.
- **Instructions that grant too much.** Anything in a `SKILL.md` or agent
  frontmatter that pre-approves a tool or command beyond what the rules need.
- **Repository tooling.** Command injection or path traversal in
  `tools/*.sh` when run on a crafted ledger or fixture.

> Found a vulnerability **in a repository you mapped**? That isn't ours to
> receive. Report it through that project's own security policy.

## What is out of scope

- A diagram being wrong - a missed or false edge. That's a real bug, but it's
  an [extraction issue](https://github.com/arav7781/service-topology/issues/new?template=20-extraction-issue.yml).
- Vulnerabilities in a repository this skill was pointed at.
- Theoretical prompt-injection concerns with no demonstrated reliable bypass.

## Reporting

Use [GitHub's private vulnerability reporting](https://github.com/arav7781/service-topology/security/advisories/new)
for this repository. Include the content that triggers the problem, the host
and model you used, and what you expected to happen instead. Please don't open
a public issue for a security report.
