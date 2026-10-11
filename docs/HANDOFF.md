# Handoff

## Current state
- Agent workflow set up: `CLAUDE.md`, `docs/MODULES.md`, `docs/tool-efficiency.md`, `scripts/agent/` wrappers, `.claude/settings.json`.
- No automated tests yet; `scripts/agent/test.sh` is a syntax gate only.

## Open threads
- README references `.env.example`, which does not exist in the repo.
- `AUTO_SEND_EMAILS` and `MAX_DAILY_EMAILS` are defined in `config.py` but never read (the daily cap is hard-coded `20` in `app.py`). See the code review findings.
- Candidate first tests: `lead_scorer`, `website_check` classification, `email_verifier` syntax checks, `auto_campaign` send-window maths (all pure, no network).
