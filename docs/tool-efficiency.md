# Tool efficiency

> Rule: a tool call should return a **decision**, not a dump. Locate first, read narrowly, batch independent calls.

## 1. Batch independent calls
- Put every independent read/search in ONE response (parallel tool calls). Chain only when call B needs A's result.
- Session start = one command: `bash scripts/agent/ctx.sh` (branch, changed files, last commits, whether the last PASS is still valid, handoff headings, recent plans).
- Dependent shell checks: one Bash call with `&&`, not one call per command.

## 2. Use the wrappers instead of raw commands (`scripts/agent/`)
| Instead of | Run | You get back |
|---|---|---|
| the test runner | `bash scripts/agent/test.sh` | PASS / CACHED PASS, or only the errors; raw log in `.agent-cache/` |
| a broad grep for a symbol | `bash scripts/agent/where.sh '<regex>' [path]` | counts per file + 2 sample lines for the top 5 files |
| several status commands | `bash scripts/agent/ctx.sh` | the whole Level-0 picture |
`--force` ignores the cache. Use raw commands only when a wrapper hides what you need (read the log file first).

## 3. Smart cache
- A PASS is stored against **HEAD + uncommitted changes under that directory + the arguments**. Same code and args = `CACHED PASS` instantly.
- Any edit changes the fingerprint, so a stale PASS can never be reported for changed code. Only PASS is cached; FAIL always re-runs.
- `ctx.sh` shows each stored result as VALID or STALE for the current tree. The cache dir is gitignored.
- No test suite shares the DB yet; when one does, never run it in parallel.

## 4. Output budgets for built-in tools
- `Read`: pass `offset`/`limit` once you know the region. Never read a whole file over ~300 lines "to look around".
- `Grep`: start with `files_with_matches` or `count`; then `content` with `head_limit` ~30 and a narrow `glob`.
- `git diff --stat` first, then `git diff -- <one file>`. `git log -n 5 --format='%h %s'`.
- Do not re-read unchanged files; do not paste what you already have.
- Generated blobs are deny-listed in `.claude/settings.json`; ask the user instead of working around it.
- A truncated result means "narrow the command", not "raise the cap".

## 5. Docs load on demand
- Handoff: read the top "Current state" digest; open the archive only when a task names something in it.
- `docs/HANDOFF.md` holds in-flight state; `CLAUDE.md` holds rules only.
- `docs/MODULES.md` before searching the source.

## 6. Keep the cache-friendly prefix stable
Rules files (`CLAUDE.md` / `AGENTS.md`) load every turn. No dates, counters or in-flight status in them (that goes in the handoff file); edit rarely, in one commit.

## 7. Repo specifics
- `test.sh` = `compileall` + `node --check` on `static/*.js`. `build.sh` is not configured (no build step).
- `app.py` is ~880 lines: `where.sh` the route or function, then `Read` with offset/limit.
- `.env`, lead CSV exports and logs are deny-listed (secrets / third-party personal data).
