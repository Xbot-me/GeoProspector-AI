"""
Tiny local CRM. One row per business, one lightweight table -- no ORM
needed for a starter repo. Powered by modern PostgreSQL.

Also stores search run history so every query is browsable later.
"""
from contextlib import contextmanager
import psycopg
from psycopg.rows import dict_row

from config import DATABASE_URL

SCHEMA_BUSINESSES = """
CREATE TABLE IF NOT EXISTS businesses (
    place_id TEXT PRIMARY KEY,
    name TEXT,
    address TEXT,
    phone TEXT,
    category TEXT,
    website TEXT,
    email TEXT,
    email_source TEXT,
    rating REAL,
    review_count INTEGER,
    website_quality TEXT,
    website_notes TEXT,
    facebook_url TEXT,
    instagram_url TEXT,
    owner_name TEXT,
    contact_sources TEXT,
    lead_score INTEGER,
    score_breakdown TEXT,
    analysis TEXT,
    pitch_subject TEXT,
    pitch_body TEXT,
    approval_status TEXT DEFAULT 'pending',
    send_status TEXT DEFAULT 'not_sent',
    email_language TEXT DEFAULT 'English',
    email_verified BOOLEAN,
    opened_at TIMESTAMP WITH TIME ZONE,
    open_count INTEGER DEFAULT 0,
    sent_at TIMESTAMP WITH TIME ZONE,
    error_message TEXT,
    log_hidden BOOLEAN DEFAULT FALSE,
    latitude DOUBLE PRECISION,
    longitude DOUBLE PRECISION,
    timezone TEXT,
    international_phone TEXT,
    niches TEXT,
    owner_role TEXT,
    owner_linkedin TEXT,
    company_linkedin TEXT,
    contacts_json TEXT,
    review_source TEXT,
    review_url TEXT,
    market_context TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
"""

SCHEMA_RUNS = """
CREATE TABLE IF NOT EXISTS search_runs (
    run_id TEXT PRIMARY KEY,
    query TEXT NOT NULL,
    location TEXT NOT NULL,
    radius INTEGER,
    max_results INTEGER,
    result_count INTEGER DEFAULT 0,
    status TEXT DEFAULT 'running',
    ip_address TEXT DEFAULT 'unknown',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
"""

SCHEMA_RUN_BUSINESSES = """
CREATE TABLE IF NOT EXISTS run_businesses (
    run_id TEXT NOT NULL,
    place_id TEXT NOT NULL,
    PRIMARY KEY (run_id, place_id),
    FOREIGN KEY (run_id) REFERENCES search_runs(run_id) ON DELETE CASCADE,
    FOREIGN KEY (place_id) REFERENCES businesses(place_id) ON DELETE CASCADE
);
"""

SCHEMA_SUPPRESSION = """
CREATE TABLE IF NOT EXISTS suppression_list (
    email TEXT PRIMARY KEY,
    reason TEXT,
    source TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
"""

# Monthly Places API call counter. Lives in Postgres so it survives container
# rebuilds (the old quota_state.json was reset on every deploy).
SCHEMA_PLACES_QUOTA = """
CREATE TABLE IF NOT EXISTS places_quota (
    month TEXT PRIMARY KEY,
    calls INTEGER NOT NULL DEFAULT 0
);
"""

# Columns that may not exist in older databases.
_MIGRATION_COLUMNS = [
    ("rating", "REAL"),
    ("review_count", "INTEGER"),
    ("website_quality", "TEXT"),
    ("website_notes", "TEXT"),
    ("facebook_url", "TEXT"),
    ("instagram_url", "TEXT"),
    ("owner_name", "TEXT"),
    ("contact_sources", "TEXT"),
    ("lead_score", "INTEGER"),
    ("score_breakdown", "TEXT"),
    ("website", "TEXT"),
    ("email_language", "TEXT"),
    ("email_verified", "BOOLEAN"),
    ("opened_at", "TIMESTAMP WITH TIME ZONE"),
    ("open_count", "INTEGER"),
    ("sent_at", "TIMESTAMP WITH TIME ZONE"),
    ("error_message", "TEXT"),
    ("log_hidden", "BOOLEAN DEFAULT FALSE"),
    ("latitude", "DOUBLE PRECISION"),
    ("longitude", "DOUBLE PRECISION"),
    ("timezone", "TEXT"),
    ("international_phone", "TEXT"),
    ("niches", "TEXT"),
    ("owner_role", "TEXT"),
    ("owner_linkedin", "TEXT"),
    ("company_linkedin", "TEXT"),
    ("contacts_json", "TEXT"),
    ("review_source", "TEXT"),
    ("review_url", "TEXT"),
    ("market_context", "TEXT"),
]


