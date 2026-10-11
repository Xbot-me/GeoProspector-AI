#!/usr/bin/env bash
# ONE call for session start (replaces ~6 separate tool calls).   scripts/agent/ctx.sh
# Level-0 context: where the tree is, what changed, what the last agent left, and whether verification is still valid.
. "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"
cd "$ROOT" || exit 1
exec 2>/dev/null   # git CRLF warnings etc. are noise for an agent

echo "== git =="
git status -sb | head -1
n="$(git status --short | wc -l | tr -d ' ')"
if [ "$n" -eq 0 ]; then echo "clean working tree"; else
  echo "$n changed path(s):"; git status --short | head -20
  [ "$n" -gt 20 ] && echo "  ... $((n - 20)) more"
  echo; git diff HEAD --shortstat
fi
echo; echo "== last commits =="
git log -5 --format='%h %s' | cut -c1-110

echo; echo "== verification cache (VALID = identical code under test) =="
found=0
for f in $(ls -t "$CACHE"/pass-* 2>/dev/null | head -8); do
  fp="$(sed -n 's/^fp=//p' "$f")"; lab="$(sed -n 's/^label=//p' "$f")"; scope="$(sed -n 's/^scope=//p' "$f")"
  state="STALE"; [ "$fp" = "$(fingerprint "${scope:-.}")" ] && state="VALID"
  echo "  [$state] $lab -> $(sed -n 's/^summary=//p' "$f" | cut -c1-90)  ($(sed -n 's/^at=//p' "$f"))"
  found=1
done
[ "$found" -eq 0 ] && echo "  none yet (scripts/agent/test.sh and build.sh record PASS results here)"

if [ -n "$HANDOFF_FILE" ] && [ -f "$HANDOFF_FILE" ]; then
  echo; echo "== $HANDOFF_FILE (headings only) =="
  grep -n '^#\{1,2\} ' "$HANDOFF_FILE" | cut -c1-120 | head -14
fi
if [ -n "$PLANS_DIR" ] && [ -d "$PLANS_DIR" ]; then
  echo; echo "== recent plans =="; ls -t "$PLANS_DIR" | head -4 | sed 's/^/  /'
fi
