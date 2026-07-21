"""
Node: score_lead

Computes a composite 0-100 lead score from enrichment data gathered by
earlier nodes. The score determines whether the business is worth spending
LLM tokens on (analysis + pitch generation) and helps the operator
prioritize the human-approval queue.

Scoring rubric:
  Website status:
    none         +30   (strongest signal of need)
    social_only  +25   (has online awareness but no real site)
    dead         +20   (had a site, let it lapse)
    outdated     +20   (site exists but is stale)

  Google reviews:
    >= 500       +20   (established, can afford services)
    >= 100       +15
    >= 20        +10
    < 20          +5   (very small / new)

  Google rating:
    >= 4.0       +10   (quality business)

  Contact-ability:
    Email found  +15   (we can actually reach them)
    Phone listed  +5

  Social presence:
    Has FB or IG +10   (online-aware, likely receptive)

  Category bonus:
    restaurant, hotel, salon, clinic, spa, gym, dentist  +10
"""
import json

from state import BusinessState

_HIGH_VALUE_CATEGORIES = {
    "restaurant", "hotel", "salon", "clinic", "spa", "gym", "dentist",
    "cafe", "bar", "bakery", "beauty_salon", "hair_care", "lodging",
    "meal_delivery", "meal_takeaway", "night_club", "shopping_mall",
    "store", "tourist_attraction",
}


def score_lead(state: BusinessState) -> dict:
    score = 0
    breakdown: list[str] = []

    # --- Website status ---
    quality = state.get("website_quality", "none")
    if quality == "none":
        score += 30
        breakdown.append("No website: +30")
    elif quality == "social_only":
        score += 25
        breakdown.append("Social-only website: +25")
    elif quality == "dead":
        score += 20
        breakdown.append("Dead website: +20")
    elif quality == "outdated":
        score += 20
        breakdown.append("Outdated website: +20")
    # "good" adds 0

    # --- Google reviews ---
    review_count = state.get("review_count") or 0
    if review_count >= 500:
        score += 20
        breakdown.append(f"{review_count} reviews: +20")
    elif review_count >= 100:
        score += 15
        breakdown.append(f"{review_count} reviews: +15")
    elif review_count >= 20:
        score += 10
        breakdown.append(f"{review_count} reviews: +10")
    else:
        score += 5
        breakdown.append(f"{review_count} reviews: +5")

    # --- Google rating ---
    rating = state.get("rating") or 0
    if rating >= 4.0:
        score += 10
        breakdown.append(f"Rating {rating:.1f}: +10")

    # --- Contact-ability ---
    if state.get("email"):
        score += 15
        breakdown.append("Email found: +15")

    if state.get("phone"):
        score += 5
        breakdown.append("Phone listed: +5")

    # --- Social presence ---
    if state.get("facebook_url") or state.get("instagram_url"):
        score += 10
        breakdown.append("Has social media: +10")

    # --- Category bonus ---
    category = (state.get("category") or "").lower().replace(" ", "_")
    if category in _HIGH_VALUE_CATEGORIES:
        score += 10
        breakdown.append(f"High-value category ({category}): +10")

    # Cap at 100
    score = min(score, 100)

    return {
        "lead_score": score,
        "score_breakdown": "\n".join(breakdown),
    }
