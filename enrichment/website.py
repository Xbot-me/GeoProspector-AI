"""
Crawl a business website (home + contact/about/team pages) and extract
contact data printed on it.
"""
import json
import re
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from nodes.website_check import REAL_BROWSER_HEADERS

MAX_PAGES = 6
PAGE_TEXT_LIMIT = 8000

# Link text / paths that usually lead to people or contact details (several languages).
_INTERESTING = re.compile(
    r"contact|about|team|staff|people|our-story|who-we-are|meet|leadership|owner|founder|"
    r"impressum|kontakt|ueber-uns|uber-uns|contacto|nosotros|equipo|equipe|a-propos|qui-sommes|"
    r"chi-siamo|contatti|over-ons|om-oss|yhteystiedot|meista",
    re.IGNORECASE,
)
_FALLBACK_PATHS = ("/contact", "/contact-us", "/about", "/about-us", "/team", "/our-team")

EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}\b")
_IGNORE_EMAIL_DOMAINS = {
    "example.com", "domain.com", "yoursite.com", "email.com", "yourdomain.com",
    "sentry.io", "wixpress.com", "squarespace.com", "sentry-next.wixpress.com",
    "godaddy.com", "wordpress.com", "schema.org",
}
_IGNORE_EMAIL_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".css", ".js")
_IGNORE_LOCAL_PARTS = ("noreply", "no-reply", "donotreply", "do-not-reply", "privacy", "abuse", "postmaster")

SOCIAL_PATTERNS = {
    "facebook_url": re.compile(r"^https?://(?:[a-z]+\.)?facebook\.com/(?!sharer|share|plugins|tr\b|dialog)[^?#]+", re.I),
    "instagram_url": re.compile(r"^https?://(?:www\.)?instagram\.com/(?!p/|share)[^?#]+", re.I),
    "company_linkedin": re.compile(r"^https?://(?:[a-z]+\.)?linkedin\.com/company/[^?#]+", re.I),
    "person_linkedin": re.compile(r"^https?://(?:[a-z]+\.)?linkedin\.com/in/[^?#]+", re.I),
    "twitter_url": re.compile(r"^https?://(?:www\.)?(?:twitter|x)\.com/(?!share|intent|home)[^?#]+", re.I),
    "youtube_url": re.compile(r"^https?://(?:www\.)?youtube\.com/(?:@|c/|channel/|user/)[^?#]+", re.I),
    "tiktok_url": re.compile(r"^https?://(?:www\.)?tiktok\.com/@[^?#]+", re.I),
}


def site_domain(website: str | None) -> str | None:
    if not website:
        return None
    host = urlparse(website if "://" in website else f"http://{website}").hostname or ""
    host = host.lower()
    return host[4:] if host.startswith("www.") else host or None


def _fetch(url: str) -> str | None:
    try:
        resp = requests.get(url, timeout=8, allow_redirects=True, headers=REAL_BROWSER_HEADERS)
    except requests.RequestException:
        return None
    if resp.status_code >= 400 or "html" not in resp.headers.get("Content-Type", "html"):
        return None
    return resp.text


def decode_cfemail(encoded: str) -> str | None:
    """Cloudflare 'email protection' hides addresses as data-cfemail hex."""
    try:
        key = int(encoded[:2], 16)
        return "".join(chr(int(encoded[i:i + 2], 16) ^ key) for i in range(2, len(encoded), 2))
    except ValueError:
        return None


def clean_email(raw: str) -> str | None:
    email = raw.strip().strip(".").lower()
    if not EMAIL_RE.fullmatch(email):
        return None
    local, domain = email.rsplit("@", 1)
    if domain in _IGNORE_EMAIL_DOMAINS or email.endswith(_IGNORE_EMAIL_EXTS):
        return None
    if any(local.startswith(p) for p in _IGNORE_LOCAL_PARTS):
        return None
    return email


def crawl(website: str) -> list[tuple[str, str]]:
    """Fetch the home page plus up to MAX_PAGES-1 same-site contact/about/team pages."""
    home = _fetch(website)
    if home is None:
        return []
    pages = [(website, home)]
    host = urlparse(website).hostname
    soup = BeautifulSoup(home, "html.parser")

    candidates: list[str] = []
    for a in soup.find_all("a", href=True):
        url = urljoin(website, a["href"]).split("#")[0]
        if urlparse(url).hostname != host or url.rstrip("/") == website.rstrip("/"):
            continue
        if _INTERESTING.search(url) or _INTERESTING.search(a.get_text(" ", strip=True)):
            if url not in candidates:
                candidates.append(url)
    if not candidates:
        base = website.rstrip("/")
        candidates = [base + p for p in _FALLBACK_PATHS]

    for url in candidates[: MAX_PAGES - 1]:
        html = _fetch(url)
        if html:
            pages.append((url, html))
    return pages


