#!/usr/bin/env bash
# Tests with COMPACT output.
#   scripts/agent/test.sh <runner args>      e.g. --filter=Foo  |  tests/test_x.py -k name  |  src/foo.test.ts
#   scripts/agent/test.sh --full             run with TEST_FULL_ARGS (fast regression suite)
#   scripts/agent/test.sh --all              run with no extra args (everything)
#   add --force to ignore a cached PASS.
# Prints totals, then only the failing tests (trimmed). Never the passing list.
# A PASS is cached against HEAD + uncommitted changes under TEST_DIR + the arguments: an identical re-run is instant,
# and any edit invalidates it. Full raw log: <cache dir>/test-last.log
. "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"

if [ -z "$TEST_CMD" ]; then echo "TEST_CMD is not set in scripts/agent/agent.conf"; exit 2; fi

force=0; args=(); mode=args
for a in "$@"; do
  case "$a" in
    --force) force=1 ;;
    --full) mode=full ;;
    --all) mode=all ;;
    *) args+=("$a") ;;
  esac
done
[ "$mode" = full ] && read -r -a fullargs <<< "$TEST_FULL_ARGS" && args+=("${fullargs[@]}")
label="$TEST_CMD ${args[*]}"; [ "$mode" = all ] && label="$TEST_CMD (all)"

fp="$(fingerprint "$TEST_DIR")"
key="$(cache_key "$fp" "$label")"
if [ "$force" -eq 0 ] && rec="$(cache_hit "$key")"; then
  echo "CACHED PASS - identical code + args already green (use --force to rerun)"
  echo "$rec" | sed -n 's/^at=/  at: /p;s/^summary=/  /p'
  exit 0
fi

LOG="$CACHE/test-last.log"
( cd "$ROOT/$TEST_DIR" && eval "$TEST_CMD \"\${args[@]}\"" ) > "$LOG" 2>&1
rc=$?

# ---- per-format totals line + failure extraction ----
case "$TEST_FORMAT" in
  collision)
    totals="$(grep -E '^\s*Tests:' "$LOG" | tail -1 | sed 's/^ *//')"; dur="$(grep -E '^\s*Duration:' "$LOG" | tail -1 | sed 's/^ *//')"
    failures() { awk '
      function skip(l) { return (l ~ /▕/ && l !~ /➜/) || l ~ /(^|[ \\\/])vendor[\\\/]/ || l ~ /^[[:space:]]*[0-9]+[[:space:]]+[A-Za-z]/ || index(l, "───") > 0 || l ~ /^[[:space:]]*$/ }
      /^[[:space:]]+FAILED[[:space:]]/ { if (shown < 5) { inb = 1; shown++; n = 0; print ""; print substr($0, 1, 180); next } else { inb = 0; more++; next } }
      /^[[:space:]]*(Tests:|Duration:)/ { inb = 0 }
      inb && n < 10 && !skip($0) { print "  " substr($0, 1, 180); n++ }
      END { if (more > 0) print "\n... and " more " more failing test(s); see the log." }' "$LOG"; } ;;
  pytest)
    totals="$(grep -E '^=+ .*(passed|failed|error|no tests ran).* =+$' "$LOG" | tail -1 | sed 's/^=* *//; s/ *=*$//')"; dur=""
    failures() { grep -E '^(FAILED|ERROR) ' "$LOG" | head -8 | cut -c1-200; echo; grep -E '^E  ' "$LOG" | head -15 | cut -c1-200; } ;;
  jest)
    totals="$(grep -E '^Tests:' "$LOG" | tail -1)"; dur="$(grep -E '^Time:' "$LOG" | tail -1)"
    failures() { awk '/^  ●/ { if (c < 5) { c++; n = 0; inb = 1; print ""; print substr($0, 1, 180); next } else { inb = 0 } }
      /^(Test Suites:|Tests:)/ { inb = 0 }
      inb && n < 10 && $0 !~ /^[[:space:]]*$/ && $0 !~ /node_modules/ { print "  " substr($0, 1, 180); n++ }' "$LOG"; } ;;
  *)
    totals=""; dur=""
    failures() { tail -30 "$LOG" | cut -c1-200; } ;;
esac

if [ "$rc" -eq 0 ]; then
  [ -z "$totals" ] && { last="$(tail -1 "$LOG" | cut -c1-80)"; totals="exit 0${last:+ ($last)}"; }
  echo "PASS  $totals  $dur"
  cache_store "$key" "$fp" "$label" "$TEST_DIR" "$totals  $dur"
  exit 0
fi

if [ -z "$totals" ] && [ "$TEST_FORMAT" != generic ]; then
  echo "NO TEST SUMMARY (crash, syntax error, or no tests matched). Last 25 lines:"
  tail -25 "$LOG" | cut -c1-200
else
  echo "FAIL (exit $rc)  $totals  $dur"
  failures
fi
echo
echo "log: $CACHE_REL/test-last.log"
exit "$rc"
