"""
Free geocoding via OpenStreetMap Nominatim (no key).

Usage policy: at most 1 request/second and an identifying User-Agent
(https://operations.osmfoundation.org/policies/nominatim/). Results are
cached in-process so repeated runs for the same location cost nothing.
"""
import threading
import time

import requests

from config import NOMINATIM_USER_AGENT

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"

_cache: dict[str, tuple[float, float, str]] = {}
_lock = threading.Lock()
_last_call = 0.0


class GeocodeError(RuntimeError):
    pass


def geocode(location: str) -> tuple[float, float, str]:
    """(lat, lng, display_name) for a free-text place like 'Austin, Texas, USA'."""
    key = " ".join(location.lower().split())
    if key in _cache:
        return _cache[key]
    global _last_call
    with _lock:
        wait = 1.1 - (time.time() - _last_call)
        if wait > 0:
            time.sleep(wait)
        try:
            resp = requests.get(
                NOMINATIM_URL,
                params={"q": location, "format": "jsonv2", "limit": 1},
                headers={"User-Agent": NOMINATIM_USER_AGENT},
                timeout=15,
            )
        finally:
            _last_call = time.time()
    if resp.status_code != 200:
        raise GeocodeError(f"Geocoding failed ({resp.status_code}) for '{location}'")
    results = resp.json()
    if not results:
        raise GeocodeError(f"Could not find location '{location}'")
    hit = results[0]
    _cache[key] = (float(hit["lat"]), float(hit["lon"]), hit.get("display_name", location))
    return _cache[key]
