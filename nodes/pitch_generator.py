"""
Node: generate_pitch

Turns the analysis into a short, personalized outreach email using Gemini.

What makes the drafts work (and not read like a template):
  - Every email is anchored on ONE concrete, verifiable finding about the
    business (see findings.describe_finding), never a generic "your site could be better".
  - The model is shown style examples from prompts/pitch_examples.txt, which
    you should replace with emails in your own voice.
  - It returns three subject lines and we keep the plainest one.
  - Output is cleaned (no em dashes, no exclamation marks) and length-capped.

Rules baked into the prompt:
  - Never claim previous clients or fake experience
  - Never fabricate portfolio links or facts about the business
  - Use owner name if discovered
  - Reference their Google reviews as THEIR social proof
  - Offer a free mockup only when OFFER_FREE_MOCKUP is on
"""
import re
from pathlib import Path

from google import genai

from config import (
    GEMINI_API_KEY,
    GEMINI_MODEL,
    OFFER_FREE_MOCKUP,
    OUTREACH_LANGUAGE,
    SENDER_NAME,
    SENDER_SIGNATURE,
    SENDER_WEBSITE,
)
from findings import describe_finding
from state import BusinessState

_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

EXAMPLES_PATH = Path(__file__).resolve().parent.parent / "prompts" / "pitch_examples.txt"
MAX_WORDS = 120


def _get_pitch_angle(state: BusinessState) -> str:
    quality = state.get("website_quality", "none")
    if quality == "outdated":
        return "outdated"
    return "no_website"


def load_examples(path: Path = EXAMPLES_PATH) -> str:
    """Style examples, comments stripped. Empty string if the file is missing."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    lines = [ln for ln in raw.splitlines() if not ln.lstrip().startswith("#")]
    return "\n".join(lines).strip()


def pick_subject(options: list[str], business_name: str = "") -> str:
    """Prefer a short, plain subject that mentions the business by name."""
    cleaned = [re.sub(r"^[\-\*\d\.\)\s]+", "", o).strip().strip('"') for o in options]
    cleaned = [o for o in cleaned if o]
    if not cleaned:
        return f"Question about {business_name}'s website" if business_name else "Quick question"
    name = business_name.lower()

    def key(o: str) -> tuple:
        words = len(o.split())
        mentions = 0 if name and name in o.lower() else 1
        too_long = 1 if words > 9 else 0
        shouty = 1 if o.isupper() or "!" in o else 0
        return (shouty, too_long, mentions, words)

    return min(cleaned, key=key)


def clean_body(body: str) -> str:
    """Remove the punctuation tics that make drafts read as machine-written."""
    body = body.replace("—", ",").replace("–", "-").replace("!", ".")
    body = re.sub(r",\s*,", ",", body)
    body = re.sub(r"[ \t]+\n", "\n", body)
    body = re.sub(r"\n{3,}", "\n\n", body)
    return body.strip()


def _append_signature(body: str) -> str:
    """Ensure the email body always ends with the configured sender signature."""
    if SENDER_WEBSITE in body:
        return body

    for placeholder in ("[Your Name]", "[Your name]", "[your name]", "[YOUR NAME]", SENDER_NAME):
        if placeholder and placeholder in body:
            return body.replace(placeholder, SENDER_SIGNATURE).strip()

    return f"{body.strip()}\n\n{SENDER_SIGNATURE}"


def parse_response(text: str) -> tuple[str, list[str], str]:
    """Split the model output into (language, subject options, body)."""
    language = "English"
    subjects: list[str] = []
    body = text.strip()

    m_lang = re.search(r"^LANGUAGE:\s*(.+)$", text, re.MULTILINE)
    if m_lang:
        language = m_lang.group(1).strip()

    m_subj = re.search(r"^SUBJECTS?:\s*(.*?)^BODY:\s*", text, re.MULTILINE | re.DOTALL)
    if m_subj:
        subjects = [ln.strip() for ln in m_subj.group(1).splitlines() if ln.strip()]
        body = text[m_subj.end():].strip()
    elif "BODY:" in text:
        body = text.split("BODY:", 1)[1].strip()

    # a model sometimes puts a single "SUBJECT: x" inline
    m_one = re.search(r"^SUBJECT:\s*(.+)$", text, re.MULTILINE)
    if m_one and not subjects:
        subjects = [m_one.group(1).strip()]
    return language, subjects, body


def build_prompt(state: BusinessState) -> str:
    angle = _get_pitch_angle(state)
    owner = state.get("owner_name")

    personalization = []
    rating = state.get("rating")
    review_count = state.get("review_count")
    if rating and review_count and review_count >= 10:
        personalization.append(
            f"They have {review_count} Google reviews with a {rating}/5 rating. "
            "Mention it as THEIR achievement, not yours."
        )
    if owner:
        personalization.append(f"The owner/manager's name appears to be {owner}. Address them by name.")
    personalization_block = "\n".join(f"- {p}" for p in personalization) or "- No extra personalization data."

    offer = (
        "Offer to put together a free, no-obligation homepage mockup, and say you will only do it if they reply."
        if OFFER_FREE_MOCKUP
        else "Offer something small and free that you can deliver quickly for every reply, for example a short list "
             "of specific fixes or a note on what a basic site for them would include. Do NOT promise a free website or mockup."
    )

    if OUTREACH_LANGUAGE.strip().lower() == "auto":
        language_rule = (
            f"Write in the primary local language of the business's location ({state.get('address')}). "
            "Name that language on the LANGUAGE line."
        )
    else:
        language_rule = f"Write the whole email in {OUTREACH_LANGUAGE}. Put {OUTREACH_LANGUAGE} on the LANGUAGE line."

    examples = load_examples()
    examples_block = (
        f"\nSTYLE EXAMPLES (copy the voice and rhythm only, never their facts):\n{examples}\n" if examples else ""
    )

    goal = (
        "pitch fixing or modernizing their existing website, not building one from scratch"
        if angle == "outdated"
        else "pitch a clean, fast, dedicated website so customers can find and contact them"
    )

    return f"""You write short cold emails for a solo web developer who contacts local businesses. Write one email to this business.

