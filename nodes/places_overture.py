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
import os
import re
import threading
import time
from pathlib import Path
from typing import Callable

import requests

from auto_campaign import timezone_for_coordinates
from config import OVERTURE_MIN_CONFIDENCE, OVERTURE_RELEASE
from geocode import GeocodeError, boundary_box, geocode
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
    "solar panel": ["solar_installation"],
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
    # Niches from catalog/target_catalog.json (category names checked against the 2026-09 release)
    # not "automotive_service": it is the parent of car washes and detailers
    "auto": ["automotive_repair", "auto_body_shop", "tire_dealer_and_repair", "oil_change_station"],
    "hair salon": ["hair_salon", "hair_stylist", "beauty_salon"],
    "salon": ["hair_salon", "beauty_salon", "nail_salon"],
    "barber": ["barber"],
    "barbershop": ["barber"],
    "tattoo": ["tattoo_and_piercing", "tattoo"],
    "tailor": ["tailor", "sewing_and_alterations"],
    "alteration": ["tailor", "sewing_and_alterations"],
    "accounting": ["accountant", "bookkeeper", "tax_service"],
    "bookkeeping": ["bookkeeper", "accountant"],
    "law": ["attorney_or_law_firm"],
    "lawyer": ["attorney_or_law_firm"],
    "attorney": ["attorney_or_law_firm"],
    "pet grooming": ["pet_groomer"],
    "photography": ["photography_service", "event_photography_service", "session_photography_service"],
    "photographer": ["photography_service", "event_photography_service", "session_photography_service"],
    "gym": ["gym", "fitness_trainer"],
    "fitness": ["gym", "fitness_trainer"],
    "daycare": ["child_care_and_day_care", "day_care_preschool", "preschool"],
    "childcare": ["child_care_and_day_care", "day_care_preschool", "preschool"],
    "dry cleaner": ["dry_cleaning", "laundry_service"],
    "laundry": ["laundromat", "laundry_service"],
    # Construction / home improvement words as Overture names them
    "builder": ["builder", "home_developer", "building_contractor"],
    "home builder": ["builder", "home_developer"],
    "cabinet": ["cabinet_sales_service", "carpenter"],
    "millwork": ["carpenter", "cabinet_sales_service"],
    "carpenter": ["carpenter"],
    "carpentry": ["carpenter"],
    "deck": ["deck_and_railing_sales_service", "patio_covers"],
    "patio": ["patio_covers", "deck_and_railing_sales_service"],
    "hardscape": ["landscaping", "masonry_concrete"],
    "hardscaper": ["landscaping", "masonry_concrete"],
    "landscape architect": ["landscape_architect"],
    "interior design": ["interior_design"],
    "interior designer": ["interior_design"],
    "pool builder": ["swimming_pool_contractor", "pool_and_hot_tub_service"],
    "spa": ["spa", "day_spa", "health_spa", "medical_spa"],
    "med spa": ["medical_spa"],
    "medical spa": ["medical_spa"],
    "window tint": ["car_window_tinting", "home_window_tinting"],
    "siding": ["siding"],
    "window": ["windows_installation", "window_supplier", "window_washing"],
    "window install": ["windows_installation", "window_supplier"],
    "door": ["door_sales_service", "garage_door_service"],
    "drywall": ["drywall_service"],
    "countertop": ["countertop_installation"],
    "kitchen": ["kitchen_remodeling", "kitchen_and_bath_store"],
    "bathroom": ["bathroom_remodeling", "kitchen_and_bath_store"],
    "pressure wash": ["pressure_washing"],
    "power wash": ["pressure_washing"],
    "irrigation": ["irrigation_service"],
    "sprinkler": ["irrigation_service"],
    "foundation": ["foundation_repair"],
    "chimney": ["chimney_sweep", "chimney_service"],
    "appliance": ["appliance_repair_service"],
    "well drill": ["well_drilling"],
    "tile": ["flooring_contractor", "tile_store"],
}

