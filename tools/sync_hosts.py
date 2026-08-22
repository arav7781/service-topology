#!/usr/bin/env python3
"""Keep the four host trees in step with the canonical skill.

This repository ships its skill four times, once per host:

    skills/topology-cartographer/           Claude Code   (canonical)
    .github/skills/topology-cartographer/   GitHub Copilot
    .cursor/skills/topology-cartographer/   Cursor
    .agents/skills/topology-cartographer/   Antigravity

Most of that payload must be byte-identical everywhere - the playbooks, the
templates, and the scripts carry no host-specific content. Only `SKILL.md`
frontmatter and a handful of "where do the subagents live" sentences legitimately
differ, and the same is true of the agent definitions: identical bodies,
host-specific frontmatter.

Four copies drift. This script is the check that they have not.

    python3 tools/sync_hosts.py             # report drift, exit 1 if any
    python3 tools/sync_hosts.py --write     # copy the canonical payload over

What is enforced
----------------
1. references/, templates/, scripts/  must be byte-identical in all four trees.
   `--write` fixes these automatically.
2. Agent bodies (everything after the YAML frontmatter) must be byte-identical
   across all four agent sets. Reported only - frontmatter differences are
   deliberate, so the merge is a human decision.
3. SKILL.md section headings must match the canonical's, in order. The prose
   inside a section may differ per host; the contract may not.

Standard library only, like everything else in this project.
"""

from __future__ import annotations

import argparse
import filecmp
import re
import shutil
import sys
from pathlib import Path
from typing import Dict, List, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent

SKILLS = ["topology-cartographer"]

# Where each host expects a skill to live. The first entry is canonical.
SKILL_TREES = ["skills", ".github/skills", ".cursor/skills", ".agents/skills"]


def canonical_skill(name: str) -> Path:
    return Path(SKILL_TREES[0]) / name


def mirror_skills(name: str) -> List[Path]:
    return [Path(tree) / name for tree in SKILL_TREES[1:]]

# Subtrees that carry no host-specific content.
SHARED_SUBTREES = ["references", "templates", "scripts"]

CANONICAL_AGENTS = Path("agents")
# (directory, filename pattern) - Copilot suffixes its agent files.
MIRROR_AGENTS: List[Tuple[Path, str]] = [
    (Path(".github/agents"), "{name}.agent.md"),
    (Path(".cursor/agents"), "{name}.md"),
    (Path(".agents/agents"), "{name}.md"),
]

FRONTMATTER_RE = re.compile(r"^---\n.*?\n---\n", re.DOTALL)
HEADING_RE = re.compile(r"^#{1,3} .+$", re.MULTILINE)


def strip_frontmatter(text: str) -> str:
    return FRONTMATTER_RE.sub("", text, count=1)


def headings(text: str) -> List[str]:
    return HEADING_RE.findall(text)


# Build artifacts and OS junk are not payload: they appear on one machine and
# not another (CI writes __pycache__ during the compile check; Finder drops
# .DS_Store), so counting them would report drift where none exists - and
# --write must never copy them into the mirrors.
IGNORED_DIRS = {"__pycache__"}
IGNORED_FILES = {".DS_Store"}
IGNORED_SUFFIXES = {".pyc", ".pyo"}


def relative_files(root: Path) -> List[Path]:
    files = []
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(root)
        if IGNORED_DIRS.intersection(rel.parts):
            continue
        if rel.name in IGNORED_FILES or rel.suffix in IGNORED_SUFFIXES:
            continue
        files.append(rel)
    return sorted(files)


def check_shared_subtrees(write: bool) -> List[str]:
    problems: List[str] = []
    for skill in SKILLS:
        problems += check_one_skill(skill, write)
    return problems


