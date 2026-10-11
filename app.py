"""
Web dashboard entry point.

Serves the dashboard at http://localhost:8000: search an area for one or more
niches, enrich every business (website, owner, contacts, reviews), and build a
manual outreach kit (analysis, mockup prompt, email draft) per lead. Emails are
sent only when the user explicitly dispatches one lead. The CLI (main.py) is a
parallel entry point.

Usage:
    python app.py
    # then open http://localhost:8000
"""
import asyncio
import base64
import csv
import io
import logging
import secrets
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from threading import Thread
from urllib.parse import quote

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect, Response
from fastapi.responses import FileResponse, StreamingResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from db import (
    get_all_leads, get_all_runs, get_business, get_businesses_for_run,
    init_db, link_business_to_run, save_search_run, update_search_run,
    upsert_business, record_email_open, record_email_sent,
    get_email_logs, clear_email_logs, is_business_already_processed,
    unsubscribe_business, add_to_suppression, get_suppression_list,
    claim_lead_for_sending, get_processed_place_ids,
)
from email_sender import send_email
from graph import build_graph, get_checkpointer_cm
from nodes.area_search import SearchError, search_area
from suggestions import split_niches, suggest_bundle
from config import ADMIN_USERNAME, ADMIN_PASSWORD, PLACES_PROVIDER

logger = logging.getLogger(__name__)

# ── In-memory run tracking ──────────────────────────────────────────────
# Maps run_id -> {"status", "events": [...], "stats": {}}
_runs: dict[str, dict] = {}

# Maps run_id -> list of WebSocket connections listening to it
_ws_clients: dict[str, list[WebSocket]] = {}

# Maps session token -> username for modern HTML login page
_sessions: dict[str, str] = {}


STATIC_DIR = Path(__file__).parent / "static"


# ── Lifespan ────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Maps Outreach Agent", lifespan=lifespan)


# ── Authentication Middleware ───────────────────────────────────────────

def _is_authenticated(conn: Request | WebSocket) -> bool:
    """True for a valid session cookie or valid HTTP Basic credentials."""
    session_token = conn.cookies.get("admin_session")
    if session_token and session_token in _sessions:
        return True

    auth_header = conn.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Basic "):
        return False
    try:
        decoded_creds = base64.b64decode(auth_header.split(" ", 1)[1]).decode("utf-8")
        username, _, password = decoded_creds.partition(":")
        return secrets.compare_digest(username, ADMIN_USERNAME) and secrets.compare_digest(password, ADMIN_PASSWORD)
    except Exception:
        return False


def _is_public_path(path: str) -> bool:
    # The public archive may list runs and (redacted) leads; CSV exports stay private.
    if path == "/api/runs" or (path.startswith("/api/runs/") and path.endswith("/leads")):
        return True
    return (
        path in ("/history", "/runs", "/public", "/login") or
        path.startswith("/api/track/") or
        path.startswith("/api/auth/") or
        path.startswith("/api/unsubscribe/") or
        path.startswith("/api/webhooks/") or
        path in ("/static/history.html", "/static/history.js", "/static/login.html", "/static/style.css", "/favicon.ico")
    )


@app.middleware("http")
async def basic_auth_middleware(request: Request, call_next):
    path = request.url.path
    if _is_public_path(path) or _is_authenticated(request):
        return await call_next(request)

    if path.startswith("/api/"):
        return Response(
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="Admin Dashboard"'},
            content="Unauthorized: Admin credentials required.",
        )
    # Redirect browser navigation to modern login page
    return RedirectResponse(url="/login", status_code=303)


# ── Static file serving ─────────────────────────────────────────────────
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
async def index():
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/login")
async def login_page():
    return FileResponse(str(STATIC_DIR / "login.html"))


@app.get("/history")
@app.get("/runs")
@app.get("/public")
async def history_page():
    return FileResponse(str(STATIC_DIR / "history.html"))


# ── Auth & Log Endpoints ─────────────────────────────────────────────────