def _walk_jsonld(node, people: list, org: dict) -> None:
    if isinstance(node, list):
        for item in node:
            _walk_jsonld(item, people, org)
        return
    if not isinstance(node, dict):
        return
    types = node.get("@type")
    types = [types] if isinstance(types, str) else (types or [])
    if "Person" in types and isinstance(node.get("name"), str):
        people.append({"name": node["name"].strip(), "role": (node.get("jobTitle") or "").strip() or None,
                       "email": node.get("email"), "phone": node.get("telephone")})
    for key in ("founder", "employee", "employees", "owner", "member", "founders"):
        value = node.get(key)
        if value:
            if isinstance(value, dict) and value.get("name") and "@type" not in value:
                value = {**value, "@type": "Person"}
            if isinstance(value, dict) and not value.get("jobTitle") and key in ("founder", "founders", "owner"):
                value = {**value, "jobTitle": "Owner" if key == "owner" else "Founder"}
            _walk_jsonld(value, people, org)
    if any(t for t in types if t not in ("Person", "WebPage", "WebSite", "BreadcrumbList")):
        if isinstance(node.get("aggregateRating"), dict) and "aggregate_rating" not in org:
            org["aggregate_rating"] = node["aggregateRating"]
        for key in ("email", "telephone"):
            if isinstance(node.get(key), str):
                org.setdefault(key + "s", []).append(node[key])
        same_as = node.get("sameAs")
        if same_as:
            org.setdefault("sameAs", []).extend([same_as] if isinstance(same_as, str) else same_as)
    for key in ("@graph", "mainEntity", "author", "publisher"):
        if key in node:
            _walk_jsonld(node[key], people, org)


def extract(pages: list[tuple[str, str]]) -> dict:
    """Pull emails, phones, social links, schema.org people and page text from crawled pages."""
    emails: dict[str, str] = {}      # email -> page url
    phones: list[str] = []
    socials: dict[str, str] = {}
    people: list[dict] = []
    org: dict = {}
    texts: list[str] = []

    for url, html in pages:
        soup = BeautifulSoup(html, "html.parser")

        for script in soup.find_all("script", type="application/ld+json"):
            try:
                _walk_jsonld(json.loads(script.string or ""), people, org)
            except (json.JSONDecodeError, TypeError):
                continue

        for tag in soup.find_all(attrs={"data-cfemail": True}):
            decoded = decode_cfemail(tag["data-cfemail"])
            if decoded and (email := clean_email(decoded)):
                emails.setdefault(email, url)

        hrefs = []
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if href.lower().startswith("mailto:"):
                if email := clean_email(href[7:].split("?")[0]):
                    emails.setdefault(email, url)
            elif href.lower().startswith("tel:"):
                phone = re.sub(r"[^\d+]", "", href[4:])
                if len(re.sub(r"\D", "", phone)) >= 7 and phone not in phones:
                    phones.append(phone)
            else:
                hrefs.append(urljoin(url, href))

        for link in hrefs + [s for s in org.get("sameAs", []) if isinstance(s, str)]:
            for key, pattern in SOCIAL_PATTERNS.items():
                if key not in socials and (m := pattern.match(link)):
                    socials[key] = m.group(0).rstrip("/")

        for script in soup(["script", "style", "noscript"]):
            script.decompose()
        text = soup.get_text(" ", strip=True)
        for raw in EMAIL_RE.findall(text):
            if email := clean_email(raw):
                emails.setdefault(email, url)
        texts.append(text)

    for email in org.get("emails", []):
        if email := clean_email(email.replace("mailto:", "")):
            emails.setdefault(email, "schema.org")
    for phone in org.get("telephones", []):
        if phone not in phones:
            phones.append(phone)

    # Home page text last: about/team pages are the useful part for people extraction.
    combined = " \n".join(texts[1:] + texts[:1])
    return {
        "emails": [{"value": e, "source": "website", "page": p} for e, p in emails.items()],
        "phones": phones,
        "socials": socials,
        "people": [{**p, "source": "website_schema"} for p in people if p.get("name")],
        "aggregate_rating": org.get("aggregate_rating"),
        "text": combined[:PAGE_TEXT_LIMIT],
    }
