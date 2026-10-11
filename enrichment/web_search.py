"""
DuckDuckGo lookups for public profile URLs: Facebook, Instagram, LinkedIn
person and company pages, plus last-resort email and owner-name searches.

Only search-result titles/snippets/URLs are used; LinkedIn and Facebook pages
themselves are never fetched. Every hit must match the business (or person)
name, because search results often belong to a similarly named business.
"""
import logging
import re
import time

from config import ENABLE_WEB_SEARCH
from enrichment.website import EMAIL_RE, clean_email

logger = logging.getLogger(__name__)

_PAUSE_SECONDS = 1.0   # be gentle: DDG rate-limits bursts
_AD_HOSTS = ("bing.com/aclick", "duckduckgo.com/y.js", "/aclk?")
_STOPWORDS = {"the", "and", "of", "llc", "inc", "ltd", "co", "company", "services", "service", "&"}

_OWNER_RE = re.compile(
    r"(?:owner|proprietor|founder|founded by|run by|managing director|ceo)[:,\s]+([A-Z][a-z]+(?: [A-Z][a-z]+){1,2})"
)


def _ddgs():
    try:
        from ddgs import DDGS
    except ImportError:
        from duckduckgo_search import DDGS  # older package name
    return DDGS


def search(query: str, max_results: int = 5) -> list[dict]:
    """Tolerant search: returns [] on any error, no results or disabled web search."""
    if not ENABLE_WEB_SEARCH:
        return []
    try:
        results = _ddgs()().text(query, max_results=max_results) or []
    except Exception as e:  # ddgs raises when nothing is found; rate limits too
        logger.debug(f"Web search failed for {query!r}: {e}")
        results = []
    time.sleep(_PAUSE_SECONDS)
    return [r for r in results if not any(a in (r.get("href") or "") for a in _AD_HOSTS)]


def name_tokens(name: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", (name or "").lower())
    return {w for w in words if w not in _STOPWORDS and len(w) > 1}


def matches_business(text: str, business_name: str, threshold: float = 0.6) -> bool:
    """True when most significant words of the business name appear in text."""
    wanted = name_tokens(business_name)
    if not wanted:
        return False
    have = name_tokens(text)
    return len(wanted & have) / len(wanted) >= threshold


def city_from_address(address: str) -> str:
    """'1 Main St, Austin, TX 78701, USA' -> 'Austin'; '2 Rue X, 75001 Paris, France' -> 'Paris'."""
    parts = [p.strip() for p in (address or "").split(",") if p.strip()]
    if len(parts) >= 4:
        candidate = parts[-3]          # street, city, region+postcode, country
    elif len(parts) >= 2:
        candidate = parts[-2]          # street, postcode+city, country
    else:
        candidate = parts[0] if parts else ""
    words = [w for w in candidate.split() if not any(ch.isdigit() for ch in w)]
    return " ".join(words)


_city = city_from_address


def _clean_url(href: str) -> str:
    return href.split("?")[0].rstrip("/")


def find_social(business_name: str, address: str, site: str) -> str | None:
    """site is 'facebook.com' or 'instagram.com'."""
    for r in search(f'site:{site} "{business_name}" {_city(address)}', 3):
        href = r.get("href") or ""
        if site in href and matches_business(f"{r.get('title', '')} {href.replace('.', ' ').replace('/', ' ')}", business_name):
            return _clean_url(href)
    return None


def _parse_linkedin_title(title: str) -> tuple[str, str | None, str | None]:
    """'Jane Doe - Owner - Acme Roofing | LinkedIn' -> ('Jane Doe', 'Owner', 'Acme Roofing')."""
    title = re.sub(r"\s*[|·]\s*LinkedIn.*$", "", title).strip()
    parts = [p.strip() for p in re.split(r"\s+[-–—]\s+", title) if p.strip()]
    name = parts[0] if parts else ""
    role = parts[1] if len(parts) >= 3 else None
    company = parts[-1] if len(parts) >= 2 else None
    return name, role, company


def find_company_linkedin(business_name: str, address: str) -> str | None:
    for r in search(f'site:linkedin.com/company "{business_name}" {_city(address)}', 3):
        href = r.get("href") or ""
        if "linkedin.com/company/" in href and matches_business(r.get("title", ""), business_name):
            return _clean_url(href)
    return None


def find_person_linkedin(person_name: str, business_name: str) -> str | None:
    """LinkedIn profile URL of a known person, verified by name in the result title."""
    wanted = name_tokens(person_name)
    for r in search(f'site:linkedin.com/in "{person_name}" "{business_name}"', 3):
        href = r.get("href") or ""
        name, _, _ = _parse_linkedin_title(r.get("title", ""))
        if "linkedin.com/in/" in href and wanted and wanted <= name_tokens(name):
            return _clean_url(href)
    return None


def find_owner_on_linkedin(business_name: str, address: str) -> dict | None:
    """Owner/founder profile at this business: {"name", "role", "linkedin"}."""
    query = f'site:linkedin.com/in "{business_name}" (owner OR founder OR president OR director) {_city(address)}'
    for r in search(query, 5):
        href = r.get("href") or ""
        if "linkedin.com/in/" not in href:
            continue
        name, role, company = _parse_linkedin_title(r.get("title", ""))
        if len(name.split()) >= 2 and company and matches_business(company, business_name):
            return {"name": name, "role": role, "linkedin": _clean_url(href), "source": "linkedin_search"}
    return None


def find_owner_name(business_name: str, address: str) -> dict | None:
    """Last resort: 'owner: Jane Doe' style mentions in search snippets about this business."""
    for r in search(f'"{business_name}" {_city(address)} owner OR founder OR "run by"', 5):
        text = f"{r.get('title', '')} {r.get('body', '')}"
        if not matches_business(text, business_name):
            continue
        if m := _OWNER_RE.search(text):
            return {"name": m.group(1).strip(), "role": "Owner", "source": "web_search"}
    return None


def find_emails(business_name: str, address: str, domain: str | None) -> list[dict]:
    """Emails in search snippets. Kept only if on the business domain, or (no site)
    when the snippet is clearly about this business."""
    found = []
    for r in search(f'"{business_name}" {_city(address)} email', 5):
        text = f"{r.get('title', '')} {r.get('body', '')}"
        for raw in EMAIL_RE.findall(text):
            email = clean_email(raw)
            if not email:
                continue
            on_domain = domain and email.endswith("@" + domain)
            if on_domain or (not domain and matches_business(text, business_name)):
                if email not in {e["value"] for e in found}:
                    found.append({"value": email, "source": "web_search"})
    return found
