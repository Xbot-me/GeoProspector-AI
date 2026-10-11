"""
Gemini extraction of owner / staff names and roles from website text.

LLMs invent plausible names, so every returned name must appear verbatim
(case/whitespace-insensitive) in the source text or it is dropped.
"""
import logging
import re

import llm

logger = logging.getLogger(__name__)

MAX_PEOPLE = 6


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def extract_people(text: str, business_name: str) -> list[dict]:
    if not text or not llm.available():
        return []
    prompt = f"""Below is text from the website of the business "{business_name}".
List the real people named in it who own, run or work at this business, with their role.
Only include names that appear in the text exactly. Do not guess or invent anyone.
Prefer owners, founders, directors and managers. Skip testimonial/review authors and customers.

Return JSON: {{"people": [{{"name": "Full Name", "role": "Owner"}}]}}  (role may be null; empty list if none)

TEXT:
{text}"""
    try:
        data = llm.generate_json(prompt, temperature=0)
    except Exception as e:
        logger.warning(f"AI people extraction failed for {business_name}: {e}")
        return []

    haystack = _norm(text)
    people = []
    for item in (data.get("people") if isinstance(data, dict) else None) or []:
        name = (item.get("name") or "").strip() if isinstance(item, dict) else ""
        if len(name.split()) < 2 or _norm(name) not in haystack:
            continue  # single words are too ambiguous; unseen names are hallucinations
        role = (item.get("role") or "").strip() or None
        people.append({"name": name, "role": role, "source": "website_ai"})
    return people[:MAX_PEOPLE]
