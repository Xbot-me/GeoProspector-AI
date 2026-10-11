import auto_campaign as ac
from nodes.lead_scorer import score_lead


def test_trades_get_category_bonus_and_owner_points():
    base = {"website_quality": "none", "review_count": 50, "rating": 4.6, "phone": "1", "email": "a@b.com"}
    plain = score_lead({**base, "category": "bakery_supplies"})["lead_score"]
    trade = score_lead({**base, "category": "roofing_contractor"})["lead_score"]
    owner = score_lead({**base, "category": "roofing_contractor", "owner_name": "Jane Rivera",
                        "owner_linkedin": "https://linkedin.com/in/x"})
    assert trade == plain + 10
    assert owner["lead_score"] == trade + 10 and "Owner identified" in owner["score_breakdown"]
    assert score_lead({**base, "category": "plumber", "facebook_url": "f", "review_count": 900,
                       "owner_name": "x", "owner_linkedin": "y"})["lead_score"] <= 100


def test_lead_timezone_resolution():
    assert ac.get_lead_timezone("Paris, TX 75460, USA", "America/Chicago") == "America/Chicago"
    assert ac.get_lead_timezone("123 Main St, Paris, TX 75460, USA") == "America/New_York"
    assert ac.get_lead_timezone("1 Rue X, 75001 Paris, France") == "Europe/Paris"
    assert ac.get_lead_timezone("1 St, Wagga Wagga NSW 2650, Australia") == "Australia/Sydney"
    assert ac.get_lead_timezone("x, Germany", "Not/AZone") == "Europe/Berlin"
