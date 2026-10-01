import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Keep tests hermetic: no real keys, no real sending, local test database.
# DB tests TRUNCATE tables, so they must never touch your real database: they
# only run against TEST_DATABASE_URL and are skipped when it is not set.
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://nobody@127.0.0.1:1/none"  # unreachable on purpose
)
os.environ["GOOGLE_PLACES_API_KEY"] = "test-places-key"
os.environ["GEMINI_API_KEY"] = ""
os.environ["RESEND_API_KEY"] = ""
os.environ["SMTP_USER"] = ""
os.environ["UNSUBSCRIBE_BASE_URL"] = ""
os.environ["ADMIN_PASSWORD"] = "test-password"
os.environ["REQUIRE_APPROVAL"] = "true"
os.environ["ENABLE_PAGESPEED"] = "true"
os.environ["PAGESPEED_API_KEY"] = ""
