"""One pass of the background sender against the real database."""
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


class Stop(Exception):
    pass


@pytest.fixture
def worker(monkeypatch):
    import app

    db.init_db()
    with db.get_conn() as c:
        c.execute("TRUNCATE businesses, search_runs, run_businesses, suppression_list CASCADE")

    sent = []

    def fake_send(**kw):
        sent.append(kw)
        return True, None

    def stop(_secs):
        raise Stop

    monkeypatch.setattr(app, "send_email", fake_send)
    monkeypatch.setattr(app, "is_good_send_time", lambda tz: True)
    monkeypatch.setattr(app.time, "sleep", stop)

    def run_once():
        try:
            app._interval_worker_loop()
        except Stop:
            pass
        return sent

    return app, run_once, sent


def add(pid, **kw):
    rec = {"place_id": pid, "name": f"Biz {pid}", "email": f"{pid}@x.com", "pitch_subject": f"Subj {pid}",
           "pitch_body": "body", "approval_status": "approved", "send_status": "pending_auto_send",
           "lead_score": 60, "address": "Boise, Idaho"}
    rec.update(kw)
    db.upsert_business(rec)


def test_sends_only_approved(worker):
    _, run_once, sent = worker
    add("no", approval_status="pending")
    assert run_once() == []  # nothing approved: queue empty, no send


def test_sends_approved_first_email(worker):
    _, run_once, sent = worker
    add("a")
    run_once()
    assert len(sent) == 1 and sent[0]["place_id"] == "a" and sent[0]["subject"] == "Subj a"
    assert sent[0]["is_followup"] is False


def test_due_followup_goes_before_new_email(worker):
    _, run_once, sent = worker
    add("new")
    add("old", send_status="sent")
    with db.get_conn() as c:
        c.execute("UPDATE businesses SET sent_at = NOW() - INTERVAL '8 days' WHERE place_id='old'")
    run_once()
    assert sent[0]["place_id"] == "old" and sent[0]["is_followup"] is True
    assert sent[0]["subject"] == "Re: Subj old"


def test_daily_cap_blocks_sending(worker, monkeypatch):
    app, run_once, sent = worker
    monkeypatch.setattr(app, "MAX_DAILY_EMAILS", 1)
    add("done", send_status="sent")
    with db.get_conn() as c:
        c.execute("UPDATE businesses SET sent_at = NOW() WHERE place_id='done'")
    add("a")
    run_once()
    assert sent == []


def test_outside_business_hours_waits(worker, monkeypatch):
    app, run_once, sent = worker
    monkeypatch.setattr(app, "is_good_send_time", lambda tz: False)
    add("a")
    run_once()
    assert sent == []