def check_one_skill(skill: str, write: bool) -> List[str]:
    problems: List[str] = []
    canonical_rel = canonical_skill(skill)
    canonical = REPO_ROOT / canonical_rel

    for mirror_rel in mirror_skills(skill):
        mirror = REPO_ROOT / mirror_rel
        if not mirror.is_dir():
            problems.append("missing host tree: {0}".format(mirror_rel))
            continue

        for subtree in SHARED_SUBTREES:
            src, dst = canonical / subtree, mirror / subtree
            if not src.is_dir():
                problems.append("missing canonical subtree: {0}".format(
                    (canonical_rel / subtree)))
                continue

            src_files, dst_files = relative_files(src), relative_files(dst) if dst.is_dir() else []

            for extra in sorted(set(dst_files) - set(src_files)):
                if write:
                    (dst / extra).unlink()
                else:
                    problems.append("{0}: not in canonical".format(mirror_rel / subtree / extra))

            for name in src_files:
                s, d = src / name, dst / name
                if d.is_file() and filecmp.cmp(s, d, shallow=False):
                    continue
                if write:
                    d.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(s, d)
                else:
                    state = "differs from" if d.is_file() else "missing, canonical is"
                    problems.append("{0}: {1} {2}".format(
                        mirror_rel / subtree / name, state, canonical_rel / subtree / name))
    return problems


def check_skill_headings() -> List[str]:
    problems: List[str] = []
    for skill in SKILLS:
        problems += check_one_skill_headings(skill)
    return problems


def check_one_skill_headings(skill: str) -> List[str]:
    problems: List[str] = []
    canonical_path = REPO_ROOT / canonical_skill(skill) / "SKILL.md"
    expected = headings(strip_frontmatter(canonical_path.read_text()))

    for mirror_rel in mirror_skills(skill):
        path = REPO_ROOT / mirror_rel / "SKILL.md"
        if not path.is_file():
            problems.append("missing SKILL.md: {0}".format(mirror_rel / "SKILL.md"))
            continue
        found = headings(strip_frontmatter(path.read_text()))
        if found != expected:
            only_canonical = [h for h in expected if h not in found]
            only_mirror = [h for h in found if h not in expected]
            detail = "; ".join(
                ["missing {0!r}".format(h) for h in only_canonical]
                + ["unexpected {0!r}".format(h) for h in only_mirror]
            ) or "same headings, different order"
            problems.append("{0}: section drift - {1}".format(mirror_rel / "SKILL.md", detail))
    return problems


def check_agent_bodies() -> List[str]:
    problems: List[str] = []
    canonical_dir = REPO_ROOT / CANONICAL_AGENTS
    bodies: Dict[str, str] = {}

    for path in sorted(canonical_dir.glob("*.md")):
        bodies[path.stem] = strip_frontmatter(path.read_text())

    if not bodies:
        return ["no canonical agents found in {0}/".format(CANONICAL_AGENTS)]

    for mirror_rel, pattern in MIRROR_AGENTS:
        for name, canonical_body in bodies.items():
            path = REPO_ROOT / mirror_rel / pattern.format(name=name)
            if not path.is_file():
                problems.append("missing agent: {0}".format(path.relative_to(REPO_ROOT)))
                continue
            if strip_frontmatter(path.read_text()) != canonical_body:
                problems.append("{0}: body differs from {1}/{2}.md".format(
                    path.relative_to(REPO_ROOT), CANONICAL_AGENTS, name))
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check (or fix) drift between the four host trees.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="what is enforced:\n"
               "  1. references/, templates/ and scripts/ are byte-identical in all\n"
               "     four trees. --write fixes these automatically.\n"
               "  2. Agent bodies are byte-identical across all four agent sets.\n"
               "     Reported only - frontmatter differences are deliberate.\n"
               "  3. SKILL.md section headings match the canonical's, in order.\n",
    )
    parser.add_argument(
        "--write", action="store_true",
        help="copy the canonical references/, templates/ and scripts/ over each "
             "mirror instead of only reporting the difference",
    )
    args = parser.parse_args()

    problems = check_shared_subtrees(write=args.write)
    problems += check_skill_headings()
    problems += check_agent_bodies()

    if not problems:
        print("host trees in sync ({0} hosts, canonical is {1}/)".format(
            len(SKILL_TREES), SKILL_TREES[0]))
        return 0

    verb = "fixed" if args.write else "found"
    print("{0} {1} problem(s):\n".format(verb, len(problems)), file=sys.stderr)
    for problem in problems:
        print("  {0}".format(problem), file=sys.stderr)
    if not args.write:
        print("\nRun with --write to copy the canonical payload over the mirrors.\n"
              "SKILL.md and agent frontmatter are host-specific - merge those by hand.",
              file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