@app.post("/api/auth/login")
async def login_endpoint(payload: dict, response: Response):
    username = payload.get("username", "")
    password = payload.get("password", "")
    if secrets.compare_digest(username, ADMIN_USERNAME) and secrets.compare_digest(password, ADMIN_PASSWORD):
        token = secrets.token_urlsafe(32)
        _sessions[token] = username
        response.set_cookie(key="admin_session", value=token, httponly=True, max_age=86400 * 7, samesite="lax")
        return {"success": True}
    return Response(status_code=401, content="Invalid username or password.")


@app.post("/api/auth/logout")
async def logout_endpoint(request: Request, response: Response):
    token = request.cookies.get("admin_session")
    if token and token in _sessions:
        del _sessions[token]
    response.delete_cookie("admin_session")
    return {"success": True}


@app.get("/api/email-logs")
async def list_email_logs():
    """Return recent email send logs and tracking statuses."""
    return get_email_logs(limit=100)


@app.post("/api/email-logs/clear")
async def clear_logs_endpoint():
    """Hide current log rows. Send history is kept so nobody is emailed twice."""
    return {"success": True, "cleared_count": clear_email_logs()}


# ── API Endpoints ────────────────────────────────────────────────────────

@app.get("/api/leads")
async def list_leads(run_id: str = ""):
    """Return leads, optionally filtered by run_id."""
    if run_id:
        return get_businesses_for_run(run_id)
    return get_all_leads()


@app.get("/api/leads/{place_id}")
async def get_lead(place_id: str):
    biz = get_business(place_id)
    if not biz:
        return Response(status_code=404, content="Lead not found")
    return biz


# Fields the public archive may show to visitors who are not logged in.
# Contact details, owner names and drafts are third-party personal data.
_PUBLIC_LEAD_FIELDS = (
    "place_id", "name", "category", "rating", "review_count",
    "website", "website_quality", "lead_score",
)


@app.get("/api/runs")
async def list_runs(request: Request):
    """Return all past search runs, newest first."""
    runs = get_all_runs()
    if not _is_authenticated(request):
        for r in runs:
            r.pop("ip_address", None)
    return runs


@app.get("/api/runs/{run_id}/leads")
async def get_run_leads(run_id: str, request: Request):
    """Return all businesses found in a specific search run (redacted when not logged in)."""
    leads = get_businesses_for_run(run_id)
    if _is_authenticated(request):
        return leads
    return [{k: lead.get(k) for k in _PUBLIC_LEAD_FIELDS} for lead in leads]


_CSV_FIELDS = [
    "name", "lead_score", "website_quality", "website", "email", "email_source",
    "owner_name", "owner_role", "owner_linkedin", "company_linkedin",
    "phone", "international_phone", "facebook_url", "instagram_url",
    "rating", "review_count", "review_source", "market_context", "category", "niches", "address",
    "analysis", "mockup_prompt", "pitch_subject", "pitch_body",
]


def _csv_response(leads: list[dict], filename: str) -> StreamingResponse:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=_CSV_FIELDS, extrasaction='ignore')
    writer.writeheader()
    for lead in leads:
        writer.writerow(lead)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


@app.get("/api/runs/{run_id}/csv")
async def export_run_csv(run_id: str):
    """Export a run's leads to CSV ('all' exports every lead)."""
    if run_id == "all":
        return _csv_response(get_all_leads(), "all_leads.csv")
    leads = get_businesses_for_run(run_id)
    if not leads:
        return Response(status_code=404, content="No leads found for this run")
    return _csv_response(leads, f"run_{run_id}.csv")


@app.get("/api/export")
async def export_all_csv():
    """Export every lead (dashboard 'Export CSV' button)."""
    return _csv_response(get_all_leads(), "all_leads.csv")


@app.get("/api/suggest-target")
async def suggest_target():
    """A fresh bundle of related niches + one city, never one already searched or just suggested."""
    return await asyncio.to_thread(suggest_bundle)


