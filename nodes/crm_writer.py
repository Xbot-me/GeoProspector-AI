"""
Node: save_to_crm

Writes/updates the business row in the PostgreSQL CRM database at each stage so
progress is never lost even if a later node fails.
"""
from db import upsert_business
from state import BusinessState


def save_to_crm(state: BusinessState) -> dict:
    upsert_business({
        "place_id": state.get("place_id"),
        "name": state.get("name"),
        "address": state.get("address"),
        "phone": state.get("phone"),
        "category": state.get("category"),
        "website": state.get("website"),
        "email": state.get("email"),
        "email_source": state.get("email_source"),
        "rating": state.get("rating"),
        "review_count": state.get("review_count"),
        "website_quality": state.get("website_quality"),
        "website_notes": state.get("website_notes"),
        "facebook_url": state.get("facebook_url"),
        "instagram_url": state.get("instagram_url"),
        "owner_name": state.get("owner_name"),
        "contact_sources": state.get("contact_sources"),
        "lead_score": state.get("lead_score"),
        "score_breakdown": state.get("score_breakdown"),
        "analysis": state.get("analysis"),
        "pitch_subject": state.get("pitch_subject"),
        "pitch_body": state.get("pitch_body"),
        "approval_status": state.get("approval_status", "pending"),
        "send_status": state.get("send_status", "not_sent"),
    })
    return {}
