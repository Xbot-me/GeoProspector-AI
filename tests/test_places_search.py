import pytest

from nodes import places_search as ps
from quota import QuotaExceededError


def place(i, status="OPERATIONAL", **kw):
    p = {"id": f"p{i}", "displayName": {"text": f"Biz {i}"}, "formattedAddress": "x",
         "businessStatus": status, "rating": 4.5, "userRatingCount": 50}
    p.update(kw)
    return p


class FakeResp:
    def __init__(self, data):
        self._d = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._d


@pytest.fixture
def api(monkeypatch):
    sent = []
    pages = []
    quota = {"n": 0, "limit": 99}

    def fake_post(url, headers=None, json=None, timeout=None):
        sent.append({"headers": headers, "json": json})
        return FakeResp(pages[len(sent) - 1])

    def fake_quota(n=1):
        if quota["n"] + n > quota["limit"]:
            raise QuotaExceededError("cap")
        quota["n"] += n

    monkeypatch.setattr(ps.requests, "post", fake_post)
    monkeypatch.setattr(ps, "check_and_increment", fake_quota)
    return sent, pages, quota


def test_pages_until_60_and_passes_token(api):
    sent, pages, _ = api
    pages += [
        {"places": [place(i) for i in range(0, 20)], "nextPageToken": "t1"},
        {"places": [place(i) for i in range(20, 40)], "nextPageToken": "t2"},
        {"places": [place(i) for i in range(40, 60)]},
    ]
    out = ps.search_businesses("roofers", "Boise, Idaho, USA", max_results=60)
    assert len(out) == 60
    assert len(sent) == 3
    assert "pageToken" not in sent[0]["json"]
    assert sent[1]["json"]["pageToken"] == "t1"
    assert sent[2]["json"]["pageToken"] == "t2"
    assert "nextPageToken" in sent[0]["headers"]["X-Goog-FieldMask"]


def test_stops_when_enough_results(api):
    sent, pages, quota = api
    pages += [{"places": [place(i) for i in range(20)], "nextPageToken": "t1"}]
    out = ps.search_businesses("roofers", "Boise", max_results=20)
    assert len(out) == 20 and len(sent) == 1 and quota["n"] == 1


def test_one_billable_call_per_page(api):
    sent, pages, quota = api
    pages += [{"places": [place(0)], "nextPageToken": "t"}, {"places": [place(1)]}]
    ps.search_businesses("x", "y", max_results=60)
    assert quota["n"] == 2


def test_closed_and_duplicates_dropped(api):
    _, pages, _ = api
    pages += [{"places": [place(1), place(1), place(2, "CLOSED_PERMANENTLY"),
                          place(3, "CLOSED_TEMPORARILY"), place(4)]}]
    out = ps.search_businesses("x", "y")
    assert [b["place_id"] for b in out] == ["p1", "p4"]


def test_missing_status_is_kept(api):
    _, pages, _ = api
    p = place(1)
    del p["businessStatus"]
    pages += [{"places": [p]}]
    assert len(ps.search_businesses("x", "y")) == 1


def test_quota_hit_on_later_page_keeps_earlier_results(api):
    _, pages, quota = api
    quota["limit"] = 1
    pages += [{"places": [place(i) for i in range(20)], "nextPageToken": "t"}]
    assert len(ps.search_businesses("x", "y", max_results=60)) == 20


def test_quota_hit_on_first_page_raises(api):
    _, _, quota = api
    quota["limit"] = 0
    with pytest.raises(QuotaExceededError):
        ps.search_businesses("x", "y")


def test_page_size_shrinks_on_last_page(api):
    sent, pages, _ = api
    pages += [{"places": [place(i) for i in range(20)], "nextPageToken": "t"},
              {"places": [place(i) for i in range(20, 30)]}]
    out = ps.search_businesses("x", "y", max_results=30)
    assert len(out) == 30
    assert sent[1]["json"]["pageSize"] == 10


def test_fields_mapped(api):
    _, pages, _ = api
    pages += [{"places": [place(1, websiteUri="https://a.com", nationalPhoneNumber="555", primaryType="plumber")]}]
    b = ps.search_businesses("x", "y")[0]
    assert b["website"] == "https://a.com" and b["phone"] == "555" and b["category"] == "plumber"
    assert b["rating"] == 4.5 and b["review_count"] == 50
