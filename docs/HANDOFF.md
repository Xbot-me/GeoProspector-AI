# Handoff

## Current state
- Branch `merge/render-unify`: `main` (safety fixes, Overture search, owner/contact enrichment, reviews, competitor context, tests) merged into the live Render branch `feature/new-initiatives` (manual outreach kit, redesigned UI, 118-location catalog, Render PORT/DATABASE_URL fixes). Dropped: their Gemini-generated business discovery and our auto-send worker. VPS deploy workflow removed (Render deploys itself).
- Production: Render `maps-outreach-agent` tracks `feature/new-initiatives`; Render Postgres free plan expires 2026-11-08.
- `scripts/agent/test.sh` = syntax gate + pytest (needs a venv with `requirements-dev.txt`).

## Open threads
- Still open from the review: `radius` from the UI is ignored by `places_search` (needs a geocoded `locationBias`).
- Quick bugs not yet fixed: `get_conn` not imported in `app.py` `suggest_target`; `return {...}, 404` returns 200; unescaped `innerHTML` in `static/app.js`; unsigned Resend webhook; pitch HTML not escaped in `email_sender.py`.
- Pipeline processes businesses sequentially: a full-coverage run of a dense city can take hours and hit Gemini's daily free limit. Consider a small worker pool.
- No CI test step (the VPS deploy workflow was removed). Consider a GitHub Actions job running pytest on PRs.
- Candidate further tests: `lead_scorer`, `website_check` classification, `email_verifier` syntax checks, `auto_campaign` send-window maths (all pure, no network).
