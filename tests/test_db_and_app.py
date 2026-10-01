"""Tests that need a real PostgreSQL (DATABASE_URL, see conftest). They are
skipped automatically when the database is not reachable."""
import psycopg
import pytest

import db


def _db_up() -> bool:
    try:
        psycopg.connect(db.DATABASE_URL, connect_timeout=2).close()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _db_up(), reason="PostgreSQL not available")


@pytest.fixture(autouse=True)
def clean():
    db.init_db()
    with db.get_conn() as c:
        c.execute("TRUNCATE businesses, search_runs, run_businesses, suppression_list CASCADE")
    yield


def add(pid, **kw):
    rec = {"place_id": pid, "name": f"Biz {pid}", "email": f"{pid}@x.com", "pitch_subject": "s", "pitch_body": "b",
           "approval_status": "pending", "send_status": "pending_auto_send", "lead_score": 60,
           "website_quality": "none", "phone": "555"}
    rec.update(kw)
    db.upsert_business(rec)


def age(pid, days, col="sent_at"):
    with db.get_conn() as c:
        c.execute(f"UPDATE businesses SET {col} = NOW() - make_interval(days => %s) WHERE place_id = %s", (days, pid))


def pending_ids():
    return [b["place_id"] for b in db.get_pending_auto_send_leads(limit=50)]


# ── approval gate ───────────────────────────────────────────────────────

def test_unapproved_leads_are_never_queued():
    add("a")
    assert pending_ids() == []


def test_approved_lead_is_queued_and_best_score_first():
    add("a", approval_status="approved", lead_score=50)
    add("b", approval_status="approved", lead_score=90)
    add("c")  # not approved
    assert pending_ids() == ["b", "a"]


def test_approval_gate_can_be_turned_off(monkeypatch):
    import config
    monkeypatch.setattr(config, "REQUIRE_APPROVAL", False)
    add("a")
    assert pending_ids() == ["a"]


def test_suppressed_and_rejected_not_queued():
    add("a", approval_status="approved")
    add("b", approval_status="rejected")
    db.add_to_suppression("a@x.com", "manual")
    assert pending_ids() == []


def test_min_score_respected(monkeypatch):
    import config
    monkeypatch.setattr(config, "MIN_LEAD_SCORE", 70)
    add("a", approval_status="approved", lead_score=60)
    assert pending_ids() == []


# ── follow-ups ──────────────────────────────────────────────────────────

def test_followup_due_after_n_days_only():
    add("a", send_status="sent", approval_status="approved")
    age("a", 6)
    add("b", send_status="sent", approval_status="approved")
    age("b", 2)
    assert [b["place_id"] for b in db.get_followup_candidates(5)] == ["a"]


def test_followup_skips_replied_rejected_unsubscribed_suppressed():
    for pid, kw in [("r", {"approval_status": "replied"}), ("j", {"approval_status": "rejected"}),
                    ("u", {"send_status": "unsubscribed"}), ("s", {})]:
        add(pid, **{"send_status": "sent", "approval_status": "approved", **kw})
        age(pid, 9)
    db.add_to_suppression("s@x.com", "bounce")
    assert db.get_followup_candidates(5) == []


def test_followup_sent_once_and_not_repeated():
    add("a", send_status="sent", approval_status="approved")
    age("a", 9)
    db.record_followup_sent("a")
    assert db.get_followup_candidates(5) == []


def test_followup_does_not_touch_first_send_fields():
    add("a", send_status="sent", approval_status="approved")
    age("a", 9)
    before = db.get_business("a")["sent_at"]
    db.record_followup_sent("a")
    after = db.get_business("a")
    assert after["sent_at"] == before and after["send_status"] == "sent"


def test_failed_followup_is_not_retried_forever():
    add("a", send_status="sent", approval_status="approved")
    age("a", 9)
    db.record_followup_sent("a", status="failed", error="boom")
    assert db.get_followup_candidates(5) == []


def test_manually_marked_contacted_gets_no_followup():
    add("a", send_status="sent", approval_status="approved")  # sent_at is NULL
    assert db.get_followup_candidates(5) == []


