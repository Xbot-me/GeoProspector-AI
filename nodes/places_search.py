"""
Google Places API (New) search. This runs ONCE per CLI invocation to get
the candidate list -- it is not itself a per-business graph node, since it
produces the list the graph then iterates over.

Uses Text Search (New): https://places.googleapis.com/v1/places:searchText
"""
import requests

from config import GOOGLE_PLACES_API_KEY, MAX_PLACES_RESULTS_PER_RUN, SEARCH_FIELD_MASK
from quota import check_and_increment

SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"


def search_businesses(query: str, location: str, radius_meters: int = 5000,
                       max_results: int | None = None) -> list[dict]:
    """
    Returns a list of raw business dicts with keys:
    place_id, name, address, phone, category, website, business_status,
    rating, review_count
    """
    if not GOOGLE_PLACES_API_KEY:
        raise RuntimeError(
            "GOOGLE_PLACES_API_KEY is not set. Add it to your local .env file."
        )

    capped_max = min(max_results or MAX_PLACES_RESULTS_PER_RUN, MAX_PLACES_RESULTS_PER_RUN)
    # Text Search (New) returns up to 20 per page; we only request one page
    # to keep this a single, predictable API call per run.
    capped_max = min(capped_max, 20)

    # One search call = one Places API request against this SKU.
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
            "category": place.get("primaryType"),
            "website": place.get("websiteUri"),
            "business_status": place.get("businessStatus"),
            "rating": place.get("rating"),
            "review_count": place.get("userRatingCount"),
        })
    return results
