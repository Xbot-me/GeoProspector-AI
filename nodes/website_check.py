"""
Node: check_website

Classifies the business's web presence into one of six levels:

  "none"        — no URL listed at all
  "social_only" — URL is just a Facebook/Instagram/Linktree page or a
                  directory listing (Yelp, Yellow Pages, ...)
  "dead"        — URL returns errors or the domain does not resolve
  "outdated"    — URL works but has red flags (ancient CMS, no mobile
                  viewport, old copyright year, under construction)
  "unknown"     — we could not tell: the site blocked us (403/429/WAF
                  challenge) or the connection timed out or was reset
  "good"        — a real, functional, reasonably modern website

"good" and "unknown" sites are not pitched. An unknown site is NOT a good
site: a bot firewall or a slow connection from the operator's country says
nothing about the site itself, so those leads are kept for manual review
instead of being silently discarded as good.
"""
import re
from datetime import datetime
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from state import BusinessState

SOCIAL_ONLY_HOSTS = (
    "facebook.com", "instagram.com", "wa.me", "linktr.ee",
    "tiktok.com", "linkedin.com",
    # directory listings are not a business's own website
    "yelp.com", "yellowpages.com", "angi.com", "angieslist.com", "thumbtack.com",
    "homeadvisor.com", "bbb.org", "nextdoor.com", "mapquest.com", "manta.com",
    "houzz.com", "porch.com", "yell.com", "checkatrade.com", "trustatrader.com",
)

# CMS generator strings that signal an outdated site
_OUTDATED_CMS_PATTERNS = (
    "wordpress 3", "wordpress 4",
    "joomla 1", "joomla 2", "joomla 3",
    "drupal 6", "drupal 7",
    "wix.com",  # not outdated per se, but very basic
)

_CONSTRUCTION_PHRASES = (
    "under construction",
    "coming soon",
    "site is being built",
    "launching soon",
    "parked domain",
    "this domain is for sale",
)

REAL_BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Connection": "keep-alive",
}

_WAF_PHRASES = (
    "just a moment...",
    "attention required! | cloudflare",
    "access denied",
    "sucuri website firewall",
    "security by imperva",
    "checking your browser",
    "enable javascript and cookies to continue",
    "please stand by, while we are checking your browser",
    "request blocked",
    "blocked by cloudflare",
)


def _check_quality(html: str) -> tuple[str, str]:
    """
    Analyze fetched HTML for red flags. Returns (quality, notes).
    """
    soup = BeautifulSoup(html, "html.parser")
    notes = []

    # 1. Check for construction / parked pages
    text_lower = soup.get_text(separator=" ", strip=True).lower()[:3000]
    for phrase in _CONSTRUCTION_PHRASES:
        if phrase in text_lower:
            return "outdated", f"Page contains '{phrase}'"

    # 2. Check meta generator for ancient CMS
    gen_tag = soup.find("meta", attrs={"name": "generator"})
    if gen_tag:
        gen = (gen_tag.get("content") or "").lower()
        for pattern in _OUTDATED_CMS_PATTERNS:
            if pattern in gen:
                notes.append(f"Old CMS: {gen_tag.get('content')}")

    # 3. No mobile viewport meta tag
    viewport = soup.find("meta", attrs={"name": "viewport"})
    if not viewport:
        notes.append("No mobile viewport meta tag")

    # 4. Copyright year is 3+ years old
    year_match = re.search(
        r"(?:©|copyright)\s*(\d{4})", text_lower
    )
    if year_match:
        year = int(year_match.group(1))
        if year <= datetime.now().year - 3:
            notes.append(f"Copyright year {year} is outdated")

    # If we found red flags, it's outdated
    if notes:
        return "outdated", "; ".join(notes)

    return "good", "Live, modern website"


_BLOCKED_STATUSES = (401, 403, 406, 429, 503, 509, 520, 521, 522, 523, 524, 525)
_DNS_FAILURE_HINTS = (
    "name or service not known", "nodename nor servname", "getaddrinfo failed",
    "temporary failure in name resolution", "nameresolutionerror", "no address associated",
)


def _is_social_or_directory(website: str) -> bool:
    host = (urlparse(website if "//" in website else f"//{website}").hostname or "").lower()
    return any(host == h or host.endswith("." + h) for h in SOCIAL_ONLY_HOSTS)


def _fetch(website: str) -> requests.Response:
    """GET the site, retrying once on timeouts/connection resets (home and
    foreign connections are flaky and get rate-limited by CDNs)."""
    last_exc: Exception | None = None
    for _ in range(2):
        try:
            return requests.get(
                website, timeout=12, allow_redirects=True,
                headers=REAL_BROWSER_HEADERS,
            )
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError,
                requests.exceptions.SSLError) as e:
            err = str(e).lower()
            # DNS failure and certificate errors are real answers, don't retry.
            if any(h in err for h in _DNS_FAILURE_HINTS) or "certificate" in err:
                raise
            last_exc = e
    assert last_exc is not None
    raise last_exc


def _unknown(note: str) -> dict:
    return {"has_real_website": True, "website_quality": "unknown", "website_notes": note}


def check_website(state: BusinessState) -> dict:
    website = state.get("website")

    if not website:
        return {
            "has_real_website": False,
            "website_quality": "none",
            "website_notes": "No website URL listed in Google Maps",
        }

    # A Facebook/Instagram/directory link isn't a real website for our
    # purposes. It's still a business worth pitching a proper site to.
    if _is_social_or_directory(website):
        social_data = {"has_real_website": False, "website_quality": "social_only"}
        if "facebook.com" in website:
            social_data["facebook_url"] = website
            social_data["website_notes"] = "Website is just a Facebook page"
        elif "instagram.com" in website:
            social_data["instagram_url"] = website
            social_data["website_notes"] = "Website is just an Instagram page"
        else:
            social_data["website_notes"] = f"Website is just a social or directory link: {website}"
        return social_data

    try:
        resp = _fetch(website)
    except requests.exceptions.SSLError as e:
        err = str(e).lower()
        if "certificate" in err:
            return {
                "has_real_website": True,
                "website_quality": "outdated",
                "website_notes": "SSL certificate error (browsers warn visitors away)",
            }
        return _unknown(f"TLS handshake failed, likely a bot firewall: {type(e).__name__}")
    except requests.exceptions.ConnectionError as e:
        if any(h in str(e).lower() for h in _DNS_FAILURE_HINTS):
            return {
                "has_real_website": False,
                "website_quality": "dead",
                "website_notes": "Domain does not resolve",
            }
        return _unknown(f"Connection dropped, could not check: {type(e).__name__}")
    except requests.exceptions.Timeout as e:
        return _unknown(f"Timed out twice, could not check: {type(e).__name__}")
    except requests.RequestException as e:
        return _unknown(f"Request failed, could not check: {type(e).__name__}")

    if resp.status_code in _BLOCKED_STATUSES:
        return _unknown(f"Blocked our check (HTTP {resp.status_code}), needs a manual look")
    if resp.status_code >= 400:
        return {
            "has_real_website": False,
            "website_quality": "dead",
            "website_notes": f"HTTP {resp.status_code}",
        }

    # A WAF challenge page can come back as HTTP 200
    text_lower = resp.text.lower()[:5000]
    for phrase in _WAF_PHRASES:
        if phrase in text_lower:
            return _unknown("Bot/WAF challenge page, could not read the site")

    quality, notes = _check_quality(resp.text)
    return {
        "has_real_website": quality == "good",
        "website_quality": quality,
        "website_notes": notes,
    }
