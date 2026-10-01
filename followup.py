"""
One short follow-up email, sent a few days after the first one. Plain
template (no LLM call), written to be easy to say no to. After this we stop:
a second nudge is the last message this person gets from us.
"""
from config import SENDER_NAME, SENDER_SIGNATURE, SENDER_WEBSITE


def build_followup(biz: dict) -> tuple[str, str]:
    """Return (subject, body) for the follow-up to `biz`."""
    subject = biz.get("pitch_subject") or f"Question about {biz.get('name', 'your business')}"
    if not subject.lower().startswith("re:"):
        subject = f"Re: {subject}"

    owner = (biz.get("owner_name") or "").strip()
    greeting = f"Hi {owner}," if owner else "Hi,"
    name = biz.get("name") or "your business"

    body = (
        f"{greeting}\n\n"
        f"Just a quick follow-up on my note about {name}. "
        "If a better website isn't a priority right now, no problem at all and I won't "
        "bother you again. If it is, reply with a yes and I'll send over the details.\n\n"
        f"{SENDER_SIGNATURE}"
    )
    return subject, body