def _write_run_csv_to_disk(run_id: str):
    """Automatically save a run's CSV to the data directory."""
    leads = get_businesses_for_run(run_id)
    if not leads:
        return

    data_dir = Path("/app/data")
    if not data_dir.exists():
        data_dir = Path("data")
        data_dir.mkdir(exist_ok=True)

    filepath = data_dir / f"run_{run_id}.csv"
    with open(filepath, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=_CSV_FIELDS, extrasaction='ignore')
        writer.writeheader()
        for lead in leads:
            writer.writerow(lead)

    logger.info(f"Auto-saved CSV to {filepath}")


def _parse_niches(payload: dict) -> list[str]:
    raw = payload.get("niches")
    if isinstance(raw, list):
        niches = [str(n).strip() for n in raw if str(n).strip()]
    else:
        niches = split_niches(payload.get("query", ""))
    unique: dict[str, str] = {}
    for n in niches:
        unique.setdefault(n.lower(), n)
    return list(unique.values())[:10]


@app.post("/api/search")
async def start_search(payload: dict, request: Request):
    """Start a pipeline run in the background.

    Body: {"niches": ["Roofers", "HVAC"], "location": "...", "radius": 5000}
    ("query": "Roofers, HVAC" is accepted too). Every matching business in the
    radius is found; there is no per-run result cap."""
    niches = _parse_niches(payload)
    location = (payload.get("location") or "").strip()
    try:
        radius = max(100, min(int(payload.get("radius") or 5000), 50_000))
    except (TypeError, ValueError):
        return Response(status_code=400, content="radius must be a number of meters")

    if not niches or not location:
        return Response(status_code=400, content="niches and location are required")

    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        ip_address = forwarded.split(",")[0].strip()
    else:
        ip_address = request.client.host if request.client else "unknown"

    run_id = uuid.uuid4().hex[:12]
    save_search_run(run_id, ", ".join(niches), location, radius, 0, ip_address=ip_address)
    _runs[run_id] = {
        "status": "starting",
        "events": [],
        "stats": {
            "found": 0, "good_website": 0, "low_score": 0,
            "qualified": 0, "emails_found": 0, "approved": 0, "sent": 0,
            "owners_found": 0, "places_calls": 0,
        },
    }
    _ws_clients.setdefault(run_id, [])
    # Run pipeline in background thread (LangGraph + requests are sync)
    Thread(target=_run_pipeline_thread, args=(run_id, niches, location, radius), daemon=True).start()
    return {"run_id": run_id}


@app.get("/api/track/open/{place_id}.png")
async def track_email_open(place_id: str):
    """Transparent 1x1 pixel image endpoint for real-time open reporting."""
    record_email_open(place_id)
    # Transparent 1x1 GIF byte array
    pixel = b'\x47\x49\x46\x38\x39\x61\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff\x00\x00\x00\x21\xf9\x04\x01\x00\x00\x00\x00\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02\x44\x01\x00\x3b'
    return Response(content=pixel, media_type="image/gif")


@app.post("/api/leads/{place_id}/build-kit")
async def build_outreach_kit_endpoint(place_id: str):
    """Generate an outreach kit (analysis, mockup prompt, email draft) for a single lead."""
    from nodes.outreach_kit_generator import generate_outreach_kit
    biz = get_business(place_id)
    if not biz:
        return Response(status_code=404, content="Lead not found")

    try:
        kit = await asyncio.to_thread(generate_outreach_kit, biz)
        biz.update(kit)
        upsert_business(biz)
        return biz
    except Exception as e:
        logger.error(f"Error generating outreach kit for {place_id}: {e}")
        return Response(status_code=500, content=f"Error generating kit: {str(e)}")


@app.post("/api/leads/{place_id}/status")
async def update_lead_status(place_id: str, payload: dict):
    """Manually update lead status ('sent', 'not_sent', 'rejected') and/or the draft."""
    status = payload.get("status")
    if status not in (None, "sent", "not_sent", "rejected"):
        return Response(status_code=400, content="status must be sent, not_sent or rejected")

    biz = get_business(place_id)
    if not biz:
        return Response(status_code=404, content="Lead not found")

    if status == "sent":
        biz["send_status"] = "sent"
        biz["approval_status"] = "approved"
        biz["sent_at"] = datetime.now().isoformat()
    elif status == "not_sent":
        biz["send_status"] = "not_sent"
    elif status == "rejected":
        biz["approval_status"] = "rejected"

    if "pitch_body" in payload:
        biz["pitch_body"] = payload["pitch_body"]
    if "pitch_subject" in payload:
        biz["pitch_subject"] = payload["pitch_subject"]

    upsert_business(biz)
    return {"success": True, "send_status": biz["send_status"], "approval_status": biz["approval_status"]}


