"""
Daily Auto-Pilot Campaign Target Catalog & Rotation Engine.
Curated list of high-value local service niches and booming mid-sized cities
across the US and globally.
"""
from db import get_conn

HOME_SERVICE_NICHES = [
    "HVAC Contractors",
    "Plumbers",
    "Electricians",
    "Roofers",
    "Landscaping Services",
    "Cleaning Companies",
]

TARGET_CITIES = [
    # North Carolina
    ("Asheville", "North Carolina, USA"),
    ("Wilmington", "North Carolina, USA"),
    ("Greenville", "North Carolina, USA"),
    ("Hickory", "North Carolina, USA"),
    # Tennessee
    ("Chattanooga", "Tennessee, USA"),
    ("Knoxville", "Tennessee, USA"),
    ("Clarksville", "Tennessee, USA"),
    # Texas (smaller cities)
    ("Waco", "Texas, USA"),
    ("Tyler", "Texas, USA"),
    ("Abilene", "Texas, USA"),
    ("College Station", "Texas, USA"),
    # Florida (outside Miami/Orlando)
    ("Gainesville", "Florida, USA"),
    ("Ocala", "Florida, USA"),
    ("Lakeland", "Florida, USA"),
    ("Pensacola", "Florida, USA"),
    # Ohio
    ("Dayton", "Ohio, USA"),
    ("Toledo", "Ohio, USA"),
    ("Akron", "Ohio, USA"),
    ("Canton", "Ohio, USA"),
    # Pennsylvania
    ("Lancaster", "Pennsylvania, USA"),
    ("Erie", "Pennsylvania, USA"),
    ("Scranton", "Pennsylvania, USA"),
    # Michigan
    ("Grand Rapids", "Michigan, USA"),
    ("Kalamazoo", "Michigan, USA"),
    ("Lansing", "Michigan, USA"),
    # Global Targets (multilingual & high purchasing power)
    ("Manchester", "United Kingdom"),
    ("Bristol", "United Kingdom"),
    ("Sydney", "Australia"),
    ("Melbourne", "Australia"),
    ("Vancouver", "Canada"),
    ("Calgary", "Canada"),
    ("Dublin", "Ireland"),
    ("Madrid", "Spain"),
    ("Berlin", "Germany"),
    ("Paris", "France"),
    ("Zurich", "Switzerland"),
]


def get_all_target_combinations() -> list[dict]:
    """Return all (niche, city) combinations in sequence."""
    combos = []
    for niche in HOME_SERVICE_NICHES:
        for city_name, state_country in TARGET_CITIES:
            combos.append({
                "query": niche,
                "location": f"{city_name}, {state_country}",
                "display_name": f"{niche} in {city_name}, {state_country}",
            })
    return combos


def get_next_campaign_target() -> dict:
    """
    Select the next target combination that hasn't been searched yet.
    If all have been searched, cycles back to the beginning.
    """
    with get_conn() as conn:
        rows = conn.execute("SELECT query, location FROM search_runs").fetchall()
        executed = {(r["query"].lower().strip(), r["location"].lower().strip()) for r in rows}

    combos = get_all_target_combinations()
    for target in combos:
        key = (target["query"].lower().strip(), target["location"].lower().strip())
        if key not in executed:
            return target

    # Fallback if all completed: return first target
    return combos[0]
