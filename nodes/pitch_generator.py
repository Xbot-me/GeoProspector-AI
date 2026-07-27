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

from config import GEMINI_API_KEY, GEMINI_MODEL, SENDER_NAME, SENDER_SIGNATURE
from state import BusinessState

_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None


def _get_pitch_angle(state: BusinessState) -> str:
    quality = state.get("website_quality", "none")
    if quality == "outdated":
        return "outdated"
    return "no_website"


def _append_signature(body: str) -> str:
    """Ensure the email body always ends with the exact sender signature."""
    if "mustafizur.info" in body:
        return body
    
    for placeholder in ("[Your Name]", "[Your name]", "[your name]", "[YOUR NAME]", "Mustafizur Rahman"):
        if placeholder in body:
            return body.replace(placeholder, SENDER_SIGNATURE).strip()

    return f"{body.strip()}\n\n{SENDER_SIGNATURE}"


def generate_pitch(state: BusinessState) -> dict:
    if _client is None:
        raise RuntimeError("GEMINI_API_KEY is not set. Add it to your local .env file.")

    angle = _get_pitch_angle(state)
    owner = state.get("owner_name")

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
            "This business HAS a website but it has flaws or looks outdated. "
            f"Specific issues found: {state.get('website_notes', 'various technical/UX red flags')}. "
            "Pitch modernizing or fixing their site, NOT creating one from scratch."
        )
    else:
        situation = (
            "This business has NO website (or relies solely on social media like Facebook/Instagram). "
            "Pitch building a clean, modern, dedicated website for them so customers can easily find them on Google."
        )

    prompt = f"""You are an elite, human cold-email copywriter and native linguist. Write a short, highly compelling cold outreach email pitching web development services to this business.

Business name: {state.get('name')}
Category: {state.get('category') or 'local service business'}
Location: {state.get('address')}

Situation: {situation}

Analysis notes to draw from:
{state.get('analysis')}

Personalization data:
{personalization_block}

COPYWRITING FRAMEWORK — "Value-First Mockup Offer":
1. Compliment Hook: Start by acknowledging their hard-earned reputation (e.g., mention their Google rating/reviews or local standing as THEIR achievement).
2. Friction Point: Explain specifically WHY their website state (e.g., HTTP error, outdated design, slow mobile load, or lack of a real website) is causing potential local customers or smartphone users to bounce or call competitors.
3. Zero-Risk Offer: Offer to put together a free visual 3-page mockup or homepage design concept for them at ZERO cost or commitment before they ever pay a dime.
4. Call to Action (CTA): End with a simple, low-friction question asking if they'd be open to seeing a quick preview or 2-minute video mockup.

CRITICAL RULES — you MUST follow these:
1. LANGUAGE DETECTION & TRANSLATION: Analyze the Location ({state.get('address')}) and Business name. Determine the primary local language spoken by business owners in this city/country (e.g., Spanish for Spain/Mexico, German for Germany/Austria, French for France/Quebec, English for US/UK/Australia). You MUST write the ENTIRE subject line and email body natively in that local language!
2. Do NOT claim to have helped other businesses or fabricate client names/portfolio links. Be honest and straightforward.
3. Do NOT use robotic clichés like "I hope this email finds you well" or "In today's fast-paced digital landscape".
4. Keep the email copy under 135 words. Short, punchy, and conversational.
5. No em dashes, no exclamation-point enthusiasm.
6. Do NOT include a sign-off or signature at the end of the email (we will append our signature programmatically). Just end with your call to action question.

Output in EXACTLY this format, nothing else:
LANGUAGE: <Primary local language name, e.g. English, Spanish, German>
SUBJECT: <Subject line in local language>
BODY:
<Email body in local language>"""

    resp = _client.models.generate_content(model=GEMINI_MODEL, contents=prompt)
    text = (resp.text or "").strip()

    language = "English"
    subject = "Quick question about your online presence"
    body = text

    if "LANGUAGE:" in text and "SUBJECT:" in text and "BODY:" in text:
        try:
            lang_part, rest = text.split("SUBJECT:", 1)
            language = lang_part.replace("LANGUAGE:", "").strip()
            subject_part, body_part = rest.split("BODY:", 1)
            subject = subject_part.strip()
            body = body_part.strip()
        except ValueError:
            pass
    elif "SUBJECT:" in text and "BODY:" in text:
        subject_part, body_part = text.split("BODY:", 1)
        subject = subject_part.replace("SUBJECT:", "").strip()
        body = body_part.strip()

    body = _append_signature(body)
    return {"pitch_subject": subject, "pitch_body": body, "email_language": language}