@contextmanager
def get_conn():
    conn = psycopg.connect(DATABASE_URL, row_factory=dict_row)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _migrate(conn: psycopg.Connection) -> None:
    """Add new columns to existing tables without losing data."""
    cursor = conn.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'businesses'"
    )
    existing = {row["column_name"].lower() for row in cursor.fetchall()}
    for col_name, col_type in _MIGRATION_COLUMNS:
        if col_name.lower() not in existing:
            conn.execute(
                f"ALTER TABLE businesses ADD COLUMN IF NOT EXISTS {col_name} {col_type}"
            )

    cursor_runs = conn.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'search_runs'"
    )
    existing_runs = {row["column_name"].lower() for row in cursor_runs.fetchall()}
    if "ip_address" not in existing_runs:
        conn.execute("ALTER TABLE search_runs ADD COLUMN IF NOT EXISTS ip_address TEXT DEFAULT 'unknown'")


def init_db() -> None:
    with get_conn() as conn:
        conn.execute(SCHEMA_BUSINESSES)
        conn.execute(SCHEMA_RUNS)
        conn.execute(SCHEMA_RUN_BUSINESSES)
        conn.execute(SCHEMA_SUPPRESSION)
        conn.execute(SCHEMA_PLACES_QUOTA)
        _migrate(conn)
        conn.execute("DELETE FROM search_runs WHERE ip_address = 'auto_pilot_daemon'")
        # A lead left in 'sending' means the process died mid-send. We can't tell
        # whether the provider accepted it, so never re-send automatically.
        conn.execute(
            "UPDATE businesses SET send_status = 'failed', "
            "error_message = 'Interrupted while sending (app restarted). Check the provider log before retrying.' "
            "WHERE send_status = 'sending'"
        )


# ── Search runs ──────────────────────────────────────────────────────────

def save_search_run(run_id: str, query: str, location: str,
                    radius: int, max_results: int, ip_address: str = "unknown") -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO search_runs "
            "(run_id, query, location, radius, max_results, ip_address) "
            "VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (run_id) DO NOTHING",
            (run_id, query, location, radius, max_results, ip_address),
        )


def update_search_run(run_id: str, result_count: int, status: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE search_runs SET result_count = %s, status = %s "
            "WHERE run_id = %s",
            (result_count, status, run_id),
        )


def link_business_to_run(run_id: str, place_id: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO run_businesses (run_id, place_id) "
            "VALUES (%s, %s) ON CONFLICT (run_id, place_id) DO NOTHING",
            (run_id, place_id),
        )


def get_all_runs() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM search_runs ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def get_businesses_for_run(run_id: str) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT b.* FROM businesses b "
            "JOIN run_businesses rb ON b.place_id = rb.place_id "
            "WHERE rb.run_id = %s "
            "ORDER BY b.lead_score DESC NULLS LAST, b.name ASC",
            (run_id,),
        ).fetchall()
        return [dict(r) for r in rows]


# ── Businesses ───────────────────────────────────────────────────────────

_ALL_FIELDS = [
    "place_id", "name", "address", "phone", "category", "website", "email",
    "email_source", "rating", "review_count", "website_quality",
    "website_notes", "facebook_url", "instagram_url", "owner_name",
    "contact_sources", "lead_score", "score_breakdown", "analysis",
    "pitch_subject", "pitch_body", "approval_status", "send_status",
    "email_language", "email_verified", "opened_at", "open_count", "sent_at", "error_message",
    "latitude", "longitude", "timezone",
    "international_phone", "niches", "owner_role", "owner_linkedin", "company_linkedin", "contacts_json",
    "review_source", "review_url", "market_context",
]


