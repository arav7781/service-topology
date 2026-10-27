#!/usr/bin/env bash
# Checks a topology.ledger against the repository it describes:
#   - header first, then N, E and G blocks, each sorted byte-wise
#   - kinds, rels and tags come from the grammar in SKILL.md section 5
#   - every edge endpoint is a declared node; every non-CODE edge has a note
#   - every receipt names a file that exists and a line inside it
#
#   tools/check-ledger.sh <repo-root> <ledger>
set -euo pipefail
export LC_ALL=C
repo=${1:?usage: check-ledger.sh <repo-root> <ledger>}
ledger=${2:?usage: check-ledger.sh <repo-root> <ledger>}
fail=0

head -n 1 "$ledger" | grep -q '^# topology.ledger v2 ' || { echo "  first line is not a v2 ledger header"; fail=1; }

order=$(grep -v '^#' "$ledger" | grep -v '^$' | cut -c1 | uniq | tr -d '\n')
case "$order" in "" | N | NE | NEG | NG | E | EG | G) ;; *) echo "  blocks out of order: $order (want N, E, G)"; fail=1 ;; esac

for k in N E G; do
  block=$(grep "^$k " "$ledger" || true)
  [ -z "$block" ] && continue
  printf '%s\n' "$block" | sort -cu 2> /dev/null || { echo "  $k lines are not sorted and unique (LC_ALL=C sort -u)"; fail=1; }
done

awk -F' [|] ' -v repo="$repo" '
  function bad(msg) { print "  line " NR ": " msg; failed = 1 }
  function count(path,   f, c, l, r) {
    if (path in lines) return lines[path]
    f = repo "/" path; c = 0
    while ((r = (getline l < f)) > 0) c++
    close(f)
    return lines[path] = (r < 0 ? -1 : c)
  }
  function receipts(s,   parts, n, i, k, path, nums, m, j, c) {
    if (s == "") { bad("no receipt"); return }
    n = split(s, parts, /; /)
    for (i = 1; i <= n; i++) {
      k = match(parts[i], /:[0-9][0-9,]*$/)
      if (!k) { bad("receipt without :line - " parts[i]); continue }
      path = substr(parts[i], 1, k - 1)
      c = count(path)
      if (c < 0) { bad("missing file " path); continue }
      m = split(substr(parts[i], k + 1), nums, ",")
      for (j = 1; j <= m; j++)
        if (nums[j] + 0 < 1 || nums[j] + 0 > c) bad(path ":" nums[j] " is outside the file (" c " lines)")
    }
  }
  BEGIN {
    split("svc ref topic queue db cache store ext", a, " "); for (i in a) kinds[a[i]] = 1
    split("pub sub http grpc gql ws uses dep", a, " "); for (i in a) rels[a[i]] = 1
    split("CODE INFERENCE UNVERIFIED", a, " "); for (i in a) tags[a[i]] = 1
  }
  /^N / {
    split($1, h, " ")
    if (!(h[3] in kinds)) bad("unknown kind " h[3])
    if (h[2] in nodes) bad("duplicate node " h[2])
    nodes[h[2]] = 1; receipts($2)
  }
  /^E / {
    split($1, h, " ")
    if (!(h[3] in rels)) bad("unknown rel " h[3])
    if (!($3 in tags)) bad("unknown tag " $3)
    if ($3 != "CODE" && $5 == "") bad($3 " edge without a note")
    ends[NR] = h[2] " " h[4]; receipts($4)
  }
  /^G / { if ($3 != "") receipts($3) }
  END {
    for (r in ends) {
      split(ends[r], e, " ")
      if (!(e[1] in nodes)) { print "  line " r ": undeclared node " e[1]; failed = 1 }
      if (!(e[2] in nodes)) { print "  line " r ": undeclared node " e[2]; failed = 1 }
    }
    exit failed
  }
' "$ledger" || fail=1

if [ "$fail" = 1 ]; then echo "FAIL $ledger"; exit 1; fi
echo "ok $ledger: $(grep -c '^N ' "$ledger") nodes, $(grep -c '^E ' "$ledger") edges, $(grep -c '^G ' "$ledger" || true) gaps"
