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


def test_uncurated_niche_uses_word_matching():
    m = po.NicheMatcher("Fence Builders")
    assert m.matches("Lone Star Fence", "fence_and_gate_sales_service",
                     ["services_and_business", "home_service", "fence_and_gate_sales_service"])
    m = po.NicheMatcher("Window Tinting")
    assert m.matches("Shade Pros", "window_tinting", ["automotive", "auto_detailing", "window_tinting"])
    assert not m.matches("Windows R Us", "window_supplier", ["shopping", "window_supplier"])


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
    monkeypatch.setattr(po, "_query_area", lambda bbox, progress: rows)
    found, stats = po.search_area(["Roofers", "HVAC Contractors"], "Austin", 5000, known_place_ids={"ovt:7"})
    assert sorted(b["place_id"] for b in found) == ["ovt:1", "ovt:2"]
    assert (stats["closed"], stats["low_confidence"], stats["outside_radius"]) == (1, 1, 1)
    assert stats["niche_totals"] == {"Roofers": {"total": 2, "with_website": 1},
                                     "HVAC Contractors": {"total": 1, "with_website": 1}}  # known still counted
    assert stats["billed_calls"] == 0


def test_market_context_line():
    from app import market_context
    totals = {"Roofers": {"total": 22, "with_website": 14}, "Tiny": {"total": 2, "with_website": 1}}
    assert market_context(["Roofers"], totals, 5000) == "14 of 22 roofers within 5 km list a website"
    assert market_context(["Tiny"], totals, 5000) is None   # too few to be meaningful
