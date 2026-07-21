"""
Node: generate_pitch

Turns the analysis into a short, personalized outreach email using Gemini.
Two tracks:
  - "no website" / "dead" / "social_only" → pitch building a website
  - "outdated" → pitch modernizing their existing website

Critical rules baked into the prompt:
  - Never claim previous clients or fake experience
  - Never fabricate portfolio links
  - Use owner name if discovered
  - Reference their Google reviews as THEIR social proof
"""
from google import genai

from config import GEMINI_API_KEY, GEMINI_MODEL, SENDER_NAME
from state import BusinessState

_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None


def _get_pitch_angle(state: BusinessState) -> str:
    quality = state.get("website_quality", "none")
    if quality == "outdated":
        return "outdated"
    return "no_website"


def generate_pitch(state: BusinessState) -> dict:
    if _client is None:
        raise RuntimeError("GEMINI_API_KEY is not set. Add it to your local .env file.")

    angle = _get_pitch_angle(state)
    owner = state.get("owner_name")
    sign_off = SENDER_NAME or "[Your Name]"

    # Build personalization context
    personalization = []
    rating = state.get("rating")
    review_count = state.get("review_count")
    if rating and review_count and review_count >= 10:
        personalization.append(
            f"They have {review_count} Google reviews with a {rating}/5 rating "
            f"— reference this as THEIR achievement, not yours."
        )
    if state.get("facebook_url"):
        personalization.append(
            "They have a Facebook page — acknowledge they're doing some online marketing."
        )
    if owner:
        personalization.append(
            f"The owner/manager's name appears to be {owner} — address them by name."
        )

    personalization_block = "\n".join(f"- {p}" for p in personalization) if personalization else "No extra personalization data available."

    if angle == "outdated":
        situation = (
            "This business HAS a website but it's outdated. "
            f"Issues found: {state.get('website_notes', 'various red flags')}. "
            "Pitch modernizing/rebuilding their site, NOT creating one from scratch."
        )
    else:
        situation = (
            "This business has NO website (or only a social media page). "
            "Pitch creating a professional website for them."
        )

    prompt = f"""Write a short cold outreach email pitching web development
services to this business.

Business name: {state.get('name')}
Category: {state.get('category') or 'unknown'}
Location: {state.get('address')}

Situation: {situation}

Analysis notes to draw from:
{state.get('analysis')}

Personalization data:
{personalization_block}

CRITICAL RULES — you MUST follow these:
1. Do NOT claim to have helped other businesses. Do NOT say "I have helped
   local businesses like yours" or anything similar.
2. Do NOT fabricate experience, portfolio links, or client names.
3. Do NOT use "I hope this email finds you well" or similar clichés.
4. Write from the perspective of someone offering to help, NOT someone
   with a proven track record. Be honest and straightforward.
5. Under 130 words.
6. Reference one specific, plausible detail about the business from the
   analysis notes — not generic flattery.
7. One clear call to action: a short reply or a 10-minute call. Not a
   hard sell.
8. No em dashes, no exclamation-point enthusiasm.
9. Sign off as: {sign_off}

Output in exactly this format, nothing else:
SUBJECT: <subject line>
BODY:
<email body>"""

    resp = _client.models.generate_content(model=GEMINI_MODEL, contents=prompt)
    text = (resp.text or "").strip()

    subject, body = "Quick question about your online presence", text
    if "SUBJECT:" in text and "BODY:" in text:
        subject_part, body_part = text.split("BODY:", 1)
        subject = subject_part.replace("SUBJECT:", "").strip()
        body = body_part.strip()

    return {"pitch_subject": subject, "pitch_body": body}
