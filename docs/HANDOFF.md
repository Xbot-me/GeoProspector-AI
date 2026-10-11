# Handoff

## Current state
- Branch `fix/outreach-safety`: auth on CSV export + redacted public archive, clear-logs no longer re-queues, `email_verified` saved and failed addresses excluded, `simulated` send status, GET-confirm/POST unsubscribe (RFC 8058), `AUTO_SEND_EMAILS`/`MAX_DAILY_EMAILS` honoured. Verified end-to-end against a throwaway Postgres; not merged.
- Branch `fix/sending-correctness` (stacked on the above): atomic lead claim + shared send path for worker and `run_daily`, first in-window lead wins, timezone from coordinates (`timezonefinder`, new dependency), closed businesses dropped, Places quota in Postgres. Verified against a throwaway Postgres; Docker image build not tested.
- Branch `feat/search-v2` (stacked on the above): full-radius multi-niche area search, contact enrichment (website + Gemini, Hunter, Companies House, LinkedIn/FB/IG via ddgs), niche-bundle suggestions, fix for every emailed lead being self-flagged `skipped_duplicate` (since ff26c9f). 21 unit tests + end-to-end run against throwaway Postgres pass. Not tested against live Google/Gemini/Hunter.
- Branch `feat/overture-provider` (stacked on the above): Overture Maps as default provider (Google optional), free geocoding, reviews from websites + review sites, competitor context in pitches. Live-checked on Austin: 79 businesses in 5 km (35 s first download, <1 s cached); reviews found for ~40-60% of businesses, ratings for ~20%.
- `scripts/agent/test.sh` = syntax gate + pytest (needs a venv with `requirements-dev.txt`).

## Open threads
- Still open from the review: `radius` from the UI is ignored by `places_search` (needs a geocoded `locationBias`).
- Quick bugs not yet fixed: `get_conn` not imported in `app.py` `suggest_target`; `return {...}, 404` returns 200; unescaped `innerHTML` in `static/app.js`; unsigned Resend webhook; pitch HTML not escaped in `email_sender.py`.
- Pipeline processes businesses sequentially: a full-coverage run of a dense city can take hours and hit Gemini's daily free limit. Consider a small worker pool.
- No test step in `deploy.yml` yet.
- Candidate further tests: `lead_scorer`, `website_check` classification, `email_verifier` syntax checks, `auto_campaign` send-window maths (all pure, no network).
