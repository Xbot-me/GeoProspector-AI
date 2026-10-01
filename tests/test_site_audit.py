import requests

from nodes import site_audit as sa


class Resp:
    def __init__(self, status=200, data=None):
        self.status_code = status
        self._d = data or {}

    def json(self):
        return self._d


def lh(score, lcp="6.2 s"):
    return {"lighthouseResult": {
        "categories": {"performance": {"score": score}},
        "audits": {"largest-contentful-paint": {"displayValue": lcp}},
    }}


def state(quality="good", **kw):
    s = {"website": "https://joes.com", "website_quality": quality, "website_notes": "Live, modern website"}
    s.update(kw)
    return s


def test_slow_good_site_becomes_prospect(monkeypatch):
    monkeypatch.setattr(sa.requests, "get", lambda *a, **k: Resp(200, lh(0.31)))
    out = sa.audit_site(state("good"))
    assert out["pagespeed_score"] == 31
    assert out["website_quality"] == "outdated"
    assert out["has_real_website"] is False
    assert "31/100" in out["website_notes"] and "6.2 s" in out["website_notes"]


def test_fast_site_stays_good(monkeypatch):
    monkeypatch.setattr(sa.requests, "get", lambda *a, **k: Resp(200, lh(0.92, "1.4 s")))
    out = sa.audit_site(state("good"))
    assert out == {"pagespeed_score": 92, "pagespeed_lcp": "1.4 s"}


def test_outdated_site_keeps_existing_notes(monkeypatch):
    monkeypatch.setattr(sa.requests, "get", lambda *a, **k: Resp(200, lh(0.2)))
    out = sa.audit_site(state("outdated", website_notes="No mobile viewport meta tag"))
    assert "No mobile viewport meta tag" in out["website_notes"]
    assert "20/100" in out["website_notes"]


def test_threshold_boundary(monkeypatch):
    monkeypatch.setattr(sa.requests, "get", lambda *a, **k: Resp(200, lh(0.50)))
    assert "website_quality" not in sa.audit_site(state("good"))  # 50 is not below 50


def test_api_failure_changes_nothing(monkeypatch):
    monkeypatch.setattr(sa.requests, "get", lambda *a, **k: Resp(429))
    assert sa.audit_site(state("good")) == {}


def test_network_error_changes_nothing(monkeypatch):
    def boom(*a, **k):
        raise requests.exceptions.ConnectTimeout("x")
    monkeypatch.setattr(sa.requests, "get", boom)
    assert sa.audit_site(state("good")) == {}


def test_missing_score_changes_nothing(monkeypatch):
    monkeypatch.setattr(sa.requests, "get", lambda *a, **k: Resp(200, {"lighthouseResult": {"categories": {}}}))
    assert sa.audit_site(state("good")) == {}


def test_only_runs_for_live_sites(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("should not be called")
    monkeypatch.setattr(sa.requests, "get", boom)
    for q in ("none", "dead", "social_only", "unknown"):
        assert sa.audit_site(state(q)) == {}
    assert sa.audit_site({"website_quality": "good"}) == {}  # no website


def test_disabled_flag(monkeypatch):
    monkeypatch.setattr(sa, "ENABLE_PAGESPEED", False)
    monkeypatch.setattr(sa.requests, "get", lambda *a, **k: (_ for _ in ()).throw(AssertionError()))
    assert sa.audit_site(state("good")) == {}


def test_api_key_sent_when_configured(monkeypatch):
    seen = {}

    def fake(url, params=None, timeout=None):
        seen.update(params)
        return Resp(200, lh(0.9))

    monkeypatch.setattr(sa, "PAGESPEED_API_KEY", "abc")
    monkeypatch.setattr(sa.requests, "get", fake)
    sa.audit_site(state("good"))
    assert seen["key"] == "abc" and seen["strategy"] == "mobile"
