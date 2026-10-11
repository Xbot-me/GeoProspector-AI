"""
Area search on the Overture Maps places dataset (free, no API key).

Overture publishes ~80M places monthly as GeoParquet on S3. DuckDB reads only
the row groups inside the search box, so a run downloads the area once (tens of
seconds for a city district) and there is no per-call cost or result cap.

Licences: CDLA Permissive 2.0 / Apache 2.0 depending on source. Attribution:
"© Overture Maps Foundation" (see README). Ratings/reviews are not included;
enrichment/reviews.py finds those elsewhere.

Same interface as the Google provider (nodes/places_search.py).
"""
import json
import logging
import math
import re
import threading
import time
from pathlib import Path
from typing import Callable

import requests

from auto_campaign import timezone_for_coordinates
from config import OVERTURE_MIN_CONFIDENCE, OVERTURE_RELEASE
from geocode import GeocodeError, geocode
from nodes.places_search import SearchError, haversine_m

logger = logging.getLogger(__name__)

STAC_CATALOG = "https://stac.overturemaps.org/catalog.json"
S3_PATH = "s3://overturemaps-us-west-2/release/{release}/theme=places/type=place/*"
MAX_RADIUS_METERS = 50_000
_CLOSED = ("permanently_closed", "temporarily_closed")

# Overture puts many trades under a generic category; for those the business
# name has to mention the niche ("Acme Roofing" filed as "contractor").
GENERIC_CATEGORIES = (
    "contractor", "building_or_construction_service", "home_service", "handyman",
    "professional_service", "building_contractor", "b2b_service",
)

# Curated niche -> Overture categories (matched against taxonomy primary or any
# hierarchy level). Keys are normalised niche phrases. Unlisted niches use the
# generic word matching in NicheMatcher.
CURATED: dict[str, list[str]] = {
    "hvac": ["hvac_service"],
    "heating": ["hvac_service"],
    "air conditioning": ["hvac_service"],
    "plumber": ["plumbing"],
    "plumbing": ["plumbing"],
    "electrician": ["electrician"],
    "roofer": ["roofing", "ceiling_and_roofing_repair_and_service"],
    "roofing": ["roofing", "ceiling_and_roofing_repair_and_service"],
    "landscaping": ["landscaping"],
    "landscaper": ["landscaping"],
    "lawn care": ["lawn_service"],
    "cleaning": ["home_cleaning", "cleaning_service", "carpet_cleaning", "office_cleaning"],
    "solar": ["solar_installation"],
    "tree": ["tree_service"],
    "concrete": ["masonry_concrete"],
    "masonry": ["masonry_concrete"],
    "garage door": ["garage_door_service"],
    "kitchen bath remodel": ["kitchen_remodeling", "bathroom_remodeling", "altering_and_remodeling_contractor"],
    "remodel": ["kitchen_remodeling", "bathroom_remodeling", "altering_and_remodeling_contractor"],
    "pest control": ["pest_control_service"],
    "commercial construction": ["building_contractor", "building_or_construction_service", "commercial_contractor"],
    "painter": ["painting"],
    "painting": ["painting"],
    "fence": ["fence_and_gate_sales_service"],
    "gutter": ["gutter_service"],
    "pool": ["pool_cleaning", "swimming_pool_contractor"],
    "mover": ["mover"],
    "moving": ["mover"],
    "locksmith": ["key_and_locksmith"],
    "junk removal": ["junk_removal_and_hauling"],
    "handyman": ["handyman"],
    "flooring": ["flooring_contractor", "flooring_store"],
    "dentist": ["dentist", "general_dentistry", "cosmetic_dentist"],
    "med spa": ["medical_spa"],
    "chiropractor": ["chiropractor"],
}

# Words that don't identify a trade on their own.
_FILLER = {
    "services", "service", "company", "companies", "contractors", "contractor", "installers",
    "installer", "installation", "repair", "repairs", "removal", "specialists", "specialist",
    "experts", "pros", "professionals", "local", "and", "the", "&", "of", "shop", "shops",
}


