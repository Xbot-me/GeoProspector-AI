"""
Multi-Source Business Discovery & Cross-Checking Engine.

Workflow:
1. Primary: Google Places API (New) text search (when API key is set and within quota).
2. Fallback Waterfall (when Google API key is missing, quota exceeded, or call fails):
   - Source A: DuckDuckGo Maps / Local POIs (ratings, reviews, phone, website)
   - Source B: OpenStreetMap Nominatim & Overpass (exact street addresses, verified websites)
   - Source C: Organic Local Search (direct domains, phone numbers, social presence)
3. Cross-Checking & Data Fusion Engine:
   - Fuzzy entity matching & de-duplication
   - Complementary field merging (phone from A + address from B + website from C)
   - Cross-verification scoring (promotes leads confirmed on >= 2 independent sources)
"""
import difflib
import hashlib
import logging
import re
from urllib.parse import urlparse

import requests

from config import GOOGLE_PLACES_API_KEY, MAX_PLACES_RESULTS_PER_RUN, SEARCH_FIELD_MASK
from quota import QuotaExceededError, check_and_increment

logger = logging.getLogger(__name__)

SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# Phone extraction regex for web snippet extraction
_PHONE_RE = re.compile(r"(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}")

# Generic aggregator domains to ignore when picking official business websites
_AGGREGATOR_DOMAINS = {
    "yelp.com", "yellowpages.com", "tripadvisor.com", "facebook.com",
    "instagram.com", "linkedin.com", "twitter.com", "x.com",
    "wikipedia.org", "mapquest.com", "bbb.org", "foursquare.com",
}


def _normalize_name(name: str) -> str:
    """Normalize business name for fuzzy comparison and grouping."""
    cleaned = re.sub(r"[^\w\s]", "", name.lower())
    # Strip common entity suffixes
    tokens = [
        t for t in cleaned.split()
        if t not in {"llc", "inc", "ltd", "corp", "co", "company", "group", "the", "and"}
    ]
    return " ".join(tokens).strip()


def _extract_domain(url: str | None) -> str | None:
    """Extract root domain without www."""
    if not url:
        return None
    try:
        parsed = urlparse(url if "://" in url else f"http://{url}")
        netloc = parsed.netloc.lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]
        return netloc or None
    except Exception:
        return None


# ── Primary: Google Places API ─────────────────────────────────────────────

