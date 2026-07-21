# Maps Outreach Agent

A LangGraph agent that finds nearby businesses on Google Maps, **enriches
them with email/social/quality data**, scores lead quality, drafts a
personalized outreach pitch, and sends it by email — with a mandatory
human approval step before anything goes out.

```
START
  |
  v
search_places  (Google Places API — Text/Nearby Search, New)
  |
  v
[loop over each business, one at a time]
  |
  +──> check_website        (classify: none / social_only / dead / outdated / good)
  |        |
  |        +── good website? → save + skip
  |        |
  |        +── prospect? → continue ↓
  |
  +──> find_email           (website scrape → DuckDuckGo search → Hunter.io)
  +──> find_socials         (DuckDuckGo: Facebook, Instagram, owner name)
  +──> score_lead           (0-100 composite score)
  |        |
  |        +── low score? → save + skip
  |        |
  |        +── qualified? → continue ↓
  |
  +──> analyze_business     (Gemini: enrichment-aware talking points)
  +──> generate_pitch       (Gemini: two-track — no site vs outdated)
  +──> save_to_crm          (local SQLite db)
  +──> human_approval       (interrupt() — you approve / edit / reject)
  +──> send_email           (SMTP — only runs if approved)
  |
  v
END + run summary
```

## What's new (v2)

- **Website quality analysis** — not just alive/dead. Detects outdated CMS
  versions, missing mobile viewport, old copyright years, parked/construction
  pages, and social-only listings.
- **Multi-source email discovery** — scrapes business websites (including
  `/contact` and `/about` pages), searches DuckDuckGo, then falls back to
  Hunter.io. Filters out junk emails automatically.
- **Social media discovery** — finds Facebook pages, Instagram profiles, and
  owner/manager names via web search.
- **Lead scoring** — 0-100 composite score based on website status, Google
  reviews/rating, email availability, social presence, and business category.
  Low-score leads are auto-skipped to save your time.
- **Honest AI prompts** — the pitch generator never claims fake experience or
  fabricated client lists. Two-track pitching: "build a website" vs "modernize
  your outdated site."
- **Run summary** — end-of-run stats showing how many leads were found,
  qualified, emailed, etc.

## Why it's built this way

- **One business at a time, not a giant fan-out.** LangGraph's `Send` API
  can fan work out in parallel, but combining that with per-branch
  `interrupt()` human approval is still a sharp edge in LangGraph as of
  mid-2026 (interrupts inside parallel `Send` branches can be fiddly to
  resume correctly). For a first working version, `main.py` invokes the
  graph **once per business**, each with its own `thread_id`, so every
  approval step is simple and unambiguous. Once this works end-to-end for
  you, batching/parallelizing is a small, safe follow-up change (see
  "Next steps" below).
- **Google Places API (New)**, not the legacy API — Google no longer allows
  new projects to enable the legacy Places API.
- **Field masking is mandatory.** Places API (New) bills you at the tier
  of the *most expensive field* in your request. This repo requests `rating`
  and `userRatingCount` (Pro-tier) alongside `websiteUri` (also Pro-tier),
  so no additional billing impact.
- **A local quota guard** (`quota.py`) tracks how many Places API calls
  you've made this calendar month in a small JSON file and refuses to make
  more once you hit the cap you set in `.env`. This is a *client-side*
  safety net, not a replacement for the budget alerts you should also set
  in Google Cloud Console.

## Setup

```bash
cd maps-outreach-agent
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Now edit `.env` yourself and fill in:

- `GOOGLE_PLACES_API_KEY` — **don't paste this into a chat with any AI,
  including this one.** Put it directly in your local `.env` file. Create
  it in Google Cloud Console → APIs & Services → Credentials, and restrict
  it (API restrictions → Places API only; and IP/application restrictions)
  before you ever run this.
- `GEMINI_API_KEY` — for business analysis + pitch writing, using Gemini's
  free tier. Get a key with no credit card at https://aistudio.google.com
  (this is separate from any Gemini Pro/Ultra app subscription — the
  subscription doesn't grant API quota on its own). The default model,
  `gemini-flash-lite-latest`, is one of the two model families Google
  kept free after restricting Pro models to paid/subscription access in
  April 2026; free-tier limits (roughly 15 requests/minute, 1,000/day) are
  far more than this repo needs.
- `SMTP_*` — for sending the actual emails (Gmail App Password works well
  for testing; see comments in `.env.example`).
- `HUNTER_API_KEY` — optional, only used as a third-tier fallback in email
  discovery after website scraping and DuckDuckGo search.
- `SENDER_NAME` — your name for the pitch sign-off. If blank, pitches sign
  off with `[Your Name]`.
- `MIN_LEAD_SCORE` — leads below this score (default 50) are auto-skipped.
- `ENABLE_WEB_SEARCH` — toggle DuckDuckGo email/social discovery (default
  true). Set to false if you only want website scraping + Hunter.io.

## Running it locally

```bash
python app.py
```
Then open `http://localhost:8000` in your browser.

This will:
1. Load the web dashboard (Sniper Mode).
2. Allow you to search Places API for businesses.
3. Automatically run every found business through the LangGraph pipeline in the background.
4. Classify each business's web presence and skip businesses with good websites.
5. Search for email addresses and social media profiles.
6. Analyze and generate a highly personalized pitch for each prospect.
7. Save everything to a local database.