def _stem(word: str) -> str:
    for suffix in ("ers", "ing", "er", "es", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            return word[: -len(suffix)]
    return word


def niche_stems(niche: str) -> list[str]:
    words = re.findall(r"[a-z]+", niche.lower())
    return [_stem(w) for w in words if w not in _FILLER and len(w) >= 3]


class NicheMatcher:
    """Decides whether an Overture place belongs to a niche (and builds the SQL prefilter)."""

    def __init__(self, niche: str):
        self.niche = niche
        key = " ".join(niche_stems(niche))
        self.categories: list[str] = []
        for phrase, cats in CURATED.items():
            phrase_stems = " ".join(_stem(w) for w in phrase.split())
            if phrase_stems and (phrase_stems == key or re.search(rf"\b{re.escape(phrase_stems)}\b", key)):
                self.categories += [c for c in cats if c not in self.categories]
        self.stems = niche_stems(niche)

    def _category_tokens(self, primary: str | None, hierarchy: list[str] | None) -> set[str]:
        tokens = set()
        for cat in [primary or ""] + list(hierarchy or []):
            tokens.update(t for t in cat.split("_") if t)
        return tokens

    def matches(self, name: str | None, primary: str | None, hierarchy: list[str] | None) -> bool:
        cats = {primary} | set(hierarchy or [])
        if self.categories and cats & set(self.categories):
            return True
        tokens = self._category_tokens(primary, hierarchy)
        if not self.categories and self.stems and all(any(t.startswith(s) for t in tokens) for s in self.stems):
            return True
        # Generic category + niche in the business name ("Acme Roofing" as "contractor")
        if primary in GENERIC_CATEGORIES and self.stems:
            lname = (name or "").lower()
            return all(re.search(rf"\b{re.escape(s)}", lname) for s in self.stems)
        return False


# ── Release + data access ────────────────────────────────────────────────

_release_cache: dict[str, tuple[str, float]] = {}


def current_release() -> str:
    if OVERTURE_RELEASE and OVERTURE_RELEASE != "latest":
        return OVERTURE_RELEASE
    cached = _release_cache.get("latest")
    if cached and time.time() - cached[1] < 6 * 3600:
        return cached[0]
    try:
        latest = requests.get(STAC_CATALOG, timeout=15).json()["latest"]
    except Exception as e:
        if cached:
            return cached[0]
        raise SearchError(f"Could not determine the latest Overture release: {e}")
    _release_cache["latest"] = (latest, time.time())
    return latest


_duck_lock = threading.Lock()
_COLUMNS = """id, names.primary AS name, taxonomy.primary AS category, taxonomy.hierarchy AS hierarchy,
    websites, phones, emails, socials, confidence, operating_status, addresses,
    bbox.ymin AS lat, bbox.xmin AS lng"""


def _cache_dir() -> Path:
    base = Path("/app/data") if Path("/app/data").exists() else Path("data")
    path = base / "overture_cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _cached_area(release: str, bbox: tuple[float, float, float, float]) -> Path | None:
    """A cached download of this release whose box contains bbox."""
    south, west, north, east = bbox
    index_file = _cache_dir() / "index.json"
    try:
        index = json.loads(index_file.read_text())
    except (OSError, ValueError):
        return None
    for entry in index:
        s, w, n, e = entry["bbox"]
        path = _cache_dir() / entry["file"]
        if entry["release"] == release and s <= south and w <= west and n >= north and e >= east and path.exists():
            return path
    return None


def _remember_area(release: str, bbox: tuple, filename: str) -> None:
    index_file = _cache_dir() / "index.json"
    try:
        index = json.loads(index_file.read_text())
    except (OSError, ValueError):
        index = []
    # Keep the cache small: drop other releases' entries (their files too).
    for entry in [e for e in index if e["release"] != release]:
        (_cache_dir() / entry["file"]).unlink(missing_ok=True)
    index = [e for e in index if e["release"] == release] + [{"release": release, "bbox": list(bbox), "file": filename}]
    index_file.write_text(json.dumps(index))


def _query_area(bbox: tuple[float, float, float, float], progress: Callable[[dict], None]) -> list[dict]:
    """All places inside bbox (south, west, north, east), from the local cache or S3.

    Filtering by niche happens in Python: a text prefilter in SQL stops DuckDB
    from skipping row groups and made downloads ~10x slower."""
    import duckdb

    release = current_release()
    south, west, north, east = bbox
    with _duck_lock:  # one download at a time; DuckDB parallelises internally
        con = duckdb.connect()
        try:
            cached = _cached_area(release, bbox)
            if cached is None:
                progress({"type": "search_progress",
                          "message": "Downloading this area from Overture Maps (first time only, ~30-60s per 10 km)..."})
                filename = f"{release}_{south:.4f}_{west:.4f}_{north:.4f}_{east:.4f}.parquet".replace("-", "m")
                con.execute("INSTALL httpfs; LOAD httpfs; SET s3_region='us-west-2'; SET enable_progress_bar=false;")
                con.execute(f"""
                    COPY (SELECT * FROM read_parquet('{S3_PATH.format(release=release)}', hive_partitioning=1)
                          WHERE bbox.xmin BETWEEN {west} AND {east} AND bbox.ymin BETWEEN {south} AND {north})
                    TO '{(_cache_dir() / filename).as_posix()}' (FORMAT parquet)
                """)
                _remember_area(release, bbox, filename)
                cached = _cache_dir() / filename
            cur = con.execute(f"""
                SELECT {_COLUMNS} FROM read_parquet('{cached.as_posix()}')
                WHERE bbox.xmin BETWEEN {west} AND {east} AND bbox.ymin BETWEEN {south} AND {north}
            """)
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
        finally:
            con.close()


# ── Mapping to the pipeline's business dict ──────────────────────────────

_COUNTRY_NAMES = {"US": "USA", "GB": "UK", "CA": "Canada", "AU": "Australia", "IE": "Ireland",
                  "NZ": "New Zealand", "DE": "Germany", "FR": "France", "ES": "Spain", "PT": "Portugal",
                  "AT": "Austria", "CH": "Switzerland", "NL": "Netherlands", "BE": "Belgium", "IT": "Italy",
                  "NO": "Norway", "SE": "Sweden", "DK": "Denmark", "FI": "Finland"}


def format_address(addresses) -> str:
    """'street, city, region postcode, country' like Google's formattedAddress."""
    if not addresses:
        return ""
    a = addresses[0] or {}
    region_postcode = " ".join(p for p in (a.get("region"), a.get("postcode")) if p)
    country = _COUNTRY_NAMES.get((a.get("country") or "").upper(), a.get("country"))
    return ", ".join(p for p in (a.get("freeform"), a.get("locality"), region_postcode, country) if p)


def _pick_website(websites) -> str | None:
    """First real website; social pages are kept (check_website marks them social_only)."""
    sites = [w for w in (websites or []) if w]
    real = [w for w in sites if not re.search(r"facebook\.com|instagram\.com|linktr\.ee|wa\.me", w, re.I)]
    chosen = (real or sites or [None])[0]
    if chosen and not re.match(r"^https?://", chosen, re.I):
        chosen = "http://" + chosen
    return chosen


def to_business(row: dict) -> dict:
    lat, lng = row["lat"], row["lng"]
    phones = [p for p in (row.get("phones") or []) if p]
    return {
        "place_id": f"ovt:{row['id']}",
        "name": row.get("name") or "Unknown",
        "address": format_address(row.get("addresses")),
        "phone": phones[0] if phones else None,
        "international_phone": phones[0] if phones and phones[0].startswith("+") else None,
        "category": row.get("category"),
        "website": _pick_website(row.get("websites")),
        "business_status": "OPERATIONAL" if row.get("operating_status") in (None, "open") else row["operating_status"],
        "rating": None,
        "review_count": None,
        "latitude": lat,
        "longitude": lng,
        "timezone": timezone_for_coordinates(lat, lng),
        # Contact data Overture already has; contact_finder adds it to its candidates.
        "listing_emails": [e for e in (row.get("emails") or []) if e],
        "listing_socials": [s for s in (row.get("socials") or []) if s],
    }


_NAME_NOISE = re.compile(r"\b(llc|inc|ltd|limited|co|company|corp|corporation|the|and|services?)\b")


def _name_key(name: str) -> str:
    return " ".join(_NAME_NOISE.sub(" ", re.sub(r"[^a-z0-9 ]", " ", (name or "").lower())).split())


def _digits(phone: str | None) -> str:
    d = re.sub(r"\D", "", phone or "")
    return d[-10:] if len(d) >= 7 else ""


def _richness(b: dict) -> tuple:
    return (bool(b.get("website")), bool(b.get("phone")), len(b.get("listing_emails") or []), b.get("_confidence", 0))


def dedupe(businesses: list[dict], same_place_m: float = 200) -> list[dict]:
    """Overture often lists one business twice (e.g. 'Acme Plumbing' and 'Acme Plumbing, LLC').
    Merge entries with the same normalised name within same_place_m, or the same phone number;
    keep the richer record and union the niches and listing contacts."""
    kept: list[dict] = []
    for b in sorted(businesses, key=_richness, reverse=True):
        key, phone = _name_key(b["name"]), _digits(b.get("phone"))
        dup = next((k for k in kept if (phone and phone == _digits(k.get("phone"))) or (
            key and key == _name_key(k["name"])
            and haversine_m(b["latitude"], b["longitude"], k["latitude"], k["longitude"]) <= same_place_m)), None)
        if dup is None:
            kept.append(b)
            continue
        for field in ("niches", "listing_emails", "listing_socials"):
            dup[field] = dup[field] + [v for v in b.get(field, []) if v not in dup[field]]
        dup["website"] = dup.get("website") or b.get("website")
        dup["phone"] = dup.get("phone") or b.get("phone")
    return kept


# ── Public API ───────────────────────────────────────────────────────────

def search_area(niches: list[str], location: str, radius_m: int,
                known_place_ids: set[str] | None = None,
                progress: Callable[[dict], None] | None = None) -> tuple[list[dict], dict]:
    """Same contract as nodes.places_search.search_area (Google)."""
    progress = progress or (lambda event: None)
    known = known_place_ids or set()
    radius_m = max(100, min(int(radius_m), MAX_RADIUS_METERS))
    stats = {"billed_calls": 0, "free_calls": 0, "tiles_searched": 0, "dense_tiles": 0,
             "tiles_skipped_known": 0, "outside_radius": 0, "closed": 0, "low_confidence": 0,
             "stopped": None, "provider": "overture", "niche_totals": {}}

    try:
        lat, lng, resolved = geocode(location)
    except GeocodeError as e:
        raise SearchError(str(e))
    stats["center"] = {"latitude": lat, "longitude": lng, "resolved": resolved}

    matchers = [NicheMatcher(n) for n in niches]
    dlat = radius_m / 111_320
    dlng = radius_m / (111_320 * max(math.cos(math.radians(lat)), 0.01))
    started = time.time()
    rows = _query_area((lat - dlat, lng - dlng, lat + dlat, lng + dlng), progress)
    stats["free_calls"] = 1
    stats["rows_scanned"] = len(rows)
    progress({"type": "search_progress",
              "message": f"Overture: {len(rows)} places in the area ({time.time() - started:.0f}s), matching niches..."})

    found: dict[str, dict] = {}
    for row in rows:
        if haversine_m(lat, lng, row["lat"], row["lng"]) > radius_m:
            stats["outside_radius"] += 1
            continue
        if row.get("operating_status") in _CLOSED:
            stats["closed"] += 1
            continue
        if (row.get("confidence") or 0) < OVERTURE_MIN_CONFIDENCE:
            stats["low_confidence"] += 1
            continue
        matched = [m.niche for m in matchers if m.matches(row.get("name"), row.get("category"), row.get("hierarchy"))]
        if not matched:
            continue
        has_site = bool(_pick_website(row.get("websites")))
        for n in matched:
            totals = stats["niche_totals"].setdefault(n, {"total": 0, "with_website": 0})
            totals["total"] += 1
            totals["with_website"] += int(has_site)
        pid = f"ovt:{row['id']}"
        if pid in known or pid in found:
            continue
        biz = to_business(row)
        biz["niches"] = matched
        biz["_confidence"] = row.get("confidence") or 0
        found[pid] = biz

    businesses = dedupe(list(found.values()))
    stats["duplicates_merged"] = len(found) - len(businesses)
    for b in businesses:
        b.pop("_confidence", None)
    return businesses, stats


def search_businesses(query: str, location: str, radius_meters: int = 5000,
                      max_results: int | None = None) -> list[dict]:
    businesses, _ = search_area([query], location, radius_meters)
    return businesses[:max_results] if max_results else businesses