@app.post("/api/leads/{place_id}/send")
async def send_lead_email(place_id: str, payload: dict | None = None):
    """Send one lead's draft through the configured provider (Resend/SMTP).

    Only on an explicit click. Refuses drafts that still contain the
    [MOCKUP_LINK] placeholder, suppressed addresses (checked in send_email),
    and leads already sent or being sent (atomic claim)."""
    payload = payload or {}
    biz = get_business(place_id)
    if not biz:
        return Response(status_code=404, content="Lead not found")
    subject = (payload.get("pitch_subject") or biz.get("pitch_subject") or "").strip()
    body = (payload.get("pitch_body") or biz.get("pitch_body") or "").strip()
    if not biz.get("email"):
        return Response(status_code=400, content="This lead has no email address")
    if not subject or not body:
        return Response(status_code=400, content="Subject and body are required")
    if "[MOCKUP_LINK]" in body or "[MOCKUP_LINK]" in subject:
        return Response(status_code=400, content="Replace [MOCKUP_LINK] with the real mockup link before sending")

    # Save the edited draft, then claim the lead so a double click can't send twice.
    if subject != biz.get("pitch_subject") or body != biz.get("pitch_body"):
        biz.update({"pitch_subject": subject, "pitch_body": body})
        upsert_business(biz)
    claimed = claim_lead_for_sending(place_id)
    if not claimed:
        return Response(status_code=409, content=f"Not sent: lead status is '{biz.get('send_status')}'")

    try:
        success, err = await asyncio.to_thread(
            send_email, place_id=place_id, to_email=claimed["email"], subject=subject, body_text=body,
        )
    except Exception as e:
        success, err = False, f"Unexpected send error: {e}"
        record_email_sent(place_id, status="failed", error=err)
    if not success:
        return Response(status_code=502, content=err or "Send failed")
    lead = get_business(place_id)
    return {"success": True, "send_status": lead.get("send_status"), "error_message": lead.get("error_message")}


# ── WebSocket ────────────────────────────────────────────────────────────

@app.websocket("/ws/{run_id}")
async def websocket_endpoint(websocket: WebSocket, run_id: str):
    if not _is_authenticated(websocket):
        await websocket.close(code=4001, reason="Unauthorized")
        return

    await websocket.accept()
    _ws_clients.setdefault(run_id, []).append(websocket)

    # Send any events that already happened
    run = _runs.get(run_id)
    if run:
        for event in run["events"]:
            try:
                await websocket.send_json(event)
            except Exception:
                break

    try:
        while True:
            # Keep connection alive; client doesn't send much
            await websocket.receive_text()
    except WebSocketDisconnect:
        if run_id in _ws_clients:
            _ws_clients[run_id] = [
                ws for ws in _ws_clients[run_id] if ws != websocket
            ]


# ── Pipeline execution (runs in background thread) ──────────────────────

def _broadcast(run_id: str, event: dict):
    """Send an event to all WebSocket clients for this run."""
    run = _runs.get(run_id)
    if run:
        if "events" not in run:
            run["events"] = []
        run["events"].append(event)

    clients = _ws_clients.get(run_id, [])
    dead = []
    for ws in clients:
        try:
            # Use asyncio to send from sync thread
            loop = asyncio.new_event_loop()
            loop.run_until_complete(ws.send_json(event))
            loop.close()
        except Exception:
            dead.append(ws)

    for ws in dead:
        if ws in clients:
            clients.remove(ws)


