# GeoProspector AI

A self-hosted tool that finds local businesses with a weak web presence, checks their website, finds a contact, and drafts a short personal pitch you can review and send, or use as a phone script.

It runs on Google Maps data (Places API), a LangGraph pipeline, Gemini for the writing, PostgreSQL for storage, and a small FastAPI dashboard.

Nothing is sent without your approval. Auto-send is off by default.

## What it does

1. **Search.** Pulls up to 60 businesses per query (3 pages) from the Google Places API, skipping closed ones and duplicates.
2. **Check the website.** Classifies each business as `none`, `social_only` (Facebook, Instagram, Yelp and similar), `dead`, `outdated`, `good` or `unknown`.
   `unknown` means the site blocked the check or timed out. Those leads are kept for a manual look instead of being thrown away as "good".
3. **Audit live sites.** Runs the free Google PageSpeed API on the mobile version. A site that scores under 50 becomes a prospect, and the exact numbers go into the pitch.
4. **Find a contact.** Scrapes the site, then DuckDuckGo, then Hunter.io if you set a key. Addresses are ranked: a named person at the business's own domain beats `info@`, and `noreply@` style addresses are dropped. Then an MX check.
5. **Score.** 0 to 100, favouring businesses with a good reputation and a visible gap.
6. **Draft.** Gemini writes a short email built around one concrete finding ("on a phone your site scores 31/100 and takes 6 s to show anything"). It returns three subject lines and the plainest one is kept. Drafts are cleaned of em dashes and exclamation marks.
7. **You review.** Open a lead in the dashboard and press **Approve to send**, **Mark contacted**, **Replied** or **Reject**.
8. **Send and follow up.** If you turn auto-send on, approved leads go out at business hours in the lead's timezone, up to your daily cap. One short follow-up goes out after 5 days unless the lead replied, was rejected or unsubscribed. Then it stops.
9. **Call list.** `GET /api/call-list` (add `?format=csv` to download) returns leads with a phone number, best first, each with a short opener. For local trades businesses, a phone call often beats cold email.

## Run it on your PC

```bash
git clone https://github.com/Xbot-me/GeoProspector-AI.git
cd GeoProspector-AI
cp .env.example .env          # then fill it in

# Postgres in Docker, app in Python
docker compose -f docker-compose.local.yml up -d db
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python app.py                 # http://localhost:8000
```

Or run everything in Docker: `docker compose -f docker-compose.local.yml up -d --build`.

`docker-compose.yml` is the VPS setup (Caddy and an external `securemonitor_default` network). It is what `.github/workflows/deploy.yml` uses.

### What you need in `.env`

| Key | Needed for | Cost |
|---|---|---|
| `GOOGLE_PLACES_API_KEY` | Search | Free up to about 5,000 searches a month, but Google requires a billing account (card) on the project. |
| `GEMINI_API_KEY` | Drafting | Free tier, no card: https://aistudio.google.com |
| `DATABASE_URL` | Storage | Free (local Postgres) |
| `ADMIN_PASSWORD` | Dashboard login | A random one is printed at startup if empty |
| `RESEND_API_KEY` or SMTP settings | Sending | Free tiers exist. Only needed if you turn auto-send on |

Optional: `PAGESPEED_API_KEY` (higher rate limit for the audit), `HUNTER_API_KEY`. Everything is documented in `.env.example`.

Each Places page counts as one billable call, and `MAX_PLACES_CALLS_PER_MONTH` (default 4000) stops the app before the free tier runs out. That counter is local. Also set a budget alert in Google Cloud.

## Sending email without ending up in spam

Cold email is the easy part to get wrong. Before you turn on `AUTO_SEND_EMAILS`:

- **Use a separate sending domain or subdomain**, not your main business domain. Set SPF, DKIM and DMARC on it.
- **Warm it up** for 3 to 4 weeks before cold sends. Start at 5 to 10 emails a day (`MAX_DAILY_EMAILS`, default 10).
- **Unsubscribe links.** On a PC the app has no public URL, so leave `UNSUBSCRIBE_BASE_URL` empty. Emails then carry a `mailto:` unsubscribe, and open tracking is off. If you expose the app (for example through a Cloudflare Tunnel), set `UNSUBSCRIBE_BASE_URL` for one-click unsubscribe and open tracking.
- **Simulated sends.** With no Resend or SMTP credentials the app prints what it would send and records the lead as `simulated`, not `sent`.
- Keep spam complaints well under 0.3%. Gmail and Yahoo reject mail above that.

## Who to email

Cold B2B email is lawful with an opt-out in the US, Canada and Australia, among others. It needs prior consent in much of the EU (Germany, Spain, Italy and others) and for UK sole traders, and many trades businesses are sole traders. The default target list is limited to `OUTREACH_COUNTRIES=USA,Canada,Australia`. Check the rules for any country you add. This is not legal advice.

Every email includes your physical address (`SENDER_PHYSICAL_ADDRESS`) and an unsubscribe option, as CAN-SPAM requires.

Also be aware of the Google Maps Platform terms on caching and storing business data. Use this for your own lead generation, not for building a redistributable database.

## Writing better drafts

The prompt shows Gemini the sample emails in `prompts/pitch_examples.txt`. **Replace them with 2 or 3 emails in your own voice.** The closer they sound like you, the less the drafts read like a template.

Other knobs: `OUTREACH_LANGUAGE` (default English, or `auto`), `OFFER_FREE_MOCKUP` (off: only turn it on if you will build one for every reply), `FOLLOWUP_AFTER_DAYS`.

## Project layout

```
app.py              FastAPI dashboard, API, background sender
graph.py            LangGraph pipeline
nodes/              check_website, audit_site, find_email, find_socials,
                    score_lead, analyze_business, generate_pitch, save_to_crm,
                    places_search
email_sender.py     Resend / SMTP delivery and the HTML layout
followup.py         the one follow-up email
callscript.py       call list rows and openers
db.py               PostgreSQL schema and queries
prompts/            editable style examples for the drafter
tests/              pytest suite
```

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest tests -q                       # unit tests only (DB tests are skipped)
TEST_DATABASE_URL=postgresql://appuser:secretpassword@localhost:5432/geoprospector_test \
  python -m pytest tests -q                     # everything
```

The database tests truncate tables, so they only run against `TEST_DATABASE_URL`, never your real `DATABASE_URL`.

## Tech stack

Python, FastAPI, LangGraph, PostgreSQL 16, Google Places API (New), Google PageSpeed Insights, Gemini (Flash-Lite), Docker.

---
*Built for freelance web developers and small agencies selling to local service businesses.*
