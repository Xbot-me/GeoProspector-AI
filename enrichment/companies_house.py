"""
UK Companies House (free API key): active officers (directors) of the
registered company that matches a UK business. Only used when the address is
in the UK and COMPANIES_HOUSE_API_KEY is set.

https://developer.company-information.service.gov.uk/
"""
import logging
import re

import requests

from config import COMPANIES_HOUSE_API_KEY

logger = logging.getLogger(__name__)

API = "https://api.company-information.service.gov.uk"
_UK_MARKERS = ("uk", "united kingdom", "england", "scotland", "wales", "northern ireland")
_SUFFIXES = re.compile(r"\b(ltd|limited|llp|plc|co|company|and|the|&)\b")
_POSTCODE_RE = re.compile(r"\b([A-Z]{1,2}\d[A-Z\d]?)\s*(\d[A-Z]{2})\b", re.I)


def _is_uk(address: str) -> bool:
    return (address or "").rsplit(",", 1)[-1].strip().lower() in _UK_MARKERS


def _tokens(name: str) -> set[str]:
    return set(_SUFFIXES.sub(" ", re.sub(r"[^a-z0-9& ]", " ", name.lower())).split())


def _postcode(text: str) -> str | None:
    m = _POSTCODE_RE.search(text or "")
    return (m.group(1) + m.group(2)).upper() if m else None


def _display_name(officer_name: str) -> str:
    """'SMITH, John Paul' -> 'John Paul Smith'."""
    if "," in officer_name:
        surname, given = officer_name.split(",", 1)
        return f"{given.strip()} {surname.strip().title()}".strip()
    return officer_name.title()


def _get(path: str, params: dict | None = None) -> dict | None:
    try:
        resp = requests.get(API + path, params=params, auth=(COMPANIES_HOUSE_API_KEY, ""), timeout=10)
    except requests.RequestException as e:
        logger.warning(f"Companies House request failed: {e}")
        return None
    return resp.json() if resp.status_code == 200 else None


def officers_for(business_name: str, address: str) -> list[dict]:
    if not COMPANIES_HOUSE_API_KEY or not _is_uk(address):
        return []
    found = _get("/search/companies", {"q": business_name, "items_per_page": 10}) or {}
    wanted, wanted_pc = _tokens(business_name), _postcode(address)
    best, best_score = None, 0.0
    for item in found.get("items", []):
        if item.get("company_status") != "active":
            continue
        have = _tokens(item.get("title", ""))
        if not have or not wanted:
            continue
        score = len(wanted & have) / len(wanted | have)
        if wanted_pc and _postcode(item.get("address_snippet", "")) == wanted_pc:
            score += 0.5
        if score > best_score:
            best, best_score = item, score
    if not best or best_score < 0.6:
        return []  # no confident match: a wrong company would mean wrong people

    data = _get(f"/company/{best['company_number']}/officers", {"items_per_page": 20}) or {}
    people = []
    for officer in data.get("items", []):
        if officer.get("resigned_on") or not officer.get("name"):
            continue
        if "corporate" in (officer.get("officer_role") or ""):
            continue  # a company acting as officer, not a person
        role = (officer.get("officer_role") or "").replace("-", " ").title() or None
        people.append({"name": _display_name(officer["name"]), "role": role, "source": "companies_house",
                       "company_number": best["company_number"]})
    return people