def market_context(niches: list[str], totals: dict, radius_m: int) -> str | None:
    """Competitor line for the pitch, from the area search's per-niche counts."""
    for niche in niches:
        t = totals.get(niche)
        if t and t["total"] >= 3:
            # "list": counts come from the places data, not from checking each site
            noun = niche.lower() if niche.lower().endswith("s") else f"{niche.lower()} businesses"
            return (f"{t['with_website']} of {t['total']} {noun} within "
                    f"{radius_m / 1000:g} km list a website")
    return None


def _run_pipeline_thread(run_id: str, niches: list[str], location: str, radius: int):
    """Main pipeline execution — runs in a background thread."""
    run = _runs[run_id]
    label = ", ".join(niches)
    businesses: list[dict] = []

    # Step 1: Find every matching business in the radius
    _broadcast(run_id, {
        "type": "search_start",
        "query": label,
        "location": location,
        "message": f"🎯 LAUNCHED CAMPAIGN: {label.upper()} in {location.upper()} ({radius / 1000:g} km)"
    })
    _broadcast(run_id, {"type": "status", "message": f"Mapping {location} ({radius / 1000:g} km radius) for {label}..."})

    try:
        # Google bills per call, so skip details for places already enriched;
        # Overture is free, so return everything and reuse cached enrichment below.
        known = get_processed_place_ids() if PLACES_PROVIDER == "google" else None
        businesses, search_stats = search_area(
            niches, location, radius,
            known_place_ids=known,
            progress=lambda event: _broadcast(run_id, event),
        )
    except Exception as e:
        if not isinstance(e, (SearchError, RuntimeError)):
            logger.exception("Search failed")
        _broadcast(run_id, {"type": "error", "message": f"Search failed: {e}"})
        run["status"] = "error"
        update_search_run(run_id, 0, "error")
        return

    run["stats"]["places_calls"] = search_stats["billed_calls"]
    summary = (
        f"Coverage done: {len(businesses)} businesses ({search_stats.get('provider', 'google')}), "
        f"{search_stats['billed_calls']} billed Places calls"
    )
    if search_stats.get("dense_tiles"):
        summary += f" ({search_stats['dense_tiles']} very dense tiles may be incomplete)"
    _broadcast(run_id, {"type": "status", "message": summary})
    if search_stats.get("stopped"):
        _broadcast(run_id, {"type": "error", "message": f"Search stopped early, processing what was found: {search_stats['stopped']}"})

    # Competitor context for pitches: "14 of 22 roofers within 5 km have a website"
    for b in businesses:
        b["market_context"] = market_context(b.get("niches") or [], search_stats.get("niche_totals", {}), radius)

    run["stats"]["found"] = len(businesses)
    update_search_run(run_id, len(businesses), "running")

    _broadcast(run_id, {
        "type": "search_complete",
        "count": len(businesses),
        "businesses": [
            {"place_id": b["place_id"], "name": b["name"], "address": b["address"]}
            for b in businesses
        ],
    })

    try:
        # Step 2: Store every found business in CRM + link to run
        for b in businesses:
            existing = get_business(b["place_id"])
            if not existing:
                upsert_business({
                    "place_id": b["place_id"],
                    "name": b["name"],
                    "address": b["address"],
                    "phone": b.get("phone"),
                    "international_phone": b.get("international_phone"),
                    "category": b.get("category"),
                    "website": b.get("website"),
                    "rating": b.get("rating"),
                    "review_count": b.get("review_count"),
                    "latitude": b.get("latitude"),
                    "longitude": b.get("longitude"),
                    "timezone": b.get("timezone"),
                    "niches": ", ".join(b.get("niches") or []) or None,
                    "market_context": b.get("market_context"),
                    "contact_sources": b.get("contact_sources"),
                    "approval_status": "pending",
                    "send_status": "not_sent",
                })
            link_business_to_run(run_id, b["place_id"])

        # Step 3: Process each business through the enrichment pipeline
        with get_checkpointer_cm() as checkpointer:
            graph_app = build_graph(checkpointer)

            for i, business in enumerate(businesses):
                place_id = business["place_id"]
                name = business["name"]

                # Already contacted or unsubscribed
                if is_business_already_processed(place_id, name):
                    _broadcast(run_id, {
                        "type": "skipped",
                        "name": name,
                        "reason": "duplicate",
                        "message": f"Already contacted: {name}"
                    })
                    continue

                # Already enriched in CRM (has a lead_score): reuse instead of re-crawling
                existing = get_business(place_id)
                if existing and existing.get("lead_score") is not None:
                    quality = existing.get("website_quality")
                    if quality == "good":
                        run["stats"]["good_website"] += 1
                    else:
                        run["stats"]["qualified"] += 1
                        if existing.get("email"):
                            run["stats"]["emails_found"] += 1
                    if existing.get("owner_name"):
                        run["stats"]["owners_found"] += 1

                    _broadcast(run_id, {
                        "type": "drafted",
                        "place_id": place_id,
                        "name": name,
                        "lead_score": existing.get("lead_score"),
                        "has_pitch": bool(existing.get("pitch_body")),
                    })
                    continue

                # Not yet enriched -> run through graph
                _process_single_business(
                    run_id, graph_app, business, i + 1, len(businesses)
                )

        # Auto-save CSV to disk
        try:
            _write_run_csv_to_disk(run_id)
        except Exception as e:
            logger.error(f"Failed to auto-save CSV: {e}")

        # Done
        run["status"] = "complete"
        update_search_run(run_id, len(businesses), "complete")
        _broadcast(run_id, {"type": "complete", "stats": run["stats"]})

    except Exception as e:
        logger.error(f"Error during pipeline execution for run {run_id}: {e}", exc_info=True)
        run["status"] = "error"
        update_search_run(run_id, len(businesses), "error")
        _broadcast(run_id, {
            "type": "error",
            "message": f"Pipeline execution failed: {str(e)}",
            "stats": run["stats"],
        })


