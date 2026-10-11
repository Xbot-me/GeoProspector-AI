"""
Worldwide Location & Niche Catalog Rotation Engine.
Loads curated targets & niche references from catalog/target_catalog.json.
Provides cluster-aware rotation and niche suggestions.
"""
import json
import logging
import re
from pathlib import Path
from zoneinfo import ZoneInfo

from db import get_conn

logger = logging.getLogger(__name__)

# Load worldwide target catalog from JSON data file (checking catalog/ then data/ then root)
_CATALOG_PATH = Path(__file__).parent / "catalog" / "target_catalog.json"
if not _CATALOG_PATH.exists():
    _CATALOG_PATH = Path(__file__).parent / "data" / "target_catalog.json"
if not _CATALOG_PATH.exists():
    _CATALOG_PATH = Path(__file__).parent / "target_catalog.json"

with open(_CATALOG_PATH, "r", encoding="utf-8") as f:
    _CATALOG = json.load(f)

TARGET_LOCATIONS = _CATALOG["targets"]
NICHE_REFERENCE = _CATALOG["niche_reference"]

# Hit-rate weights for niche prioritization
HIT_RATE_WEIGHTS = {
    "high": 3,
    "medium-high": 2,
    "medium": 1,
}

# Map search terms to hit-rate weight
NICHE_WEIGHT_MAP = {
    n["search_term"].lower().strip(): HIT_RATE_WEIGHTS.get(n.get("hit_rate", "").lower().strip(), 1)
    for n in NICHE_REFERENCE
}


def format_location(target: dict) -> str:
    """Format target location into a standard string for Places API search."""
    name = target.get("name", "")
    region = target.get("region")
    country = target.get("country", "")
    if region:
        return f"{name}, {region}, {country}"
    return f"{name}, {country}"


def _parse_population(pop_str: str | None) -> int:
    """Extract numeric population count for sorting towns within clusters."""
    if not pop_str:
        return 0
    clean = re.sub(r"[^\d]", "", pop_str.split("(")[0])
    try:
        return int(clean)
    except ValueError:
        return 0


def get_all_target_combinations() -> list[dict]:
    """Return all target combinations (location + suggested niches) from the catalog."""
    combos = []
    for t in TARGET_LOCATIONS:
        loc_str = format_location(t)
        niches = t.get("suggested_niches") or ["local businesses"]
        for niche in niches:
            combos.append({
                "query": niche,
                "location": loc_str,
                "display_name": f"{niche} in {loc_str}",
                "target": t,
            })
    return combos


