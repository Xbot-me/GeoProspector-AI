"""
Hunter.io domain search: named people at a domain with role, email,
confidence, phone and LinkedIn. Free plan has a small monthly allowance;
failures (no key, out of credits) just return nothing.
"""
import logging

import requests

from config import HUNTER_API_KEY

logger = logging.getLogger(__name__)

HUNTER_URL = "https://api.hunter.io/v2/domain-search"


def domain_search(domain: str | None) -> dict:
    """Returns {"people": [...], "emails": [...]} (both possibly empty)."""
    empty = {"people": [], "emails": []}
    if not HUNTER_API_KEY or not domain:
        return empty
    try:
        resp = requests.get(HUNTER_URL, params={"domain": domain, "api_key": HUNTER_API_KEY, "limit": 10}, timeout=10)
    except requests.RequestException as e:
        logger.warning(f"Hunter request failed for {domain}: {e}")
        return empty
    if resp.status_code != 200:
        logger.info(f"Hunter returned {resp.status_code} for {domain}")
        return empty

    people, emails = [], []
    for item in (resp.json().get("data") or {}).get("emails") or []:
        value = (item.get("value") or "").lower()
        if not value:
            continue
        emails.append({
            "value": value,
            "source": "hunter",
            "type": item.get("type"),             # "personal" | "generic"
            "confidence": item.get("confidence"),
        })
        name = " ".join(p for p in (item.get("first_name"), item.get("last_name")) if p)
        if name:
            people.append({
                "name": name,
                "role": item.get("position") or None,
                "email": value,
                "phone": item.get("phone_number"),
                "linkedin": item.get("linkedin"),
                "source": "hunter",
            })
    return {"people": people, "emails": emails}
