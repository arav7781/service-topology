#!/usr/bin/env bash
# Mirrors the canonical skill (skills/topology-cartographer/) and helper agents
# (agents/) into the Copilot, Cursor and Antigravity trees. Each mirror keeps
# its own host-specific frontmatter; everything below it is copied verbatim.
#
#   tools/sync-hosts.sh           rewrite the mirrors
#   tools/sync-hosts.sh --check   exit 1 if any mirror has drifted (CI)
set -euo pipefail
cd "$(dirname "$0")/.."

check=0
[ "${1:-}" = "--check" ] && check=1
skill=skills/topology-cartographer
hosts=".github .cursor .agents"
drift=0

frontmatter() { awk '{ print } /^---$/ { if (++n == 2) exit }' "$1"; }
body() { awk 'n >= 2 { print } /^---$/ { n++ }' "$1"; }

report() {
  if [ "$check" = 1 ]; then echo "drift: $1"; drift=1; else echo "synced: $1"; fi
}

# A mirror file is created by hand once, with its host's frontmatter.
mirror_file() {
  local src=$1 dst=$2 tmp
  if [ ! -f "$dst" ]; then echo "missing: $dst (create it with its host frontmatter)"; drift=1; return; fi
  tmp=$(mktemp)
  { frontmatter "$dst"; body "$src"; } > "$tmp"
  if cmp -s "$tmp" "$dst"; then rm -f "$tmp"; return; fi
  if [ "$check" = 1 ]; then rm -f "$tmp"; else mv "$tmp" "$dst"; fi
  report "$dst"
}

mirror_dir() {
  local src=$1 dst=$2
  if diff -r "$src" "$dst" > /dev/null 2>&1; then return; fi
  if [ "$check" = 0 ]; then rm -rf "$dst"; cp -r "$src" "$dst"; fi
  report "$dst"
}

agent_path() {  # host, agent name
  if [ "$1" = .github ]; then echo "$1/agents/$2.agent.md"; else echo "$1/agents/$2.md"; fi
}

for host in $hosts; do
  mirror_file "$skill/SKILL.md" "$host/skills/topology-cartographer/SKILL.md"
  mirror_dir "$skill/references" "$host/skills/topology-cartographer/references"
  for agent in agents/*.md; do
    mirror_file "$agent" "$(agent_path "$host" "$(basename "$agent" .md)")"
  done

  # A mirror may hold nothing the canonical tree does not.
  for f in "$host/skills/topology-cartographer"/*; do
    case "$(basename "$f")" in SKILL.md | references) ;; *) echo "stray: $f"; drift=1 ;; esac
  done
  for f in "$host"/agents/*; do
    name=$(basename "$f"); name=${name%.agent.md}; name=${name%.md}
    [ -f "agents/$name.md" ] || { echo "stray: $f"; drift=1; }
  done
done

if [ "$drift" = 1 ]; then exit 1; fi
echo "host trees in sync"
