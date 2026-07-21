"""
Client-side safety net that stops the agent from making more Places API
calls than you've budgeted for the current calendar month.

This is a LOCAL counter (a JSON file next to this script) -- it has no
connection to Google's own billing/quota system. It exists to catch bugs
(e.g. an accidental loop) before they cost you money, not to replace the
budget alerts you should also set up in Google Cloud Console:
https://console.cloud.google.com/billing/budgets
"""
import json
import os
from datetime import datetime, timezone

from config import MAX_PLACES_CALLS_PER_MONTH

STATE_PATH = os.path.join(os.path.dirname(__file__), "quota_state.json")


def _current_month_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _load() -> dict:
    if not os.path.exists(STATE_PATH):
        return {}
    try:
        with open(STATE_PATH, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save(state: dict) -> None:
    with open(STATE_PATH, "w") as f:
        json.dump(state, f, indent=2)


def calls_made_this_month() -> int:
    state = _load()
    return state.get(_current_month_key(), 0)


class QuotaExceededError(RuntimeError):
    pass


def check_and_increment(n: int = 1) -> None:
    """
    Call this immediately BEFORE making n Places API request(s).
    Raises QuotaExceededError if this would exceed the configured monthly cap.
    """
    state = _load()
    month = _current_month_key()
    used = state.get(month, 0)
    if used + n > MAX_PLACES_CALLS_PER_MONTH:
        raise QuotaExceededError(
            f"Refusing to make {n} more Places API call(s): "
            f"{used} already used this month, cap is {MAX_PLACES_CALLS_PER_MONTH}. "
            f"Raise MAX_PLACES_CALLS_PER_MONTH in .env if this is intentional."
        )
    state[month] = used + n
    _save(state)
