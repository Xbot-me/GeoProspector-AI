# GeoProspector AI: agent rules

FastAPI dashboard + LangGraph pipeline: area search (Overture Maps, or Google Places), enrich (website, owner, contacts, reviews), score, build a manual outreach kit (Gemini: analysis, mockup prompt, email draft), save to Postgres. Emails go out only when the user dispatches one lead.
Module map: `docs/MODULES.md`. Current state / open threads: `docs/HANDOFF.md`. Tool habits: `docs/tool-efficiency.md`. Also see `AGENTS.md` (catalog location, migration and dedupe rules).

## Danger zones (read first)
- **Pushing the deploy branch deploys to production.** Render (`maps-outreach-agent`, Docker) auto-deploys on every commit to the branch it tracks (check with the Render MCP `get_service`; it was `feature/new-initiatives`). Never push to that branch or `main` without the owner's explicit yes. Work on a branch; the owner merges.
- **`POST /api/leads/{id}/send` sends real email** (the dashboard's "Dispatch via API"). Local runs: point `DATABASE_URL` at a local DB and leave `RESEND_API_KEY`/`SMTP_PASS` unset (sends are then recorded as `simulated`).
- Real API keys cost quota: Places calls are counted in `quota.py`; with `PLACES_PROVIDER=google` don't trigger searches to "test" without asking. Overture searches are free.
- Never commit `.env`, `data/run_*.csv` (third-party personal data), logs or `*.sqlite3`.
- Compliance code is load-bearing: CAN-SPAM footer, unsubscribe route, suppression list, bounce webhook. Don't weaken it in a refactor.

## Workflow
1. **Orient**: `bash scripts/agent/ctx.sh`, then the relevant section of `docs/MODULES.md`. Don't read whole files to look around.
2. **Plan**: for anything beyond a one-file fix, state the plan (files, behaviour change, risk) and get a yes before editing.
3. **Branch**: `feat/<topic>` or `fix/<topic>` off `main`. Never commit directly to `main`.
4. **Change**: match surrounding style; keep pipeline nodes pure functions of `BusinessState` (`state.py`); new env vars go in `config.py` with a safe default.
5. **Verify**: `bash scripts/agent/test.sh` (syntax gate + pytest; needs a venv with `requirements-dev.txt`). For behaviour changes, run the app locally against a throwaway DB and check the affected route/page.
6. **Commit**: conventional prefixes as in history (`feat:`, `fix:`, `style:`, `chore:`), one logical change per commit. Tooling/docs separate from app code.
7. **Hand off**: update `docs/HANDOFF.md` "Current state" when work is left in flight.

## Tooling
Prefer `scripts/agent/*` (`ctx.sh`, `test.sh`, `where.sh`) over raw commands; see `docs/tool-efficiency.md`.
On Windows PowerShell prefix with `bash`.
