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
from nodes.website_check import REAL_BROWSER_HEADERS

logger = logging.getLogger(__name__)

HUNTER_URL = "https://api.hunter.io/v2/domain-search"
DOMAIN_RE = re.compile(r"https?://(?:www\.)?([^/]+)")

# Regex for common email patterns (excluding image extensions, dummy domains)
_EMAIL_RE = re.compile(
    r"\b[A-Za-z0-9._%+-]+@(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}\b"
)
_IGNORE_DOMAINS = {
    "example.com", "domain.com", "yoursite.com", "email.com",
    "sentry.io", "wixpress.com", "squarespace.com",
}
_IGNORE_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".css", ".js")

_CONTACT_PATHS = ("/contact", "/about", "/contact-us", "/about-us", "/team")


def _extract_emails_from_text(text: str) -> list[str]:
    """Find valid email addresses in raw text/HTML."""
    raw = _EMAIL_RE.findall(text)
    clean = []
    for email in raw:
        email_lower = email.lower()
        domain = email_lower.split("@")[-1]
        if domain in _IGNORE_DOMAINS:
            continue
        if any(email_lower.endswith(ext) for ext in _IGNORE_EXTS):
            continue
        if email_lower not in clean:
            clean.append(email_lower)
    return clean


def _extract_domain(url: str | None) -> str | None:
    if not url:
        return None
    match = DOMAIN_RE.match(url)
    return match.group(1) if match else None


def _scrape_website_emails(website: str) -> str | None:
    """Check the business website and its contact/about pages for emails."""
    urls_to_check = [website]
    base = website.rstrip("/")
    for path in _CONTACT_PATHS:
        urls_to_check.append(f"{base}{path}")

    for url in urls_to_check:
        try:
            resp = requests.get(
                url, timeout=8, allow_redirects=True,
                headers=REAL_BROWSER_HEADERS,
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

    email = None
    source = None

    # 1. Scrape the business's own website
    if website:
        email = _scrape_website_emails(website)
        if email:
            source = "website_scrape"

    # 2. Search the web
    if not email:
        email = _search_web_for_email(name, address)
        if email:
            source = "web_search"

    # 3. Hunter.io fallback
    if not email:
        domain = _extract_domain(website)
        email = _hunter_search(domain)
        if email:
            source = "hunter"

    if not email:
        return {"email": None, "email_source": None, "email_verified": None}

    # 4. Verify email via MX record lookup
    try:
        from email_verifier import verify_email
        result = verify_email(email)
        verified = result.get("valid", None)
        if verified is False:
            logger.warning(f"Email verification failed for {email}: {result.get('reason')}")
        else:
            logger.info(f"Email verified: {email} (mx_found={result.get('mx_found')})")
    except Exception as e:
        logger.error(f"Email verification error for {email}: {e}")
        verified = None  # Fail-open: don't discard on verification errors

    return {"email": email, "email_source": source, "email_verified": verified}

