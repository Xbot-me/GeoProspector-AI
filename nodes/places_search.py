"""
Google Places API (New) area search.

Finds every business matching one or more niches inside a circle
(location + radius) using Text Search (New) with a rectangular
locationRestriction. It runs before the per-business graph and produces the
list the graph iterates over.

Text Search returns at most 60 results per query (3 pages of 20), so a dense
area must be split into tiles. Two passes keep this cheap:

  1. Discovery: search tiles with an IDs-only field mask, which Google does not
     bill. A tile that returns the full 60 is split into 4 and searched again,
     until every tile is below the limit (or too small to split).
  2. Details: search only the final tiles again with the full field mask
     (Enterprise tier, billed and counted by quota.py). Tiles whose places are
     all already processed are skipped.

Uses Text Search (New): https://places.googleapis.com/v1/places:searchText
"""
import math
import time
from typing import Callable

import requests

from auto_campaign import timezone_for_coordinates
from config import GOOGLE_PLACES_API_KEY, SEARCH_FIELD_MASK
from quota import QuotaExceededError, check_and_increment

SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"

# Businesses Google reports as closed are never worth enriching or emailing.
_CLOSED_STATUSES = ("CLOSED_PERMANENTLY", "CLOSED_TEMPORARILY")

TEXT_SEARCH_MAX_RESULTS = 60   # Google's cap across all pages of one query
PAGE_SIZE = 20
MIN_TILE_METERS = 150          # don't split tiles smaller than this
MAX_RADIUS_METERS = 50_000

_IDS_ONLY_MASK = "places.id,nextPageToken"
_GEOCODE_MASK = "places.location,places.formattedAddress"
_EARTH_RADIUS_M = 6_371_000

# (south, west, north, east) in degrees
Rect = tuple[float, float, float, float]
ProgressFn = Callable[[dict], None]


class SearchError(RuntimeError):
    pass


# ── Geometry ─────────────────────────────────────────────────────────────

def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * _EARTH_RADIUS_M * math.asin(math.sqrt(a))


def bounding_rect(lat: float, lng: float, radius_m: float) -> Rect:
    dlat = radius_m / 111_320
    dlng = radius_m / (111_320 * max(math.cos(math.radians(lat)), 0.01))
    return (lat - dlat, lng - dlng, lat + dlat, lng + dlng)


def rect_intersects_circle(rect: Rect, lat: float, lng: float, radius_m: float) -> bool:
    south, west, north, east = rect
    nearest_lat = min(max(lat, south), north)
    nearest_lng = min(max(lng, west), east)
    return haversine_m(lat, lng, nearest_lat, nearest_lng) <= radius_m


def rect_side_m(rect: Rect) -> float:
    south, west, north, east = rect
    mid_lat = (south + north) / 2
    height = (north - south) * 111_320
    width = (east - west) * 111_320 * math.cos(math.radians(mid_lat))
    return max(height, width)


def split_rect(rect: Rect) -> list[Rect]:
    south, west, north, east = rect
    mid_lat, mid_lng = (south + north) / 2, (west + east) / 2
    return [
        (south, west, mid_lat, mid_lng),
        (south, mid_lng, mid_lat, east),
        (mid_lat, west, north, mid_lng),
        (mid_lat, mid_lng, north, east),
    ]


# ── API calls ────────────────────────────────────────────────────────────

def _post(body: dict, field_mask: str) -> dict:
    """POST to Text Search with a small retry on rate limits / server errors."""
    for attempt in range(3):
        resp = requests.post(
            SEARCH_URL,
            headers={
                "Content-Type": "application/json",
                "X-Goog-Api-Key": GOOGLE_PLACES_API_KEY,
                "X-Goog-FieldMask": field_mask,
            },
            json=body,
            timeout=15,
        )
        if resp.status_code in (429, 500, 503) and attempt < 2:
            time.sleep(2 * (attempt + 1))
            continue
        if resp.status_code >= 400:
            raise SearchError(f"Places API error {resp.status_code}: {resp.text[:300]}")
        return resp.json()
    raise SearchError("Places API kept failing")  # pragma: no cover


def _search_tile(query: str, rect: Rect, field_mask: str, billed: bool, stats: dict) -> list[dict]:
    """All pages of one query restricted to rect. Billed calls go through the quota guard."""
    south, west, north, east = rect
    body = {
        "textQuery": query,
        "pageSize": PAGE_SIZE,
        "locationRestriction": {"rectangle": {
            "low": {"latitude": south, "longitude": west},
            "high": {"latitude": north, "longitude": east},
        }},
    }
    places: list[dict] = []
    while True:
        if billed:
            check_and_increment(1)
            stats["billed_calls"] += 1
        else:
            stats["free_calls"] += 1
        data = _post(body, field_mask)
        places.extend(data.get("places", []))
        token = data.get("nextPageToken")
        if not token or len(places) >= TEXT_SEARCH_MAX_RESULTS:
            return places
        body["pageToken"] = token


def geocode(location: str, stats: dict) -> tuple[float, float, str]:
    """Centre point for a free-text location ('Austin, Texas, USA')."""
    check_and_increment(1)
    stats["billed_calls"] += 1
    data = _post({"textQuery": location, "pageSize": 1}, _GEOCODE_MASK)
    places = data.get("places") or []
    if not places or "location" not in places[0]:
        raise SearchError(f"Could not find location '{location}'")
    loc = places[0]["location"]
    return loc["latitude"], loc["longitude"], places[0].get("formattedAddress", location)


