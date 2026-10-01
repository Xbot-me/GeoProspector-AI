from nodes.email_finder import rank_emails


def test_person_at_own_domain_beats_generic_inbox():
    out = rank_emails(["info@joes.com", "joe@joes.com", "joe@gmail.com"], "www.joes.com")
    assert out == ["joe@joes.com", "info@joes.com", "joe@gmail.com"]


def test_noreply_and_system_addresses_dropped():
    out = rank_emails(["noreply@joes.com", "no-reply@joes.com", "postmaster@joes.com", "sam@joes.com"], "joes.com")
    assert out == ["sam@joes.com"]


def test_subdomain_counts_as_own_domain():
    assert rank_emails(["a@mail.joes.com", "b@other.com"], "joes.com")[0] == "a@mail.joes.com"


def test_stable_order_on_ties_and_dedupe():
    out = rank_emails(["x@a.com", "y@a.com", "x@a.com"], None)
    assert out == ["x@a.com", "y@a.com"]


def test_generic_only_still_returned():
    assert rank_emails(["info@joes.com"], "joes.com") == ["info@joes.com"]


def test_empty():
    assert rank_emails([], "joes.com") == []
