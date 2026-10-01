"""
Call sheet: the phone is usually a better first channel than email for local
trades businesses, and every lead already has a phone number from Google Maps.
Each row gets a short opener built on the same concrete finding the email uses.
"""
from config import SENDER_NAME
from findings import describe_finding

CSV_FIELDS = [
    "name", "phone", "address", "category", "lead_score", "rating", "review_count",
    "website_quality", "finding", "opener", "email", "place_id",
]


def build_opener(biz: dict) -> str:
    owner = (biz.get("owner_name") or "").strip()
    who = owner if owner else f"the owner of {biz.get('name', 'the business')}"
    rating, reviews = biz.get("rating"), biz.get("review_count")
    kudos = f"{reviews} reviews at {rating} stars is great. " if rating and reviews and reviews >= 10 else ""
    finding = describe_finding(biz).rstrip(".")
    return (
        f"Hi, may I speak with {who}? I'm {SENDER_NAME}, a web developer. I'll be quick. {kudos}"
        f"I noticed: {finding[0].lower() + finding[1:]}. "
        "Is that something you'd want help with? If not, no worries at all."
    )


def build_call_sheet(leads: list[dict]) -> list[dict]:
    rows = []
    for biz in leads:
        rows.append({
            "name": biz.get("name"),
            "phone": biz.get("phone"),
            "address": biz.get("address"),
            "category": biz.get("category"),
            "lead_score": biz.get("lead_score"),
            "rating": biz.get("rating"),
            "review_count": biz.get("review_count"),
            "website_quality": biz.get("website_quality"),
            "finding": describe_finding(biz),
            "opener": build_opener(biz),
            "email": biz.get("email"),
            "place_id": biz.get("place_id"),
        })
    return rows