def test_daily_count_includes_followups_and_ignores_simulated():
    add("a", send_status="sent", approval_status="approved")
    age("a", 0)
    add("b", send_status="simulated", approval_status="approved")
    age("b", 0)
    add("c", send_status="sent", approval_status="approved")
    age("c", 9)
    db.record_followup_sent("c")
    with db.get_conn() as c:
        c.execute("UPDATE businesses SET followup_sent_at = NOW() WHERE place_id='c'")
    assert db.get_daily_sent_count() == 2


def test_retry_requeues_failed_and_simulated():
    add("a", send_status="failed")
    add("b", send_status="simulated")
    add("c", send_status="sent")
    assert db.retry_failed_emails() == 2
    assert db.get_business("c")["send_status"] == "sent"


# ── call list ───────────────────────────────────────────────────────────

def test_call_list_filters_and_orders():
    add("a", lead_score=40)
    add("b", lead_score=90)
    add("c", phone=None)
    add("d", website_quality="good")
    add("e", website_quality="unknown")
    add("f", approval_status="rejected")
    add("g", approval_status="replied")
    add("h", send_status="unsubscribed")
    assert [b["place_id"] for b in db.get_call_list()] == ["b", "a"]
    assert [b["place_id"] for b in db.get_call_list(min_score=50)] == ["b"]


def test_pagespeed_fields_round_trip():
    add("a", pagespeed_score=31, pagespeed_lcp="6.2 s")
    b = db.get_business("a")
    assert b["pagespeed_score"] == 31 and b["pagespeed_lcp"] == "6.2 s"


# ── HTTP API ────────────────────────────────────────────────────────────

@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    import app as app_module
    with TestClient(app_module.app) as c:
        yield c


AUTH = ("admin", "test-password")


def test_api_requires_auth(client):
    assert client.get("/api/call-list").status_code == 401
    assert client.post("/api/leads/a/status", json={"status": "approved"}).status_code == 401


def test_worker_not_started_when_auto_send_off(client):
    r = client.get("/api/scheduler/status", auth=AUTH).json()
    assert r["is_running"] is False and r["daily_limit"] == 10
    assert "off" in r["next_send_time"].lower()


def test_approve_then_replied_flow(client):
    add("a")
    assert pending_ids() == []
    assert client.post("/api/leads/a/status", json={"status": "approved"}, auth=AUTH).json()["approval_status"] == "approved"
    assert pending_ids() == ["a"]
    assert client.post("/api/leads/a/status", json={"status": "replied"}, auth=AUTH).json()["approval_status"] == "replied"
    assert pending_ids() == []


def test_unknown_status_rejected(client):
    add("a")
    assert "error" in client.post("/api/leads/a/status", json={"status": "bogus"}, auth=AUTH).json()
    assert db.get_business("a")["approval_status"] == "pending"


def test_call_list_json_and_csv(client):
    add("a", lead_score=80, rating=4.6, review_count=90)
    j = client.get("/api/call-list?min_score=50", auth=AUTH).json()
    assert j["count"] == 1 and j["leads"][0]["phone"] == "555" and "90 reviews" in j["leads"][0]["opener"]
    r = client.get("/api/call-list?format=csv", auth=AUTH)
    assert r.headers["content-type"].startswith("text/csv")
    assert r.text.splitlines()[0].startswith("name,phone")
    assert "Biz a" in r.text


def test_unsubscribe_blocks_followup(client):
    add("a", send_status="sent", approval_status="approved")
    age("a", 9)
    assert client.get("/api/unsubscribe/a").status_code == 200
    assert db.get_followup_candidates(5) == []


# ── regression: a lead must not be its own duplicate ────────────────────

def test_lead_is_not_a_duplicate_of_its_own_email():
    add("a", email="owner@x.com")
    assert db.is_business_already_processed("", "", "owner@x.com", exclude_place_id="a") is False


def test_same_email_on_another_lead_is_still_a_duplicate():
    add("a", email="owner@x.com")
    add("b", email="owner@x.com")
    assert db.is_business_already_processed("", "", "owner@x.com", exclude_place_id="b") is True
