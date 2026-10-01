"""
Google Places API (New) search. This runs ONCE per search to get the
candidate list -- it is not itself a per-business graph node, since it
produces the list the graph then iterates over.

Uses Text Search (New): https://places.googleapis.com/v1/places:searchText

Results come back 20 per page with a nextPageToken, up to 3 pages (60). Each
page is one billable request, so every page goes through the monthly quota
counter before it is made.
"""
import requests

from config import GOOGLE_PLACES_API_KEY, MAX_PLACES_RESULTS_PER_RUN, SEARCH_FIELD_MASK
from quota import QuotaExceededError, check_and_increment

SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
PAGE_SIZE = 20
MAX_PAGES = 3  # the API stops returning tokens after 60 results


def _parse_place(place: dict) -> dict:
    return {
        "place_id": place.get("id"),
        "name": place.get("displayName", {}).get("text", "Unknown"),
        "address": place.get("formattedAddress", ""),
        "phone": place.get("nationalPhoneNumber"),
        "category": place.get("primaryType"),
        "website": place.get("websiteUri"),
        "business_status": place.get("businessStatus"),
        "rating": place.get("rating"),
        "review_count": place.get("userRatingCount"),
    }


def _is_operational(place: dict) -> bool:
    # Missing status means "unknown": keep it. Closed businesses are noise.
    return place.get("business_status") in (None, "OPERATIONAL")


def search_businesses(query: str, location: str, radius_meters: int = 5000,
                      max_results: int | None = None) -> list[dict]:
    """
    Returns a list of raw business dicts with keys:
    place_id, name, address, phone, category, website, business_status,
    rating, review_count

    Pages through results until max_results (capped at 60) is reached or
    there are no more pages. Permanently/temporarily closed places and
    duplicate place ids are dropped.
    """
    if not GOOGLE_PLACES_API_KEY:
        raise RuntimeError(
            "GOOGLE_PLACES_API_KEY is not set. Add it to your local .env file."
        )

    wanted = min(max_results or MAX_PLACES_RESULTS_PER_RUN, MAX_PLACES_RESULTS_PER_RUN,
                 PAGE_SIZE * MAX_PAGES)

    results: list[dict] = []
    seen: set[str] = set()
    page_token: str | None = None

    for _ in range(MAX_PAGES):
        if len(results) >= wanted:
            break

        # One page = one Places API request against this SKU.
        try:
            check_and_increment(1)
        except QuotaExceededError:
            if results:
                break  # keep what earlier pages already returned
            raise

        body = {
            "textQuery": f"{query} in {location}",
            "pageSize": min(PAGE_SIZE, wanted - len(results)),
        }
        if page_token:
            body["pageToken"] = page_token

        resp = requests.post(
            SEARCH_URL,
            headers={
                "Content-Type": "application/json",
                "X-Goog-Api-Key": GOOGLE_PLACES_API_KEY,
                # nextPageToken must be in the mask or the API omits it.
                "X-Goog-FieldMask": SEARCH_FIELD_MASK + ",nextPageToken",
            },
            json=body,
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        for place in data.get("places", []):
            biz = _parse_place(place)
            pid = biz["place_id"]
            if not pid or pid in seen or not _is_operational(biz):
                continue
            seen.add(pid)
            results.append(biz)

        page_token = data.get("nextPageToken")
        if not page_token:
            break

    return results[:wanted]
