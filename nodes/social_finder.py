"""
Node: find_socials

Discovers Facebook, Instagram, and owner/contact name for the business
using DuckDuckGo web search. Does not duplicate work already done by
check_website (which may have already captured a social URL if the
business's "website" was just a Facebook page).

This node adds to the state -- it never overwrites a social URL that
check_website already found.
"""
import logging
import re

from config import ENABLE_WEB_SEARCH
from state import BusinessState

logger = logging.getLogger(__name__)

_FB_RE = re.compile(r"https?://(?:www\.)?facebook\.com/[^\s\"'<>,;]+")
_IG_RE = re.compile(r"https?://(?:www\.)?instagram\.com/[^\s\"'<>,;]+")

# Simple heuristic: look for "owner" or "manager" followed by a name.
_OWNER_RE = re.compile(
    r"(?:owner|proprietor|manager|founded by|run by)[:\s]+([A-Z][a-z]+ [A-Z][a-z]+)",
    re.IGNORECASE,
)


def find_socials(state: BusinessState) -> dict:
    if not ENABLE_WEB_SEARCH:
        return {}

    try:
        from duckduckgo_search import DDGS
    except ImportError:
        logger.warning("duckduckgo-search not installed, skipping social search")
        return {}

    name = state.get("name", "")
    address = state.get("address", "")
    parts = [p.strip() for p in address.split(",")]
    city = parts[0] if parts else ""

    result: dict = {}
    sources: list[str] = []

    try:
        with DDGS() as ddgs:
            # Search for Facebook page
            if not state.get("facebook_url"):
                fb_query = f'site:facebook.com "{name}" "{city}"'
                fb_results = list(ddgs.text(fb_query, max_results=3))
                for r in fb_results:
                    href = r.get("href", "")
                    if "facebook.com" in href:
                        # Clean the URL (remove query params)
                        clean = href.split("?")[0].rstrip("/")
                        result["facebook_url"] = clean
                        sources.append("ddg:facebook")
                        break

            # Search for Instagram page
            if not state.get("instagram_url"):
                ig_query = f'site:instagram.com "{name}" "{city}"'
                ig_results = list(ddgs.text(ig_query, max_results=3))
                for r in ig_results:
                    href = r.get("href", "")
                    if "instagram.com" in href:
                        clean = href.split("?")[0].rstrip("/")
                        result["instagram_url"] = clean
                        sources.append("ddg:instagram")
                        break

            # Try to find owner name (general search)
            if not state.get("owner_name"):
                owner_query = f'"{name}" "{city}" owner OR manager OR "founded by"'
                owner_results = list(ddgs.text(owner_query, max_results=5))
                for r in owner_results:
                    text = f"{r.get('title', '')} {r.get('body', '')}"
                    match = _OWNER_RE.search(text)
                    if match:
                        result["owner_name"] = match.group(1).strip()
                        sources.append("ddg:owner_search")
                        break

    except Exception as e:
        logger.warning(f"Social search failed: {e}")

    if sources:
        # Merge with any existing sources
        existing = state.get("contact_sources", "")
        all_sources = ([existing] if existing else []) + sources
        result["contact_sources"] = ", ".join(all_sources)

    return result