def get_next_campaign_target() -> dict:
    """
    Select the next campaign target using cluster-aware rotation:
    1. Group locations by cluster_group.
    2. Sort towns within each cluster by population descending.
    3. Pick the next cluster with NO runs yet (returning its largest town & best weighted niche).
    4. If all clusters have runs, check if any cluster's first run had low yield (result_count < 15) and pick 2nd town.
    5. Rotate through remaining un-executed (niche, location) combinations.
    """
    executed_runs = []
    try:
        with get_conn() as conn:
            rows = conn.execute("SELECT query, location, result_count FROM search_runs").fetchall()
            executed_runs = [dict(r) for r in rows]
    except Exception as e:
        logger.warning(f"Failed to fetch past search runs: {e}")

    executed_keys = {
        (r["query"].lower().strip(), r["location"].lower().strip())
        for r in executed_runs if r.get("query") and r.get("location")
    }

    executed_locations = {
        r["location"].lower().strip() for r in executed_runs if r.get("location")
    }

    # Group locations by cluster_group
    clusters = {}
    for t in TARGET_LOCATIONS:
        cg = t.get("cluster_group") or f"Singleton-{t['name']}"
        if cg not in clusters:
            clusters[cg] = []
        clusters[cg].append(t)

    # Sort towns in each cluster by population descending
    for cg in clusters:
        clusters[cg].sort(key=lambda t: _parse_population(t.get("population")), reverse=True)

    # 1. Look for an un-run cluster (no town in cluster has been searched yet)
    for cg, towns in clusters.items():
        cluster_run_locations = [
            format_location(t).lower().strip() for t in towns
            if format_location(t).lower().strip() in executed_locations
        ]
        
        if not cluster_run_locations:
            # Entire cluster has no runs yet! Pick largest town in cluster.
            top_town = towns[0]
            loc_str = format_location(top_town)
            best_niche = _select_best_niche(top_town, executed_keys, loc_str)
            return {
                "query": best_niche,
                "location": loc_str,
                "display_name": f"{best_niche} in {loc_str}",
                "target": top_town,
            }

    # 2. Check if any cluster's first run yielded low results (result_count < 15) -> pick 2nd town if available
    for cg, towns in clusters.items():
        if len(towns) > 1:
            first_loc = format_location(towns[0]).lower().strip()
            first_runs = [r for r in executed_runs if r.get("location", "").lower().strip() == first_loc]
            first_yield = max([r.get("result_count") or 0 for r in first_runs], default=0)
            
            second_loc = format_location(towns[1]).lower().strip()
            if first_yield < 15 and second_loc not in executed_locations:
                second_town = towns[1]
                loc_str = format_location(second_town)
                best_niche = _select_best_niche(second_town, executed_keys, loc_str)
                return {
                    "query": best_niche,
                    "location": loc_str,
                    "display_name": f"{best_niche} in {loc_str}",
                    "target": second_town,
                }

    # 3. All clusters run -> iterate through catalog to find any un-executed (niche, location) combo
    all_combos = get_all_target_combinations()
    for combo in all_combos:
        key = (combo["query"].lower().strip(), combo["location"].lower().strip())
        if key not in executed_keys:
            return combo

    # 4. Fallback if entire catalog is 100% exhausted
    return all_combos[0]


def _select_best_niche(town: dict, executed_keys: set, loc_str: str) -> str:
    """Select the highest-weighted niche for a town that hasn't been executed yet."""
    niches = town.get("suggested_niches") or ["local businesses"]
    
    # Sort niches by weight descending (High > Medium-High > Medium)
    sorted_niches = sorted(
        niches,
        key=lambda n: NICHE_WEIGHT_MAP.get(n.lower().strip(), 1),
        reverse=True
    )
    
    for niche in sorted_niches:
        key = (niche.lower().strip(), loc_str.lower().strip())
        if key not in executed_keys:
            return niche
            
    return sorted_niches[0]


# ---------------------------------------------------------------------------
# Timezone mapping for every city in TARGET_CITIES
# ---------------------------------------------------------------------------
CITY_TIMEZONES: dict[str, str] = {
    # US Eastern
    "Greenville":       "America/New_York",
    "Asheville":        "America/New_York",
    "Wilmington":       "America/New_York",
    "Lancaster":        "America/New_York",
    "Gainesville":      "America/New_York",
    "Pensacola":        "America/Chicago",
    "Dayton":           "America/New_York",
    "Erie":             "America/New_York",
    "Grand Rapids":     "America/New_York",
    "Kalamazoo":        "America/New_York",
    "Chattanooga":      "America/New_York",
    "Knoxville":        "America/New_York",
    "Appleton":         "America/Chicago",
    
    # US Central & Mountain & Pacific
    "Tyler":            "America/Chicago",
    "Waco":             "America/Chicago",
    "Lafayette":        "America/Chicago",
    "Monroe":           "America/Chicago",
    "Fargo":            "America/Chicago",
    "Boise":            "America/Boise",
    "Bend":             "America/Los_Angeles",

    # Canada
    "Kelowna":          "America/Vancouver",
    "Sudbury":          "America/Toronto",
    "Guelph":           "America/Toronto",
    "Vancouver":        "America/Vancouver",
    "Calgary":          "America/Edmonton",

    # Europe & Global
    "Aberdeen":         "Europe/London",
    "Manchester":       "Europe/London",
    "Bristol":          "Europe/London",
    "Swansea":          "Europe/London",
    "Dublin":           "Europe/Dublin",
    "Linz":             "Europe/Vienna",
    "Tampere":          "Europe/Helsinki",
    "Turku":            "Europe/Helsinki",
    "Santander":        "Europe/Madrid",
    "Madrid":           "Europe/Madrid",
    "Brest":            "Europe/Paris",
    "Paris":            "Europe/Paris",
    "Stavanger":        "Europe/Oslo",
    "Odense":           "Europe/Copenhagen",
    "Augsburg":         "Europe/Berlin",
    "Berlin":           "Europe/Berlin",
    "Coimbra":          "Europe/Lisbon",
    "Zurich":           "Europe/Zurich",

    # Australia
    "Sydney":           "Australia/Sydney",
    "Melbourne":        "Australia/Melbourne",
}

