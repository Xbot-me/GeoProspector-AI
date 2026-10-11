"""
"Suggest target": a fresh bundle of 3-5 related niches plus one city.

Rules
  - never suggest a niche already searched in that location (search_runs)
  - never repeat a bundle suggested recently, so each click gives a new one
  - Gemini proposes when available; the curated catalog is the fallback and
    is randomised among the best candidates
"""
import logging
import random
from collections import deque

import llm
from auto_campaign import NICHE_REFERENCE, TARGET_LOCATIONS, format_location
from db import get_conn

logger = logging.getLogger(__name__)

MIN_NICHES, MAX_NICHES = 3, 5

# From catalog/target_catalog.json: niches (best hit rate first) and locations.
_HIT_ORDER = {"high": 0, "medium-high": 1, "medium": 2}
CATALOG_NICHES = [
    n["search_term"].title()
    for n in sorted(NICHE_REFERENCE, key=lambda n: _HIT_ORDER.get(str(n.get("hit_rate", "")).lower(), 3))
]
CATALOG_LOCATIONS = [format_location(t) for t in TARGET_LOCATIONS]

# (location_lower, frozenset(niches_lower)) of recent suggestions, in-process only.
_recent: deque = deque(maxlen=40)


def _norm(s: str) -> str:
    return " ".join((s or "").lower().split())


def split_niches(query: str) -> list[str]:
    """Run queries store bundles as 'Roofers, HVAC Contractors'."""
    return [n.strip() for n in (query or "").split(",") if n.strip()]


def executed_targets() -> tuple[set[tuple[str, str]], list[str]]:
    """(set of (niche, location) already searched, recent 'niche in location' lines newest first)."""
    try:
        with get_conn() as conn:
            rows = conn.execute("SELECT query, location FROM search_runs ORDER BY created_at DESC").fetchall()
    except Exception as e:
        logger.warning(f"Could not read search history for suggestions: {e}")
        return set(), []
    executed, recent = set(), []
    for r in rows:
        for niche in split_niches(r["query"]):
            executed.add((_norm(niche), _norm(r["location"])))
            if len(recent) < 40:
                recent.append(f"{niche} in {r['location']}")
    return executed, recent


def _fresh_niches(niches: list[str], location: str, executed: set) -> list[str]:
    seen, out = set(), []
    for n in niches:
        key = _norm(n)
        if key and key not in seen and (key, _norm(location)) not in executed:
            seen.add(key)
            out.append(n.strip())
    return out[:MAX_NICHES]


def is_searchable(niche: str) -> bool:
    """True when the area search maps every word of the niche to known business categories.
    Suggested niches like 'Architectural Millwork Specialists' found nothing in production."""
    from nodes.places_overture import NicheMatcher
    return NicheMatcher(niche).curated


def _is_recent(location: str, niches: list[str]) -> bool:
    return (_norm(location), frozenset(_norm(n) for n in niches)) in _recent


def _remember(location: str, niches: list[str]) -> None:
    _recent.append((_norm(location), frozenset(_norm(n) for n in niches)))


def _from_gemini(executed: set, recent_runs: list[str]) -> dict | None:
    recent_suggestions = [f"{', '.join(sorted(n))} in {loc}" for loc, n in list(_recent)[-10:]]
    prompt = f"""I run a web design agency that builds websites for local service businesses.
Suggest ONE city and {MIN_NICHES}-{MAX_NICHES} related local business niches to prospect there together.

Good niches: high customer value ($2k+ jobs), owner-operated, often weak or outdated websites
(trades, home services, clinics, specialist contractors). Related means they share customers
or suppliers (e.g. Roofers, Gutter Installers, Siding Contractors).
Use plain, common trade names exactly as a map would list them ("Roofers", "Plumbers", "Med Spas",
"Carpenters", "Pool Builders"). No adjectives like Custom, Luxury, High-End or Architectural.
Good cities: growing mid-sized cities in the US, Canada, UK, Ireland, Australia, New Zealand
or Western Europe. Vary country and region; do not default to the largest cities.

Already searched (do NOT repeat these niche + city combinations):
{chr(10).join('- ' + r for r in recent_runs) or '- none yet'}

Recently suggested (suggest something clearly different):
{chr(10).join('- ' + r for r in recent_suggestions) or '- none yet'}

Return JSON: {{"location": "City, Region, Country", "niches": ["Niche One", "Niche Two", "Niche Three"]}}"""
    for _ in range(2):
        try:
            data = llm.generate_json(prompt, temperature=1.0)
        except Exception as e:
            logger.warning(f"Gemini suggestion failed: {e}")
            return None
        location = (data.get("location") or "").strip() if isinstance(data, dict) else ""
        proposed = [n for n in data.get("niches", []) if isinstance(n, str) and is_searchable(n)]
        niches = _fresh_niches(proposed, location, executed) if location else []
        if location and len(niches) >= 2 and not _is_recent(location, niches):
            return {"location": location, "niches": niches, "source": "gemini"}
    return None


def _from_catalog(executed: set) -> dict:
    """City with unsearched niches, chosen at random among the best, skipping recent suggestions."""
    options = []
    for location in CATALOG_LOCATIONS:
        fresh = _fresh_niches(CATALOG_NICHES, location, executed)
        if len(fresh) >= 2:
            options.append((location, fresh))
    if not options:  # everything searched: allow repeats rather than return nothing
        options = [(loc, CATALOG_NICHES[:MAX_NICHES]) for loc in CATALOG_LOCATIONS]

    random.shuffle(options)
    options.sort(key=lambda o: len(o[1]), reverse=True)
    top = options[: max(5, len(options) // 3)]
    random.shuffle(top)
    for location, fresh in top + options:
        niches = random.sample(fresh, min(len(fresh), random.randint(MIN_NICHES, MAX_NICHES)))
        if not _is_recent(location, niches):
            return {"location": location, "niches": niches, "source": "catalog"}
    location, fresh = top[0]
    return {"location": location, "niches": fresh[:MAX_NICHES], "source": "catalog"}


def suggest_bundle() -> dict:
    executed, recent_runs = executed_targets()
    result = (_from_gemini(executed, recent_runs) if llm.available() else None) or _from_catalog(executed)
    _remember(result["location"], result["niches"])
    result["query"] = ", ".join(result["niches"])  # old single-field clients
    return result
