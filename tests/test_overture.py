import pytest

from nodes import places_overture as po

CENTER = (30.2649, -97.7474)

# (name, taxonomy.primary, taxonomy.hierarchy) as seen in the Overture 2026-09-23 release
ROOFING = ("Twin Exteriors", "roofing", ["services_and_business", "home_service", "ceiling_and_roofing_repair_and_service", "roofing"])
GENERIC_ROOFER = ("Red Owl Roofing", "contractor", ["services_and_business", "home_service", "contractor"])
GENERIC_OTHER = ("Austin Builders", "contractor", ["services_and_business", "home_service", "contractor"])
HVAC = ("Green Leaf Air", "hvac_service", ["services_and_business", "home_service", "hvac_service"])
THEATRE = ("Paramount", "theatre_venue", ["arts_and_entertainment", "performing_arts_venue", "theatre_venue"])
UTILITY = ("Austin Energy", "electric_utility_provider", ["community_and_government", "public_utility", "electric_utility_provider"])
ELECTRICIAN = ("Mister Sparky", "electrician", ["services_and_business", "home_service", "electrician"])
PUBLIC_POOL = ("Barton Springs Pool", "swimming_pool", ["sports_and_recreation", "sport_or_fitness_facility", "swimming_pool"])
POOL_CLEAN = ("Blue Pool Care", "pool_cleaning", ["services_and_business", "home_service", "pool_cleaning"])
TREE = ("Arbor Pros", "tree_service", ["services_and_business", "home_service", "landscaping", "tree_service"])
LASER = ("Smooth Skin", "laser_hair_removal", ["lifestyle_services", "personal_or_beauty_service", "hair_removal", "laser_hair_removal"])
GARAGE_DOOR = ("Precision Door", "garage_door_service", ["services_and_business", "home_service", "garage_door_service"])
PARKING = ("Downtown Garage", "parking_garage", ["travel_and_transportation", "parking", "parking_garage"])


@pytest.mark.parametrize("niche,place,expected", [
    ("Roofers", ROOFING, True),
    ("Roofers", GENERIC_ROOFER, True),          # generic category, niche in the name
    ("Roofers", GENERIC_OTHER, False),
    ("HVAC Contractors", HVAC, True),
    ("HVAC Contractors", THEATRE, False),        # 'heat' vs 'theatre'
    ("Electricians", ELECTRICIAN, True),
    ("Electricians", UTILITY, False),            # 'electric' utility is not an electrician
    ("Pool Cleaning", POOL_CLEAN, True),
    ("Pool Cleaning", PUBLIC_POOL, False),
    ("Tree Removal Services", TREE, True),
    ("Tree Removal Services", LASER, False),     # 'removal' alone must not match hair removal
    ("Garage Door Repair", GARAGE_DOOR, True),
    ("Garage Door Repair", PARKING, False),
    ("Landscaping Services", TREE, True),        # tree service sits under landscaping
])
def test_niche_matching(niche, place, expected):
    assert po.NicheMatcher(niche).matches(*place) is expected


VOCAB = {  # category -> count, as _area_vocabulary returns it
    "services_and_business": 900, "home_service": 600, "home_cleaning": 39, "home_developer": 77,
    "builder": 83, "fence_and_gate_sales_service": 8, "window_supplier": 5, "car_window_tinting": 6,
    "interior_design": 206, "medical_spa": 63, "carpenter": 6, "cabinet_sales_service": 3,
    "deck_and_railing_sales_service": 3, "patio_covers": 1, "landscape_architect": 23, "roofing": 70,
}


@pytest.fixture
def no_ai(monkeypatch):
    import llm
    monkeypatch.setattr(llm, "available", lambda: False)
    po._ai_cache.clear()


def resolved(niche):
    m = po.NicheMatcher(niche)
    m.resolve(VOCAB)
    return m


@pytest.mark.parametrize("niche,expected", [
    # Production searches that returned nothing before (Gemini-suggested niches)
    ("Custom Cabinet Makers", {"cabinet_sales_service", "carpenter"}),
    ("High-End Interior Designers", {"interior_design"}),
    ("Architectural Millwork Specialists", {"carpenter", "cabinet_sales_service"}),
    ("Custom Home Builders", {"builder", "home_developer"}),
    ("Luxury Deck and Patio Builders", {"deck_and_railing_sales_service", "patio_covers"}),
    ("Med Spas", {"medical_spa"}),                                   # plural "spas"
    ("Fence Builders", {"fence_and_gate_sales_service"}),            # word matching
])
def test_descriptive_niches_resolve_to_real_categories(no_ai, niche, expected):
    assert set(resolved(niche).categories) == expected


