#!/usr/bin/env bash
# The skill is instructions an agent pays for on every run, so its size is a
# released property. Prints each file's cost (tokens ~ bytes / 4) and what a
# typical run loads, and fails if any file outgrows its budget.
set -euo pipefail
cd "$(dirname "$0")/.."
s=skills/topology-cartographer
status=0

bytes() { wc -c < "$1" | tr -d ' '; }

check() {  # file, budget in bytes
  local n; n=$(bytes "$1")
  printf '%-56s %6d bytes  ~%5d tokens  (budget ~%d)\n' "$1" "$n" $((n / 4)) $(($2 / 4))
  if [ "$n" -gt "$2" ]; then echo "  over budget"; status=1; fi
}

check $s/SKILL.md 11000
check $s/references/signatures.md 15000
check $s/references/lenses.md 7500
check $s/references/smells.md 5500
check $s/references/drawio.md 5000
check agents/topology-extractor.md 2500
check agents/topology-verifier.md 2500

first=$(( ($(bytes $s/SKILL.md) + $(bytes $s/references/signatures.md) + $(bytes $s/references/lenses.md)) / 4 ))
again=$(( ($(bytes $s/SKILL.md) + $(bytes $s/references/lenses.md)) / 4 ))
echo
echo "first question on a repository (SKILL + signatures + lenses): ~$first tokens"
echo "follow-up answered from the ledger (SKILL + lenses):          ~$again tokens"
exit $status