def upsert_business(record: dict) -> None:
    if isinstance(record.get("niches"), list):  # pipeline state keeps niches as a list
        record = {**record, "niches": ", ".join(record["niches"]) or None}
    values = [record.get(f) for f in _ALL_FIELDS]
    placeholders = ",".join("%s" for _ in _ALL_FIELDS)
    updates = ",".join(
        f"{f}=excluded.{f}" for f in _ALL_FIELDS if f != "place_id"
    )

    with get_conn() as conn:
        conn.execute(
            f"""
            INSERT INTO businesses ({",".join(_ALL_FIELDS)})
            VALUES ({placeholders})
            ON CONFLICT(place_id) DO UPDATE SET
                {updates},
                updated_at=CURRENT_TIMESTAMP
            """,
            values,
        )


def get_business(place_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM businesses WHERE place_id = %s", (place_id,)
        ).fetchone()
        return dict(row) if row else None


def already_processed(place_id: str) -> bool:
    """Avoid re-emailing the same business across repeated runs."""
    biz = get_business(place_id)
    return bool(biz and biz["send_status"] == "sent")


def get_all_leads() -> list[dict]:
    """Return all businesses, ordered by score then name."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM businesses "
            "ORDER BY lead_score DESC NULLS LAST, created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def get_run_stats() -> dict:
    """Return aggregate counts for end-of-run summary."""
    with get_conn() as conn:
        total = conn.execute(
            "SELECT COUNT(*) AS cnt FROM businesses"
        ).fetchone()["cnt"]
        good_website = conn.execute(
            "SELECT COUNT(*) AS cnt FROM businesses WHERE website_quality = 'good'"
        ).fetchone()["cnt"]
        low_score = conn.execute(
            "SELECT COUNT(*) AS cnt FROM businesses WHERE lead_score IS NOT NULL "
            "AND lead_score < 50 AND website_quality != 'good'"
        ).fetchone()["cnt"]
        emails_found = conn.execute(
            "SELECT COUNT(*) AS cnt FROM businesses WHERE email IS NOT NULL "
            "AND email != ''"
        ).fetchone()["cnt"]
        approved = conn.execute(
            "SELECT COUNT(*) AS cnt FROM businesses WHERE approval_status = 'approved'"
        ).fetchone()["cnt"]
        sent = conn.execute(
            "SELECT COUNT(*) AS cnt FROM businesses WHERE send_status = 'sent'"
        ).fetchone()["cnt"]
    return {
        "total": total,
        "good_website": good_website,
        "low_score": low_score,
        "emails_found": emails_found,
        "approved": approved,
        "sent": sent,
    }


def get_daily_sent_count() -> int:
    """Return number of emails dispatched in the last 24 hours."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM businesses "
            "WHERE send_status = 'sent' AND sent_at >= NOW() - INTERVAL '24 hours'"
        ).fetchone()
        return row["cnt"] if row else 0


def record_email_open(place_id: str, ip: str = "unknown") -> None:
    """Record that an email was opened via tracking pixel."""
    with get_conn() as conn:
        conn.execute(
            "UPDATE businesses SET "
            "open_count = COALESCE(open_count, 0) + 1, "
            "opened_at = COALESCE(opened_at, CURRENT_TIMESTAMP), "
            "updated_at = CURRENT_TIMESTAMP "
            "WHERE place_id = %s",
            (place_id,),
        )


def record_email_sent(place_id: str, status: str = "sent", error: str = None) -> None:
    """Update send_status and sent_at timestamp when an email is dispatched.
    status is 'sent', 'failed' or 'simulated' (no provider credentials)."""
    with get_conn() as conn:
        conn.execute(
            "UPDATE businesses SET "
            "send_status = %s, "
            "sent_at = CASE WHEN %s = 'sent' THEN CURRENT_TIMESTAMP ELSE sent_at END, "
            "error_message = %s, "
            "log_hidden = FALSE, "
            "updated_at = CURRENT_TIMESTAMP "
            "WHERE place_id = %s",
            (status, status, error, place_id),
        )