def test_word_matching_ignores_parent_categories(no_ai):
    # "home" must not match everything under home_service
    m = resolved("Home Stagers")
    assert "home_service" not in m.categories and "home_cleaning" not in m.categories


def test_ai_mapping_only_accepts_real_categories(monkeypatch):
    import llm
    po._ai_cache.clear()
    monkeypatch.setattr(llm, "available", lambda: True)
    monkeypatch.setattr(llm, "generate_json", lambda prompt, temperature=None: {
        "categories": ["roofing", "invented_category", "landscape_architect"]})
    m = resolved("Scaffolding Hire and Erection")  # not curated -> AI
    assert m.source == "ai" and m.categories == ["roofing", "landscape_architect"]
    monkeypatch.setattr(llm, "generate_json", lambda *a, **k: (_ for _ in ()).throw(AssertionError("cached")))
    assert resolved("scaffolding hire and erection").categories == ["roofing", "landscape_architect"]


def test_ai_failure_falls_back_to_words(monkeypatch):
    import llm
    po._ai_cache.clear()
    monkeypatch.setattr(llm, "available", lambda: True)
    monkeypatch.setattr(llm, "generate_json", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("429")))
    assert resolved("Fence Builders").categories == ["fence_and_gate_sales_service"]


def test_format_address_and_business_mapping():
    row = {"id": "abc", "name": "Assurance Roofing", "category": "roofing", "hierarchy": [],
           "websites": ["https://facebook.com/assurance", "assuranceroofer.com"], "phones": ["+15127319446"],
           "emails": ["info@assuranceroofer.com"], "socials": ["https://www.facebook.com/282833685429"],
           "confidence": 0.9, "operating_status": "open", "lat": CENTER[0], "lng": CENTER[1],
           "addresses": [{"freeform": "3910 S Interstate Ste 300", "locality": "Austin",
                          "postcode": "78704", "region": "TX", "country": "US"}]}
    b = po.to_business(row)
    assert b["place_id"] == "ovt:abc"
    assert b["address"] == "3910 S Interstate Ste 300, Austin, TX 78704, USA"
    assert b["website"] == "http://assuranceroofer.com"            # real site preferred over Facebook
    assert b["international_phone"] == "+15127319446"
    assert b["listing_emails"] == ["info@assuranceroofer.com"]
    assert b["rating"] is None and b["timezone"] == "America/Chicago"


def test_dedupe_merges_same_business():
    base = {"latitude": CENTER[0], "longitude": CENTER[1], "listing_emails": [], "listing_socials": []}
    a = {**base, "place_id": "1", "name": "Economy Plumbing Services, LLC", "phone": "5125807829",
         "website": "https://plumbersthatcare.com", "niches": ["Plumbers"]}
    b = {**base, "place_id": "2", "name": "Economy Plumbing Services", "phone": "5127555037",
         "website": None, "niches": ["Drain Cleaning"], "latitude": CENTER[0] + 0.0005}
    c = {**base, "place_id": "3", "name": "Economy Plumbing", "phone": "5125807829", "website": None,
         "niches": ["Plumbers"], "latitude": CENTER[0] + 0.2}              # far away but same phone
    d = {**base, "place_id": "4", "name": "Economy Plumbing", "phone": None, "website": None,
         "niches": ["Plumbers"], "latitude": CENTER[0] + 0.2}              # far away, other branch
    out = po.dedupe([b, a, c, d])
    assert sorted(x["place_id"] for x in out) == ["1", "4"]
    kept = next(x for x in out if x["place_id"] == "1")
    assert kept["niches"] == ["Plumbers", "Drain Cleaning"]


