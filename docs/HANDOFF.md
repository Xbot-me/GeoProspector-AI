# Handoff

## Current state
- Branch `fix/outreach-safety`: auth on CSV export + redacted public archive, clear-logs no longer re-queues, `email_verified` saved and failed addresses excluded, `simulated` send status, GET-confirm/POST unsubscribe (RFC 8058), `AUTO_SEND_EMAILS`/`MAX_DAILY_EMAILS` honoured. Verified end-to-end against a throwaway Postgres; not merged.
- Branch `fix/sending-correctness` (stacked on the above): atomic lead claim + shared send path for worker and `run_daily`, first in-window lead wins, timezone from coordinates (`timezonefinder`, new dependency), closed businesses dropped, Places quota in Postgres. Verified against a throwaway Postgres; Docker image build not tested.
- No automated tests in the repo yet; `scripts/agent/test.sh` is a syntax gate only.

## Open threads
- README references `.env.example`, which does not exist in the repo.
- Still open from the review: `radius` from the UI is ignored by `places_search` (needs a geocoded `locationBias`).
- Quick bugs not yet fixed: `get_conn` not imported in `app.py` `suggest_target`; `return {...}, 404` returns 200; unescaped `innerHTML` in `static/app.js`; unsigned Resend webhook; pitch HTML not escaped in `email_sender.py`.
- Candidate first tests: `lead_scorer`, `website_check` classification, `email_verifier` syntax checks, `auto_campaign` send-window maths (all pure, no network).