def _process_single_business(run_id: str, graph_app, business: dict,
                             index: int, total: int):
    """Process one business through the pipeline."""
    run = _runs[run_id]
    place_id = business["place_id"]
    name = business["name"]
    address = business.get("address", "")

    _broadcast(run_id, {
        "type": "processing",
        "place_id": place_id,
        "name": name,
        "address": address,
        "index": index,
        "total": total,
        "step": "check_website",
    })

    thread_id = f"biz-{place_id}-{uuid.uuid4().hex[:8]}"
    config = {"configurable": {"thread_id": thread_id}}

    try:
        result = graph_app.invoke(business, config=config)
    except Exception as e:
        _broadcast(run_id, {
            "type": "business_error",
            "place_id": place_id,
            "name": name,
            "error": str(e),
        })
        return

    if result.get("owner_name"):
        run["stats"]["owners_found"] += 1

    # Check early exits
    quality = result.get("website_quality")
    score = result.get("lead_score")

    if quality == "good":
        run["stats"]["good_website"] += 1
        _broadcast(run_id, {
            "type": "drafted",
            "place_id": place_id,
            "name": name,
            "lead_score": score,
            "has_pitch": False,
        })
        return

    run["stats"]["qualified"] += 1
    if result.get("email"):
        # Only matches leads already sent or unsubscribed, so a lead never matches itself.
        if is_business_already_processed("", "", result["email"]):
            logger.info(f"Skipping {name} — duplicate email {result['email']} already processed.")
            result["send_status"] = "skipped_duplicate"
            upsert_business(result)
            _broadcast(run_id, {
                "type": "skipped",
                "name": name,
                "reason": "duplicate_email",
                "message": f"Skipping duplicate email: {result['email']} (already contacted)"
            })
            return
        run["stats"]["emails_found"] += 1

    _broadcast(run_id, {
        "type": "drafted",
        "place_id": place_id,
        "name": name,
        "lead_score": score,
        "has_pitch": True,
    })


# ── Unsubscribe endpoints (public — no auth required) ──────────────────
# GET only shows a confirmation button: link scanners and mail-client
# prefetchers follow GET links, so GET must not change anything.
# POST performs the unsubscribe. It also serves RFC 8058 one-click requests
# (List-Unsubscribe-Post), which Gmail/Yahoo send as a POST to the same URL.

