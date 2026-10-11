# Module map

Read this before searching the source. Line numbers drift; use `bash scripts/agent/where.sh '<regex>'` to confirm.

## Entry points
| File | Role |
|---|---|
| `app.py` | FastAPI app: routes, cookie auth middleware, WebSocket progress, pipeline threads, interval auto-send worker (started in `lifespan`). Biggest file (~880 lines): read by region. |
| `main.py` | Older CLI runner for the pipeline (interactive approval prompt). |
| `auto_campaign.py` | Campaign target catalog (niche x city), lead timezone lookup (stored tz > city > country) and send-window logic. |

## Pipeline (`graph.py`, state in `state.py`)
`check_website -> find_contacts -> score_lead -> (good site? save_to_crm_skip : analyze_business -> generate_pitch -> save_to_crm)`.
Checkpointer: Postgres via `get_checkpointer_cm()`.

| Node (`nodes/`) | Does |
|---|---|
| `area_search.py` | provider switch (`PLACES_PROVIDER`): `overture` (default) or `google`; same `search_area()` / `search_businesses()` contract |
| `places_overture.py` | Overture Maps places via DuckDB: downloads the search box once (cached in `data/overture_cache/`), matches niches to Overture categories (`NicheMatcher`: curated map + whole-word fallback + name match for generic `contractor`), drops closed/low-confidence/outside radius, merges duplicate listings, returns listing emails/socials and per-niche competitor totals. Geocoding: `geocode.py` (Nominatim). |
| `places_search.py` | Google provider. `search_area(niches, location, radius)`: finds every business in the circle. Free IDs-only pass splits tiles that hit Google's 60-result cap; billed pass only on leaf tiles with unknown places. Drops closed/outside-radius, adds coordinates + timezone. |
| `website_check.py` | classifies `website_quality`: none / dead / social_only / outdated / good |
| `contact_finder.py` | combines `enrichment/*` sources; picks owner (role priority) and send email (own domain > owner > generic); full detail in `contacts_json` |
| `lead_scorer.py` | 0-100 score + breakdown |
| `business_analyzer.py` | Gemini analysis of the business |
| `pitch_generator.py` | Gemini subject/body/language |
| `crm_writer.py` | upsert to DB via `db.py` |

## Support modules
| File | Role |
|---|---|
| `config.py` | all env vars + defaults (keys, limits, email provider, `AUTO_SEND_EMAILS`, admin auth) |
| `db.py` | psycopg Postgres: schema + `_migrate`, runs, businesses, email log, opens, suppression, unsubscribe |
| `email_sender.py` | HTML email builder (letterhead, stat card, CTA, CAN-SPAM footer) + `send_email` (Resend or SMTP) |
| `email_verifier.py` | syntax + MX verification |
| `enrichment/` | `website` (crawl + extract incl. schema.org rating), `ai_extract` (Gemini names, verified in text), `hunter`, `companies_house` (UK), `web_search` (ddgs: FB/IG/LinkedIn URLs), `reviews` (rating/count from site or review-site profile pages; strict name + slug match) |
| `llm.py` | shared Gemini client: `generate_text` / `generate_json` with 429 backoff |
| `suggestions.py` | `suggest_bundle()`: 3-5 niches + city, never searched or recently suggested; Gemini then catalog |
| `quota.py` | monthly Places call cap, counted in the `places_quota` table (old `quota_state.json` only seeds a month) |

## HTTP surface (`app.py`)
- Pages: `/`, `/login`, `/history` (also `/runs`, `/public`).
- Auth: `POST /api/auth/login|logout`.
- Leads/runs: `GET /api/leads[/{place_id}]`, `POST /api/leads/{place_id}/status`, `GET /api/runs`, `/api/runs/{id}/leads`, `/api/runs/{id}/csv`.
- Search: `POST /api/search` `{niches[], location, radius}` (starts pipeline thread), `WS /ws/{run_id}` (progress), `GET /api/suggest-target` (niche bundle + city).
- Email ops: `GET /api/email-logs`, `POST /api/email-logs/clear|retry-failed`, `GET /api/scheduler/status`, `POST /api/campaign/run_daily`.
- Compliance/tracking: `GET /api/track/open/{place_id}.png`, `GET /api/unsubscribe/{place_id}` (confirm page) + `POST` (unsubscribe, RFC 8058 one-click), `POST /api/webhooks/resend`, `GET /api/suppression`, `POST /api/suppression/add`.

## Frontend (`static/`, vanilla JS)
`index.html` + `app.js` (search dashboard, WebSocket), `history.html` + `history.js` (runs/leads/email log), `login.html`, `style.css`.

## Deploy
`Dockerfile` (non-root, uvicorn :8000) + `docker-compose.yml` (web + postgres:16, external network `securemonitor_default`, behind Caddy).
Push to `main` triggers `.github/workflows/deploy.yml`: SSH to VPS, `git pull`, `docker compose up -d --build`.

## Tests
`tests/` (pytest, no network/DB; externals monkeypatched). `bash scripts/agent/test.sh` runs them with `$PYTHON`, `./venv` or `./.venv` (install `requirements-dev.txt`).

## Invariants
- `BusinessState` is `total=False`: nodes read with `.get()` and return only the keys they set.
- Every outbound email carries the CAN-SPAM footer + unsubscribe link; suppressed addresses are never sent to.
- Daily send cap `MAX_DAILY_EMAILS`; send only inside the lead's local send window (`auto_campaign.py`).
- Email dedupe after enrichment must exclude the lead's own row (`is_email_already_contacted(..., exclude_place_id)`).
- Names from Gemini are kept only if they appear verbatim in the source text.
- A review count is used only from the business's own site or its own profile page on a review site (not "Top 10" lists, not similarly named businesses), with at least 3 reviews. Pitches never invent ratings.
- Every send goes through `app._send_next_due_lead()`: cap check, first in-window lead, atomic `claim_lead_for_sending` (`send_status='sending'`). A lead stuck in `sending` at startup becomes `failed`, never auto-resent.
