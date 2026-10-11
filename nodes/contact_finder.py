"""
Node: find_contacts

Builds the contact picture for a business from every free source and picks
the best owner and the best email to send to.

  1. Business website: emails (incl. Cloudflare-protected), phones, social and
     LinkedIn links, schema.org people; Gemini names owners/staff from the
     about/team text (verified against the text)
  2. Hunter.io domain search (if HUNTER_API_KEY): named people, roles, emails
  3. UK Companies House officers (if COMPANIES_HOUSE_API_KEY and a UK address)
  4. DuckDuckGo: Facebook / Instagram / LinkedIn company page, the owner's
     LinkedIn profile, and last-resort owner name and email searches
  5. Emails and social links from the places listing itself (Overture)
  6. Rating + review count when the places provider has none (enrichment/reviews.py)

Everything found is kept in contacts_json; the chosen values go into the
regular columns (email, owner_name, owner_role, owner_linkedin, ...).
"""
import json
import logging
import re

from enrichment import ai_extract, companies_house, hunter, reviews, web_search, website
from email_verifier import verify_email
from state import BusinessState

logger = logging.getLogger(__name__)

# Higher = more likely to be the decision maker we want to address.
_ROLE_PRIORITY = (
    (re.compile(r"\b(co-?)?owner\b|proprietor|inhaber|propietario|propriétaire|eigenaar", re.I), 100),
    (re.compile(r"\b(co-?)?founder\b|gründer|fundador|fondateur", re.I), 95),
    (re.compile(r"\bceo\b|chief executive|president|principal|geschäftsführer|gerente general", re.I), 90),
    (re.compile(r"managing director|\bmd\b", re.I), 85),
    (re.compile(r"\bdirector\b|\bpartner\b", re.I), 70),
    (re.compile(r"general manager|office manager|\bmanager\b", re.I), 60),
)
_SOURCE_TRUST = {"companies_house": 4, "hunter": 3, "website_schema": 3, "website_ai": 2,
                 "linkedin_search": 2, "web_search": 1}
_GENERIC_LOCAL_PARTS = {"info", "contact", "office", "hello", "admin", "sales", "enquiries", "inquiries",
                        "service", "support", "mail", "team", "booking", "bookings", "reception", "kontakt"}


def role_score(role: str | None) -> int:
    for pattern, score in _ROLE_PRIORITY:
        if role and pattern.search(role):
            return score
    return 30 if role else 20


def _person_key(name: str) -> tuple[str, str]:
    words = re.findall(r"[a-zà-ÿ]+", name.lower())
    return (words[0], words[-1]) if words else ("", "")


def merge_people(people: list[dict]) -> list[dict]:
    """Merge records of the same person (same first + last name) across sources."""
    merged: dict[tuple[str, str], dict] = {}
    for p in people:
        name = (p.get("name") or "").strip()
        if len(name.split()) < 2:
            continue
        key = _person_key(name)
        cur = merged.setdefault(key, {"name": name, "role": None, "email": None, "phone": None,
                                      "linkedin": None, "sources": []})
        if p.get("source") and p["source"] not in cur["sources"]:
            cur["sources"].append(p["source"])
        for field in ("email", "phone", "linkedin"):
            cur[field] = cur[field] or p.get(field)
        if role_score(p.get("role")) > role_score(cur["role"]):
            cur["role"] = p.get("role")
    return list(merged.values())


def pick_owner(people: list[dict]) -> dict | None:
    if not people:
        return None
    return max(people, key=lambda p: (role_score(p.get("role")),
                                      sum(_SOURCE_TRUST.get(s, 0) for s in p.get("sources", []))))


def email_score(candidate: dict, domain: str | None, owner: dict | None) -> int:
    email = candidate["value"]
    local, email_domain = email.rsplit("@", 1)
    score = 0
    if domain and (email_domain == domain or email_domain.endswith("." + domain)):
        score += 4
    elif domain:
        score -= 3  # someone else's address (web designer, directory, other business)
    if owner:
        first, last = _person_key(owner["name"])
        if owner.get("email") == email or (first and first in local) or (last and len(last) > 2 and last in local):
            score += 3
    if local in _GENERIC_LOCAL_PARTS:
        score += 1  # monitored inbox: better than an unknown individual
    if candidate.get("source") == "hunter" and (candidate.get("confidence") or 0) >= 80:
        score += 1
    if candidate.get("source") == "web_search":
        score -= 1
    return score


