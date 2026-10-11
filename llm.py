"""
Shared Gemini client with retry/backoff.

The free tier rate-limits aggressively (HTTP 429); without a retry a single
limit hit used to drop the lead from the run.
"""
import json
import logging
import time

from config import GEMINI_API_KEY, GEMINI_MODEL

logger = logging.getLogger(__name__)

_client = None


def available() -> bool:
    return bool(GEMINI_API_KEY)


def _get_client():
    global _client
    if _client is None:
        if not GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY is not set. Add it to your local .env file.")
        from google import genai
        _client = genai.Client(api_key=GEMINI_API_KEY)
    return _client


def _is_retryable(exc: Exception) -> bool:
    text = str(exc).lower()
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    return code in (429, 500, 503) or "429" in text or "resource_exhausted" in text or "unavailable" in text


def generate_text(prompt: str, temperature: float | None = None, json_output: bool = False,
                  retries: int = 4) -> str:
    """Return the model's text, retrying rate limits with exponential backoff."""
    from google.genai import types

    config = types.GenerateContentConfig(
        temperature=temperature,
        response_mime_type="application/json" if json_output else None,
    )
    delay = 5.0
    for attempt in range(retries + 1):
        try:
            resp = _get_client().models.generate_content(model=GEMINI_MODEL, contents=prompt, config=config)
            return (resp.text or "").strip()
        except Exception as e:
            if attempt < retries and _is_retryable(e):
                logger.warning(f"Gemini rate-limited/unavailable, retrying in {delay:.0f}s: {e}")
                time.sleep(delay)
                delay = min(delay * 2, 60)
                continue
            raise
    return ""  # pragma: no cover


def generate_json(prompt: str, temperature: float | None = None):
    """generate_text in JSON mode, parsed. Tolerates a stray ``` fence."""
    text = generate_text(prompt, temperature=temperature, json_output=True)
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0]
    return json.loads(text)
