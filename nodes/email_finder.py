"""
Node: find_email

Multi-source email discovery waterfall:

  1. Scrape the business's own website (contact/about pages) for emails
  2. Search DuckDuckGo for "{name} {city} email contact"
  3. Fall back to Hunter.io domain search (if API key is set)
  4. Return None honestly if nothing found

Each source is tried in order; the first valid email wins.
"""
import re
import logging

import requests

from config import ENABLE_WEB_SEARCH, HUNTER_API_KEY
from state import BusinessState

logger = logging.getLogger(__name__)

HUNTER_URL = "https://api.hunter.io/v2/domain-search"
DOMAIN_RE = re.compile(r"https?://(?:www\.)?([^/]+)")

# Matches most email-like strings, deliberately broad to catch edge cases.
EMAIL_RE = re.compile(
    r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"
)

# Common junk emails we should skip
_JUNK_EMAILS = {
    "noreply@", "no-reply@", "donotreply@", "mailer-daemon@",
    "postmaster@", "webmaster@", "abuse@", "hostmaster@",
    "example@", "test@", "admin@wix", "info@wix",
    "sentry@", "support@wordpress",
}

# Pages to check on a business website for contact info
_CONTACT_PATHS = ("/contact", "/contact-us", "/about", "/about-us", "/impressum")


def _is_junk_email(email: str) -> bool:
    email_lower = email.lower()
    return any(junk in email_lower for junk in _JUNK_EMAILS)


def _extract_domain(url: str | None) -> str | None:
    if not url:
        return None
    match = DOMAIN_RE.match(url)
    return match.group(1) if match else None


def _extract_emails_from_text(text: str) -> list[str]:
    """Find all email addresses in text, filter out junk."""
    found = EMAIL_RE.findall(text)
    return [e for e in found if not _is_junk_email(e)]


def _scrape_website_emails(website: str) -> str | None:
    """Check the business website and its contact/about pages for emails."""
    urls_to_check = [website]
    base = website.rstrip("/")
    for path in _CONTACT_PATHS:
        urls_to_check.append(f"{base}{path}")

    for url in urls_to_check:
        try:
            resp = requests.get(
                url, timeout=6, allow_redirects=True,
                headers={"User-Agent": "Mozilla/5.0 (compatible; OutreachBot/1.0)"},
            )
            if resp.status_code < 400:
                emails = _extract_emails_from_text(resp.text)
                if emails:
                    return emails[0]
        except requests.RequestException:
            continue
    return None


def _search_web_for_email(name: str, address: str) -> str | None:
    """Use DuckDuckGo to find email addresses for the business."""
    if not ENABLE_WEB_SEARCH:
        return None

    try:
        from duckduckgo_search import DDGS
    except ImportError:
        logger.warning("duckduckgo-search not installed, skipping web search")
        return None

    # Extract city from address (take the first two comma-separated parts)
    parts = [p.strip() for p in address.split(",")]
    city = parts[0] if parts else ""

    queries = [
        f'"{name}" "{city}" email',
        f'"{name}" "{city}" contact',
    ]

    try:
        with DDGS() as ddgs:
            for query in queries:
                results = list(ddgs.text(query, max_results=5))
                for result in results:
                    # Search in title + body snippet
                    text = f"{result.get('title', '')} {result.get('body', '')}"
                    emails = _extract_emails_from_text(text)
                    if emails:
                        return emails[0]
    except Exception as e:
        logger.warning(f"DuckDuckGo search failed: {e}")

    return None


def _hunter_search(domain: str) -> str | None:
    """Try Hunter.io domain search as a final fallback."""
    if not HUNTER_API_KEY or not domain:
        return None

    try:
        resp = requests.get(
            HUNTER_URL,
            params={"domain": domain, "api_key": HUNTER_API_KEY, "limit": 1},
            timeout=10,
        )
        if resp.status_code == 200:
            emails = resp.json().get("data", {}).get("emails", [])
            if emails:
                return emails[0]["value"]
    except requests.RequestException:
        pass
    return None


def find_email(state: BusinessState) -> dict:
    website = state.get("website")
    name = state.get("name", "")
    address = state.get("address", "")

    # 1. Scrape the business's own website
    if website:
        email = _scrape_website_emails(website)
        if email:
            return {"email": email, "email_source": "website_scrape"}

    # 2. Search the web
    email = _search_web_for_email(name, address)
    if email:
        return {"email": email, "email_source": "web_search"}

    # 3. Hunter.io fallback
    domain = _extract_domain(website)
    email = _hunter_search(domain)
    if email:
        return {"email": email, "email_source": "hunter"}

    return {"email": None, "email_source": None}
