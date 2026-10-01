from callscript import build_call_sheet, build_opener
from findings import describe_finding
from followup import build_followup
from nodes.lead_scorer import score_lead


def test_unknown_site_scores_no_gap_points():
    out = score_lead({"website_quality": "unknown", "review_count": 0})
    assert "unknown" not in out["score_breakdown"].lower()
    assert out["lead_score"] == 5  # just the tiny-reviews baseline


def test_none_site_with_reputation_gets_winnable_bonus():
    out = score_lead({"website_quality": "none", "rating": 4.6, "review_count": 120})
    assert "Strong reputation" in out["score_breakdown"]


def test_good_site_never_winnable():
    out = score_lead({"website_quality": "good", "rating": 4.9, "review_count": 500})
    assert "Strong reputation" not in out["score_breakdown"]


def test_low_rating_not_winnable():
    out = score_lead({"website_quality": "none", "rating": 3.9, "review_count": 120})
    assert "Strong reputation" not in out["score_breakdown"]


def test_pagespeed_bonus_tiers():
    s = lambda p: score_lead({"website_quality": "outdated", "pagespeed_score": p})["score_breakdown"]
    assert "PageSpeed 20/100: +10" in s(20)
    assert "PageSpeed 40/100: +5" in s(40)
    assert "PageSpeed" not in s(70)


def test_score_capped_at_100():
    out = score_lead({"website_quality": "none", "rating": 5, "review_count": 900, "email": "a@b.com",
                      "phone": "1", "facebook_url": "x", "category": "restaurant"})
    assert out["lead_score"] == 100


def test_finding_prefers_measured_pagespeed():
    f = describe_finding({"website_quality": "outdated", "pagespeed_score": 31, "pagespeed_lcp": "6.2 s"})
    assert "31/100" in f and "6.2 s" in f


def test_finding_for_each_quality():
    assert "no website listed" in describe_finding({"website_quality": "none"})
    assert "does not load" in describe_finding({"website_quality": "dead", "website_notes": "HTTP 404"})
    assert "social media" in describe_finding({"website_quality": "social_only"})
    assert "viewport" in describe_finding({"website_quality": "outdated", "website_notes": "No mobile viewport"})


def test_followup_subject_and_tone():
    subj, body = build_followup({"name": "Joe's Plumbing", "pitch_subject": "Joe's Plumbing on Google", "owner_name": "Joe"})
    assert subj == "Re: Joe's Plumbing on Google"
    assert body.startswith("Hi Joe,")
    assert "won't" in body and "—" not in body and "!" not in body


def test_followup_does_not_double_re():
    subj, _ = build_followup({"name": "J", "pitch_subject": "Re: hi"})
    assert subj == "Re: hi"


def test_followup_without_subject_or_owner():
    subj, body = build_followup({"name": "Joe's"})
    assert subj.startswith("Re:") and body.startswith("Hi,")


def test_call_opener_uses_finding_and_reviews():
    lead = {"name": "Joe's", "phone": "555", "website_quality": "none", "rating": 4.7, "review_count": 80}
    op = build_opener(lead)
    assert "80 reviews at 4.7 stars" in op and "no website listed" in op


def test_call_sheet_rows():
    rows = build_call_sheet([{"name": "A", "phone": "1", "website_quality": "dead", "website_notes": "HTTP 404", "lead_score": 70}])
    assert rows[0]["phone"] == "1" and rows[0]["opener"] and rows[0]["lead_score"] == 70