Business name: {state.get('name')}
Category: {state.get('category') or 'local business'}
Location: {state.get('address')}

THE ONE FINDING TO BUILD THE EMAIL AROUND (state it plainly, add no other claims about their site):
{describe_finding(state)}

Goal: {goal}.

Background notes (use at most one detail, only if it is clearly relevant):
{state.get('analysis')}

Personalization:
{personalization_block}
{examples_block}
STRUCTURE (no headings, no bullet points, 3 short paragraphs):
1. One sentence of genuine, specific recognition, then the finding.
2. What that likely costs them in plain terms (missed calls, customers leaving), in one or two sentences.
3. {offer} End with one easy yes/no question.

RULES:
1. {language_rule}
2. Never claim past clients, results, or portfolio links. Do not invent facts about the business.
3. No clichés ("I hope this finds you well", "in today's digital landscape").
4. Under {MAX_WORDS} words. Plain, conversational, like one person writing to another.
5. No em dashes. No exclamation marks. No emojis.
6. Do NOT write a sign-off or signature. End on the question.
7. The email must work if read in five seconds.

Output in EXACTLY this format, nothing else:
LANGUAGE: <language name>
SUBJECTS:
<option 1: plain, under 8 words, mentions the business name>
<option 2>
<option 3>
BODY:
<email body>"""


def generate_pitch(state: BusinessState) -> dict:
    if _client is None:
        raise RuntimeError("GEMINI_API_KEY is not set. Add it to your local .env file.")

    resp = _client.models.generate_content(model=GEMINI_MODEL, contents=build_prompt(state))
    language, subjects, body = parse_response((resp.text or "").strip())

    subject = pick_subject(subjects, state.get("name") or "")
    body = _append_signature(clean_body(body))
    return {"pitch_subject": subject, "pitch_body": body, "email_language": language}
