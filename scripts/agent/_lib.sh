#!/usr/bin/env bash
# Shared helpers for scripts/agent/*. Source it; do not run it.
# These wrappers make a tool call return a DECISION (pass/fail, where, what changed) instead of a raw dump.
# The full raw output is always kept in the cache dir for the rare deep dive.

_HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$_HERE/../.." && pwd)"

# ---- defaults (override in scripts/agent/agent.conf) ----
CACHE_REL=".agent-cache"      # gitignored; raw logs + cached PASS records
TEST_DIR="."                  # directory the test command runs in (relative to repo root)
TEST_CMD=""                   # e.g. "php artisan test" | "python -m pytest" | "npx jest"
TEST_FULL_ARGS=""             # args for --full (fast regression), e.g. "--exclude-group=slow"
TEST_FORMAT="generic"         # collision (Laravel) | pytest | jest | generic
BUILD_APPS=""                 # "name:dir name2:dir2", e.g. "admin:admin-frontend web:storefront"
BUILD_CMD="npm run build"
FP_EXCLUDES=""                # extra git pathspecs ignored by the fingerprint, e.g. ":!backend/storage"
WHERE_EXCLUDES=""             # extra git pathspecs ignored by where.sh
HANDOFF_FILE=""               # file whose headings ctx.sh lists (e.g. docs/HANDOFF.md)
PLANS_DIR=""                  # directory listed by ctx.sh (e.g. .agent-work/plans)
[ -f "$_HERE/agent.conf" ] && . "$_HERE/agent.conf"

CACHE="$ROOT/$CACHE_REL"
mkdir -p "$CACHE"

# fingerprint <pathspec>...  -> one hash of: HEAD + uncommitted diff + untracked files under the pathspec.
# Identical hash == identical code under test, so a previous PASS is still valid.
fingerprint() {
  (
    cd "$ROOT" || exit 1
    exec 2>/dev/null
    spec=("$@"); [ ${#spec[@]} -eq 0 ] && spec=(.)
    {
      git rev-parse HEAD
      git diff HEAD -- "${spec[@]}" $FP_EXCLUDES ":!$CACHE_REL"
      git ls-files -o --exclude-standard -- "${spec[@]}" $FP_EXCLUDES ":!$CACHE_REL" | while IFS= read -r f; do
        printf '%s ' "$f"; git hash-object -- "$f"
      done
    } | git hash-object --stdin
  )
}

# cache_key <fingerprint> <label>
cache_key() { printf '%s|%s' "$@" | git hash-object --stdin; }

# cache_hit <key>  -> prints the stored record and returns 0 if a PASS is stored for this exact key
cache_hit() { [ -f "$CACHE/pass-$1" ] && cat "$CACHE/pass-$1"; }

# cache_store <key> <fingerprint> <label> <scope-dir> <summary>
cache_store() {
  printf 'fp=%s\nlabel=%s\nscope=%s\nat=%s\nsummary=%s\n' "$2" "$3" "$4" "$(date '+%Y-%m-%d %H:%M:%S')" "$5" > "$CACHE/pass-$1"
}
