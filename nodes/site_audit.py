"""
Node: audit_site

Measures how a live website actually performs on a phone using the free
Google PageSpeed Insights API (Lighthouse). A concrete number ("scores 31/100
on mobile, 6.2 s to show the main content") is a far better reason to get in
touch than a vague "your site looks dated", and it lets us find sites the
HTML heuristics in check_website call "good" that are in fact painfully slow.

Only runs for sites check_website found live ("good" or "outdated"). If the
API is unreachable, rate-limited, or the site cannot be tested, this node
changes nothing.
"""
import logging

import requests

from config import ENABLE_PAGESPEED, PAGESPEED_API_KEY, PAGESPEED_SLOW_THRESHOLD
from state import BusinessState

logger = logging.getLogger(__name__)

PAGESPEED_URL = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"


def run_pagespeed(url: str) -> tuple[int, str | None] | None:
    """Return (mobile performance score 0-100, LCP display text) or None."""
    params = {"url": url, "strategy": "mobile", "category": "performance"}
    if PAGESPEED_API_KEY:
        params["key"] = PAGESPEED_API_KEY
    try:
        resp = requests.get(PAGESPEED_URL, params=params, timeout=90)
        if resp.status_code != 200:
            logger.info("PageSpeed returned HTTP %s for %s", resp.status_code, url)
            return None
        lh = resp.json().get("lighthouseResult", {})
        raw = lh.get("categories", {}).get("performance", {}).get("score")
        if raw is None:
            return None
        lcp = lh.get("audits", {}).get("largest-contentful-paint", {}).get("displayValue")
        return round(raw * 100), lcp
    except (requests.RequestException, ValueError) as e:
        logger.info("PageSpeed failed for %s: %s", url, e)
        return None


def audit_site(state: BusinessState) -> dict:
    website = state.get("website")
    quality = state.get("website_quality")
    if not ENABLE_PAGESPEED or not website or quality not in ("good", "outdated"):
        return {}

    result = run_pagespeed(website)
    if result is None:
        return {}
    score, lcp = result

    out: dict = {"pagespeed_score": score, "pagespeed_lcp": lcp}
    if score < PAGESPEED_SLOW_THRESHOLD:
        finding = f"Mobile PageSpeed score {score}/100"
        if lcp:
            finding += f", main content takes {lcp} to appear"
        notes = state.get("website_notes") or ""
        out["website_quality"] = "outdated"
        out["has_real_website"] = False
        out["website_notes"] = f"{notes}; {finding}".strip("; ") if quality == "outdated" else finding
    return out