def _unsubscribe_page(title: str, message: str, form_action: str | None = None) -> Response:
    button = ""
    if form_action:
        button = f"""<form method="post" action="{form_action}" style="margin-top:20px;">
        <button type="submit" style="background:#0f172a; color:#fff; border:0; border-radius:8px;
            padding:12px 24px; font-size:14px; cursor:pointer;">Unsubscribe</button>
    </form>"""
    return Response(
        content=f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title></head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    display: flex; justify-content: center; align-items: center; min-height: 100vh;
    background: #f5f5f5; margin: 0; color: #333;">
<div style="text-align: center; max-width: 400px; padding: 40px; background: white;
    border-radius: 12px; box-shadow: 0 2px 12px rgba(0,0,0,0.08);">
    <h1 style="font-size: 20px; margin: 0 0 12px;">{title}</h1>
    <p style="color: #666; font-size: 14px; line-height: 1.5;">{message}</p>
    {button}
</div>
</body></html>""",
        media_type="text/html",
    )


@app.get("/api/unsubscribe/{place_id}")
async def confirm_unsubscribe(place_id: str):
    """Confirmation page linked in every outgoing email."""
    return _unsubscribe_page(
        "Unsubscribe from these emails?",
        "Click the button below and you won't receive any more emails from us.",
        form_action=f"/api/unsubscribe/{quote(place_id, safe='')}",
    )


@app.post("/api/unsubscribe/{place_id}")
async def handle_unsubscribe(place_id: str):
    """Perform the unsubscribe (confirmation form or RFC 8058 one-click POST)."""
    result = unsubscribe_business(place_id)
    name = result["name"] if result else "Unknown"
    logger.info(f"Unsubscribed: {name} (place_id={place_id})")
    return _unsubscribe_page(
        "You've been unsubscribed",
        "You won't receive any more emails from us. Sorry for the interruption.",
    )


# ── Resend webhook endpoint (public — no auth, verified by event type) ──

@app.post("/api/webhooks/resend")
async def resend_webhook(request: Request):
    """Handle Resend bounce/complaint/delivery webhook events."""
    try:
        payload = await request.json()
    except Exception:
        return Response(status_code=400, content="Invalid JSON")

    event_type = payload.get("type", "")
    data = payload.get("data", {})
    to_email = ""

    # Resend sends 'to' as a list of strings
    to_list = data.get("to", [])
    if isinstance(to_list, list) and to_list:
        to_email = to_list[0]
    elif isinstance(to_list, str):
        to_email = to_list

    logger.info(f"Resend webhook: type={event_type}, to={to_email}")

    if event_type == "email.bounced" and to_email:
        add_to_suppression(to_email, reason="bounced", source="resend_webhook")
        logger.warning(f"BOUNCE: {to_email} added to suppression list")

    elif event_type == "email.complained" and to_email:
        add_to_suppression(to_email, reason="complained", source="resend_webhook")
        logger.warning(f"COMPLAINT: {to_email} added to suppression list")

    elif event_type == "email.delivered" and to_email:
        logger.info(f"DELIVERED: {to_email}")

    return {"status": "ok"}


# ── Suppression list API (auth required) ────────────────────────────────

@app.get("/api/suppression")
async def get_suppression():
    """Return all emails on the suppression list."""
    return get_suppression_list()


@app.post("/api/suppression/add")
async def add_suppression(request: Request):
    """Manually add an email to the suppression list."""
    body = await request.json()
    email = body.get("email", "").strip()
    reason = body.get("reason", "manual")
    if not email or "@" not in email:
        return Response(status_code=400, content="Invalid email")
    add_to_suppression(email, reason=reason, source="manual")
    return {"status": "ok", "email": email}


# ── Entry point ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    import os
    import uvicorn
    port = int(os.getenv("PORT", "8000"))  # Render sets $PORT
    print("\n  🗺️  Maps Outreach Agent")
    print(f"  Dashboard: http://localhost:{port}\n")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
