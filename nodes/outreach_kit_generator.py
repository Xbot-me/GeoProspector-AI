"""
Node: generate_outreach_kit

Generates three outreach artifacts for a target business using Gemini:
1. Analysis summary — Plain-language brief of website weaknesses and single strongest pitch angle.
2. Lovable mockup prompt — Ready-to-paste prompt for an AI site builder (Lovable.dev / v0) describing a 1-page static demo mockup for this business.
3. Email draft — Short (~100-130 words), first-person human voice with a literal [MOCKUP_LINK] placeholder. No enforced signature or domain-locked links.
"""
import logging
import os
from google import genai

from config import GEMINI_API_KEY, GEMINI_MODEL
from state import BusinessState

logger = logging.getLogger(__name__)


def _get_client():
    key = GEMINI_API_KEY or os.getenv("GEMINI_API_KEY", "")
    if not key:
        return None
    try:
        return genai.Client(api_key=key)
    except Exception as e:
        logger.error(f"Failed to initialize Gemini client: {e}")
        return None


def generate_outreach_kit(state: BusinessState) -> dict:
    name = state.get("name") or "Local Business"
    category = state.get("category") or "Local Business"
    address = state.get("address") or "Location"
    quality = state.get("website_quality", "none")
    notes = state.get("website_notes", "")
    owner = state.get("owner_name")
    rating = state.get("rating")
    review_count = state.get("review_count")

    # Smart fallback kit in case Gemini API is unavailable, unconfigured, or errors out
    fallback_analysis = f"{name} ({category}) in {address} has website condition '{quality}'. Strongest pitch angle: Offer a modern high-converting 1-page demo site to capture lost local search traffic."
    fallback_prompt = f"Create a clean, responsive, high-converting 1-page modern landing page demo for '{name}', a {category} in {address}. Include Hero section with call-to-action, Services grid, Customer Reviews, and direct Contact/Booking form."
    fallback_subject = f"Quick website concept for {name}"
    fallback_body = f"Hi,\n\nI noticed {name} in {address} and put together a quick, custom 1-page interactive website demo for your business:\n\n[MOCKUP_LINK]\n\nWould you be open to taking a 60-second look?\n\nBest,\nMustafizur Rahman\nhello@mustafizur.info"

    client = _get_client()
    if client is None:
        logger.warning(f"GEMINI_API_KEY not configured — returning template fallback kit for {name}")
        return {
            "analysis": fallback_analysis,
            "mockup_prompt": fallback_prompt,
            "pitch_subject": fallback_subject,
            "pitch_body": fallback_body,
            "email_language": "English",
        }

    personalization = []
    if rating and review_count and review_count >= 5:
        personalization.append(f"They have {review_count} Google reviews with a {rating}/5 rating.")
    if owner:
        personalization.append(f"Owner/Manager name: {owner}")
    if state.get("facebook_url"):
        personalization.append("Has active Facebook page.")
    if state.get("instagram_url"):
        personalization.append("Has active Instagram page.")

    personalization_str = "\n".join(f"- {p}" for p in personalization) if personalization else "No extra social/review context."

    prompt = f"""You are an expert web development consultant and cold outreach specialist. Create a complete 3-part outreach kit for this business.

Business Name: {name}
Category: {category}
Location: {address}
Website URL: {state.get('website') or 'None'}
Website Quality: {quality}
Website Analysis Notes: {notes or 'No website or broken site.'}

Personalization Context:
{personalization_str}

REQUIREMENTS FOR THE 3 ARTIFACTS:

1. ANALYSIS SUMMARY:
   Write a 2-3 sentence plain-language brief explaining specifically why their current web presence (or lack thereof) is costing them revenue and customer trust, and state the single strongest pitch angle to approach them with.

2. LOVABLE MOCKUP PROMPT:
   Write a clear, detailed, ready-to-paste prompt for an AI site builder (such as Lovable.dev or v0.dev) to generate a high-converting 1-page modern landing page demo for "{name}".
   Include:
   - Target industry and brand tone
   - Key section layout (Hero section, Services, Customer Social Proof/Reviews, Direct Call to Action / Booking Form)
   - Color palette recommendation
   - Explicit instruction: "Keep as a clean, responsive, fully static HTML/CSS/JS 1-page demo site ready for instant web preview deployment."

3. EMAIL DRAFT:
   Write a short, conversational, first-person cold outreach email (~100-130 words).
   - Tone: Friendly, direct, helpful web developer (human voice, no sales fluff).
   - Hook: Reference their local reputation/reviews or standing as THEIR achievement.
   - Core Message: Mention you built a custom 1-page interactive demo mockup site specifically for them.
   - Include a literal placeholder: [MOCKUP_LINK] where the link will be inserted.
   - CTA: Ask a simple low-friction question if they'd like to take a look or see a 60-second walkthrough.
   - No forced company signature, no letterhead HTML, no domain-locked URLs.

LANGUAGE RULE:
Detect the local language from Location ({address}) and write the Subject Line and Email Draft in that local language (e.g. English, Spanish, German, French). The Analysis and Mockup Prompt should remain in English.

Output in EXACTLY this format:

LANGUAGE: English

ANALYSIS:
<Analysis summary>

MOCKUP_PROMPT:
<Lovable mockup prompt>

SUBJECT:
<Email subject line>

BODY:
<Email draft body with [MOCKUP_LINK]>"""

    try:
        resp = client.models.generate_content(model=GEMINI_MODEL, contents=prompt)
        text = (resp.text or "").strip()
    except Exception as e:
        logger.error(f"Gemini API call failed for {name}: {e}")
        return {
            "analysis": fallback_analysis,
            "mockup_prompt": fallback_prompt,
            "pitch_subject": fallback_subject,
            "pitch_body": fallback_body,
            "email_language": "English",
        }

    language = "English"
    analysis = fallback_analysis
    mockup_prompt = fallback_prompt
    subject = fallback_subject
    body = fallback_body

    try:
        # Flexible section extraction
        clean_text = text.replace("**", "").replace("### ", "")
        
        if "ANALYSIS:" in clean_text and "MOCKUP_PROMPT:" in clean_text:
            analysis_part = clean_text.split("ANALYSIS:", 1)[1].split("MOCKUP_PROMPT:", 1)[0].strip()
            if analysis_part: analysis = analysis_part

        if "MOCKUP_PROMPT:" in clean_text and "SUBJECT:" in clean_text:
            mockup_part = clean_text.split("MOCKUP_PROMPT:", 1)[1].split("SUBJECT:", 1)[0].strip()
            if mockup_part: mockup_prompt = mockup_part

        if "SUBJECT:" in clean_text and "BODY:" in clean_text:
            subject_part = clean_text.split("SUBJECT:", 1)[1].split("BODY:", 1)[0].strip()
            if subject_part: subject = subject_part

        if "BODY:" in clean_text:
            body_part = clean_text.split("BODY:", 1)[1].strip()
            if body_part: body = body_part

        if "LANGUAGE:" in clean_text:
            lang_line = clean_text.split("LANGUAGE:", 1)[1].split("\n", 1)[0].strip()
            if lang_line: language = lang_line
    except Exception as parse_err:
        logger.warning(f"Error parsing Gemini response for {name}: {parse_err}")

    return {
        "analysis": analysis,
        "mockup_prompt": mockup_prompt,
        "pitch_subject": subject,
        "pitch_body": body,
        "email_language": language,
    }
