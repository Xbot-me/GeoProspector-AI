"""
Node: analyze_business

Uses Gemini (free-tier Flash-Lite model) to turn raw Places data + enrichment
findings into a short set of talking points. Now aware of website quality
level (not just "has/doesn't have") and enrichment data (reviews, socials).
"""
from google import genai

from config import GEMINI_API_KEY, GEMINI_MODEL
from state import BusinessState

_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None


def _describe_web_status(state: BusinessState) -> str:
    quality = state.get("website_quality", "none")
    notes = state.get("website_notes", "")

    if quality == "none":
        return "No website at all"
    if quality == "social_only":
        return f"Only has a social media page as their 'website' ({notes})"
    if quality == "dead":
        return f"Website exists but is down/broken ({notes})"
    if quality == "outdated":
        return f"Website exists but is outdated ({notes})"
    return f"Has a working website ({notes})"


def analyze_business(state: BusinessState) -> dict:
    if _client is None:
        raise RuntimeError("GEMINI_API_KEY is not set. Add it to your local .env file.")

    web_status = _describe_web_status(state)
    rating = state.get("rating")
    review_count = state.get("review_count")
    review_info = ""
    if rating and review_count:
        review_info = f"Google rating: {rating}/5 with {review_count} reviews"

    social_info = ""
    socials = []
    if state.get("facebook_url"):
        socials.append(f"Facebook: {state['facebook_url']}")
    if state.get("instagram_url"):
        socials.append(f"Instagram: {state['instagram_url']}")
    if socials:
        social_info = "Social presence: " + ", ".join(socials)

    owner_info = ""
    if state.get("owner_name"):
        owner_info = f"Owner/manager: {state['owner_name']}"

    prompt = f"""A local business was found with a web presence issue:

Name: {state.get('name')}
Category: {state.get('category') or 'unknown'}
Address: {state.get('address')}
Phone listed: {state.get('phone') or 'none'}
Web status: {web_status}
{review_info}
{social_info}
{owner_info}

In 3-4 short bullet points, note:
1. What this specific business is likely losing due to their web presence
   issue (be specific to their category and location, not generic)
2. One concrete opportunity they're missing (e.g. online ordering for a
   restaurant, appointment booking for a salon)
3. If they have good Google reviews, mention that as an asset they could
   leverage better with a proper website
Prioritize opportunities where a solo senior developer can realistically close $2,000-$20,000 projects or create recurring SaaS revenue without needing a large sales team.
Be concrete and avoid generic filler. Output only the bullets, no preamble."""

    resp = _client.models.generate_content(model=GEMINI_MODEL, contents=prompt)
    analysis = (resp.text or "").strip()

    return {"analysis": analysis}
