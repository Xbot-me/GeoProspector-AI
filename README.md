# GeoProspector AI — Local Lead Generation & Automated Outreach

**GeoProspector AI** (formerly Maps Outreach Agent) is a powerful, self-hosted LangGraph agent and web dashboard designed to automate B2B lead generation. It scrapes Google Maps to find local businesses, enriches them with contact information, scores their digital presence, and uses AI to draft hyper-personalized cold outreach pitches.

Whether you run a web design agency, a marketing firm, or a SaaS company, GeoProspector AI allows you to instantly find high-ticket local clients (like roofers, HVAC contractors, and medi-spas) and extract their data with a single click.

![GeoProspector AI Dashboard](https://img.shields.io/badge/Status-Active-success) ![License](https://img.shields.io/badge/License-MIT-blue)

---

## 🚀 Key Features

* **Full-Radius Search on Free Open Data:** Finds every business for several niches at once inside a radius using [Overture Maps](https://overturemaps.org) places (free, no API key, includes listing emails and social links). Each area is downloaded once and cached. Google Places remains available as an optional provider (`PLACES_PROVIDER=google`).
* **Reviews Without Google:** Ratings and review counts come from the business's own website (schema.org ratings, review widgets) and from review-site profiles (Yelp, BBB, Birdeye, Angi, Houzz, ...), recorded with their source so pitches can say "your 127 reviews on Yelp".
* **Local Competition Angle:** Every pitch can cite how many competitors nearby have a website ("14 of 22 roofers within 5 km have a website").
* **Built-in AI Niche Generator:** Don't know who to target? The built-in Gemini AI niche generator brainstorms high-ticket, low-tech industries in booming US cities and auto-fills your search.
* **Deep Data Enrichment:** Crawls each business site (emails, phones, schema.org, Gemini-read team pages), Hunter.io people search, UK Companies House directors, and public LinkedIn/Facebook/Instagram profile URLs to identify the owner, their role and the best email.
* **Automated Website Auditing:** Analyzes business websites to detect outdated CMS versions, missing mobile optimization, parked domains, or "social-only" businesses with no real website.
* **Smart Lead Scoring:** Ranks prospects from 0-100 based on review count, rating, digital presence, and website quality so you can focus on the warmest leads.
* **AI-Personalized Cold Emails:** Uses Google's Gemini AI to write highly personalized, honest outreach pitches based on the business's actual Google reviews and website status.
* **Auto-CSV Export:** Automatically saves all extracted data and generated pitches to a CSV file on your server for easy import into your CRM.
* **Beautiful Web Dashboard:** A sleek, dark-mode real-time UI built with FastAPI and WebSockets to monitor the pipeline as it hunts for leads.

## 🛠️ Tech Stack
- **Backend:** Python, FastAPI, LangGraph, PostgreSQL
- **Frontend:** Vanilla HTML/CSS/JS (WebSockets for real-time updates)
- **AI Integrations:** Google Gemini (Flash-Lite), Google Places API (New)
- **Deployment:** Docker, Docker Compose (with PostgreSQL 16 service)

---

## 📦 Setup & Installation

GeoProspector AI is built for easy local usage or production deployment to a VPS.

### Option 1: Run Locally

```bash
git clone https://github.com/your-username/geoprospector-ai.git
cd geoprospector-ai
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Edit your `.env` file and add your `GEMINI_API_KEY`. Business data comes from Overture Maps by default (no key needed); set `PLACES_PROVIDER=google` and `GOOGLE_PLACES_API_KEY` to use Google Places instead. `HUNTER_API_KEY` and `COMPANIES_HOUSE_API_KEY` are optional extra contact sources.

Run the tests with `pip install -r requirements-dev.txt` then `pytest tests`.

Start the server:
```bash
python app.py
```
Open `http://localhost:8000` in your browser to access the dashboard.

### Option 2: Deploy to VPS (Docker Compose + Caddy)

The repository includes a production-ready `Dockerfile` running as a non-root user for security, and a `docker-compose.yml` configured to run behind a reverse proxy without exposing host ports.

1. Clone the repository on your VPS.
2. Configure your `.env` file.
3. Run Docker Compose:
```bash
docker compose up -d --build
```
4. If using Caddy, add this block to your global Caddyfile:
```caddyfile
leads.yourdomain.com {
    reverse_proxy maps-outreach-agent:8000
}
```

---

## 🧠 How the LangGraph Pipeline Works

GeoProspector AI isn't just a scraper; it's an intelligent multi-agent pipeline. For every business found on Google Maps, the agent executes the following workflow:

1. **Website Check:** Determines if the business has a modern website, an outdated website, or no website at all.
2. **Contact Discovery:** Runs multi-stage enrichment to hunt down the business owner's email and social media links.
3. **Lead Scoring:** Assigns a composite score. If the business already has a fantastic website, it skips generating a pitch but still extracts the data.
4. **AI Pitch Generation:** If the lead is qualified, the agent generates a custom cold email referencing their specific Google reviews and website flaws (e.g., pitching a modernization vs. a brand-new build).
5. **Database Storage:** Saves the business and the pitch to a PostgreSQL database and auto-exports to a CSV file.

## 💰 API Costs & Free Tiers

This tool is designed to cost **$0/month** to run:
- **Overture Maps (default):** Free. Data © Overture Maps Foundation, CDLA Permissive 2.0 / Apache 2.0 depending on source; keep this attribution if you publish the data.
- **Google Places API (optional):** The fields needed (website, phone, rating) are billed as Text Search Enterprise: 1,000 free calls/month, then about $35 per 1,000 (check your Cloud Console). One billed call returns up to 20 businesses; mapping the search area uses the free IDs-only tier. `MAX_PLACES_CALLS_PER_MONTH` (default 1000) stops runs before you exceed it.
- **Gemini API:** Uses the Gemini free tier (1,500 requests/day).
- **DuckDuckGo:** Free web search scraping.

## ⚠️ Compliance & Terms of Service

* **CAN-SPAM / GDPR:** If you decide to send cold emails to the leads generated by this tool, you must ensure you comply with CAN-SPAM laws (e.g., including an unsubscribe option and physical address) and GDPR regulations for B2B outreach in Europe.
* **Google Maps ToS:** Be aware of the Google Maps API Terms of Service regarding the caching and long-term storage of business data. This tool is intended for personal lead generation and direct outreach, not for building public redistributable databases.

---
*Built for local service web designers and B2B growth hackers.*
