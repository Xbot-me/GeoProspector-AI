"""
Ratings and review counts without Google Places.

Sources, free, in order of trust:
  1. The business's own website: schema.org AggregateRating, or review widgets
     ("4.9 stars from 213 Google reviews")
  2. Search-result snippets from review sites (Yelp, BBB, Angi, Houzz,
     Facebook, Nextdoor, Trustpilot, Checkatrade, ...). Only results whose
     title matches the business name are used; the site is recorded so a pitch
     can say "your 127 reviews on Yelp".

Returns {"rating", "review_count", "review_source", "review_url"} or None.
"""
import logging
import re

from enrichment.web_search import city_from_address, matches_business, name_tokens, search

logger = logging.getLogger(__name__)

REVIEW_SITES = {
    "yelp.": "Yelp", "bbb.org": "BBB", "angi.com": "Angi", "angieslist.com": "Angi",
    "homeadvisor.com": "HomeAdvisor", "houzz.": "Houzz", "facebook.com": "Facebook",
    "nextdoor.com": "Nextdoor", "thumbtack.com": "Thumbtack", "trustpilot.com": "Trustpilot",
    "yellowpages.": "YellowPages", "birdeye.com": "Birdeye", "porch.com": "Porch",
    "checkatrade.com": "Checkatrade", "trustatrader.com": "TrustATrader", "yell.com": "Yell",
    "mybuilder.com": "MyBuilder", "ratedpeople.com": "Rated People", "google.com": "Google",
    "productreview.com.au": "ProductReview", "hipages.com.au": "hipages", "homestars.com": "HomeStars",
}

MIN_REVIEWS = 3   # fewer is not worth quoting in a pitch

# Numbers must stand alone: "22 Reviews" must not read as rating 2 + count 2.
_NUM = r"(?<![\d.,])(\d{1,3}(?:,\d{3})+|\d+)(?![\d.,]\d)"
_UNIT = r"(?:\s*/\s*5|\s*out of 5|\s*stars?|\s*★)"
# A rating needs a decimal ("4.8") or an explicit 5-point unit ("5 stars", "4/5").
_RATING = r"(?<![\d.,])([1-5][.,]\d{1,2}(?![\d])" + _UNIT + r"?|[1-5]" + _UNIT + r")"
_REVIEWS_WORD = r"\+?\s*(?:verified\s+|google\s+|customer\s+|client\s+|5[- ]star\s+)?(?:reviews?|ratings?)\b"
# "4.8 stars from 213 reviews", "Rated 4.9/5 based on 127 Google reviews", "4.5 (38 reviews)"
_RATING_THEN_COUNT = re.compile(_RATING + r"[^\d\n]{0,40}?" + _NUM + _REVIEWS_WORD, re.I)
# "213 Google reviews · 4.9 ★", "127 reviews with an average of 4.8"
_COUNT_THEN_RATING = re.compile(_NUM + _REVIEWS_WORD + r"[^\d\n]{0,40}?" + _RATING, re.I)
# "Rating: 4.7 stars" alone (count unknown)
_RATING_ONLY = re.compile(r"(?:rating|rated)\s*:?\s*" + _RATING, re.I)
# "Acme Roofing - 28 Reviews - Contractors in Austin" (count without a rating)
_COUNT_ONLY = re.compile(_NUM + _REVIEWS_WORD, re.I)


def _to_float(s: str) -> float | None:
    m = re.match(r"\s*(\d+(?:[.,]\d+)?)", s)  # leading number only ("4.9 out of 5", "4/5", "5 stars")
    if not m:
        return None
    try:
        value = float(m.group(1).replace(",", "."))
    except ValueError:
        return None
    return value if 1.0 <= value <= 5.0 else None


def _to_int(s: str) -> int | None:
    try:
        value = int(re.sub(r"[,.]", "", s))
    except ValueError:
        return None
    return value if 1 <= value <= 200_000 else None


def parse_rating_text(text: str) -> tuple[float | None, int | None]:
    """Best (rating, review_count) mentioned in free text."""
    best: tuple[float | None, int | None] = (None, None)
    for m in _RATING_THEN_COUNT.finditer(text or ""):
        rating, count = _to_float(m.group(1)), _to_int(m.group(2))
        if rating and count and (best[1] or 0) < count:
            best = (rating, count)
    for m in _COUNT_THEN_RATING.finditer(text or ""):
        count, rating = _to_int(m.group(1)), _to_float(m.group(2))
        if rating and count and (best[1] or 0) < count:
            best = (rating, count)
    if best == (None, None) and (m := _RATING_ONLY.search(text or "")):
        best = (_to_float(m.group(1)), None)
    if best == (None, None):
        counts = [c for m in _COUNT_ONLY.finditer(text or "") if (c := _to_int(m.group(1)))]
        if counts:
            best = (None, max(counts))
    return best


def from_aggregate(aggregate: dict | None) -> dict | None:
    """schema.org AggregateRating {ratingValue, reviewCount|ratingCount}."""
    if not isinstance(aggregate, dict):
        return None
    rating = _to_float(str(aggregate.get("ratingValue", "")))
    count = _to_int(str(aggregate.get("reviewCount") or aggregate.get("ratingCount") or ""))
    if rating and count:
        return {"rating": rating, "review_count": count, "review_source": "their website", "review_url": None}
    return None


def from_site_text(text: str) -> dict | None:
    rating, count = parse_rating_text(text)
    if rating and count and count >= MIN_REVIEWS:
        source = "Google" if re.search(r"google\s+reviews?", text or "", re.I) else "their website"
        return {"rating": rating, "review_count": count, "review_source": source, "review_url": None}
    return None


