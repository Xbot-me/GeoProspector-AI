#!/usr/bin/env bash
# Build with COMPACT output.   scripts/agent/build.sh <app> [--force]      (apps = BUILD_APPS in agent.conf)
# Success: one line. Failure: only the error blocks, not the whole build log.
# A PASS is cached against HEAD + uncommitted changes under that app's dir. Full log: <cache dir>/build-<app>.log
. "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"

app="${1:-}"; force=0; [ "${2:-}" = "--force" ] && force=1
dir=""
for pair in $BUILD_APPS; do [ "${pair%%:*}" = "$app" ] && dir="${pair#*:}"; done
if [ -z "$dir" ]; then
  names="$(for p in $BUILD_APPS; do printf '%s ' "${p%%:*}"; done)"
  echo "usage: build.sh <app> [--force]   apps: ${names:-none configured (set BUILD_APPS in agent.conf)}"; exit 2
fi

label="build $app"
fp="$(fingerprint "$dir")"
key="$(cache_key "$fp" "$label")"
if [ "$force" -eq 0 ] && rec="$(cache_hit "$key")"; then
  echo "CACHED PASS - identical $app code already built clean (use --force to rerun)"
  echo "$rec" | sed -n 's/^at=/  at: /p;s/^summary=/  /p'
  exit 0
fi

LOG="$CACHE/build-$app.log"
( cd "$ROOT/$dir" && eval "$BUILD_CMD" ) > "$LOG" 2>&1
rc=$?

if [ "$rc" -eq 0 ]; then
  routes="$(grep -cE '^(├|└|┌|│) ' "$LOG")"
  warns="$(grep -ciE 'warning' "$LOG")"
  summary="BUILD OK $app: $warns warning line(s)"; [ "$routes" -gt 0 ] && summary="BUILD OK $app: ~$routes route lines, $warns warning line(s)"
  echo "$summary"
  cache_store "$key" "$fp" "$label" "$dir" "$summary"
  exit 0
fi

echo "BUILD FAILED $app (exit $rc). Error blocks:"
PAT='Failed to compile|Type error|error TS[0-9]+|Module not found|Syntax error|^Error:|error\[|^ERROR|Unhandled|ReferenceError|SyntaxError|FAILED'
grep -nE -B1 -A4 "$PAT" "$LOG" | head -60 | cut -c1-200
if ! grep -qE "$PAT" "$LOG"; then echo "(no recognised error pattern - last 25 lines)"; tail -25 "$LOG" | cut -c1-200; fi
echo
echo "log: $CACHE_REL/build-$app.log"
exit "$rc"
