"""
Client-side safety net that stops the agent from making more Places API
calls than you've budgeted for the current calendar month.

This is a LOCAL counter (the places_quota table in Postgres) -- it has no
connection to Google's own billing/quota system. It exists to catch bugs
(e.g. an accidental loop) before they cost you money, not to replace the
budget alerts you should also set up in Google Cloud Console:
https://console.cloud.google.com/billing/budgets
"""
import json
import os
from datetime import datetime, timezone

from config import MAX_PLACES_CALLS_PER_MONTH
from db import get_places_calls, increment_places_calls

# Legacy counter file. Only read to seed a month that has no DB row yet, so
# calls already counted this month before the move to Postgres still count.
STATE_PATH = os.path.join(os.path.dirname(__file__), "quota_state.json")


def _current_month_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _legacy_count(month: str) -> int:
    try:
        with open(STATE_PATH, "r") as f:
            return int(json.load(f).get(month, 0))
    except (OSError, ValueError, AttributeError):
        return 0


def calls_made_this_month() -> int:
    return get_places_calls(_current_month_key())


class QuotaExceededError(RuntimeError):
    pass


def check_and_increment(n: int = 1) -> None:
    """
    Call this immediately BEFORE making n Places API request(s).
    Raises QuotaExceededError if this would exceed the configured monthly cap.
    """
    month = _current_month_key()
    total = increment_places_calls(month, n, MAX_PLACES_CALLS_PER_MONTH, seed=_legacy_count(month))
    if total is None:
        used = get_places_calls(month)
        raise QuotaExceededError(
            f"Refusing to make {n} more Places API call(s): "
            f"{used} already used this month, cap is {MAX_PLACES_CALLS_PER_MONTH}. "
            f"Raise MAX_PLACES_CALLS_PER_MONTH in .env if this is intentional."
        )
