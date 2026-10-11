import random

import pytest

from nodes import places_search as ps
from quota import QuotaExceededError

CENTER = (30.2672, -97.7431)  # Austin


def make_places(n_dense=400, n_sparse=60, seed=1):
    """Synthetic businesses: a dense downtown cluster plus scattered ones up to ~6 km out."""
    rnd = random.Random(seed)
    places = []
    for i in range(n_dense + n_sparse):
        spread = 0.004 if i < n_dense else 0.05
        lat = CENTER[0] + rnd.uniform(-spread, spread)
        lng = CENTER[1] + rnd.uniform(-spread, spread)
        places.append({
            "id": f"p{i}", "displayName": {"text": f"Biz {i}"}, "formattedAddress": "x, Austin, TX, USA",
            "location": {"latitude": lat, "longitude": lng}, "businessStatus": "OPERATIONAL",
            "websiteUri": None, "rating": 4.5, "userRatingCount": 10,
        })
    return places


class FakePlaces:
    """Mimics Text Search (New): rectangle restriction, 20/page, 60 max, IDs-only masks."""

    def __init__(self, places):
        self.places = places
        self.calls = []

    def __call__(self, body, field_mask):
        self.calls.append(field_mask)
        if "locationRestriction" not in body:  # geocode
            return {"places": [{"location": {"latitude": CENTER[0], "longitude": CENTER[1]},
                                "formattedAddress": "Austin, TX, USA"}]}
        r = body["locationRestriction"]["rectangle"]
        inside = [p for p in self.places
                  if r["low"]["latitude"] <= p["location"]["latitude"] < r["high"]["latitude"]
                  and r["low"]["longitude"] <= p["location"]["longitude"] < r["high"]["longitude"]]
        inside = inside[:ps.TEXT_SEARCH_MAX_RESULTS]
        offset = int(body.get("pageToken", 0))
        page = inside[offset:offset + body["pageSize"]]
        if field_mask == ps._IDS_ONLY_MASK:
            page = [{"id": p["id"]} for p in page]
        out = {"places": page}
        if offset + body["pageSize"] < len(inside):
            out["nextPageToken"] = str(offset + body["pageSize"])
        return out


@pytest.fixture
def fake(monkeypatch):
    def install(places, cap=None):
        api = FakePlaces(places)
        monkeypatch.setattr(ps, "_post", api)
        counter = {"n": 0}

        def check(n=1):
            if cap is not None and counter["n"] + n > cap:
                raise QuotaExceededError("monthly cap reached")
            counter["n"] += n
        monkeypatch.setattr(ps, "check_and_increment", check)
        monkeypatch.setattr(ps, "timezone_for_coordinates", lambda lat, lng: "America/Chicago")
        return api, counter
    return install


def within(places, radius):
    return {p["id"] for p in places
            if ps.haversine_m(*CENTER, p["location"]["latitude"], p["location"]["longitude"]) <= radius}


def test_finds_every_business_in_radius_despite_60_result_cap(fake):
    places = make_places()
    api, billed = fake(places)
    found, stats = ps.search_area(["plumbers"], "Austin", 5000)
    assert {b["place_id"] for b in found} == within(places, 5000)
    assert len(found) > 300  # far more than one query (60) could return
    assert stats["tiles_searched"] > 1 and stats["stopped"] is None


def test_tiling_pass_is_free_and_billing_is_about_one_call_per_20(fake):
    places = make_places()
    api, billed = fake(places)
    found, stats = ps.search_area(["plumbers"], "Austin", 5000)
    assert stats["free_calls"] == sum(1 for m in api.calls if m == ps._IDS_ONLY_MASK)
    assert billed["n"] == stats["billed_calls"]
    # geocode + ~len/20 pages, with slack for partially filled leaf pages
    assert stats["billed_calls"] <= 1 + len(found) / 20 * 2.5


def test_radius_is_respected(fake):
    places = make_places()
    fake(places)
    found, stats = ps.search_area(["plumbers"], "Austin", 400)
    assert {b["place_id"] for b in found} == within(places, 400)
    assert stats["outside_radius"] > 0


def test_known_places_skip_billed_detail_calls(fake):
    places = make_places(n_dense=30, n_sparse=0)
    fake(places)
    first, s1 = ps.search_area(["plumbers"], "Austin", 3000)
    _, counter = fake(places)
    again, s2 = ps.search_area(["plumbers"], "Austin", 3000, known_place_ids={b["place_id"] for b in first})
    assert again == [] and s2["billed_calls"] == 1  # only the geocode


def test_closed_businesses_dropped_and_niches_merged(fake):
    places = make_places(n_dense=10, n_sparse=0)
    places[0]["businessStatus"] = "CLOSED_PERMANENTLY"
    fake(places)
    found, stats = ps.search_area(["roofers", "gutter installers"], "Austin", 3000)
    ids = {b["place_id"] for b in found}
    assert "p0" not in ids and stats["closed"] == 1
    assert all(b["niches"] == ["roofers", "gutter installers"] for b in found)


def test_quota_cap_returns_partial_results(fake):
    fake(make_places(), cap=4)
    found, stats = ps.search_area(["plumbers"], "Austin", 5000)
    assert stats["stopped"] and 0 < len(found) <= 60


def test_geometry_helpers():
    rect = ps.bounding_rect(*CENTER, 1000)
    assert ps.rect_intersects_circle(rect, *CENTER, 1000)
    assert abs(ps.rect_side_m(rect) - 2000) < 20
    far = (CENTER[0] + 1, CENTER[1] + 1, CENTER[0] + 1.1, CENTER[1] + 1.1)
    assert not ps.rect_intersects_circle(far, *CENTER, 1000)
    assert len(ps.split_rect(rect)) == 4