def pick_email(candidates: list[dict], domain: str | None, owner: dict | None) -> dict | None:
    if not candidates:
        return None
    best = max(candidates, key=lambda c: email_score(c, domain, owner))
    return best if email_score(best, domain, owner) > -2 else None


def find_contacts(state: BusinessState) -> dict:
    name = state.get("name", "")
    address = state.get("address", "")
    url = state.get("website")
    quality = state.get("website_quality")
    domain = website.site_domain(url) if quality not in ("none", "social_only") else None

    people: list[dict] = []
    emails: list[dict] = []
    phones: list[str] = []
    socials: dict[str, str] = {}
    sources: list[str] = []
    site = None

    # 1. The business's own website
    if url and domain and quality != "dead":
        site = website.extract(website.crawl(url))
        emails += site["emails"]
        phones += site["phones"]
        socials.update(site["socials"])
        people += site["people"]
        people += ai_extract.extract_people(site["text"], name)
        if site["emails"] or site["people"]:
            sources.append("website")

    # 1b. Contacts already in the places listing (Overture has emails + socials)
    for raw in state.get("listing_emails") or []:
        if clean := website.clean_email(raw):
            emails.append({"value": clean, "source": "listing"})
    for link in state.get("listing_socials") or []:
        for key, pattern in website.SOCIAL_PATTERNS.items():
            if key not in socials and (m := pattern.match(link)):
                socials[key] = m.group(0).rstrip("/")
    if state.get("listing_emails") or state.get("listing_socials"):
        sources.append("listing")

    # 2. Hunter.io
    h = hunter.domain_search(domain)
    if h["people"] or h["emails"]:
        people += h["people"]
        emails += h["emails"]
        sources.append("hunter")

    # 3. UK Companies House
    officers = companies_house.officers_for(name, address)
    if officers:
        people += officers
        sources.append("companies_house")

    # 4. Public profiles via web search
    socials.setdefault("facebook_url", state.get("facebook_url"))
    socials.setdefault("instagram_url", state.get("instagram_url"))
    if not socials.get("facebook_url"):
        socials["facebook_url"] = web_search.find_social(name, address, "facebook.com")
    if not socials.get("instagram_url"):
        socials["instagram_url"] = web_search.find_social(name, address, "instagram.com")
    if not socials.get("company_linkedin"):
        socials["company_linkedin"] = web_search.find_company_linkedin(name, address)

    people = merge_people(people)
    owner = pick_owner(people)
    if owner is None:
        found = web_search.find_owner_on_linkedin(name, address) or web_search.find_owner_name(name, address)
        if found:
            people = merge_people(people + [found])
            owner = pick_owner(people)
            sources.append(found["source"])
    if owner and not owner.get("linkedin"):
        # A personal LinkedIn link on the site counts only if its slug carries the owner's surname.
        site_profile = socials.get("person_linkedin")
        _, last = _person_key(owner["name"])
        if site_profile and last and last in site_profile.lower():
            owner["linkedin"] = site_profile
        else:
            owner["linkedin"] = web_search.find_person_linkedin(owner["name"], name)

    if not emails:
        emails = web_search.find_emails(name, address, domain)
        if emails:
            sources.append("web_search")

    # De-duplicate emails, keeping the first (most trusted) source of each
    unique: dict[str, dict] = {}
    for e in emails:
        unique.setdefault(e["value"], e)
    emails = list(unique.values())

    best = pick_email(emails, domain, owner)
    email, verified = (best["value"], None) if best else (None, None)
    if email:
        try:
            verified = verify_email(email).get("valid")
        except Exception as e:
            logger.error(f"Email verification error for {email}: {e}")

    review = None
    if not state.get("review_count"):
        review = reviews.find_reviews(name, address, site)

    existing = state.get("contact_sources")
    contacts = {
        "people": people,
        "emails": emails,
        "phones": phones,
        "socials": {k: v for k, v in socials.items() if v},
    }
    return {
        "email": email,
        "email_source": best["source"] if best else None,
        "email_verified": verified,
        "owner_name": owner["name"] if owner else None,
        "owner_role": owner.get("role") if owner else None,
        "owner_linkedin": owner.get("linkedin") if owner else None,
        "company_linkedin": socials.get("company_linkedin"),
        "facebook_url": socials.get("facebook_url"),
        "instagram_url": socials.get("instagram_url"),
        "contacts_json": json.dumps(contacts),
        "contact_sources": ", ".join(([existing] if existing else []) + sources) or None,
        **(review or {}),
    }
