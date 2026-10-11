#!/usr/bin/env bash
# Locate before you read.   scripts/agent/where.sh <regex> [path]
# Returns: total matches/files, the top files by match count, and 2 sample lines for the top 5 files.
# Then open only the file(s) you need with Read offset/limit. Lockfiles, archives and generated data are excluded.
. "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"

pat="${1:-}"; path="${2:-.}"
[ -z "$pat" ] && { echo "usage: where.sh <regex> [path]"; exit 2; }

cd "$ROOT" || exit 1
EXCL=(':!**/package-lock.json' ':!**/composer.lock' ':!**/yarn.lock' ':!**/pnpm-lock.yaml' ':!**/poetry.lock' ':!**/Cargo.lock' ':!**/*.min.*' ':!**/archive' ':!**/node_modules')
# shellcheck disable=SC2206
EXTRA=($WHERE_EXCLUDES)

counts="$(git grep -I -c -E -- "$pat" -- "$path" "${EXCL[@]}" "${EXTRA[@]}" 2>/dev/null | sort -t: -k2 -nr)"
if [ -z "$counts" ]; then echo "no matches for /$pat/ under $path"; exit 1; fi

files="$(echo "$counts" | wc -l | tr -d ' ')"
total="$(echo "$counts" | awk -F: '{s+=$NF} END{print s}')"
echo "$total matches in $files file(s) for /$pat/ under $path (top 15 files):"
echo "$counts" | head -15 | awk -F: '{printf "  %4d  %s\n", $NF, substr($0, 1, length($0)-length($NF)-1)}'
[ "$files" -gt 15 ] && echo "  ... $((files - 15)) more file(s); narrow with a path or a stricter regex"
echo
echo "samples (first 2 lines of the top 5 files):"
echo "$counts" | head -5 | sed 's/:[0-9]*$//' | while IFS= read -r f; do
  git grep -I -n -E -m 2 -- "$pat" -- "$f" | cut -c1-170 | sed 's/^/  /'
done
