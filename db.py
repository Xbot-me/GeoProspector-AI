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
    opened_at TIMESTAMP WITH TIME ZONE,
    open_count INTEGER DEFAULT 0,
    sent_at TIMESTAMP WITH TIME ZONE,
    error_message TEXT,
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
    ("opened_at", "TIMESTAMP WITH TIME ZONE"),
    ("open_count", "INTEGER"),
    ("sent_at", "TIMESTAMP WITH TIME ZONE"),
    ("error_message", "TEXT"),
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
        _migrate(conn)


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
    "email_language", "opened_at", "open_count", "sent_at", "error_message",
]


def upsert_business(record: dict) -> None:
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
    """Update send_status and sent_at timestamp when an email is dispatched."""
    with get_conn() as conn:
        conn.execute(
            "UPDATE businesses SET "
            "send_status = %s, "
            "sent_at = CASE WHEN %s = 'sent' THEN CURRENT_TIMESTAMP ELSE sent_at END, "
            "error_message = %s, "
            "updated_at = CURRENT_TIMESTAMP "
            "WHERE place_id = %s",
            (status, status, error, place_id),
        )


def get_pending_auto_send_leads(limit: int = 1) -> list[dict]:
    """Fetch leads ready to be emailed (have email, not yet sent, score qualified)."""
    from config import MIN_LEAD_SCORE
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM businesses "
            "WHERE email IS NOT NULL AND email != '' "
            "AND send_status IN ('not_sent', 'pending_auto_send', 'queued') "
            "AND (lead_score IS NULL OR lead_score >= %s) "
            "AND pitch_subject IS NOT NULL AND pitch_subject != '' "
            "ORDER BY lead_score DESC NULLS LAST, created_at ASC "
            "LIMIT %s",
            (MIN_LEAD_SCORE, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def get_email_logs(limit: int = 50) -> list[dict]:
    """Fetch recent email dispatch logs (sent or failed)."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT place_id, name, email, send_status, sent_at, error_message, open_count, opened_at "
            "FROM businesses "
            "WHERE send_status IN ('sent', 'failed') OR open_count > 0 "
            "ORDER BY COALESCE(sent_at, updated_at) DESC NULLS LAST "
            "LIMIT %s",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