You can then review the generated pitches in the dashboard, copy them to your clipboard, and manually send them via your own email client for perfect deliverability.

## Docker & Google Cloud (GCP) Deployment

This app is fully Dockerized and ready to be deployed to GCP (e.g. Cloud Run or a Compute Engine VM).

**1. Build the Docker Image**
```bash
docker build -t maps-outreach-agent .
```

**2. Run locally with Docker**
```bash
docker run -p 8000:8000 --env-file .env -v $(pwd)/data:/app/data maps-outreach-agent
```
*(Note: We mount the `/app/data` volume so your SQLite databases persist between container restarts).*

**3. Deploying to GCP Cloud Run**
Cloud Run is stateless. If you deploy there, your SQLite databases will be wiped every time the container spins down. To prevent this, you must mount a Cloud Storage FUSE volume or a Memorystore/Filestore volume to `/app/data`.

1. Push your image to Artifact Registry:
```bash
gcloud builds submit --tag gcr.io/YOUR_PROJECT_ID/maps-outreach-agent
```
2. Deploy to Cloud Run (with volume mount):
```bash
gcloud run deploy maps-outreach-agent \
  --image gcr.io/YOUR_PROJECT_ID/maps-outreach-agent \
  --port 8000 \
  --set-env-vars GOOGLE_PLACES_API_KEY="...",GEMINI_API_KEY="..." \
  --execution-environment gen2 \
  --add-volume name=data-vol,type=cloud-storage,bucket=YOUR_BUCKET_NAME \
  --add-volume-mount volume=data-vol,mount-path=/app/data
```
*(Make sure your Cloud Run service account has Storage Object Admin permissions).*

## Lead scoring rubric

| Signal | Points | Notes |
|--------|--------|-------|
| No website | +30 | Strongest signal of need |
| Social-only "website" | +25 | Has online awareness but no real site |
| Dead/outdated website | +20 | Still a good prospect |
| Google reviews ≥ 500 | +20 | Established business |
| Google reviews ≥ 100 | +15 | |
| Google reviews ≥ 20 | +10 | |
| Google rating ≥ 4.0 | +10 | Quality business |
| Email found | +15 | We can actually contact them |
| Phone listed | +5 | Reachable |
| Has Facebook/Instagram | +10 | Online-aware |
| High-value category | +10 | restaurant, hotel, salon, etc. |

Maximum possible score: 100. Default minimum to qualify: 50.

## Cost: this stack is $0/month

- Places API: free within quota (see below).
- Gemini Flash-Lite: free tier, well above what this repo needs.
- DuckDuckGo search: free, no API key.
- Gmail SMTP: free.
- Hunter.io: free tier if you enable it (25 lookups/month).

If you later want sharper copywriting than a Flash-Lite model gives you,
the pitch-generation node is the one place to swap in a paid model --
`nodes/pitch_generator.py` is a self-contained file, and keeping
`nodes/business_analyzer.py` on free Gemini while paying only for the
final pitch draft keeps costs minimal even then.

## Staying inside the free tier

As of the SKU-based pricing Google introduced in March 2025, Places API
(New) gives you **10,000 free calls/month for Essentials-tier fields**
(what this repo uses), 5,000/month for Pro-tier fields (adds rating,
website, etc.), separately. Since finding "no website" businesses
requires the `websiteUri` field, this repo's search node uses the
**Pro tier** for that reason — meaning your real free ceiling is
**5,000 search calls/month**, not 10,000. Config defaults are set far
below that (25 results per run) so you'd need ~200 runs in a month before
paying anything. Double check current SKU pricing/limits in your own
Cloud Console billing page — Google revises these periodically, and this
README's numbers were true as of mid-2026.

## What's stubbed / needs your judgment

- **Email finding** uses DuckDuckGo as the primary web search engine. It's
  free but rate-limited. If you need higher volume, swap in SerpAPI or
  Google Custom Search API in `nodes/email_finder.py`.
- **Compliance**: `nodes/email_sender.py` includes a CAN-SPAM footer
  (physical address placeholder + unsubscribe line) that you must fill in
  with your real business address before sending anything for real. If
  you're contacting anyone in the EU/UK, read up on GDPR's rules for B2B
  cold email before running this against real businesses.
- **Google Places API Terms of Service**: re-read the current ToS before
  storing scraped listing data long-term or using it for anything beyond
  contacting businesses about your own services once. Building a
  redistributable database of this data is against the terms.

## Next steps (not built yet, on purpose)

- Swap the "one business, one graph run" loop in `main.py` for a
  `Send`-based fan-out once you're comfortable with how `interrupt()`
  behaves in this codebase.
- Add a `PostgresSaver`/`SqliteSaver` checkpointer so approval can happen
  asynchronously (e.g., via a Slack bot) instead of blocking your
  terminal.
- Add a suppression-list check (people who've unsubscribed) to
  `email_sender.py` before every send — required for CAN-SPAM compliance
  in production use.
- Build a React dashboard to visualize leads, scores, and outreach status
  instead of the CLI.