def _site_name(href: str) -> str | None:
    host = (href or "").lower()
    return next((name for key, name in REVIEW_SITES.items() if key in host), None)


# Pages listing many businesses ("TOP 10 BEST Roofing in Austin") quote totals that
# belong to someone else; a review page must be the business's own profile.
_LISTING_TITLE = re.compile(r"^\s*(?:the\s+)?(?:top\s*\d+|\d+\s+best|best\b)|near me|\bbest\s+\d+\b", re.I)
_PROFILE_PATH = {"Yelp": "/biz/", "BBB": "/profile/", "Houzz": "/professionals/", "Angi": "/companylist/"}


def _is_business_profile(site: str, href: str, title: str, business_name: str) -> bool:
    if _LISTING_TITLE.search(title or ""):
        return False
    path = href.lower().split("?")[0]
    if site in _PROFILE_PATH and _PROFILE_PATH[site] not in path:
        return False
    # Titles start with the listed name ("Vantage Roofing - Austin, TX - Yelp",
    # "Dustin Johnson Exteriors & Roofing | BBB"); it must be this business, not
    # "Austin Roofing and Construction" for "Austin Roofing".
    listed = re.split(r"\s+[-–|·]\s+|\s*\|\s*", title or "", maxsplit=1)[0]
    if not same_business_name(listed, business_name):
        return False
    # The URL slug must carry the business name as a phrase (yelp.com/biz/acme-roofing-austin);
    # word overlap alone accepts "lone-star-roofing-austin" for "Austin Roofing".
    slug = "-" + re.sub(r"[^a-z0-9]+", "-", re.sub(r"https?://[^/]+", "", path)) + "-"
    variants = name_slugs(business_name) + name_slugs(listed)
    # HomeAdvisor-style slugs run the words together: rated.VantageRoofing.121975442
    variants += [v.replace("-", "") for v in variants]
    return any(f"-{variant}-" in slug for variant in variants)


# Words a listing may add to the same business's name ("Radiant Plumbing & AC").
_DESCRIPTOR_WORDS = {"and", "ac", "air", "hvac", "heating", "cooling", "conditioning", "services", "service",
                     "of", "the", "tx", "llc", "inc", "co", "company", "ltd", "pllc", "reviews", "review", "ratings"}


def _name_words(name: str) -> list[str]:
    base = _LEGAL_SUFFIX.sub(" ", (name or "").lower().replace("'", "").replace("’", "").replace("&", " and "))
    return re.findall(r"[a-z0-9]+", base)


def same_business_name(listed: str, business_name: str) -> bool:
    """Same business name on a review site.

    The site may ADD only descriptor words ('Radiant Plumbing & AC' for 'Radiant Plumbing',
    never 'Austin Roofing and Construction' for 'Austin Roofing'). It may DROP trailing
    words when at least 3 distinctive words remain ('Dustin Johnson Exteriors' for
    'Dustin Johnson Exteriors & Roofing')."""
    a = [w for w in _name_words(listed) if w not in ("reviews", "review", "ratings")]
    b = _name_words(business_name)
    if not a or not b:
        return False
    if len(a) >= len(b):
        return a[: len(b)] == b and all(w in _DESCRIPTOR_WORDS or w.isdigit() for w in a[len(b):])
    distinctive = [w for w in a if w not in _DESCRIPTOR_WORDS]
    return b[: len(a)] == a and len(distinctive) >= 3


_LEGAL_SUFFIX = re.compile(r"\b(llc|inc|ltd|limited|co|corp|company|pllc|lp)\b\.?", re.I)


def name_slugs(business_name: str) -> list[str]:
    """URL slug spellings of a business name: 'Roger's Plumbing Inc.' -> ['rogers-plumbing', ...]."""
    base = _LEGAL_SUFFIX.sub(" ", (business_name or "").lower().replace("'", "").replace("’", ""))
    variants = set()
    for amp in (" and ", " "):
        words = re.findall(r"[a-z0-9]+", base.replace("&", amp))
        if words:
            variants.add("-".join(words))
            # Sites often drop a trailing generic word ("redhome-hvac" for "RedHome HVAC Services")
            if len(words) > 2 and words[-1] in ("services", "service", "company", "group"):
                variants.add("-".join(words[:-1]))
    return [v for v in variants if len(v) >= 4]


def from_search(business_name: str, address: str) -> dict | None:
    """Review-site snippets for this business. A result with a rating beats one with only
    a count; among equals the one with more reviews wins."""
    city = city_from_address(address)
    best, best_key = None, (-1, -1)
    results = search(f'"{business_name}" {city} reviews', 8)
    if not any(_site_name(r.get("href") or "") for r in results):
        # Search results vary a lot; one more try aimed at the big review sites.
        results = search(f'{business_name} {city} yelp bbb reviews', 8)
    for r in results:
        href = r.get("href") or ""
        site = _site_name(href)
        # Strict name match: review sites list many similarly named businesses.
        if not site or not matches_business(r.get("title", ""), business_name, threshold=0.75):
            continue
        if not _is_business_profile(site, href, r.get("title", ""), business_name):
            continue
        rating, count = parse_rating_text(f"{r.get('title', '')} {r.get('body', '')}")
        if not count or count < MIN_REVIEWS:
            continue
        key = (int(rating is not None), count)
        if key > best_key:
            best_key = key
            best = {"rating": rating, "review_count": count, "review_source": site, "review_url": href.split("?")[0]}
    return best


def find_reviews(business_name: str, address: str, site: dict | None = None) -> dict | None:
    """site is website.extract() output (may be None when there is no website)."""
    if site:
        found = from_aggregate(site.get("aggregate_rating")) or from_site_text(site.get("text", ""))
        if found:
            return found
    return from_search(business_name, address)