def get_pending_auto_send_leads(limit: int = 1) -> list[dict]:
    """Fetch leads ready to be emailed (have email, not yet sent, score qualified).
    Excludes unsubscribed, bounced, and complained leads, and addresses
    that failed verification. Prioritizes verified emails over unchecked ones."""
    from config import MIN_LEAD_SCORE
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM businesses "
            "WHERE email IS NOT NULL AND email != '' "
            "AND send_status IN ('not_sent', 'pending_auto_send', 'queued') "
            "AND (lead_score IS NULL OR lead_score >= %s) "
            "AND pitch_subject IS NOT NULL AND pitch_subject != '' "
            "AND email_verified IS DISTINCT FROM FALSE "
            "AND LOWER(email) NOT IN (SELECT LOWER(email) FROM suppression_list) "
            "ORDER BY "
            "  CASE WHEN email_verified = TRUE THEN 0 ELSE 1 END, "
            "  lead_score DESC NULLS LAST, created_at ASC "
            "LIMIT %s",
            (MIN_LEAD_SCORE, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def claim_lead_for_sending(place_id: str) -> dict | None:
    """Atomically move a pending lead to 'sending' and return it.

    Returns None if another sender claimed it first or its status changed
    (unsubscribed, already sent), so the same lead is never emailed twice."""
    with get_conn() as conn:
        row = conn.execute(
            "UPDATE businesses SET send_status = 'sending', updated_at = CURRENT_TIMESTAMP "
            "WHERE place_id = %s AND send_status IN ('not_sent', 'pending_auto_send', 'queued') "
            "RETURNING *",
            (place_id,),
        ).fetchone()
        return dict(row) if row else None


def get_email_logs(limit: int = 50) -> list[dict]:
    """Fetch recent email dispatch logs (sent, failed or simulated) not hidden by a clear."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT place_id, name, email, send_status, sent_at, error_message, open_count, opened_at "
            "FROM businesses "
            "WHERE (send_status IN ('sent', 'failed', 'simulated') OR open_count > 0) "
            "AND NOT COALESCE(log_hidden, FALSE) "
            "ORDER BY COALESCE(sent_at, updated_at) DESC NULLS LAST "
            "LIMIT %s",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def clear_email_logs() -> int:
    """Hide current rows from the email log view.

    Send history is kept: resetting send_status would put already-contacted
    leads back into the auto-send queue and email them a second time."""
    with get_conn() as conn:
        cursor = conn.execute(
            "UPDATE businesses SET log_hidden = TRUE "
            "WHERE (send_status IN ('sent', 'failed', 'simulated') OR open_count > 0) "
            "AND NOT COALESCE(log_hidden, FALSE)"
        )
        return cursor.rowcount


def retry_failed_emails() -> int:
    """Re-queue all failed email dispatches by resetting send_status to 'pending_auto_send'."""
    with get_conn() as conn:
        cursor = conn.execute(
            "UPDATE businesses "
            "SET send_status = 'pending_auto_send', error_message = NULL "
            "WHERE send_status = 'failed' AND email IS NOT NULL AND email != ''"
        )
        return cursor.rowcount


def is_email_already_contacted(email: str, exclude_place_id: str = "") -> bool:
    """True if a different business with this email was already emailed or is queued."""
    if not email or "@" not in email:
        return False
    with get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM businesses WHERE LOWER(email) = LOWER(%s) AND place_id <> %s "
            "AND send_status IN ('sent', 'pending_auto_send', 'queued', 'sending')",
            (email.strip(), exclude_place_id or ""),
        ).fetchone()
        return row is not None


def get_processed_place_ids() -> set[str]:
    """place_ids that never need enriching again (same rule as is_business_already_processed).
    The area search skips billed detail calls for tiles holding only these."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT place_id FROM businesses WHERE lead_score IS NOT NULL "
            "OR send_status IN ('sent', 'pending_auto_send', 'queued', 'sending') "
            "OR approval_status IN ('approved', 'rejected')"
        ).fetchall()
        return {r["place_id"] for r in rows}


