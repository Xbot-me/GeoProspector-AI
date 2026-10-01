"""Full pipeline through the real FastAPI app, LangGraph (Postgres checkpointer)
and database, with every outbound network call faked."""
import time

import psycopg
import pytest
import requests

import db


def _db_up() -> bool:
    try:
        psycopg.connect(db.DATABASE_URL, connect_timeout=2).close()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _db_up(), reason="PostgreSQL not available")

BIZ = [
    {"place_id": "p-none", "name": "No Site Plumbing", "address": "Boise, ID", "phone": "555-0001",
     "category": "plumber", "website": None, "business_status": "OPERATIONAL", "rating": 4.8, "review_count": 212},
    {"place_id": "p-slow", "name": "Slow Roofing", "address": "Boise, ID", "phone": "555-0002",
     "category": "roofing_contractor", "website": "https://slowroofing.example", "business_status": "OPERATIONAL",
     "rating": 4.5, "review_count": 60},
    {"place_id": "p-blocked", "name": "Blocked HVAC", "address": "Boise, ID", "phone": "555-0003",
     "category": "hvac", "website": "https://blockedhvac.example", "business_status": "OPERATIONAL",
     "rating": 4.4, "review_count": 40},
    {"place_id": "p-fast", "name": "Fast Electric", "address": "Boise, ID", "phone": "555-0004",
     "category": "electrician", "website": "https://fastelectric.example", "business_status": "OPERATIONAL",
     "rating": 4.9, "review_count": 300},
]

PAGE = ("<html><head><meta name='viewport' content='width=device-width'></head>"
        "<body>Contact: owner@slowroofing.example or info@slowroofing.example</body></html>")


class R:
    def __init__(self, status=200, text=PAGE, data=None):
        self.status_code, self.text, self._d = status, text, data or {}

    def json(self):
        return self._d


def fake_get(url, *a, **k):
    if "pagespeedonline" in url:
        target = k["params"]["url"]
        score = 0.28 if "slowroofing" in target else 0.95
        return R(data={"lighthouseResult": {"categories": {"performance": {"score": score}},
                                           "audits": {"largest-contentful-paint": {"displayValue": "7.4 s"}}}})
    if "blockedhvac" in url:
        return R(403, "forbidden")
    if "fastelectric" in url:
        return R(200, PAGE.replace("slowroofing", "fastelectric"))
    if "slowroofing" in url:
        return R(200, PAGE)
    raise requests.exceptions.ConnectionError("unexpected " + url)


class FakeGemini:
    class models:
        @staticmethod
        def generate_content(model, contents):
            class T:
                text = ("LANGUAGE: English\nSUBJECTS:\nQuestion about the business\nHi\nHello\nBODY:\n"
                        "Hi there, a quick note.\n\nWould you like ideas?")
            if "bullet" in contents or "In 3-4 short bullet points" in contents:
                T.text = "- they lose calls"
            return T()


@pytest.fixture
def client(monkeypatch):
    import app as app_module
    import nodes.business_analyzer as ba
    import nodes.email_finder as ef
    import nodes.pitch_generator as pg
    import nodes.site_audit as sa
    import nodes.social_finder as sf
    import nodes.website_check as wc

    db.init_db()
    with db.get_conn() as c:
        c.execute("TRUNCATE businesses, search_runs, run_businesses, suppression_list CASCADE")

    for mod in (wc, ef, sa):
        monkeypatch.setattr(mod.requests, "get", fake_get)
    monkeypatch.setattr(ef, "ENABLE_WEB_SEARCH", False)
    monkeypatch.setattr(sf, "ENABLE_WEB_SEARCH", False)
    monkeypatch.setattr(ef, "_hunter_search", lambda d: None)
    monkeypatch.setattr(ba, "_client", FakeGemini())
    monkeypatch.setattr(pg, "_client", FakeGemini())
    monkeypatch.setattr(app_module, "search_businesses", lambda **k: [dict(b) for b in BIZ])
    monkeypatch.setattr(app_module, "_write_run_csv_to_disk", lambda run_id: None)  # keep tests off disk
    monkeypatch.setattr("email_verifier.verify_email", lambda e: {"valid": True, "mx_found": True})

    from fastapi.testclient import TestClient
    with TestClient(app_module.app) as c:
        c.auth = ("admin", "test-password")
        yield c


def test_full_run(client):
    run_id = client.post("/api/search", json={"query": "trades", "location": "Boise, Idaho, USA"}).json()["run_id"]

    for _ in range(100):
        if any(r["run_id"] == run_id and r["status"] in ("complete", "error") for r in client.get("/api/runs").json()):
            break
        time.sleep(0.2)

    leads = {b["place_id"]: b for b in db.get_all_leads()}
    assert set(leads) == {"p-none", "p-slow", "p-blocked", "p-fast"}

    none, slow, blocked, fast = (leads[k] for k in ("p-none", "p-slow", "p-blocked", "p-fast"))

    # no website: pitched
    assert none["website_quality"] == "none" and none["pitch_subject"] and none["pitch_body"]
    # slow site: PageSpeed turns a live site into a prospect and the finding is stored
    assert slow["website_quality"] == "outdated" and slow["pagespeed_score"] == 28
    assert "28/100" in slow["website_notes"] and slow["pitch_body"]
    # best address chosen: the named person, not info@
    assert slow["email"] == "owner@slowroofing.example"
    # blocked site: NOT silently treated as good, NOT pitched
    assert blocked["website_quality"] == "unknown" and not blocked["pitch_subject"]
    # fast site: good, not pitched
    assert fast["website_quality"] == "good" and fast["pagespeed_score"] == 95 and not fast["pitch_subject"]

    # nothing is queued until a human approves
    assert db.get_pending_auto_send_leads(limit=10) == []
    client.post("/api/leads/p-slow/status", json={"status": "approved"})
    assert [b["place_id"] for b in db.get_pending_auto_send_leads(limit=10)] == ["p-slow"]

    # phone-first list: prospects with a gap, best first, blocked/good excluded
    ids = [r["place_id"] for r in client.get("/api/call-list").json()["leads"]]
    assert set(ids) == {"p-none", "p-slow"}
