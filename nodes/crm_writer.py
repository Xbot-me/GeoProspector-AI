"""
Node: save_to_crm

Writes/updates the business row in the PostgreSQL CRM database at each stage so
progress is never lost even if a later node fails.
"""
from db import upsert_business
from state import BusinessState


def save_to_crm(state: BusinessState) -> dict:
    send_status = state.get("send_status", "not_sent")
    if send_status == "not_sent" and state.get("email") and state.get("pitch_subject"):
        send_status = "pending_auto_send"

    upsert_business({
        "place_id": state.get("place_id"),
        "name": state.get("name"),
        "address": state.get("address"),
        "phone": state.get("phone"),
        "category": state.get("category"),
        "website": state.get("website"),
        "email": state.get("email"),
        "email_source": state.get("email_source"),
        "email_verified": state.get("email_verified"),
        "rating": state.get("rating"),
        "review_count": state.get("review_count"),
        "review_source": state.get("review_source"),
        "review_url": state.get("review_url"),
        "market_context": state.get("market_context"),
        "latitude": state.get("latitude"),
        "longitude": state.get("longitude"),
        "timezone": state.get("timezone"),
        "website_quality": state.get("website_quality"),
        "website_notes": state.get("website_notes"),
        "facebook_url": state.get("facebook_url"),
        "instagram_url": state.get("instagram_url"),
        "owner_name": state.get("owner_name"),
        "owner_role": state.get("owner_role"),
        "owner_linkedin": state.get("owner_linkedin"),
        "company_linkedin": state.get("company_linkedin"),
        "contacts_json": state.get("contacts_json"),
        "international_phone": state.get("international_phone"),
        "niches": ", ".join(state.get("niches") or []) or None,
        "contact_sources": state.get("contact_sources"),
        "lead_score": state.get("lead_score"),
        "score_breakdown": state.get("score_breakdown"),
        "analysis": state.get("analysis"),
        "pitch_subject": state.get("pitch_subject"),
        "pitch_body": state.get("pitch_body"),
        "email_language": state.get("email_language", "English"),
        "approval_status": state.get("approval_status", "pending"),
        "send_status": send_status,
    })
    return {}
