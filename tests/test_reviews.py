import pytest

from enrichment import reviews


@pytest.mark.parametrize("text,expected", [
    ("Rated 4.9 out of 5 based on 213 Google reviews", (4.9, 213)),
    ("4.8 stars from 1,204 verified reviews", (4.8, 1204)),
    ("Acme Roofing - 4.5 (38 reviews) - Austin, TX", (4.5, 38)),
    ("213 Google reviews · 4.9 ★", (4.9, 213)),
    ("Rating: 4.7 stars", (4.7, None)),
    ("Call 512-555-0100 for 24/7 service since 1998", (None, None)),
    ("We have 25 years experience and 5 trucks", (None, None)),
    ("9.5 out of 10 from 40 reviews", (None, 40)),     # not a 5-point rating; count still usable
    ("5 stars from 40 reviews", (5.0, 40)),
    # Live false positives seen in search snippets:
    ("Austin Commercial Flat Roofing - 22 Reviews - Contractors in Austin", (None, 22)),
    ("The last 3 experiences were with Christian Brothers in 31 reviews.", (None, 31)),
    ("1005 Congress Ave. Ste 925, Austin, TX 78701 - 2 reviews", (None, 2)),
])
def test_parse_rating_text(text, expected):
    assert reviews.parse_rating_text(text) == expected


def test_aggregate_rating_from_schema():
    got = reviews.from_aggregate({"@type": "AggregateRating", "ratingValue": "4.9", "reviewCount": "87"})
    assert (got["rating"], got["review_count"], got["review_source"]) == (4.9, 87, "their website")
    assert reviews.from_aggregate({"ratingValue": "4.9"}) is None


def test_site_widget_attributed_to_google():
    got = reviews.from_site_text("What our customers say: 4.9 stars from 213 Google reviews")
    assert got["review_source"] == "Google" and got["review_count"] == 213


def test_from_search_uses_matching_review_sites_only(monkeypatch):
    results = [
        {"href": "https://www.yelp.com/biz/radiant-plumbing-austin", "title": "Radiant Plumbing & AC - Austin - Yelp",
         "body": "4.6 (127 reviews) · Plumbing, Water Heater Installation"},
        {"href": "https://www.bbb.org/us/tx/austin/profile/radiant", "title": "Radiant Plumbing | BBB",
         "body": "4.9/5 average of 31 Customer Reviews"},
        {"href": "https://www.yelp.com/biz/brilliant-electric", "title": "Brilliant Electric - Yelp",
         "body": "4.9 (900 reviews)"},                                    # other business
        {"href": "https://radiantplumbing.com/reviews", "title": "Radiant Plumbing reviews",
         "body": "4.9 stars from 2,000 reviews"},                         # not a review site
    ]
    monkeypatch.setattr(reviews, "search", lambda q, n=8: results)
    got = reviews.from_search("Radiant Plumbing", "1 Main St, Austin, TX 78701, USA")
    assert (got["rating"], got["review_count"], got["review_source"]) == (4.6, 127, "Yelp")
    assert got["review_url"] == "https://www.yelp.com/biz/radiant-plumbing-austin"


def test_from_search_rejects_wrong_business_and_tiny_counts(monkeypatch):
    results = [
        {"href": "https://www.yelp.com/biz/church-services-austin", "title": "CHURCH SERVICES - 17 Photos & 116 ...Christian Brothers",
         "body": "4.9 (116 reviews)"},
        {"href": "https://www.yelp.com/biz/christian-brothers-air-conditioning-austin", "title": "Christian Brothers Air Conditioning - Yelp",
         "body": "4.0 (2 reviews)"},
        {"href": "https://reviews.birdeye.com/christian-brothers-air-conditioning-1234", "title": "Christian Brothers Air Conditioning - 28 Reviews - Birdeye",
         "body": "Read 28 customer reviews of Christian Brothers Air Conditioning"},
    ]
    monkeypatch.setattr(reviews, "search", lambda q, n=8: results)
    got = reviews.from_search("Christian Brothers Air Conditioning", "x, Austin, TX 78701, USA")
    assert (got["rating"], got["review_count"], got["review_source"]) == (None, 28, "Birdeye")


def test_listing_pages_and_foreign_profiles_rejected(monkeypatch):
    results = [
        {"href": "https://www.yelp.com/search?find_desc=roofing&find_loc=Austin",
         "title": "TOP 10 BEST Austin Roofing in Austin, TX - Updated 2026 - Yelp", "body": "4.8 (299 reviews)"},
        {"href": "https://www.yelp.com/biz/lone-star-roofing-austin", "title": "Austin Roofing Experts - Lone Star - Yelp",
         "body": "4.8 (150 reviews)"},                                   # slug is another business
        {"href": "https://reviews.birdeye.com/austin-roofing-and-construction-1646", "body": "Read 299 customer reviews",
         "title": "Austin Roofing and Construction - 299 Reviews - Birdeye"},  # different company
        {"href": "https://www.yelp.com/biz/austin-roofing-austin-3", "title": "Austin Roofing - Austin, TX - Yelp",
         "body": "4.2 (17 reviews)"},
    ]
    monkeypatch.setattr(reviews, "search", lambda q, n=8: results)
    got = reviews.from_search("Austin Roofing", "x, Austin, TX 78701, USA")
    assert (got["rating"], got["review_count"]) == (4.2, 17)


@pytest.mark.parametrize("listed,ours,same", [
    ("Radiant Plumbing & AC", "Radiant Plumbing", True),
    ("Vantage Roofing Reviews", "Vantage Roofing", True),
    ("Dustin Johnson Exteriors", "Dustin Johnson Exteriors & Roofing", True),
    ("Roger's Plumbing", "Roger's Plumbing Inc.", True),
    ("Austin Roofing and Construction", "Austin Roofing", False),
    ("Austin Roofing", "Austin Roofing and Construction", False),   # only 2 distinctive words left
    ("Lone Star Roofing", "Austin Roofing", False),
])
def test_same_business_name(listed, ours, same):
    assert reviews.same_business_name(listed, ours) is same


@pytest.mark.parametrize("href,title,name", [
    ("https://www.homeadvisor.com/rated.VantageRoofing.121975442.html", "Vantage Roofing Reviews - Austin, TX | HomeAdvisor", "Vantage Roofing"),
    ("https://www.angi.com/companylist/us/tx/austin/vantage-roofing-reviews-123.htm", "Vantage Roofing Reviews - Austin, TX | Angi", "Vantage Roofing"),
    ("https://www.bbb.org/us/tx/austin/profile/roofing-contractors/dustin-johnson-exteriors-roofing-0825-1",
     "Dustin Johnson Exteriors & Roofing | BBB Reviews", "Dustin Johnson Exteriors & Roofing"),
])
def test_real_profile_pages_accepted(href, title, name):
    assert reviews._is_business_profile(reviews._site_name(href), href, title, name)


def test_find_reviews_prefers_website(monkeypatch):
    monkeypatch.setattr(reviews, "search", lambda q, n=8: (_ for _ in ()).throw(AssertionError("no search needed")))
    site = {"aggregate_rating": {"ratingValue": 4.8, "reviewCount": 55}, "text": ""}
    assert reviews.find_reviews("X", "a, Austin, TX, USA", site)["review_count"] == 55