# Words that don't identify a trade on their own: business words and marketing
# adjectives ("Custom", "Luxury", "High-End"...) that never appear in category names.
_FILLER = {
    "services", "service", "company", "companies", "contractors", "contractor", "installers",
    "installer", "installation", "repair", "repairs", "removal", "specialists", "specialist",
    "experts", "expert", "pros", "professionals", "professional", "local", "and", "the", "&", "of",
    "shop", "shops", "custom", "luxury", "high", "end", "premium", "commercial", "residential",
    "best", "top", "quality", "affordable", "family", "owned", "independent", "specialty",
    "small", "certified", "licensed", "emergency", "mobile", "modern", "boutique", "hire",
    "erection", "providers", "provider", "businesses", "business", "firm", "firms", "agency",
    "agencies", "studio", "studios", "center", "centre", "centers", "for", "in", "with",
    "maker", "makers", "architectural",
}


def _stem(word: str) -> str:
    if word.endswith("ss"):  # glass, grass, fitness
        return word
    for suffix in ("ers", "ing", "er", "es", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            return word[: -len(suffix)]
    # Short plurals: "spas" -> "spa", "gyms" -> "gym" (not "glass")
    if word.endswith("s") and not word.endswith("ss") and len(word) >= 4:
        return word[:-1]
    return word


def niche_stems(niche: str) -> list[str]:
    words = re.findall(r"[a-z]+", niche.lower())
    return [_stem(w) for w in words if w not in _FILLER and len(w) >= 3]


class NicheMatcher:
    """Decides whether an Overture place belongs to a niche (and builds the SQL prefilter)."""

    def __init__(self, niche: str):
        self.niche = niche
        key = " ".join(niche_stems(niche))
        matched: dict[str, list[str]] = {}
        for phrase, cats in CURATED.items():
            phrase_stems = " ".join(_stem(w) for w in phrase.split())
            if phrase_stems and (phrase_stems == key or re.search(rf"\b{re.escape(phrase_stems)}\b", key)):
                matched.setdefault(phrase_stems, [])
                matched[phrase_stems] += [c for c in cats if c not in matched[phrase_stems]]
        # The most specific phrase wins: "dry clean" must not also pull in "clean" (home cleaning).
        specific = [p for p in matched if not any(p != q and re.search(rf"\b{re.escape(p)}\b", q) for q in matched)]
        # "Deck and Patio Builders": "builder" is the role, deck/patio the trade.
        if len(specific) > 1 and "build" in specific:
            specific.remove("build")
        self.categories: list[str] = []
        for p in specific:
            self.categories += [c for c in matched[p] if c not in self.categories]
        self.stems = niche_stems(niche)
        # Curated only when the curated phrases explain every core word of the niche;
        # "Scaffolding Hire" partly matching nothing, or "Cabinet ... Showroom" matching
        # only "cabinet", goes to AI mapping (which can pick better categories) first.
        covered = {w for p in matched for w in p.split()}
        self.curated = bool(self.categories) and set(self.stems) <= covered
        self._curated_fallback = list(self.categories)
        if not self.curated:
            self.categories = []
        self.source = "curated" if self.curated else None

    def resolve(self, vocabulary: dict[str, int]) -> None:
        """Pick categories for an uncurated niche from the categories present in this area:
        AI mapping first (Gemini chooses only from real names), then word matching."""
        if self.curated:
            self.categories = [c for c in self.categories if c in vocabulary] or self.categories
            return
        ai = ai_map_categories(self.niche, vocabulary)
        if ai:
            self.categories, self.source = ai, "ai"
            return
        partial = [c for c in self._curated_fallback if c in vocabulary]
        words = fuzzy_categories(self.stems, vocabulary)
        self.categories = partial + [c for c in words if c not in partial]
        self.source = "curated+words" if partial else ("words" if words else "name_only")

    def matches(self, name: str | None, primary: str | None, hierarchy: list[str] | None) -> bool:
        cats = {primary} | set(hierarchy or [])
        if self.categories and cats & set(self.categories):
            return True
        # Generic category + niche in the business name ("Acme Roofing" as "contractor")
        if primary in GENERIC_CATEGORIES and self.stems:
            lname = (name or "").lower()
            return all(re.search(rf"\b{re.escape(s)}", lname) for s in self.stems)
        return False

    def sql(self) -> str:
        """WHERE clause for the local (cached) parquet: same rule as matches()."""
        parts = []
        if self.categories:
            cats = ", ".join("'" + c.replace("'", "") + "'" for c in self.categories)
            parts.append(f"taxonomy.primary IN ({cats}) OR list_has_any(taxonomy.hierarchy, [{cats}])")
        if self.stems:
            generic = ", ".join(f"'{c}'" for c in GENERIC_CATEGORIES)
            names = " AND ".join(
                f"regexp_matches(lower(names.primary), '\\b{re.sub(r'[^a-z]', '', s)}')" for s in self.stems)
            parts.append(f"(taxonomy.primary IN ({generic}) AND {names})")
        return "(" + " OR ".join(f"({p})" for p in parts) + ")" if parts else "FALSE"


def _category_words(category: str) -> list[str]:
    return [t for t in category.split("_") if t]


def fuzzy_categories(stems: list[str], vocabulary: dict[str, int], limit: int = 8) -> list[str]:
    """Categories whose own words cover the niche's core words.

    Only the category's own name counts (not its parents), so 'home' in
    'Custom Home Builders' can't match everything under 'home_service'. A niche with
    3+ core words needs 2 of them; shorter niches need all."""
    if not stems:
        return []
    need = len(stems) if len(stems) <= 2 else 2
    scored = []
    for cat, count in vocabulary.items():
        words = _category_words(cat)
        hits = sum(1 for s in stems if any(w.startswith(s) or s.startswith(w) and len(w) >= 4 for w in words))
        if hits >= need:
            scored.append((hits, count, cat))
    scored.sort(reverse=True)
    return [cat for _, _, cat in scored[:limit]]


# Niche -> categories chosen by Gemini, cached for the process (category names are global).
_ai_cache: dict[str, list[str]] = {}


def ai_map_categories(niche: str, vocabulary: dict[str, int], max_categories: int = 8) -> list[str]:
    """Ask Gemini which of the area's real category names fit the niche. Returns [] when
    Gemini is unavailable or fails; anything not in the vocabulary is discarded."""
    import llm

    key = " ".join(niche.lower().split())
    if key in _ai_cache:
        return [c for c in _ai_cache[key] if c in vocabulary]
    if not llm.available() or not vocabulary:
        return []
    listing = ", ".join(f"{c} ({n})" for c, n in sorted(vocabulary.items(), key=lambda kv: -kv[1])[:900])
    prompt = f"""A user wants to find local businesses for this niche: "{niche}".

Below are the business category names used in this area's map data, with how many businesses each has.
Pick the categories a business in this niche would be filed under. Prefer specific categories; add a
broader one only if no specific category fits. Pick at most {max_categories}. Use names exactly as listed.

CATEGORIES:
{listing}

Return JSON: {{"categories": ["name_one", "name_two"]}} (empty list if nothing fits)"""
    try:
        data = llm.generate_json(prompt, temperature=0)
    except Exception as e:
        logger.warning(f"AI category mapping failed for {niche!r}: {e}")
        return []
    raw = data.get("categories", []) if isinstance(data, dict) else []
    chosen = [c for c in raw if isinstance(c, str) and c in vocabulary][:max_categories]
    if chosen:
        _ai_cache[key] = chosen
        logger.info(f"AI mapped niche {niche!r} -> {chosen}")
    return chosen


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


# Small servers (Render free: 512 MB): cap DuckDB memory/threads. Unbounded, an 80 km
# metro download peaked at ~580 MB RSS.
DUCKDB_MEMORY_LIMIT = os.getenv("DUCKDB_MEMORY_LIMIT") or "256MB"
DUCKDB_THREADS = int(os.getenv("DUCKDB_THREADS") or 1)


def _duck():
    import duckdb

    con = duckdb.connect()
    con.execute(f"SET memory_limit='{DUCKDB_MEMORY_LIMIT}'; SET threads={DUCKDB_THREADS}; "
                "SET preserve_insertion_order=false; SET enable_progress_bar=false;")
    tmp = _cache_dir() / "duckdb_tmp"
    tmp.mkdir(exist_ok=True)
    con.execute(f"SET temp_directory='{tmp.as_posix()}'")  # spill to disk instead of RAM
    return con


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


def _ensure_area(bbox: tuple[float, float, float, float], progress: Callable[[dict], None]) -> Path:
    """Local parquet covering bbox (south, west, north, east): cached, or downloaded once from S3.

    The download filters on the bbox only: a text filter against S3 stops DuckDB
    from skipping row groups and made downloads ~10x slower. Niche filtering
    happens afterwards on the local file."""
    import duckdb

    release = current_release()
    south, west, north, east = bbox
    with _duck_lock:  # one download at a time; DuckDB parallelises internally
        cached = _cached_area(release, bbox)
        if cached is not None:
            return cached
        side_km = max(north - south, (east - west) * math.cos(math.radians((north + south) / 2))) * 111.32
        progress({"type": "search_progress",
                  "message": f"Downloading a {side_km:.0f} km wide area from Overture Maps "
                             f"(first time only; large areas can take a few minutes)..."})
        filename = f"{release}_{south:.4f}_{west:.4f}_{north:.4f}_{east:.4f}.parquet".replace("-", "m")
        con = _duck()
        try:
            con.execute("INSTALL httpfs; LOAD httpfs; SET s3_region='us-west-2';")
            con.execute(f"""
                COPY (SELECT * FROM read_parquet('{S3_PATH.format(release=release)}', hive_partitioning=1)
                      WHERE bbox.xmin BETWEEN {west} AND {east} AND bbox.ymin BETWEEN {south} AND {north})
                TO '{(_cache_dir() / filename).as_posix()}' (FORMAT parquet, ROW_GROUP_SIZE 20000)
            """)
        finally:
            con.close()
        _remember_area(release, bbox, filename)
        return _cache_dir() / filename


def _bbox_sql(bbox: tuple[float, float, float, float]) -> str:
    south, west, north, east = bbox
    return f"bbox.xmin BETWEEN {west} AND {east} AND bbox.ymin BETWEEN {south} AND {north}"


def _area_vocabulary(path: Path, bbox: tuple[float, float, float, float]) -> dict[str, int]:
    """Every category name used in the area (primary and parent levels) -> number of places."""
    import duckdb

    con = _duck()
    try:
        rows = con.execute(f"""
            SELECT cat, count(*) FROM (
                SELECT unnest(list_distinct(list_append(coalesce(taxonomy.hierarchy, []), taxonomy.primary))) AS cat
                FROM read_parquet('{path.as_posix()}') WHERE {_bbox_sql(bbox)}
            ) WHERE cat IS NOT NULL GROUP BY cat
        """).fetchall()
    finally:
        con.close()
    return {cat: n for cat, n in rows}


def _query_matches(path: Path, bbox: tuple[float, float, float, float], where: str) -> list[dict]:
    """Only rows matching the niches: keeps memory small even for whole-city areas."""
    import duckdb

    con = _duck()
    try:
        cur = con.execute(f"SELECT {_COLUMNS} FROM read_parquet('{path.as_posix()}') "
                          f"WHERE {_bbox_sql(bbox)} AND ({where})")
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

AREA_MODES = ("auto", "radius", "city")
AUTO_MIN_RESULTS = 20             # auto mode widens the area until at least this many matches
AUTO_MAX_RADIUS_METERS = 40_000
CITY_MAX_SIDE_METERS = 60_000     # whole-city boxes are capped (memory/download on small servers)


def _circle_bbox(lat: float, lng: float, radius_m: float) -> tuple[float, float, float, float]:
    dlat = radius_m / 111_320
    dlng = radius_m / (111_320 * max(math.cos(math.radians(lat)), 0.01))
    return (lat - dlat, lng - dlng, lat + dlat, lng + dlng)


def _cap_box(box: tuple[float, float, float, float], lat: float, lng: float) -> tuple[float, float, float, float]:
    """Shrink a boundary box around its centre so no side exceeds CITY_MAX_SIDE_METERS."""
    south, west, north, east = box
    half_lat = min((north - south) / 2, CITY_MAX_SIDE_METERS / 2 / 111_320)
    half_lng = min((east - west) / 2, CITY_MAX_SIDE_METERS / 2 / (111_320 * max(math.cos(math.radians(lat)), 0.01)))
    c_lat, c_lng = (south + north) / 2, (west + east) / 2
    return (c_lat - half_lat, c_lng - half_lng, c_lat + half_lat, c_lng + half_lng)


def _match_area(matchers: list[NicheMatcher], bbox: tuple, inside, progress, stats) -> list[dict]:
    """Download/cache bbox, resolve niche categories against it, return matching rows inside the area."""
    started = time.time()
    path = _ensure_area(bbox, progress)
    vocabulary = _area_vocabulary(path, bbox)
    for m in matchers:
        m.resolve(vocabulary)
        stats["niche_categories"][m.niche] = {"source": m.source, "categories": m.categories}
    where = " OR ".join(m.sql() for m in matchers)
    rows = [r for r in _query_matches(path, bbox, where) if inside(r["lat"], r["lng"])]
    stats["free_calls"] += 1
    progress({"type": "search_progress",
              "message": f"Overture: {len(rows)} candidate places in the area "
                         f"({time.time() - started:.0f}s), checking them..."})
    return rows


def search_area(niches: list[str], location: str, radius_m: int,
                known_place_ids: set[str] | None = None,
                progress: Callable[[dict], None] | None = None,
                area_mode: str = "auto") -> tuple[list[dict], dict]:
    """Same contract as nodes.places_search.search_area (Google), plus area_mode:

    auto    start at radius_m and double it (up to 40 km) until AUTO_MIN_RESULTS match
    radius  exactly the circle
    city    the whole city/region boundary from the geocoder (capped at 60 km a side)
    """
    progress = progress or (lambda event: None)
    known = known_place_ids or set()
    area_mode = area_mode if area_mode in AREA_MODES else "auto"
    radius_m = max(100, min(int(radius_m), MAX_RADIUS_METERS))
    stats = {"billed_calls": 0, "free_calls": 0, "tiles_searched": 0, "dense_tiles": 0,
             "tiles_skipped_known": 0, "outside_radius": 0, "closed": 0, "low_confidence": 0,
             "stopped": None, "provider": "overture", "niche_totals": {}, "niche_categories": {},
             "area_mode": area_mode}

    try:
        lat, lng, resolved = geocode(location)
    except GeocodeError as e:
        raise SearchError(str(e))
    stats["center"] = {"latitude": lat, "longitude": lng, "resolved": resolved}
    matchers = [NicheMatcher(n) for n in niches]

    if area_mode == "city":
        box = boundary_box(location) or _circle_bbox(lat, lng, radius_m)
        bbox = _cap_box(box, lat, lng)
        south, west, north, east = bbox
        rows = _match_area(matchers, bbox, lambda a, b: south <= a <= north and west <= b <= east, progress, stats)
        stats["area"] = f"whole {resolved.split(',')[0]} area"
    else:
        widened = False
        while True:
            bbox = _circle_bbox(lat, lng, radius_m)
            r = radius_m
            rows = _match_area(matchers, bbox, lambda a, b: haversine_m(lat, lng, a, b) <= r, progress, stats)
            usable = sum(1 for row in rows if row.get("operating_status") not in _CLOSED
                         and (row.get("confidence") or 0) >= OVERTURE_MIN_CONFIDENCE)
            if area_mode != "auto" or usable >= AUTO_MIN_RESULTS or radius_m >= AUTO_MAX_RADIUS_METERS:
                break
            new_radius = min(radius_m * 2, AUTO_MAX_RADIUS_METERS)
            progress({"type": "search_progress",
                      "message": f"Only {usable} found within {radius_m / 1000:g} km, widening to {new_radius / 1000:g} km..."})
            if not widened:
                # Most of a download is fixed overhead: fetch the whole widening range once,
                # so every further step is a local query instead of another download.
                _ensure_area(_circle_bbox(lat, lng, AUTO_MAX_RADIUS_METERS), progress)
                widened = True
            radius_m = new_radius
        stats["area"] = f"{radius_m / 1000:g} km radius"
    stats["radius_m"] = radius_m
    stats["rows_scanned"] = len(rows)

    found: dict[str, dict] = {}
    for row in rows:
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
