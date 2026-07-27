"""
Node: check_website

Classifies the business's web presence into one of five levels:

  "none"        — no URL listed at all
  "social_only" — URL is just a Facebook/Instagram/Linktree page
  "dead"        — URL returns errors or times out
  "outdated"    — URL works but has red flags (ancient CMS, no mobile
                  viewport, old copyright year, under construction)
  "good"        — a real, functional, reasonably modern website

Only "good" websites cause the pipeline to skip a business entirely.
Everything else is a prospect worth enriching.
"""
import re
from datetime import datetime

import requests
from bs4 import BeautifulSoup

from state import BusinessState

SOCIAL_ONLY_HOSTS = ("facebook.com", "instagram.com", "wa.me", "linktr.ee")

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


def check_website(state: BusinessState) -> dict:
    website = state.get("website")

    if not website:
        return {
            "has_real_website": False,
            "website_quality": "none",
            "website_notes": "No website URL listed in Google Maps",
        }

    # A Facebook/Instagram/Linktree link isn't a real website for our
    # purposes — it's still a business worth pitching a proper site to.
    if any(host in website for host in SOCIAL_ONLY_HOSTS):
        # Extract the social URL for later use
        social_data = {"has_real_website": False, "website_quality": "social_only"}
        if "facebook.com" in website:
            social_data["facebook_url"] = website
            social_data["website_notes"] = "Website is just a Facebook page"
        elif "instagram.com" in website:
            social_data["instagram_url"] = website
            social_data["website_notes"] = "Website is just an Instagram page"
        else:
            social_data["website_notes"] = f"Website is just a social link: {website}"
        return social_data

    # Try to fetch the actual page with realistic desktop browser headers
    try:
        resp = requests.get(
            website, timeout=10, allow_redirects=True,
            headers=REAL_BROWSER_HEADERS,
        )
        if resp.status_code in (403, 406, 429, 503, 509, 520, 521, 522, 523, 524, 525):
            return {
                "has_real_website": True,
                "website_quality": "good",
                "website_notes": f"Live website (protected by firewall/bot defense: HTTP {resp.status_code})",
            }
        if resp.status_code >= 400:
            return {
                "has_real_website": False,
                "website_quality": "dead",
                "website_notes": f"HTTP {resp.status_code}",
            }
        
        # Check if page content returned a Cloudflare or WAF challenge page despite HTTP 200/300
        text_lower = resp.text.lower()[:5000]
        for phrase in _WAF_PHRASES:
            if phrase in text_lower:
                return {
                    "has_real_website": True,
                    "website_quality": "good",
                    "website_notes": "Live website (protected by Cloudflare/WAF challenge)",
                }

    except (requests.exceptions.SSLError, requests.exceptions.ReadTimeout, requests.exceptions.ConnectionError) as e:
        # Some WAFs (like Cloudflare or Sucuri) drop TLS/TCP connections from automated crawlers or foreign VPS IPs
        err_str = str(e).lower()
        if "ssl" in err_str or "handshake" in err_str or "read timed out" in err_str or "reset by peer" in err_str:
            return {
                "has_real_website": True,
                "website_quality": "good",
                "website_notes": f"Live website (bot/location firewall dropped connection: {type(e).__name__})",
            }
        return {
            "has_real_website": False,
            "website_quality": "dead",
            "website_notes": f"Connection failed: {type(e).__name__}",
        }
    except requests.RequestException as e:
        return {
            "has_real_website": False,
            "website_quality": "dead",
            "website_notes": f"Connection failed: {type(e).__name__}",
        }

    # Page loaded — analyze quality
    quality, notes = _check_quality(resp.text)

    return {
        "has_real_website": quality == "good",
        "website_quality": quality,
        "website_notes": notes,
    }