# Country fallback, matched against the last part of a Places formattedAddress
# ("..., Australia"). Used only for leads saved before coordinates were stored.
# Multi-zone countries map to their most populous zone.
COUNTRY_TIMEZONES: dict[str, str] = {
    "usa": "America/New_York",
    "united states": "America/New_York",
    "canada": "America/Toronto",
    "uk": "Europe/London",
    "united kingdom": "Europe/London",
    "ireland": "Europe/Dublin",
    "australia": "Australia/Sydney",
    "new zealand": "Pacific/Auckland",
    "germany": "Europe/Berlin",
    "deutschland": "Europe/Berlin",
    "france": "Europe/Paris",
    "spain": "Europe/Madrid",
    "españa": "Europe/Madrid",
    "portugal": "Europe/Lisbon",
    "austria": "Europe/Vienna",
    "österreich": "Europe/Vienna",
    "switzerland": "Europe/Zurich",
    "schweiz": "Europe/Zurich",
    "netherlands": "Europe/Amsterdam",
    "belgium": "Europe/Brussels",
    "italy": "Europe/Rome",
    "italia": "Europe/Rome",
    "norway": "Europe/Oslo",
    "norge": "Europe/Oslo",
    "sweden": "Europe/Stockholm",
    "denmark": "Europe/Copenhagen",
    "danmark": "Europe/Copenhagen",
    "finland": "Europe/Helsinki",
    "suomi": "Europe/Helsinki",
}

_DEFAULT_TZ = "America/New_York"

_tz_finder = None


def timezone_for_coordinates(lat: float | None, lng: float | None) -> str | None:
    """IANA timezone for a point (offline lookup), or None if unknown."""
    global _tz_finder
    if lat is None or lng is None:
        return None
    try:
        if _tz_finder is None:
            from timezonefinder import TimezoneFinder
            _tz_finder = TimezoneFinder()
        return _tz_finder.timezone_at(lat=lat, lng=lng)
    except Exception:
        return None


def _is_valid_tz(name: str | None) -> bool:
    if not name:
        return False
    try:
        ZoneInfo(name)
        return True
    except Exception:
        return False


def get_lead_timezone(address: str, stored_tz: str | None = None) -> str:
    """Return the IANA timezone for a lead.

    Prefers the timezone stored from the lead's coordinates. Older leads fall
    back to a known campaign city in the address, then the country (last
    address component), then ``America/New_York``.
    """
    if _is_valid_tz(stored_tz):
        return stored_tz

    addr_lower = (address or "").lower()
    country = addr_lower.rsplit(",", 1)[-1].strip()
    country_tz = COUNTRY_TIMEZONES.get(country)

    # Iterate longest names first so "Grand Rapids" matches before a shorter
    # substring. A city match only counts when it agrees with the country, so
    # "Paris, TX, USA" doesn't resolve to Europe/Paris.
    for city in sorted(CITY_TIMEZONES, key=len, reverse=True):
        if city.lower() in addr_lower:
            city_tz = CITY_TIMEZONES[city]
            if country_tz is None or city_tz.split("/")[0] == country_tz.split("/")[0]:
                return city_tz
    return country_tz or _DEFAULT_TZ
