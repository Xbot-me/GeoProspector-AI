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

MAX_PLACES_RESULTS_PER_RUN = _int("MAX_PLACES_RESULTS_PER_RUN", 25)
MAX_PLACES_CALLS_PER_MONTH = _int("MAX_PLACES_CALLS_PER_MONTH", 4000)

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://appuser:secretpassword@localhost:5432/geoprospector")

# Email Delivery & Auto-Pilot Outreach Settings
EMAIL_PROVIDER = os.getenv("EMAIL_PROVIDER", "resend").lower()
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
EMAIL_FROM = os.getenv("EMAIL_FROM", f"{SENDER_NAME or 'Mustafizur Rahman'} <hello@mustafizur.info>")

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = _int("SMTP_PORT", 587)
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")

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
