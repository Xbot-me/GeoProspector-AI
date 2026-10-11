"""Unit tests: pure logic only, no network, no database (externals are monkeypatched)."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# Never let a developer's .env reach real services from tests.
os.environ.update({
    "ADMIN_PASSWORD": "test",
    "GEMINI_API_KEY": "",
    "HUNTER_API_KEY": "",
    "COMPANIES_HOUSE_API_KEY": "",
    "RESEND_API_KEY": "",
    "GOOGLE_PLACES_API_KEY": "test-key",
    "ENABLE_WEB_SEARCH": "false",
    "AUTO_SEND_EMAILS": "false",
})
