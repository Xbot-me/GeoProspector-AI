import pytest

import email_sender as es


@pytest.fixture
def recorded(monkeypatch):
    rec = []
    monkeypatch.setattr(es, "record_email_sent", lambda pid, status="sent", error=None: rec.append(("first", pid, status, error)))
    monkeypatch.setattr(es, "record_followup_sent", lambda pid, status="sent", error=None: rec.append(("followup", pid, status, error)))
    monkeypatch.setattr(es, "is_suppressed", lambda e: False)
    return rec


def test_unconfigured_resend_is_not_recorded_as_sent(monkeypatch, recorded):
    monkeypatch.setattr(es, "EMAIL_PROVIDER", "resend")
    monkeypatch.setattr(es, "RESEND_API_KEY", "")
    ok, err = es.send_email("p1", "a@b.com", "s", "body")
    assert ok is False and "not configured" in err
    assert recorded == [("first", "p1", "simulated", err)]


def test_unconfigured_smtp_is_not_recorded_as_sent(monkeypatch, recorded):
    monkeypatch.setattr(es, "EMAIL_PROVIDER", "smtp")
    monkeypatch.setattr(es, "SMTP_USER", "")
    ok, err = es.send_email("p1", "a@b.com", "s", "body")
    assert ok is False
    assert recorded[0][2] == "simulated"


def test_placeholder_resend_key_is_simulated(monkeypatch, recorded):
    monkeypatch.setattr(es, "EMAIL_PROVIDER", "resend")
    monkeypatch.setattr(es, "RESEND_API_KEY", "re_xxxx123")
    ok, _ = es.send_email("p1", "a@b.com", "s", "body")
    assert ok is False


def test_followup_uses_followup_recorder(monkeypatch, recorded):
    monkeypatch.setattr(es, "EMAIL_PROVIDER", "resend")
    monkeypatch.setattr(es, "RESEND_API_KEY", "")
    es.send_email("p1", "a@b.com", "s", "body", is_followup=True)
    assert recorded[0][0] == "followup"


def test_invalid_and_suppressed_recipients(monkeypatch, recorded):
    ok, err = es.send_email("p1", "nope", "s", "b")
    assert not ok and "Invalid" in err
    monkeypatch.setattr(es, "is_suppressed", lambda e: True)
    ok, err = es.send_email("p2", "a@b.com", "s", "b")
    assert not ok and "Suppressed" in err


def test_resend_success_sends_headers(monkeypatch, recorded):
    sent = {}

    class R:
        status_code = 200
        text = "ok"

    def fake_post(url, headers=None, json=None, timeout=None):
        sent.update(json)
        return R()

    monkeypatch.setattr(es, "EMAIL_PROVIDER", "resend")
    monkeypatch.setattr(es, "RESEND_API_KEY", "re_live_key")
    monkeypatch.setattr(es.requests, "post", fake_post)
    ok, _ = es.send_email("p1", "a@b.com", "s", "body")
    assert ok and recorded == [("first", "p1", "sent", None)]
    assert sent["headers"]["List-Unsubscribe"].startswith("<mailto:")
    assert "List-Unsubscribe-Post" not in sent["headers"]  # no one-click without a real endpoint
    assert "Unsubscribe: mailto:" in sent["text"]


def test_one_click_unsubscribe_with_public_url(monkeypatch, recorded):
    monkeypatch.setattr(es, "UNSUBSCRIBE_BASE_URL", "https://app.example.com")
    assert es._unsubscribe_target("p1") == "https://app.example.com/api/unsubscribe/p1"
    assert es._unsubscribe_headers("https://x", True)["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"


def test_html_has_no_tracking_pixel_without_public_url(monkeypatch):
    monkeypatch.setattr(es, "TRACKING_BASE_URL", "")
    html = es.format_html_email("Hello there", "p1")
    assert "/api/track/open/" not in html
    assert "mailto:" in html


def test_html_has_pixel_with_public_url(monkeypatch):
    monkeypatch.setattr(es, "TRACKING_BASE_URL", "https://app.example.com")
    assert "https://app.example.com/api/track/open/p1.png" in es.format_html_email("Hello", "p1")


def test_html_uses_configured_identity_and_hides_missing_phone():
    html = es.format_html_email("Hello", "p1")
    assert es.SENDER_NAME in html and es.SENDER_EMAIL in html
    assert "+880" not in html


def test_signature_stripped_from_html_copy():
    body = f"Hello Joe.\n\n{es.SENDER_NAME}\nWeb dev"
    html = es.format_html_email(body, "p1")
    assert "Web dev" not in html
