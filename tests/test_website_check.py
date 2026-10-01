import requests
import pytest

from nodes import website_check as wc

MODERN = (
    "<html><head><meta name='viewport' content='width=device-width'>"
    "<title>Joe's</title></head><body>Welcome to Joe's Plumbing. Call us today for fast, "
    "friendly service across the whole city.</body></html>"
)


class Resp:
    def __init__(self, status=200, text=MODERN):
        self.status_code = status
        self.text = text


def run(monkeypatch, behaviour, url="https://joes.com"):
    calls = {"n": 0}

    def fake_get(*a, **k):
        calls["n"] += 1
        b = behaviour
        if callable(b):
            b = b(calls["n"])
        if isinstance(b, Exception):
            raise b
        return b

    monkeypatch.setattr(wc.requests, "get", fake_get)
    return wc.check_website({"website": url}), calls["n"]


def test_no_website():
    assert wc.check_website({})["website_quality"] == "none"


@pytest.mark.parametrize("url", [
    "https://www.facebook.com/joes", "https://yelp.com/biz/joes", "https://m.yelp.com/biz/joes",
    "https://www.yellowpages.com/x", "https://linktr.ee/joes",
])
def test_social_and_directory_links_count_as_no_site(url):
    assert wc.check_website({"website": url})["website_quality"] == "social_only"


def test_lookalike_domain_is_not_social(monkeypatch):
    out, _ = run(monkeypatch, Resp(), url="https://notyelp.com.example.org")
    assert out["website_quality"] != "social_only"


def test_modern_site_is_good(monkeypatch):
    out, _ = run(monkeypatch, Resp())
    assert out["website_quality"] == "good"
    assert out["has_real_website"] is True


@pytest.mark.parametrize("status", [401, 403, 406, 429, 503, 520, 522])
def test_blocked_is_unknown_not_good(monkeypatch, status):
    out, _ = run(monkeypatch, Resp(status))
    assert out["website_quality"] == "unknown"


@pytest.mark.parametrize("status", [404, 410, 500, 502])
def test_hard_errors_are_dead(monkeypatch, status):
    out, _ = run(monkeypatch, Resp(status))
    assert out["website_quality"] == "dead"


def test_waf_challenge_page_is_unknown(monkeypatch):
    out, _ = run(monkeypatch, Resp(200, "<html><title>Just a moment...</title></html>"))
    assert out["website_quality"] == "unknown"


def test_timeout_retries_once_then_unknown(monkeypatch):
    out, n = run(monkeypatch, requests.exceptions.ReadTimeout("slow"))
    assert out["website_quality"] == "unknown"
    assert n == 2


def test_timeout_then_success_recovers(monkeypatch):
    out, n = run(monkeypatch, lambda i: requests.exceptions.ReadTimeout("slow") if i == 1 else Resp())
    assert out["website_quality"] == "good"
    assert n == 2


def test_dns_failure_is_dead_without_retry(monkeypatch):
    err = requests.exceptions.ConnectionError("NameResolutionError: Failed to resolve: Name or service not known")
    out, n = run(monkeypatch, err)
    assert out["website_quality"] == "dead"
    assert n == 1


def test_connection_reset_is_unknown(monkeypatch):
    out, _ = run(monkeypatch, requests.exceptions.ConnectionError("Connection reset by peer"))
    assert out["website_quality"] == "unknown"


def test_bad_certificate_is_a_real_finding(monkeypatch):
    err = requests.exceptions.SSLError("certificate verify failed: certificate has expired")
    out, n = run(monkeypatch, err)
    assert out["website_quality"] == "outdated"
    assert "certificate" in out["website_notes"].lower()
    assert n == 1


def test_tls_handshake_failure_is_unknown(monkeypatch):
    out, _ = run(monkeypatch, requests.exceptions.SSLError("EOF occurred in violation of protocol"))
    assert out["website_quality"] == "unknown"


def test_no_viewport_is_outdated(monkeypatch):
    out, _ = run(monkeypatch, Resp(200, "<html><body>Hello</body></html>"))
    assert out["website_quality"] == "outdated"
