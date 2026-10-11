# Module map

Read this before searching the source. Line numbers drift; use `bash scripts/agent/where.sh '<regex>'` to confirm.

## Entry points
| File | Role |
|---|---|
| `app.py` | FastAPI app: routes, cookie auth middleware, WebSocket progress, pipeline thread (links every found business to the run, reuses already-enriched leads, skips only sent/unsubscribed), outreach-kit and single-lead send endpoints. No background sender: outreach is manual. Read by region. |
| `main.py` | Older CLI runner for the pipeline (interactive approval prompt). |
| `auto_campaign.py` | Worldwide target catalog (`catalog/target_catalog.json`, 118 locations + niche reference) with cluster-aware rotation; lead timezone lookup (stored tz > city > country). |

## Pipeline (`graph.py`, state in `state.py`)
`check_website -> find_contacts -> score_lead -> (good site? save_to_crm_skip : analyze_business -> generate_outreach_kit -> save_to_crm)`.
Checkpointer: Postgres via `get_checkpointer_cm()`.

| Node (`nodes/`) | Does |
|---|---|
| `area_search.py` | provider switch (`PLACES_PROVIDER`): `overture` (default) or `google`; same `search_area()` / `search_businesses()` contract |
| `places_overture.py` | Overture Maps places via DuckDB (memory-capped: `DUCKDB_MEMORY_LIMIT` 256MB, `DUCKDB_THREADS` 1 for Render free). Area modes: `auto` (requested radius; if < 20 matches, downloads the 40 km range once and widens 2x locally), `radius`, `city` (Nominatim boundary, max 60 km). Areas cached in `data/overture_cache/`. Niche -> categories: `NicheMatcher` curated map (used only when it explains every core word; marketing adjectives ignored), else Gemini picks from the categories actually present in the area (`ai_map_categories`, validated), else word matching on the category's own name; plus name match for generic `contractor`. Only matching rows are read into Python. Drops closed/low-confidence, merges duplicate listings. |
| `places_search.py` | Google provider. `search_area(niches, location, radius)`: finds every business in the circle. Free IDs-only pass splits tiles that hit Google's 60-result cap; billed pass only on leaf tiles with unknown places. Drops closed/outside-radius, adds coordinates + timezone. |
| `website_check.py` | classifies `website_quality`: none / dead / social_only / outdated / good |
| `contact_finder.py` | combines `enrichment/*` sources; picks owner (role priority) and send email (own domain > owner > generic); full detail in `contacts_json` |
| `lead_scorer.py` | 0-100 score + breakdown |
| `business_analyzer.py` | Gemini analysis of the business |
| `outreach_kit_generator.py` | Gemini outreach kit: analysis, Lovable/v0 mockup prompt, email draft with `[MOCKUP_LINK]` placeholder (uses reviews, competitor line, owner role) |
| `crm_writer.py` | upsert to DB via `db.py` |

## Support modules
| File | Role |
|---|---|
| `config.py` | all env vars + defaults (provider, keys, limits, email provider, admin auth; normalises Render `postgres://` URLs) |
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
- Outreach: `POST /api/leads/{id}/build-kit` (regenerate kit), `POST /api/leads/{id}/send` (real send; refuses `[MOCKUP_LINK]`, suppressed or already-sent leads), `POST /api/leads/{id}/status` (manual sent/not_sent/rejected + draft edits), `GET /api/email-logs`, `POST /api/email-logs/clear`, `GET /api/export` (all leads CSV).
- Compliance/tracking: `GET /api/track/open/{place_id}.png`, `GET /api/unsubscribe/{place_id}` (confirm page) + `POST` (unsubscribe, RFC 8058 one-click), `POST /api/webhooks/resend`, `GET /api/suppression`, `POST /api/suppression/add`.

## Frontend (`static/`, vanilla JS)
`index.html` + `app.js` (search dashboard, WebSocket), `history.html` + `history.js` (runs/leads/email log), `login.html`, `style.css`.

## Deploy
`Dockerfile` (non-root, uvicorn :8000) + `docker-compose.yml` (web + postgres:16, external network `securemonitor_default`, behind Caddy).
Production: Render web service `maps-outreach-agent` (Docker, `$PORT`) + Render Postgres `outreach-db`; auto-deploys on commit to its tracked branch. `docker-compose.yml` remains for self-hosting.

## Tests
`tests/` (pytest, no network/DB; externals monkeypatched). `bash scripts/agent/test.sh` runs them with `$PYTHON`, `./venv` or `./.venv` (install `requirements-dev.txt`).

## Invariants
- `BusinessState` is `total=False`: nodes read with `.get()` and return only the keys they set.
- Every outbound email carries the CAN-SPAM footer + unsubscribe link; suppressed addresses are never sent to.
- Daily send cap `MAX_DAILY_EMAILS`; send only inside the lead's local send window (`auto_campaign.py`).
- Email dedupe after enrichment must exclude the lead's own row (`is_email_already_contacted(..., exclude_place_id)`).
- Names from Gemini are kept only if they appear verbatim in the source text.
- A review count is used only from the business's own site or its own profile page on a review site (not "Top 10" lists, not similarly named businesses), with at least 3 reviews. Pitches never invent ratings.
- Every send goes through `/api/leads/{id}/send` with an atomic `claim_lead_for_sending` (`send_status='sending'`). A lead stuck in `sending` at startup becomes `failed`, never auto-resent.
