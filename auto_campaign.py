"""
Worldwide Location & Niche Catalog Rotation Engine.
Loads curated targets & niche references from data/target_catalog.json.
Provides cluster-aware rotation and niche suggestions.
"""
import json
import logging
import re
from pathlib import Path

from db import get_conn

logger = logging.getLogger(__name__)

# Load worldwide target catalog from JSON data file
_CATALOG_PATH = Path(__file__).parent / "data" / "target_catalog.json"
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
