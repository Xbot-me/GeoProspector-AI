"""
Shared state that flows through every node for a single business.
"""
from typing import Optional, TypedDict


class BusinessState(TypedDict, total=False):
    # From Places API
    place_id: str
    name: str
    address: str
    phone: Optional[str]
    category: Optional[str]
    website: Optional[str]
    business_status: Optional[str]
    rating: Optional[float]
    review_count: Optional[int]

    # Website analysis
    has_real_website: bool
    website_quality: Optional[str]   # "none" | "dead" | "social_only" | "outdated" | "good"
    website_notes: Optional[str]     # details about what was found

    # Email discovery (multi-source)
    email: Optional[str]
    email_source: Optional[str]  # "website_scrape" | "web_search" | "hunter" | None
    email_verified: Optional[bool]  # MX record verified

    # Social / contact enrichment
    facebook_url: Optional[str]
    instagram_url: Optional[str]
    owner_name: Optional[str]
    contact_sources: Optional[str]  # JSON list of where info came from

    # Lead scoring
    lead_score: Optional[int]        # 0-100
    score_breakdown: Optional[str]   # human-readable breakdown

    # LLM outputs
    analysis: Optional[str]
    pitch_subject: Optional[str]
    pitch_body: Optional[str]
    email_language: Optional[str]

    # Human-in-the-loop
    approval_status: str  # "pending" | "approved" | "edited" | "rejected" | "skipped"

    # Final outcome
    send_status: str  # "not_sent" | "sent" | "failed" | "no_email" | "pending_auto_send" | "queued"
    opened_at: Optional[str]
    open_count: Optional[int]
    sent_at: Optional[str]
    error_message: Optional[str]
