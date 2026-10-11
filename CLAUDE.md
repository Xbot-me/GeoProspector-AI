# GeoProspector AI: agent rules

FastAPI dashboard + LangGraph pipeline: Google Places search, then enrich, score, pitch (Gemini), save to Postgres, and auto-send email (Resend/SMTP).
Module map: `docs/MODULES.md`. Current state / open threads: `docs/HANDOFF.md`. Tool habits: `docs/tool-efficiency.md`.

## Danger zones (read first)
- **`git push` to `main` deploys to the production VPS** (`.github/workflows/deploy.yml`). Never push to `main` without the owner's explicit yes. Work on a branch; the owner merges.
- **The app sends real email.** The interval worker starts with the app and has no kill switch (`AUTO_SEND_EMAILS` exists in `config.py` but nothing reads it). Local runs: point `DATABASE_URL` at a local DB and leave `RESEND_API_KEY`/`SMTP_PASS` unset (sends are then simulated, but still mark leads `sent`).
- Real API keys cost quota: Places calls are counted in `quota.py`; don't trigger searches or `/api/campaign/run_daily` to "test" without asking.
- Never commit `.env`, `data/run_*.csv` (third-party personal data), logs or `*.sqlite3`.
- Compliance code is load-bearing: CAN-SPAM footer, unsubscribe route, suppression list, bounce webhook. Don't weaken it in a refactor.

## Workflow
1. **Orient**: `bash scripts/agent/ctx.sh`, then the relevant section of `docs/MODULES.md`. Don't read whole files to look around.
2. **Plan**: for anything beyond a one-file fix, state the plan (files, behaviour change, risk) and get a yes before editing.
3. **Branch**: `feat/<topic>` or `fix/<topic>` off `main`. Never commit directly to `main`.
4. **Change**: match surrounding style; keep pipeline nodes pure functions of `BusinessState` (`state.py`); new env vars go in `config.py` with a safe default.
5. **Verify**: `bash scripts/agent/test.sh` (syntax gate for Python + dashboard JS; no unit tests exist yet). For behaviour changes, run the app locally with auto-send off and check the affected route/page.
6. **Commit**: conventional prefixes as in history (`feat:`, `fix:`, `style:`, `chore:`), one logical change per commit. Tooling/docs separate from app code.
7. **Hand off**: update `docs/HANDOFF.md` "Current state" when work is left in flight.

## Tooling
Prefer `scripts/agent/*` (`ctx.sh`, `test.sh`, `where.sh`) over raw commands; see `docs/tool-efficiency.md`.
On Windows PowerShell prefix with `bash`.
