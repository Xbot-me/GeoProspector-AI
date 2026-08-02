"""
Location Rotation Catalog for Business Discovery.
Curated list of high-value mid-sized cities across North America and globally.
"""
from db import get_conn

TARGET_CITIES = [
    # Tier 1: Premier Opportunities (High Revenue, Low Tech, Low Agency Competition)
    ("Bend", "Oregon, USA"),
    ("Greenville", "South Carolina, USA"),
    ("Kelowna", "British Columbia, Canada"),
    ("Tyler", "Texas, USA"),
    ("Aberdeen", "Scotland, United Kingdom"),
    ("Fargo", "North Dakota, USA"),
    ("Boise", "Idaho, USA"),
    ("Lancaster", "Pennsylvania, USA"),
    ("Linz", "Austria"),
    ("Pensacola", "Florida, USA"),
    ("Sudbury", "Ontario, Canada"),
    ("Tampere", "Finland"),
    ("Greenville", "North Carolina, USA"),
    ("Santander", "Cantabria, Spain"),
    ("Appleton", "Wisconsin, USA"),

    # Tier 2: High-Growth Regional Corridors
    ("Asheville", "North Carolina, USA"),
    ("Wilmington", "North Carolina, USA"),
    ("Chattanooga", "Tennessee, USA"),
    ("Knoxville", "Tennessee, USA"),
    ("Guelph", "Ontario, Canada"),
    ("Waco", "Texas, USA"),
    ("Stavanger", "Norway"),
    ("Erie", "Pennsylvania, USA"),
    ("Brest", "France"),
    ("Dayton", "Ohio, USA"),
    ("Odense", "Denmark"),
    ("Grand Rapids", "Michigan, USA"),
    ("Augsburg", "Germany"),
    ("Lafayette", "Louisiana, USA"),
    ("Swansea", "Wales, United Kingdom"),
    ("Kalamazoo", "Michigan, USA"),
    ("Gainesville", "Florida, USA"),
    ("Turku", "Finland"),
    ("Monroe", "Louisiana, USA"),
    ("Coimbra", "Portugal"),

    # Tier 3: Global & Niche Trade Hubs
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
    """
    Return city targets with a broad business search query ("local businesses").
    """
    combos = []
    for city_name, state_country in TARGET_CITIES:
        combos.append({
            "query": "local businesses",
            "location": f"{city_name}, {state_country}",
            "display_name": f"Local Businesses in {city_name}, {state_country}",
        })
    return combos


def get_next_campaign_target() -> dict:
    """
    Select the next location target that hasn't been searched yet.
    """
    try:
        with get_conn() as conn:
            rows = conn.execute("SELECT query, location FROM search_runs").fetchall()
            executed = {(r["query"].lower().strip(), r["location"].lower().strip()) for r in rows}
    except Exception:
        executed = set()

    combos = get_all_target_combinations()
    for target in combos:
        key = (target["query"].lower().strip(), target["location"].lower().strip())
        if key not in executed:
            return target

    # Fallback if all cities have been searched: return a random target
    import random
    shuffled = list(combos)
    random.shuffle(shuffled)
    for target in shuffled:
        key = (target["query"].lower().strip(), target["location"].lower().strip())
        if key not in executed:
            return target

    return combos[0]
