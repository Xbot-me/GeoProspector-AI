"""
Node: generate_outreach_kit

Generates three outreach artifacts for a target business using Gemini:
1. Analysis summary — Plain-language brief of website weaknesses and single strongest pitch angle.
2. Lovable mockup prompt — Ready-to-paste prompt for an AI site builder (Lovable.dev / v0) describing a 1-page static demo mockup for this business.
3. Email draft — Short (~100-130 words), first-person human voice with a literal [MOCKUP_LINK] placeholder. No enforced signature or domain-locked links.
"""
from google import genai

from config import GEMINI_API_KEY, GEMINI_MODEL
from state import BusinessState

_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None


def generate_outreach_kit(state: BusinessState) -> dict:
    if _client is None:
        raise RuntimeError("GEMINI_API_KEY is not set. Add it to your local .env file.")

    quality = state.get("website_quality", "none")
    notes = state.get("website_notes", "")
    owner = state.get("owner_name")
    rating = state.get("rating")
    review_count = state.get("review_count")

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

Business Name: {state.get('name')}
Category: {state.get('category') or 'Local Business'}
Location: {state.get('address')}
Website URL: {state.get('website') or 'None'}
Website Quality: {quality}
Website Analysis Notes: {notes or 'No website or broken site.'}

Personalization Context:
{personalization_str}

REQUIREMENTS FOR THE 3 ARTIFACTS:

1. ANALYSIS SUMMARY:
   Write a 2-3 sentence plain-language brief explaining specifically why their current web presence (or lack thereof) is costing them revenue and customer trust, and state the single strongest pitch angle to approach them with.

2. LOVABLE MOCKUP PROMPT:
   Write a clear, detailed, ready-to-paste prompt for an AI site builder (such as Lovable.dev or v0.dev) to generate a high-converting 1-page modern landing page demo for "{state.get('name')}".
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
Detect the local language from Location ({state.get('address')}) and write the Subject Line and Email Draft in that local language (e.g. English, Spanish, German, French). The Analysis and Mockup Prompt should remain in English.

Output in EXACTLY this format:

LANGUAGE: <Language name, e.g. English, Spanish, German>

ANALYSIS:
<Analysis summary>

MOCKUP_PROMPT:
<Lovable mockup prompt>

SUBJECT:
<Email subject line>

BODY:
<Email draft body with [MOCKUP_LINK]>"""

    resp = _client.models.generate_content(model=GEMINI_MODEL, contents=prompt)
    text = (resp.text or "").strip()

    language = "English"
    analysis = f"Business website state is '{quality}'. Potential opportunity for modern site build."
    mockup_prompt = f"Build a modern, clean 1-page website demo for {state.get('name')}, a {state.get('category') or 'local business'} located in {state.get('address')}."
    subject = f"Quick concept for {state.get('name')}"
    body = f"Hi,\n\nI noticed {state.get('name')} and built a quick mockup of a modern site layout for you: [MOCKUP_LINK]\n\nWould you be open to taking a 60-second look?\n\nBest,"

    if "LANGUAGE:" in text:
        try:
            parts = text.split("ANALYSIS:", 1)
            lang_line = parts[0].replace("LANGUAGE:", "").strip()
            if lang_line:
                language = lang_line

            rest = parts[1]
            mockup_split = rest.split("MOCKUP_PROMPT:", 1)
            analysis = mockup_split[0].strip()

            subj_split = mockup_split[1].split("SUBJECT:", 1)
            mockup_prompt = subj_split[0].strip()

            body_split = subj_split[1].split("BODY:", 1)
            subject = body_split[0].strip()
            body = body_split[1].strip()
        except (IndexError, ValueError):
            pass

    return {
        "analysis": analysis,
        "mockup_prompt": mockup_prompt,
        "pitch_subject": subject,
        "pitch_body": body,
        "email_language": language,
    }
