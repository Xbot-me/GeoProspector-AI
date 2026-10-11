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
SENDER_NAME = os.getenv("SENDER_NAME", "") or "Mustafizur Rahman"
SENDER_SIGNATURE = """Mustafizur Rahman
Full-Stack Web Developer

https://www.mustafizur.info
https://www.fiverr.com/users/mustafizur_dev/portfolio
hello@mustafizur.info
+8801886769509"""

# Billed Places calls per calendar month (counted in Postgres by quota.py).
# Area search bills one call per 20 businesses (plus one geocode per run);
# the tiling pass uses the free IDs-only tier. 1000 = the Enterprise free tier.
MAX_PLACES_CALLS_PER_MONTH = _int("MAX_PLACES_CALLS_PER_MONTH", 1000)

# Optional enrichment sources (all free tiers)
COMPANIES_HOUSE_API_KEY = os.getenv("COMPANIES_HOUSE_API_KEY", "")  # UK company officers

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://appuser:secretpassword@localhost:5432/geoprospector")

# Email Delivery & Auto-Pilot Outreach Settings
EMAIL_PROVIDER = os.getenv("EMAIL_PROVIDER", "resend").lower()
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
EMAIL_FROM = os.getenv("EMAIL_FROM", f"{SENDER_NAME or 'Mustafizur Rahman'} <hello@mustafizur.info>")

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = _int("SMTP_PORT", 587)
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")

AUTO_SEND_EMAILS = _bool("AUTO_SEND_EMAILS", True)
MAX_DAILY_EMAILS = _int("MAX_DAILY_EMAILS", 20)

# CAN-SPAM compliance — legally required in every commercial email
SENDER_PHYSICAL_ADDRESS = os.getenv("SENDER_PHYSICAL_ADDRESS", "") or "Dhaka, Bangladesh"
UNSUBSCRIBE_BASE_URL = os.getenv("UNSUBSCRIBE_BASE_URL", "https://b2b.mustafizur.info")

# Dashboard Security & Authentication
# Fail-fast: refuse to start with the old hardcoded default on a public deploy.
_raw_admin_pw = os.getenv("ADMIN_PASSWORD", "")
if not _raw_admin_pw:
    import warnings
    warnings.warn(
        "ADMIN_PASSWORD is not set in .env — using insecure default. "
        "Set a strong password before exposing to the internet.",
        stacklevel=2,
    )
    _raw_admin_pw = "mustafizur2026"  # keep working locally, but warn loudly
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = _raw_admin_pw

# Field mask for the billed details pass of the area search. Places API (New)
# bills a request at the tier of its most expensive field: websiteUri, the
# phone numbers, rating and userRatingCount are "Text Search Enterprise"
# (1,000 free calls/month, then about $35 per 1,000 as of 2026). Check current
# tiers in your Cloud Console. nextPageToken is needed for pagination.
SEARCH_FIELD_MASK = (
    "places.id,"
    "places.displayName,"
    "places.formattedAddress,"
    "places.location,"
    "places.websiteUri,"
    "places.nationalPhoneNumber,"
    "places.internationalPhoneNumber,"
    "places.primaryType,"
    "places.businessStatus,"
    "places.rating,"
    "places.userRatingCount,"
    "nextPageToken"
)
