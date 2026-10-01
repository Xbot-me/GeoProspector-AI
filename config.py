"""
Central config. Loads everything from .env — never hardcode secrets here.
"""
import os
from dotenv import load_dotenv

load_dotenv()


def _int(name: str, default: int) -> int:
    val = os.getenv(name)
    return int(val) if val else default


def _bool(name: str, default: bool) -> bool:
    val = os.getenv(name, "").lower()
    if val in ("1", "true", "yes"):
        return True
    if val in ("0", "false", "no"):
        return False
    return default


GOOGLE_PLACES_API_KEY = os.getenv("GOOGLE_PLACES_API_KEY", "")

# Gemini API (Google AI Studio) -- used for business analysis + pitch
# writing. gemini-flash-lite-latest is a Google-maintained alias that
# always points at the current Flash-Lite model, which is the tier that
# stays free (Pro models were pulled from the free tier in April 2026).
# Get a free key with no credit card at https://aistudio.google.com
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-lite-latest")

HUNTER_API_KEY = os.getenv("HUNTER_API_KEY", "")

# Lead enrichment & scoring
ENABLE_WEB_SEARCH = _bool("ENABLE_WEB_SEARCH", True)
MIN_LEAD_SCORE = _int("MIN_LEAD_SCORE", 0)
# Sender identity. Everything here is configurable from .env so no personal
# details need to live in the repo.
SENDER_NAME = os.getenv("SENDER_NAME", "") or "Mustafizur Rahman"
SENDER_TITLE = os.getenv("SENDER_TITLE", "") or "Full-Stack Web Developer"
SENDER_WEBSITE = os.getenv("SENDER_WEBSITE", "") or "https://www.mustafizur.info"
SENDER_EMAIL = os.getenv("SENDER_EMAIL", "") or "hello@mustafizur.info"
SENDER_PHONE = os.getenv("SENDER_PHONE", "")  # optional, left out when empty
SENDER_PORTFOLIO_URL = os.getenv("SENDER_PORTFOLIO_URL", "")  # optional extra link


def _build_signature() -> str:
    lines = [SENDER_NAME, SENDER_TITLE, "", SENDER_WEBSITE]
    if SENDER_PORTFOLIO_URL:
        lines.append(SENDER_PORTFOLIO_URL)
    lines.append(SENDER_EMAIL)
    if SENDER_PHONE:
        lines.append(SENDER_PHONE)
    return "\n".join(lines)


SENDER_SIGNATURE = os.getenv("SENDER_SIGNATURE", "").replace("\\n", "\n") or _build_signature()

# Pagination: Text Search (New) returns 20 per page, up to 3 pages (60).
# Every page is one billable Places call and counts against the monthly cap.
MAX_PLACES_RESULTS_PER_RUN = _int("MAX_PLACES_RESULTS_PER_RUN", 60)

# Website audit (Google PageSpeed Insights API). A key is optional but gives
# a much higher rate limit: https://developers.google.com/speed/docs/insights/v5/get-started
ENABLE_PAGESPEED = _bool("ENABLE_PAGESPEED", True)
PAGESPEED_API_KEY = os.getenv("PAGESPEED_API_KEY", "")
# A live site scoring below this on mobile is treated as a prospect.
PAGESPEED_SLOW_THRESHOLD = _int("PAGESPEED_SLOW_THRESHOLD", 50)

# Outreach content
OUTREACH_LANGUAGE = os.getenv("OUTREACH_LANGUAGE", "English")
# Only offer a free mockup if you will actually build one for every reply.
OFFER_FREE_MOCKUP = _bool("OFFER_FREE_MOCKUP", False)

# Countries to prospect in (matched against the last part of each target
# city's "state, country"). Cold B2B email needs prior consent in much of the
# EU (Germany, Spain, Italy and others) and for UK sole traders, so the
# default is limited to markets where opt-out cold email is lawful. Check the
# rules for any country you add. Not legal advice.
OUTREACH_COUNTRIES = [
    c.strip().lower()
    for c in os.getenv("OUTREACH_COUNTRIES", "USA,Canada,Australia").split(",")
    if c.strip()
]

# Follow-up: one short nudge N days after the first email, then stop.
FOLLOWUP_ENABLED = _bool("FOLLOWUP_ENABLED", True)
FOLLOWUP_AFTER_DAYS = _int("FOLLOWUP_AFTER_DAYS", 5)
MAX_PLACES_CALLS_PER_MONTH = _int("MAX_PLACES_CALLS_PER_MONTH", 4000)

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://appuser:secretpassword@localhost:5432/geoprospector")

# Email Delivery & Auto-Pilot Outreach Settings
EMAIL_PROVIDER = os.getenv("EMAIL_PROVIDER", "resend").lower()
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
EMAIL_FROM = os.getenv("EMAIL_FROM", f"{SENDER_NAME} <{SENDER_EMAIL}>")

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = _int("SMTP_PORT", 587)
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")

# Auto-send is OFF by default. Even when on, only leads you have approved in
# the dashboard are sent (REQUIRE_APPROVAL), so a bad draft never goes out
# without a human looking at it.
AUTO_SEND_EMAILS = _bool("AUTO_SEND_EMAILS", False)
REQUIRE_APPROVAL = _bool("REQUIRE_APPROVAL", True)
# Keep this low while a new sending domain warms up (5-10/day for the first weeks).
MAX_DAILY_EMAILS = _int("MAX_DAILY_EMAILS", 10)

# CAN-SPAM compliance — legally required in every commercial email
SENDER_PHYSICAL_ADDRESS = os.getenv("SENDER_PHYSICAL_ADDRESS", "") or "Dhaka, Bangladesh"
# Public URL where THIS app is reachable by recipients (e.g. a Cloudflare
# Tunnel hostname). When running on a PC with no public URL leave it empty:
# emails then use a mailto: unsubscribe and open tracking is switched off,
# instead of shipping links that point nowhere.
UNSUBSCRIBE_BASE_URL = os.getenv("UNSUBSCRIBE_BASE_URL", "").rstrip("/")
TRACKING_BASE_URL = os.getenv("TRACKING_BASE_URL", "").rstrip("/") or UNSUBSCRIBE_BASE_URL

# Dashboard Security & Authentication
# Fail-fast: refuse to start with the old hardcoded default on a public deploy.
_raw_admin_pw = os.getenv("ADMIN_PASSWORD", "")
if not _raw_admin_pw:
    import secrets as _secrets
    _raw_admin_pw = _secrets.token_urlsafe(12)
    print(
        "[config] ADMIN_PASSWORD is not set in .env. Using a random password "
        f"for this run: {_raw_admin_pw}  (set ADMIN_PASSWORD to keep it stable)"
    )
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = _raw_admin_pw

# Minimal field masks -- keep these as small as possible to control billing tier.
# Places API (New) bills the WHOLE request at the tier of its most expensive
# field. websiteUri lives in the "Pro" tier, so any search that needs it to
# detect "no website" businesses is billed as Pro (5,000 free calls/month as
# of the SKU pricing Google introduced in March 2025), not Essentials
# (10,000 free calls/month). Verify current tiers/limits in your own Cloud
# Console before relying on these numbers for budgeting.
#
# rating and userRatingCount are also Pro-tier — since we're already on
# Pro for websiteUri, requesting them doesn't change the billing tier.
SEARCH_FIELD_MASK = (
    "places.id,"
    "places.displayName,"
    "places.formattedAddress,"
    "places.location,"
    "places.websiteUri,"
    "places.nationalPhoneNumber,"
    "places.primaryType,"
    "places.businessStatus,"
    "places.rating,"
    "places.userRatingCount"
)