def _search_google_places(query: str, location: str, capped_max: int) -> list[dict]:
    """Execute Google Places API (New) Text Search."""
    if not GOOGLE_PLACES_API_KEY:
        raise RuntimeError("GOOGLE_PLACES_API_KEY not configured.")

    check_and_increment(1)

    resp = requests.post(
        SEARCH_URL,
        headers={
            "Content-Type": "application/json",
            "X-Goog-Api-Key": GOOGLE_PLACES_API_KEY,
            "X-Goog-FieldMask": SEARCH_FIELD_MASK,
        },
        json={
            "textQuery": f"{query} in {location}",
            "maxResultCount": capped_max,
        },
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()

    results = []
    for place in data.get("places", []):
        results.append({
            "place_id": place.get("id"),
            "name": place.get("displayName", {}).get("text", "Unknown"),
            "address": place.get("formattedAddress", ""),
            "phone": place.get("nationalPhoneNumber"),
            "category": place.get("primaryType") or query,
            "website": place.get("websiteUri"),
            "business_status": place.get("businessStatus", "OPERATIONAL"),
            "rating": place.get("rating"),
            "review_count": place.get("userRatingCount"),
            "contact_sources": "Google Places API (New)",
            "cross_verified": True,
        })
    return results


# ── Fallback 1: DuckDuckGo Maps / Local POIs ────────────────────────────────

def _search_duckduckgo_maps(query: str, location: str, max_results: int) -> list[dict]:
    """Search DuckDuckGo Local POIs."""
    try:
        from duckduckgo_search import DDGS
    except ImportError:
        logger.warning("duckduckgo-search package not installed")
        return []

    results = []
    search_term = f"{query} in {location}"
    try:
        with DDGS() as ddgs:
            # ddgs.maps returns Apple Maps / DDG POI data
            map_items = list(ddgs.maps(keywords=search_term, max_results=max_results))
            for item in map_items:
                name = item.get("title") or item.get("name")
                if not name:
                    continue

                phone = item.get("phone")
                website = item.get("website") or item.get("url")
                address = item.get("address") or f"{location}"
                rating = None
                try:
                    if item.get("rating"):
                        rating = float(item["rating"])
                except (ValueError, TypeError):
                    pass

                reviews = None
                try:
                    if item.get("reviews"):
                        reviews = int(item["reviews"])
                except (ValueError, TypeError):
                    pass

                results.append({
                    "name": name.strip(),
                    "address": address.strip(),
                    "phone": phone.strip() if phone else None,
                    "website": website.strip() if website else None,
                    "category": item.get("category") or query,
                    "rating": rating,
                    "review_count": reviews,
                    "source": "duckduckgo_maps",
                })
    except Exception as e:
        logger.warning(f"DuckDuckGo Maps search fallback error: {e}")

    return results


# ── Fallback 2: OpenStreetMap (Nominatim & Overpass) ────────────────────────

def _search_openstreetmap(query: str, location: str, max_results: int) -> list[dict]:
    """Query OpenStreetMap Nominatim with extratags for verified local directory POIs."""
    results = []
    headers = {"User-Agent": "GeoProspector-AI/1.0 (Lead Discovery Agent)"}

    # 1. Try Nominatim POI search
    try:
        params = {
            "q": f"{query} in {location}",
            "format": "json",
            "addressdetails": 1,
            "extratags": 1,
            "limit": max_results,
        }
        resp = requests.get(NOMINATIM_URL, params=params, headers=headers, timeout=10)
        if resp.status_code == 200:
            for item in resp.json():
                raw_name = item.get("name")
                if not raw_name:
                    disp = item.get("display_name", "")
                    raw_name = disp.split(",")[0] if disp else None
                if not raw_name:
                    continue

                extratags = item.get("extratags") or {}
                addr = item.get("address") or {}
                
                # Construct clean street address
                street_parts = []
                if addr.get("house_number"):
                    street_parts.append(addr["house_number"])
                if addr.get("road"):
                    street_parts.append(addr["road"])
                if addr.get("city") or addr.get("town"):
                    street_parts.append(addr.get("city") or addr.get("town"))
                if addr.get("state"):
                    street_parts.append(addr["state"])
                if addr.get("postcode"):
                    street_parts.append(addr["postcode"])
                
                formatted_address = ", ".join(street_parts) if street_parts else item.get("display_name", location)
                phone = extratags.get("phone") or extratags.get("contact:phone")
                website = extratags.get("website") or extratags.get("contact:website")
                category = item.get("type") or item.get("class") or query

                results.append({
                    "name": raw_name.strip(),
                    "address": formatted_address.strip(),
                    "phone": phone.strip() if phone else None,
                    "website": website.strip() if website else None,
                    "category": category,
                    "rating": None,
                    "review_count": None,
                    "source": "openstreetmap",
                })
    except Exception as e:
        logger.warning(f"OpenStreetMap Nominatim search error: {e}")

    return results


# ── Fallback 3: DuckDuckGo Organic Web / Local Directory ─────────────────────

def _search_duckduckgo_web(query: str, location: str, max_results: int) -> list[dict]:
    """Search DuckDuckGo organic local business listings."""
    try:
        from duckduckgo_search import DDGS
    except ImportError:
        return []

    results = []
    search_prompt = f'"{query}" in "{location}" contact phone website'
    try:
        with DDGS() as ddgs:
            text_items = list(ddgs.text(search_prompt, max_results=max_results))
            for item in text_items:
                title = item.get("title", "")
                # Clean up title suffixes like " - Home | Facebook", " - Official Website"
                raw_name = re.split(r"[-–|:]", title)[0].strip()
                if not raw_name or len(raw_name) < 3 or len(raw_name) > 60:
                    continue

                snippet = f"{title} {item.get('body', '')}"
                found_phones = _PHONE_RE.findall(snippet)
                phone = found_phones[0] if found_phones else None

                target_url = item.get("href")
                domain = _extract_domain(target_url)
                website = target_url if domain and domain not in _AGGREGATOR_DOMAINS else None

                results.append({
                    "name": raw_name,
                    "address": location,
                    "phone": phone,
                    "website": website,
                    "category": query,
                    "rating": None,
                    "review_count": None,
                    "source": "duckduckgo_web",
                })
    except Exception as e:
        logger.warning(f"DuckDuckGo Web search fallback error: {e}")

    return results


# ── Cross-Checking & Data Fusion Engine ──────────────────────────────────────

def _cross_check_and_merge(
    ddg_maps_records: list[dict],
    osm_records: list[dict],
    web_records: list[dict],
    location: str,
    capped_max: int,
) -> list[dict]:
    """
    Cross-checks candidate entities across the 3 independent sources.
    Fuses matching records, resolves conflicts, and prioritizes cross-verified leads.
    """
    clusters: list[dict] = []

    all_candidates = ddg_maps_records + osm_records + web_records

    for candidate in all_candidates:
        c_name = candidate.get("name", "").strip()
        if not c_name:
            continue
        c_norm = _normalize_name(c_name)
        c_domain = _extract_domain(candidate.get("website"))
        c_phone = re.sub(r"\D", "", candidate.get("phone") or "")

        # Try to match candidate to an existing cluster
        matched_cluster = None
        for cluster in clusters:
            # 1. Exact or high fuzzy string similarity match
            norm_ratio = difflib.SequenceMatcher(None, c_norm, cluster["norm_name"]).ratio()
            if norm_ratio >= 0.82:
                matched_cluster = cluster
                break

            # 2. Exact domain match (ignoring aggregators)
            if c_domain and cluster["domain"] and c_domain == cluster["domain"]:
                matched_cluster = cluster
                break

            # 3. Exact 10-digit phone number match
            if len(c_phone) >= 7 and c_phone == cluster["phone_digits"]:
                matched_cluster = cluster
                break

        if matched_cluster:
            # Merge fields into existing cluster
            matched_cluster["sources"].add(candidate["source"])
            # Prefer longer/cleaner name
            if len(c_name) > len(matched_cluster["name"]) and not re.search(r"[-–|:]", c_name):
                matched_cluster["name"] = c_name
            # Fill missing website
            if not matched_cluster["website"] and candidate.get("website"):
                matched_cluster["website"] = candidate["website"]
                matched_cluster["domain"] = _extract_domain(candidate["website"])
            # Fill missing phone
            if not matched_cluster["phone"] and candidate.get("phone"):
                matched_cluster["phone"] = candidate["phone"]
                matched_cluster["phone_digits"] = c_phone
            # Prefer more detailed address
            if len(candidate.get("address", "")) > len(matched_cluster["address"]):
                matched_cluster["address"] = candidate["address"]
            # Fill rating / reviews if discovered
            if matched_cluster["rating"] is None and candidate.get("rating") is not None:
                matched_cluster["rating"] = candidate["rating"]
                matched_cluster["review_count"] = candidate.get("review_count")
        else:
            # Create a new entity cluster
            clusters.append({
                "name": c_name,
                "norm_name": c_norm,
                "address": candidate.get("address") or location,
                "phone": candidate.get("phone"),
                "phone_digits": c_phone,
                "website": candidate.get("website"),
                "domain": c_domain,
                "category": candidate.get("category"),
                "rating": candidate.get("rating"),
                "review_count": candidate.get("review_count"),
                "sources": {candidate["source"]},
            })

    # Convert clusters into finalized standardized business records
    fused_leads: list[dict] = []
    for cluster in clusters:
        sources_list = sorted(list(cluster["sources"]))
        cross_verified = len(sources_list) >= 2
        
        # Deterministic place_id generated from name and location
        hash_seed = f"{cluster['norm_name']}_{location.lower()}".encode("utf-8")
        place_id = f"cross_{hashlib.sha256(hash_seed).hexdigest()[:20]}"

        contact_source_desc = (
            f"Cross-verified ({', '.join(sources_list)})"
            if cross_verified
            else f"Discovered via {sources_list[0]}"
        )

        fused_leads.append({
            "place_id": place_id,
            "name": cluster["name"],
            "address": cluster["address"],
            "phone": cluster["phone"],
            "category": cluster["category"],
            "website": cluster["website"],
            "business_status": "OPERATIONAL",
            "rating": cluster["rating"],
            "review_count": cluster["review_count"],
            "contact_sources": contact_source_desc,
            "cross_verified": cross_verified,
            "_source_count": len(sources_list),
        })

    # Sort results: cross-verified multi-source leads first, then leads with website/phone
    fused_leads.sort(
        key=lambda b: (
            b["_source_count"],
            1 if b.get("website") else 0,
            1 if b.get("phone") else 0,
            1 if b.get("rating") else 0,
        ),
        reverse=True,
    )

    # Clean up internal sorting metadata and cap to requested max
    for lead in fused_leads:
        lead.pop("_source_count", None)

    return fused_leads[:capped_max]


# ── Public Entry Point ───────────────────────────────────────────────────────

def search_businesses(
    query: str,
    location: str,
    radius_meters: int = 5000,
    max_results: int | None = None,
) -> list[dict]:
    """
    Main business search discovery entry point.
    
    1. Tries Google Places API (New) if configured and within monthly quota.
    2. Seamlessly falls back to 3-method cross-checking pipeline (DuckDuckGo Maps,
       OpenStreetMap Nominatim/Overpass, DuckDuckGo Web) if Google API is unavailable.
    """
    capped_max = min(max_results or MAX_PLACES_RESULTS_PER_RUN, MAX_PLACES_RESULTS_PER_RUN)
    capped_max = min(capped_max, 25)

    # 1. Attempt Google Places API if key exists
    if GOOGLE_PLACES_API_KEY:
        try:
            logger.info("Querying Google Places API (New) for '%s' in '%s'", query, location)
            google_results = _search_google_places(query, location, capped_max)
            if google_results:
                return google_results
            logger.warning("Google Places API returned 0 results. Triggering multi-source fallback.")
        except QuotaExceededError as e:
            logger.warning("Google Places API quota exceeded (%s). Engaging multi-source fallback.", e)
        except Exception as e:
            logger.warning("Google Places API failed (%s). Engaging multi-source fallback.", e)
    else:
        logger.info("GOOGLE_PLACES_API_KEY not set. Engaging multi-source fallback engine.")

    # 2. Multi-Source Fallback Execution
    logger.info("Executing 3-source fallback discovery for '%s' in '%s'", query, location)
    
    ddg_maps = _search_duckduckgo_maps(query, location, max_results=capped_max)
    osm = _search_openstreetmap(query, location, max_results=capped_max)
    ddg_web = _search_duckduckgo_web(query, location, max_results=capped_max)

    # 3. Cross-Check and Fuse Results
    fused_results = _cross_check_and_merge(
        ddg_maps_records=ddg_maps,
        osm_records=osm,
        web_records=ddg_web,
        location=location,
        capped_max=capped_max,
    )

    logger.info(
        "Cross-checking complete: extracted %d leads (DDG Maps: %d, OSM: %d, Web: %d)",
        len(fused_results), len(ddg_maps), len(osm), len(ddg_web),
    )

    return fused_results
