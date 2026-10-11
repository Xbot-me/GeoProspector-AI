import json

from enrichment import ai_extract, website
from enrichment.web_search import _parse_linkedin_title, city_from_address, matches_business
from nodes import contact_finder as cf

SITE_HOME = """<html><head>
<script type="application/ld+json">{"@context":"https://schema.org","@type":"Plumber","name":"Radiant Plumbing",
 "telephone":"+1 512-555-0100","email":"office@radiantplumbing.com",
 "founder":{"name":"Jane Rivera"},"sameAs":["https://www.linkedin.com/company/radiant-plumbing"]}</script>
</head><body>
<a href="/about-us">About Us</a> <a href="https://facebook.com/sharer.php?u=x">share</a>
<a href="https://www.facebook.com/RadiantPlumbingATX/">Facebook</a>
<a href="mailto:info@radiantplumbing.com?subject=hi">Email us</a>
<a href="tel:+1 (512) 555-0199">Call</a>
<span class="__cf_email__" data-cfemail="{cf}">[email protected]</span>
<p>Website by <a href="mailto:hello@webagency.io">hello@webagency.io</a></p>
</body></html>"""


def cf_encode(email, key=0x42):
    return f"{key:02x}" + "".join(f"{ord(c) ^ key:02x}" for c in email)


def test_website_extract_finds_contacts_and_schema_people():
    html = SITE_HOME.replace("{cf}", cf_encode("jane@radiantplumbing.com"))
    about = "<html><body><h1>Our team</h1><p>Owner Jane Rivera and office manager Tom Okafor.</p></body></html>"
    out = website.extract([("https://radiantplumbing.com", html), ("https://radiantplumbing.com/about-us", about)])
    emails = {e["value"] for e in out["emails"]}
    assert {"info@radiantplumbing.com", "jane@radiantplumbing.com", "office@radiantplumbing.com"} <= emails
    assert "+15125550199" in out["phones"]
    assert out["socials"]["facebook_url"] == "https://www.facebook.com/RadiantPlumbingATX"
    assert out["socials"]["company_linkedin"].endswith("/company/radiant-plumbing")
    assert {"name": "Jane Rivera", "role": "Founder"}.items() <= out["people"][0].items()
    assert out["text"].startswith("Our team")  # about page text comes before home text


def test_clean_email_rejects_junk():
    assert website.clean_email("logo@2x.png") is None
    assert website.clean_email("noreply@shop.com") is None
    assert website.clean_email("Info@Shop.com.") == "info@shop.com"


def test_ai_extract_drops_names_not_in_text(monkeypatch):
    monkeypatch.setattr(ai_extract.llm, "available", lambda: True)
    monkeypatch.setattr(ai_extract.llm, "generate_json", lambda prompt, temperature=None: {"people": [
        {"name": "Jane Rivera", "role": "Owner"},
        {"name": "John Invented", "role": "CEO"},       # hallucinated
        {"name": "Tom", "role": "Manager"},             # single word: ambiguous
    ]})
    people = ai_extract.extract_people("Meet owner Jane  Rivera and Tom.", "Radiant")
    assert [p["name"] for p in people] == ["Jane Rivera"]


def test_linkedin_title_parsing_and_name_matching():
    assert _parse_linkedin_title("Jane Rivera - Owner - Radiant Plumbing & AC | LinkedIn") == \
        ("Jane Rivera", "Owner", "Radiant Plumbing & AC")
    assert matches_business("Radiant Plumbing & AC", "Radiant Plumbing")
    assert not matches_business("Brilliant Electric", "Radiant Plumbing")


def test_city_from_address_formats():
    assert city_from_address("123 Main St, Austin, TX 78701, USA") == "Austin"
    assert city_from_address("2 Rue X, 75001 Paris, France") == "Paris"
    assert city_from_address("12 High St, Leeds LS1 4AB, UK") == "Leeds"


def test_merge_and_pick_owner_prefers_owner_role_and_trusted_sources():
    people = cf.merge_people([
        {"name": "Tom Okafor", "role": "Office Manager", "source": "website_ai"},
        {"name": "Jane Rivera", "role": None, "source": "website_ai"},
        {"name": "JANE RIVERA", "role": "Director", "source": "companies_house"},
        {"name": "Jane Rivera", "role": "Owner", "email": "jane@x.com", "source": "hunter"},
    ])
    assert len(people) == 2
    owner = cf.pick_owner(people)
    assert owner["name"] == "Jane Rivera" and owner["role"] == "Owner" and owner["email"] == "jane@x.com"
    assert set(owner["sources"]) == {"website_ai", "companies_house", "hunter"}


def test_pick_email_prefers_owner_on_business_domain():
    owner = {"name": "Jane Rivera", "email": None}
    cands = [
        {"value": "hello@webagency.io", "source": "website"},
        {"value": "info@radiantplumbing.com", "source": "website"},
        {"value": "jane@radiantplumbing.com", "source": "hunter", "confidence": 90},
    ]
    assert cf.pick_email(cands, "radiantplumbing.com", owner)["value"] == "jane@radiantplumbing.com"
    assert cf.pick_email(cands[:2], "radiantplumbing.com", None)["value"] == "info@radiantplumbing.com"
    assert cf.pick_email(cands[:1], "radiantplumbing.com", None) is None  # only someone else's address


def test_find_contacts_combines_sources(monkeypatch):
    monkeypatch.setattr(cf.website, "crawl", lambda url: [("u", "h")])
    monkeypatch.setattr(cf.website, "extract", lambda pages: {
        "emails": [{"value": "info@radiantplumbing.com", "source": "website"}],
        "phones": ["+15125550199"], "socials": {"person_linkedin": "https://linkedin.com/in/jane-rivera-123"},
        "people": [], "text": "Owner Jane Rivera"})
    monkeypatch.setattr(cf.ai_extract, "extract_people", lambda text, name: [{"name": "Jane Rivera", "role": "Owner", "source": "website_ai"}])
    monkeypatch.setattr(cf.hunter, "domain_search", lambda d: {"people": [], "emails": []})
    monkeypatch.setattr(cf.companies_house, "officers_for", lambda n, a: [])
    monkeypatch.setattr(cf.web_search, "find_social", lambda *a: None)
    monkeypatch.setattr(cf.web_search, "find_company_linkedin", lambda *a: "https://linkedin.com/company/radiant")
    monkeypatch.setattr(cf.web_search, "find_person_linkedin", lambda *a: (_ for _ in ()).throw(AssertionError("not needed")))
    monkeypatch.setattr(cf, "verify_email", lambda e: {"valid": True})

    out = cf.find_contacts({"name": "Radiant Plumbing", "address": "1 Main St, Austin, TX 78701, USA",
                            "website": "https://www.radiantplumbing.com", "website_quality": "outdated"})
    assert out["email"] == "info@radiantplumbing.com" and out["email_verified"] is True
    assert (out["owner_name"], out["owner_role"]) == ("Jane Rivera", "Owner")
    assert out["owner_linkedin"] == "https://linkedin.com/in/jane-rivera-123"  # site link with owner's surname
    assert out["company_linkedin"] == "https://linkedin.com/company/radiant"
    assert json.loads(out["contacts_json"])["phones"] == ["+15125550199"]