def is_business_already_processed(place_id: str, name: str = "", email: str = "") -> bool:
    """Check if a business has already been processed or contacted (100% solid deduplication)."""
    with get_conn() as conn:
        # 1. Check by place_id
        if place_id:
            row = conn.execute(
                "SELECT send_status, approval_status, lead_score FROM businesses WHERE place_id = %s",
                (place_id,),
            ).fetchone()
            if row and (
                row["send_status"] in ("sent", "pending_auto_send", "queued")
                or row["approval_status"] in ("approved", "rejected")
                or row["lead_score"] is not None
            ):
                return True
        # 2. Check by exact name if already queued or emailed
        if name and name.strip():
            row = conn.execute(
                "SELECT send_status FROM businesses WHERE LOWER(name) = LOWER(%s) AND (send_status IN ('sent', 'pending_auto_send', 'queued') OR lead_score IS NOT NULL)",
                (name.strip(),),
            ).fetchone()
            if row:
                return True
        # 3. Check by email if present
        if email and "@" in email:
            row = conn.execute(
                "SELECT send_status FROM businesses WHERE LOWER(email) = LOWER(%s) AND send_status IN ('sent', 'pending_auto_send', 'queued')",
                (email.strip(),),
            ).fetchone()
            if row:
                return True
    return False


# ── Suppression list ─────────────────────────────────────────────────────

def add_to_suppression(email: str, reason: str, source: str = "manual") -> None:
    """Add an email to the suppression list (bounced, complained, unsubscribed)."""
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO suppression_list (email, reason, source) "
            "VALUES (LOWER(%s), %s, %s) "
            "ON CONFLICT (email) DO UPDATE SET reason = %s, source = %s",
            (email, reason, source, reason, source),
        )


def is_suppressed(email: str) -> bool:
    """Check if an email is on the suppression list."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM suppression_list WHERE email = LOWER(%s)",
            (email,),
        ).fetchone()
        return row is not None


def get_suppression_list() -> list[dict]:
    """Return all suppressed emails."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM suppression_list ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def unsubscribe_business(place_id: str) -> dict | None:
    """Mark a business as unsubscribed and add to suppression list."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT email, name FROM businesses WHERE place_id = %s", (place_id,)
        ).fetchone()
        if not row:
            return None
        conn.execute(
            "UPDATE businesses SET send_status = 'unsubscribed', updated_at = CURRENT_TIMESTAMP "
            "WHERE place_id = %s",
            (place_id,),
        )
        if row["email"]:
            conn.execute(
                "INSERT INTO suppression_list (email, reason, source) "
                "VALUES (LOWER(%s), 'unsubscribed', 'unsubscribe_link') "
                "ON CONFLICT (email) DO UPDATE SET reason = 'unsubscribed', source = 'unsubscribe_link'",
                (row["email"],),
            )
        return dict(row)


# ── Places API quota ─────────────────────────────────────────────────────

def increment_places_calls(month: str, n: int, cap: int, seed: int = 0) -> int | None:
    """Add n calls to month's counter if that stays within cap.

    Returns the new total, or None when the cap would be exceeded. The check
    and increment are one UPDATE, so concurrent runs cannot overshoot.
    seed initialises a month that has no row yet (legacy JSON counter)."""
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO places_quota (month, calls) VALUES (%s, %s) ON CONFLICT (month) DO NOTHING",
            (month, seed),
        )
        row = conn.execute(
            "UPDATE places_quota SET calls = calls + %s "
            "WHERE month = %s AND calls + %s <= %s RETURNING calls",
            (n, month, n, cap),
        ).fetchone()
        return row["calls"] if row else None


def get_places_calls(month: str) -> int:
    with get_conn() as conn:
        row = conn.execute("SELECT calls FROM places_quota WHERE month = %s", (month,)).fetchone()
        return row["calls"] if row else 0


def delete_daemon_search_runs() -> int:
    """Delete search runs created by the automated daemon loop."""
    try:
        with get_conn() as conn:
            cursor = conn.execute("DELETE FROM search_runs WHERE ip_address = 'auto_pilot_daemon'")
            return cursor.rowcount if hasattr(cursor, 'rowcount') else 0
    except Exception:
        return 0