def test_search_area_filters_and_counts(monkeypatch):
    monkeypatch.setattr(po, "geocode", lambda loc: (*CENTER, "Austin"))

    def row(i, name, cat, hier, dlat=0.0, status="open", conf=0.9, web=True):
        return {"id": str(i), "name": name, "category": cat, "hierarchy": hier, "confidence": conf,
                "websites": [f"https://b{i}.com"] if web else [], "phones": [], "emails": [], "socials": [],
                "operating_status": status, "addresses": [], "lat": CENTER[0] + dlat, "lng": CENTER[1]}

    rows = [
        row(1, *ROOFING),
        row(2, *GENERIC_ROOFER, web=False),
        row(3, *ROOFING, status="permanently_closed"),
        row(4, *ROOFING, conf=0.2),
        row(5, *ROOFING, dlat=0.2),               # ~22 km away
        row(6, *THEATRE),
        row(7, *HVAC),
    ]
    install_fake_area(monkeypatch, rows)
    found, stats = po.search_area(["Roofers", "HVAC Contractors"], "Austin", 5000,
                                  known_place_ids={"ovt:7"}, area_mode="radius")
    assert sorted(b["place_id"] for b in found) == ["ovt:1", "ovt:2"]
    assert (stats["closed"], stats["low_confidence"]) == (1, 1)
    assert stats["niche_totals"] == {"Roofers": {"total": 2, "with_website": 1},
                                     "HVAC Contractors": {"total": 1, "with_website": 1}}  # known still counted
    assert stats["billed_calls"] == 0 and stats["area"] == "5 km radius"


def install_fake_area(monkeypatch, rows, bbox_log=None):
    """Replace the S3/DuckDB layer: the 'area' holds rows; queries filter by bbox + matcher in Python."""
    import llm
    monkeypatch.setattr(llm, "available", lambda: False)
    monkeypatch.setattr(po, "geocode", lambda loc: (*CENTER, "Austin, Texas"))
    monkeypatch.setattr(po, "_ensure_area", lambda bbox, progress: (bbox_log.append(bbox) if bbox_log is not None else None) or bbox)
    vocab = {}
    for r in rows:
        for c in [r["category"]] + r["hierarchy"]:
            vocab[c] = vocab.get(c, 0) + 1
    monkeypatch.setattr(po, "_area_vocabulary", lambda path, bbox: vocab)

    def query(path, bbox, where):
        s, w, n, e = bbox
        return [r for r in rows if s <= r["lat"] <= n and w <= r["lng"] <= e]
    monkeypatch.setattr(po, "_query_matches", query)


def _roofers(n, dlat_step):
    return [{"id": f"r{i}", "name": f"Roof Co {i}", "category": ROOFING[1], "hierarchy": ROOFING[2],
             "confidence": 0.9, "websites": [], "phones": [f"5125550{i:03d}"], "emails": [], "socials": [],
             "operating_status": "open", "addresses": [], "lat": CENTER[0] + i * dlat_step, "lng": CENTER[1]}
            for i in range(n)]


def test_auto_mode_widens_until_enough_results(monkeypatch):
    rows = _roofers(30, 0.003)            # one roofer every ~330 m going north, up to ~10 km
    boxes = []
    install_fake_area(monkeypatch, rows, boxes)
    events = []
    found, stats = po.search_area(["Roofers"], "Austin", 2000, progress=events.append)
    assert len(found) >= po.AUTO_MIN_RESULTS
    assert stats["radius_m"] == 8000                            # 2 km -> 4 km -> 8 km
    # First the requested radius, then (once more is needed) the whole widening range at once
    prefetch = boxes[1]
    assert (prefetch[2] - prefetch[0]) * 111_320 / 2 >= po.AUTO_MAX_RADIUS_METERS - 100 and len(boxes) == 4
    assert any("widening to 4 km" in e["message"] for e in events)


def test_radius_mode_never_widens(monkeypatch):
    install_fake_area(monkeypatch, _roofers(30, 0.003))
    found, stats = po.search_area(["Roofers"], "Austin", 2000, area_mode="radius")
    assert stats["radius_m"] == 2000 and len(found) < po.AUTO_MIN_RESULTS


def test_city_mode_uses_boundary_box(monkeypatch):
    rows = _roofers(30, 0.003)
    install_fake_area(monkeypatch, rows)
    monkeypatch.setattr(po, "boundary_box", lambda loc: (CENTER[0] - 0.01, CENTER[1] - 0.01, CENTER[0] + 0.05, CENTER[1] + 0.01))
    found, stats = po.search_area(["Roofers"], "Austin", 500, area_mode="city")
    assert len(found) == 17 and stats["area"] == "whole Austin area"   # rows at 0..0.048 deg north


def test_stem_handles_short_plurals():
    assert po._stem("spas") == "spa" and po._stem("glass") == "glass" and po._stem("roofers") == "roof"


def test_market_context_line():
    from app import market_context
    totals = {"Roofers": {"total": 22, "with_website": 14}, "Tiny": {"total": 2, "with_website": 1}}
    assert market_context(["Roofers"], totals, 5000) == "14 of 22 roofers within 5 km list a website"
    assert market_context(["Tiny"], totals, 5000) is None   # too few to be meaningful
