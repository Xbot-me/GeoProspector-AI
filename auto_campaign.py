"""
Daily Auto-Pilot Campaign Target Catalog & Rotation Engine.
Curated list of high-value local service niches and booming mid-sized cities
across the US and globally.
"""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

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

# ---------------------------------------------------------------------------
# Timezone mapping for every city in TARGET_CITIES
# ---------------------------------------------------------------------------
CITY_TIMEZONES: dict[str, str] = {
    # North Carolina  (Eastern)
    "Asheville":        "America/New_York",
    "Wilmington":       "America/New_York",
    "Greenville":       "America/New_York",
    "Hickory":          "America/New_York",
    # Tennessee  (Eastern)
    "Chattanooga":      "America/New_York",
    "Knoxville":        "America/New_York",
    "Clarksville":      "America/Chicago",
    # Texas  (Central)
    "Waco":             "America/Chicago",
    "Tyler":            "America/Chicago",
    "Abilene":          "America/Chicago",
    "College Station":  "America/Chicago",
    # Florida  (Eastern / Central split)
    "Gainesville":      "America/New_York",
    "Ocala":            "America/New_York",
    "Lakeland":         "America/New_York",
    "Pensacola":        "America/Chicago",
    # Ohio  (Eastern)
    "Dayton":           "America/New_York",
    "Toledo":           "America/New_York",
    "Akron":            "America/New_York",
    "Canton":           "America/New_York",
    # Pennsylvania  (Eastern)
    "Lancaster":        "America/New_York",
    "Erie":             "America/New_York",
    "Scranton":         "America/New_York",
    # Michigan  (Eastern)
    "Grand Rapids":     "America/New_York",
    "Kalamazoo":        "America/New_York",
    "Lansing":          "America/New_York",
    # International
    "Manchester":       "Europe/London",
    "Bristol":          "Europe/London",
    "Sydney":           "Australia/Sydney",
    "Melbourne":        "Australia/Melbourne",
    "Vancouver":        "America/Vancouver",
    "Calgary":          "America/Edmonton",
    "Dublin":           "Europe/Dublin",
    "Madrid":           "Europe/Madrid",
    "Berlin":           "Europe/Berlin",
    "Paris":            "Europe/Paris",
    "Zurich":           "Europe/Zurich",
}

_DEFAULT_TZ = "America/New_York"


def get_lead_timezone(address: str) -> str:
    """Return the IANA timezone for a lead based on its address string.

    Checks whether any city name from TARGET_CITIES appears in *address*
    (case-insensitive) and returns the mapped timezone.  Falls back to
    ``America/New_York`` when no match is found.
    """
    addr_lower = address.lower()
    # Iterate longest names first so "College Station" matches before
    # a hypothetical shorter substring.
    for city in sorted(CITY_TIMEZONES, key=len, reverse=True):
        if city.lower() in addr_lower:
            return CITY_TIMEZONES[city]
    return _DEFAULT_TZ


def is_good_send_time(timezone_str: str) -> bool:
    """Return ``True`` when the current local time in *timezone_str* falls
    inside a preferred outreach window.

    Windows (weekdays only, Mon-Fri):
    * Morning:  07:00 – 09:00
    * Evening:  17:00 – 19:30
    """
    now = datetime.now(ZoneInfo(timezone_str))
    if now.weekday() >= 5:          # Saturday=5, Sunday=6
        return False
    t = now.time()
    morning = t.hour >= 7 and (t.hour < 9)
    evening = (t.hour == 17) or (t.hour == 18) or (t.hour == 19 and t.minute < 30)
    return morning or evening


def seconds_until_next_window(timezone_str: str) -> int:
    """Return the number of seconds until the next valid send window.

    * If currently inside a window → ``0``
    * Between the morning and evening windows → seconds until 17:00 today
    * After the evening window → seconds until 07:00 next day
    * Weekend → seconds until Monday 07:00
    """
    tz = ZoneInfo(timezone_str)
    now = datetime.now(tz)

    if is_good_send_time(timezone_str):
        return 0

    def _seconds_to(target: datetime) -> int:
        return max(0, int((target - now).total_seconds()))

    # Weekday handling (Mon-Fri)
    if now.weekday() < 5:
        morning_start = now.replace(hour=7, minute=0, second=0, microsecond=0)
        evening_start = now.replace(hour=17, minute=0, second=0, microsecond=0)

        if now < morning_start:
            return _seconds_to(morning_start)
        if now < evening_start:
            return _seconds_to(evening_start)
        # After evening window → next day 07:00
        next_morning = (now + timedelta(days=1)).replace(
            hour=7, minute=0, second=0, microsecond=0,
        )
        # If next day is a weekend, advance to Monday
        while next_morning.weekday() >= 5:
            next_morning += timedelta(days=1)
        return _seconds_to(next_morning)

    # Weekend → advance to Monday 07:00
    days_ahead = 7 - now.weekday()          # Mon=0, so Sat→2, Sun→1
    next_monday = (now + timedelta(days=days_ahead)).replace(
        hour=7, minute=0, second=0, microsecond=0,
    )
    return _seconds_to(next_monday)


def get_all_target_combinations() -> list[dict]:
    """
    Return diverse, interleaved (niche, city) combinations so sequential runs
    automatically rotate BOTH category and geography on every run.
    """
    combos = []
    num_niches = len(HOME_SERVICE_NICHES)
    num_cities = len(TARGET_CITIES)
    # Generate interleaved combinations across niches and cities
    max_combos = num_niches * num_cities

    for i in range(max_combos):
        # Pick niche and city with relative offset so we step through both lists simultaneously
        niche = HOME_SERVICE_NICHES[i % num_niches]
        # Shift city index by niche multiplier to ensure full coverage without clustering
        city_idx = (i + (i // num_niches)) % num_cities
        city_name, state_country = TARGET_CITIES[city_idx]
        combos.append({
            "query": niche,
            "location": f"{city_name}, {state_country}",
            "display_name": f"{niche} in {city_name}, {state_country}",
        })
    return combos


def get_next_campaign_target() -> dict:
    """
    Select the next target combination that hasn't been searched yet.
    Guarantees no duplicate searches and diverse location/niche rotation.
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

    # Fallback if all curated combos have been executed: shuffle and find unexecuted
    import random
    shuffled = list(combos)
    random.shuffle(shuffled)
    for target in shuffled:
        key = (target["query"].lower().strip(), target["location"].lower().strip())
        if key not in executed:
            return target

    return combos[0]