def _to_business(place: dict) -> dict:
    location = place.get("location") or {}
    lat, lng = location.get("latitude"), location.get("longitude")
    return {
        "place_id": place.get("id"),
        "name": place.get("displayName", {}).get("text", "Unknown"),
        "address": place.get("formattedAddress", ""),
        "phone": place.get("nationalPhoneNumber"),
        "international_phone": place.get("internationalPhoneNumber"),
        "category": place.get("primaryType"),
        "website": place.get("websiteUri"),
        "business_status": place.get("businessStatus"),
        "rating": place.get("rating"),
        "review_count": place.get("userRatingCount"),
        "latitude": lat,
        "longitude": lng,
        "timezone": timezone_for_coordinates(lat, lng),
    }


# ── Area search ──────────────────────────────────────────────────────────

def _discover_leaf_tiles(query: str, lat: float, lng: float, radius_m: float,
                         stats: dict, progress: ProgressFn) -> list[tuple[Rect, set[str]]]:
    """Free IDs-only pass: split saturated tiles until each is below the 60 cap."""
    leaves: list[tuple[Rect, set[str]]] = []
    pending = [bounding_rect(lat, lng, radius_m)]
    while pending:
        rect = pending.pop()
        ids = {p["id"] for p in _search_tile(query, rect, _IDS_ONLY_MASK, billed=False, stats=stats) if p.get("id")}
        stats["tiles_searched"] += 1
        saturated = len(ids) >= TEXT_SEARCH_MAX_RESULTS
        if saturated and rect_side_m(rect) > MIN_TILE_METERS:
            pending.extend(t for t in split_rect(rect) if rect_intersects_circle(t, lat, lng, radius_m))
        else:
            if saturated:
                stats["dense_tiles"] += 1  # still capped at the smallest tile size
            if ids:
                leaves.append((rect, ids))
        progress({"type": "search_progress", "niche": query, "tiles_searched": stats["tiles_searched"],
                  "tiles_pending": len(pending), "message": f"Mapping '{query}': {stats['tiles_searched']} tiles searched, {len(pending)} to go"})
    return leaves


def search_area(niches: list[str], location: str, radius_m: int,
                known_place_ids: set[str] | None = None,
                progress: ProgressFn | None = None) -> tuple[list[dict], dict]:
    """
    Find every open business matching any niche within radius_m of location.

    Returns (businesses, stats). businesses carry a "niches" list of the
    queries that matched them. stats["stopped"] is set if the monthly quota
    cap interrupted the run; the businesses found so far are still returned.
    known_place_ids lets the details pass skip tiles that hold nothing new.
    """
    if not GOOGLE_PLACES_API_KEY:
        raise RuntimeError("GOOGLE_PLACES_API_KEY is not set. Add it to your local .env file.")
    progress = progress or (lambda event: None)
    known = known_place_ids or set()
    radius_m = max(100, min(int(radius_m), MAX_RADIUS_METERS))
    stats = {"billed_calls": 0, "free_calls": 0, "tiles_searched": 0, "dense_tiles": 0,
             "tiles_skipped_known": 0, "outside_radius": 0, "closed": 0, "stopped": None,
             "provider": "google", "niche_totals": {}}

    found: dict[str, dict] = {}
    rejected: set[str] = set()  # closed / outside radius: counted once even if several niches return them
    try:
        lat, lng, resolved = geocode(location, stats)
        stats["center"] = {"latitude": lat, "longitude": lng, "resolved": resolved}

        for niche in niches:
            leaves = _discover_leaf_tiles(niche, lat, lng, radius_m, stats, progress)
            for i, (rect, ids) in enumerate(leaves, 1):
                new_ids = ids - known - rejected - found.keys()
                if not new_ids:
                    stats["tiles_skipped_known"] += 1
                    # Still record the niche match for businesses found by an earlier niche.
                    for pid in ids & found.keys():
                        if niche not in found[pid]["niches"]:
                            found[pid]["niches"].append(niche)
                    continue
                for place in _search_tile(niche, rect, SEARCH_FIELD_MASK, billed=True, stats=stats):
                    biz = _to_business(place)
                    pid = biz["place_id"]
                    if not pid or pid in known or pid in rejected:
                        continue
                    if pid in found:
                        if niche not in found[pid]["niches"]:
                            found[pid]["niches"].append(niche)
                        continue
                    if biz["business_status"] in _CLOSED_STATUSES:
                        stats["closed"] += 1
                        rejected.add(pid)
                        continue
                    if biz["latitude"] is None or haversine_m(lat, lng, biz["latitude"], biz["longitude"]) > radius_m:
                        stats["outside_radius"] += 1
                        rejected.add(pid)
                        continue
                    biz["niches"] = [niche]
                    found[pid] = biz
                progress({"type": "search_progress", "niche": niche, "found": len(found),
                          "message": f"Loading '{niche}' details: tile {i}/{len(leaves)}, {len(found)} businesses so far"})
    except QuotaExceededError as e:
        stats["stopped"] = str(e)

    # Competitor counts (new businesses only: known tiles were not re-fetched)
    for biz in found.values():
        for n in biz["niches"]:
            totals = stats["niche_totals"].setdefault(n, {"total": 0, "with_website": 0})
            totals["total"] += 1
            totals["with_website"] += int(bool(biz.get("website")))
    return list(found.values()), stats


def search_businesses(query: str, location: str, radius_meters: int = 5000,
                      max_results: int | None = None) -> list[dict]:
    """Single-niche wrapper kept for the CLI (main.py)."""
    businesses, stats = search_area([query], location, radius_meters)
    if stats["stopped"] and not businesses:
        raise QuotaExceededError(stats["stopped"])
    return businesses[:max_results] if max_results else businesses
