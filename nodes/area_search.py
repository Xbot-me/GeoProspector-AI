"""
Area search provider switch. PLACES_PROVIDER picks the data source:

  overture (default)  nodes/places_overture.py  free open data, no key, no ratings
  google              nodes/places_search.py    Places API (billed), has ratings

Both return (businesses, stats) with the same business dict keys.
"""
from config import PLACES_PROVIDER
from nodes.places_search import SearchError  # noqa: F401  (re-exported for callers)


def _provider():
    if PLACES_PROVIDER == "google":
        from nodes import places_search
        return places_search
    if PLACES_PROVIDER == "overture":
        from nodes import places_overture
        return places_overture
    raise SearchError(f"Unknown PLACES_PROVIDER '{PLACES_PROVIDER}' (use 'overture' or 'google')")


def search_area(niches, location, radius_m, known_place_ids=None, progress=None, area_mode="auto"):
    """area_mode: auto (widen until enough results), radius (exact circle), city (whole boundary).
    Only the Overture provider supports widening/city; Google always uses the exact radius."""
    provider = _provider()
    if PLACES_PROVIDER == "overture":
        return provider.search_area(niches, location, radius_m, known_place_ids=known_place_ids,
                                    progress=progress, area_mode=area_mode)
    return provider.search_area(niches, location, radius_m, known_place_ids=known_place_ids, progress=progress)


def search_businesses(query, location, radius_meters=5000, max_results=None):
    return _provider().search_businesses(query, location, radius_meters, max_results)
