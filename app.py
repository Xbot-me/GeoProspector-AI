"""
Web dashboard entry point.

Serves a real-time dashboard at http://localhost:8000 that replaces the
CLI for running the outreach pipeline. The existing CLI (main.py) still
works — this is a parallel entry point.

Usage:
    python app.py
    # then open http://localhost:8000
"""
import asyncio
import base64
import csv
import io
import json
import logging
import random
import secrets
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from threading import Thread

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect, Response
from fastapi.responses import FileResponse, StreamingResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from db import (
    get_all_leads, get_all_runs, get_business, get_businesses_for_run,
    init_db, link_business_to_run, save_search_run, update_search_run,
    upsert_business, record_email_open, get_pending_auto_send_leads,
    get_daily_sent_count, get_email_logs, clear_email_logs, is_business_already_processed,
    unsubscribe_business, add_to_suppression, get_suppression_list, record_email_sent,
)
from email_sender import format_html_email, send_email
from auto_campaign import get_next_campaign_target, get_lead_timezone, is_good_send_time, seconds_until_next_window
from graph import build_graph, get_checkpointer_cm
from nodes.places_search import search_businesses
from quota import QuotaExceededError
from config import MIN_LEAD_SCORE, GEMINI_API_KEY, GEMINI_MODEL, ADMIN_USERNAME, ADMIN_PASSWORD

from google import genai
_gemini_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

logger = logging.getLogger(__name__)

# ── In-memory run tracking ──────────────────────────────────────────────
# Maps run_id -> {"status", "events": [...], "stats": {}}
_runs: dict[str, dict] = {}

# Maps run_id -> list of WebSocket connections listening to it
_ws_clients: dict[str, list[WebSocket]] = {}

# Maps session token -> username for modern HTML login page
_sessions: dict[str, str] = {}

# Background interval email scheduler state
_scheduler_state = {
    "is_running": False,
    "next_send_time": None,
    "scheduled_count": 0,
    "interval_minutes": 30,
    "last_error": None,
}


def _interval_worker_loop():
    logger.info("Starting background interval email sender...")
    _scheduler_state["is_running"] = True
    while True:
        try:
            sent_today = get_daily_sent_count()
            if sent_today >= 20:
                _scheduler_state["next_send_time"] = "Daily quota reached (20/20)"
                time.sleep(300)
                continue

            pending = get_pending_auto_send_leads(limit=100)
            _scheduler_state["scheduled_count"] = len(pending)

            if not pending:
                _scheduler_state["next_send_time"] = "Queue empty (waiting for leads...)"
                time.sleep(60)
                continue

            # Pick the first pending lead to send
            biz = pending[0]

            # Timezone-aware send timing: only send during business hours
            lead_tz = get_lead_timezone(biz.get("address", ""))
            if not is_good_send_time(lead_tz):
                wait_secs = seconds_until_next_window(lead_tz)
                _scheduler_state["next_send_time"] = f"Waiting for business hours in {lead_tz} (~{wait_secs // 60}m)"
                logger.info(f"Outside send window for {lead_tz}, sleeping {wait_secs}s")
                time.sleep(min(wait_secs, 3600))  # Re-check at least every hour
                continue

            success, err = send_email(
                place_id=biz["place_id"],
                to_email=biz["email"],
                subject=biz["pitch_subject"],
                body_text=biz["pitch_body"]
            )
            if not success:
                _scheduler_state["last_error"] = err

            # Sleep for randomized interval (25 to 35 minutes)
            delay_mins = random.randint(25, 35)
            next_time = datetime.now() + timedelta(minutes=delay_mins)
            _scheduler_state["next_send_time"] = f"{next_time.strftime('%I:%M %p')} (~{delay_mins}m interval)"
            time.sleep(delay_mins * 60)
        except Exception as e:
            logger.error(f"Interval worker exception: {e}")
            _scheduler_state["last_error"] = str(e)
            time.sleep(60)


STATIC_DIR = Path(__file__).parent / "static"


# ── Lifespan ────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    thread = Thread(target=_interval_worker_loop, daemon=True)
    thread.start()
    yield


app = FastAPI(title="Maps Outreach Agent", lifespan=lifespan)


# ── Authentication Middleware ───────────────────────────────────────────

@app.middleware("http")
async def basic_auth_middleware(request: Request, call_next):
    path = request.url.path
    # Allow public endpoints and login assets without authentication
    if (
        path in ("/history", "/runs", "/public", "/login") or
        path.startswith("/api/runs") or
        path.startswith("/api/track/") or
        path.startswith("/api/auth/") or
        path.startswith("/api/unsubscribe/") or
        path.startswith("/api/webhooks/") or
        path in ("/static/history.html", "/static/history.js", "/static/login.html", "/static/style.css", "/favicon.ico")
    ):
        return await call_next(request)

    # 1. Check Cookie Session Token first (Modern HTML login)
    session_token = request.cookies.get("admin_session")
    if session_token and session_token in _sessions:
        return await call_next(request)

    # 2. Fallback to HTTP Basic Auth (API scripts / cron jobs)
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Basic "):
        if path.startswith("/api/"):
            return Response(
                status_code=401,
                headers={"WWW-Authenticate": 'Basic realm="Admin Dashboard"'},
                content="Unauthorized: Admin credentials required.",
            )
        # Redirect browser navigation to modern login page
        return RedirectResponse(url="/login", status_code=303)

    try:
        encoded_creds = auth_header.split(" ", 1)[1]
        decoded_creds = base64.b64decode(encoded_creds).decode("utf-8")
        username, _, password = decoded_creds.partition(":")

        if not (secrets.compare_digest(username, ADMIN_USERNAME) and secrets.compare_digest(password, ADMIN_PASSWORD)):
            return Response(
                status_code=401,
                headers={"WWW-Authenticate": 'Basic realm="Admin Dashboard"'},
                content="Invalid credentials.",
            )
    except Exception:
        return Response(
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="Admin Dashboard"'},
            content="Invalid Authorization header format.",
        )

    return await call_next(request)


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


@app.get("/api/scheduler/status")
async def get_scheduler_status():
    sent_today = get_daily_sent_count()
    pending = get_pending_auto_send_leads(limit=100)
    _scheduler_state["scheduled_count"] = len(pending)
    return {
        "is_running": _scheduler_state["is_running"],
        "scheduled_count": len(pending),
        "daily_sent_total": sent_today,
        "daily_limit": 20,
        "next_send_time": _scheduler_state["next_send_time"] or ("Queue empty" if not pending else "Calculating..."),
        "last_error": _scheduler_state.get("last_error")
    }


@app.post("/api/email-logs/clear")
async def clear_logs_endpoint():
    count = clear_email_logs()
    _scheduler_state["last_error"] = None
    return {"success": True, "cleared_count": count}


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
        return {"error": "not found"}, 404
    return biz


@app.get("/api/runs")
async def list_runs():
    """Return all past search runs, newest first."""
    return get_all_runs()


@app.get("/api/runs/{run_id}/leads")
async def get_run_leads(run_id: str):
    """Return all businesses found in a specific search run."""
    return get_businesses_for_run(run_id)


@app.get("/api/runs/{run_id}/csv")
async def export_run_csv(run_id: str):
    """Export a run's leads to CSV."""
    leads = get_businesses_for_run(run_id)
    if not leads:
        # If run_id is 'all', export everything
        if run_id == "all":
            leads = get_all_leads()
        else:
            return {"error": "no leads found"}, 404

    # Build CSV in memory
    output = io.StringIO()
    # Define columns we care about
    fieldnames = [
        "name", "lead_score", "website_quality", "email", 
        "phone", "facebook_url", "instagram_url", "owner_name", 
        "rating", "review_count", "category", "address", 
        "pitch_subject", "pitch_body"
    ]
    
    writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction='ignore')
    writer.writeheader()
    for lead in leads:
        writer.writerow(lead)

    output.seek(0)
    
    filename = "all_leads.csv" if run_id == "all" else f"run_{run_id}.csv"
    
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


@app.get("/api/suggest-target")
async def suggest_target():
    """Use Gemini to brainstorm a high-ticket, low-tech niche and growing city."""
    if not _gemini_client:
        return {"error": "Gemini API key not configured"}
        
    prompt = (
        "I run a web design agency that builds high-converting websites for local service businesses. "
        "I need ONE randomly generated 'High-Ticket, low-tech' niche. "
        "This should be a business where a single customer is worth at least $2,000 to them (e.g., Roofers, HVAC, Medi-Spas, Concrete contractors, Luxury landscaping). "
        "Also pick ONE randomly generated, rapidly growing mid-sized US city where housing or population is booming. "
        "Format the output EXACTLY as a raw JSON object with NO markdown formatting, like this:\n"
        '{"query": "Plumbing contractors", "location": "Boise, ID"}'
    )
    
    try:
        resp = _gemini_client.models.generate_content(model=GEMINI_MODEL, contents=prompt)
        text = resp.text.strip()
        # Clean up in case Gemini returns markdown JSON block
        if text.startswith("```json"):
            text = text[7:]
        if text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
            
        data = json.loads(text.strip())
        return data
    except Exception as e:
        logger.error(f"Suggest target failed: {e}")
        return {"error": "Failed to generate suggestion"}


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
    
    fieldnames = [
        "name", "lead_score", "website_quality", "email", 
        "phone", "facebook_url", "instagram_url", "owner_name", 
        "rating", "review_count", "category", "address", 
        "pitch_subject", "pitch_body"
    ]
    
    with open(filepath, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader()
        for lead in leads:
            writer.writerow(lead)
    
    logger.info(f"Auto-saved CSV to {filepath}")



@app.post("/api/search")
async def start_search(payload: dict, request: Request):
    """Start a pipeline run in the background."""
    query = payload.get("query", "").strip()
    location = payload.get("location", "").strip()
    radius = int(payload.get("radius", 5000))
    max_results = int(payload.get("max_results", 15))

    if not query or not location:
        return {"error": "query and location are required"}

    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        ip_address = forwarded.split(",")[0].strip()
    else:
        ip_address = request.client.host if request.client else "unknown"

    run_id = uuid.uuid4().hex[:12]

    # Persist the search run to DB immediately
    save_search_run(run_id, query, location, radius, max_results, ip_address=ip_address)

    _runs[run_id] = {
        "status": "starting",
        "events": [],
        "stats": {
            "found": 0, "good_website": 0, "low_score": 0,
            "qualified": 0, "emails_found": 0, "approved": 0, "sent": 0,
        },
    }
    _ws_clients.setdefault(run_id, [])

    # Run pipeline in background thread (LangGraph + requests are sync)
    thread = Thread(
        target=_run_pipeline_thread,
        args=(run_id, query, location, radius, max_results),
        daemon=True,
    )
    thread.start()

    return {"run_id": run_id}


@app.get("/api/track/open/{place_id}.png")
async def track_email_open(place_id: str):
    """Transparent 1x1 pixel image endpoint for real-time open reporting."""
    record_email_open(place_id)
    # Transparent 1x1 GIF byte array
    pixel = b'\x47\x49\x46\x38\x39\x61\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff\x00\x00\x00\x21\xf9\x04\x01\x00\x00\x00\x00\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02\x44\x01\x00\x3b'
    return Response(content=pixel, media_type="image/gif")


@app.post("/api/campaign/run_daily")
async def run_daily_campaign(request: Request):
    """Trigger the daily auto-pilot campaign (rotation target + auto-send pending leads)."""
    # 1. Process 1 pending auto-send lead immediately (the background interval worker handles the rest)
    sent_today = get_daily_sent_count()
    remaining_quota = max(0, 20 - sent_today)
    
    pending_leads = get_pending_auto_send_leads(limit=1 if remaining_quota > 0 else 0)
    dispatched_count = 0
    for biz in pending_leads:
        success, _ = send_email(
            place_id=biz["place_id"],
            to_email=biz["email"],
            subject=biz["pitch_subject"],
            body_text=biz["pitch_body"]
        )
        if success:
            dispatched_count += 1

    # 2. Select next target from curated US/Global rotation
    target = get_next_campaign_target()
    query = target["query"]
    location = target["location"]
    radius = 15000
    max_results = 20

    forwarded = request.headers.get("X-Forwarded-For")
    ip_address = forwarded.split(",")[0].strip() if forwarded else (request.client.host if request.client else "unknown")

    run_id = uuid.uuid4().hex[:12]
    save_search_run(run_id, query, location, radius, max_results, ip_address=ip_address)

    _runs[run_id] = {
        "status": "starting",
        "events": [],
        "stats": {
            "found": 0, "good_website": 0, "low_score": 0,
            "qualified": 0, "emails_found": 0, "approved": 0, "sent": 0,
        },
    }
    _ws_clients.setdefault(run_id, [])

    thread = Thread(
        target=_run_pipeline_thread,
        args=(run_id, query, location, radius, max_results),
        daemon=True,
    )
    thread.start()

    return {
        "success": True,
        "run_id": run_id,
        "target": target,
        "dispatched_from_queue": dispatched_count,
        "daily_sent_total": sent_today + dispatched_count
    }


@app.post("/api/leads/{place_id}/status")
async def update_lead_status(place_id: str, payload: dict):
    """Manually mark a lead as contacted or rejected from the UI."""
    status = payload.get("status")  # 'sent' or 'rejected'
    
    biz = get_business(place_id)
    if not biz:
        return {"error": "not found"}

    if status == "sent":
        biz["send_status"] = "sent"
        biz["approval_status"] = "approved"
    elif status == "rejected":
        biz["approval_status"] = "rejected"
    
    upsert_business(biz)

    return {"success": True, "send_status": biz["send_status"], "approval_status": biz["approval_status"]}


# ── WebSocket ────────────────────────────────────────────────────────────

@app.websocket("/ws/{run_id}")
async def websocket_endpoint(websocket: WebSocket, run_id: str):
    # Check cookie session first
    session_token = websocket.cookies.get("admin_session")
    if not (session_token and session_token in _sessions):
        # Fallback to HTTP Basic Auth
        auth_header = websocket.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Basic "):
            await websocket.close(code=4001, reason="Unauthorized")
            return
        try:
            encoded_creds = auth_header.split(" ", 1)[1]
            decoded_creds = base64.b64decode(encoded_creds).decode("utf-8")
            username, _, password = decoded_creds.partition(":")
            if not (secrets.compare_digest(username, ADMIN_USERNAME) and secrets.compare_digest(password, ADMIN_PASSWORD)):
                await websocket.close(code=4001, reason="Invalid credentials")
                return
        except Exception:
            await websocket.close(code=4001, reason="Invalid auth")
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


def _run_pipeline_thread(run_id: str, query: str, location: str,
                         radius: int, max_results: int):
    """Main pipeline execution — runs in a background thread."""
    run = _runs[run_id]

    # Step 1: Search Places API
    _broadcast(run_id, {
        "type": "search_start",
        "query": query,
        "location": location,
        "message": f"🎯 LAUNCHED CAMPAIGN: {query.upper()} in {location.upper()}"
    })
    _broadcast(run_id, {"type": "status", "message": f"Searching Google Maps for {query} in {location}..."})

    try:
        businesses = search_businesses(
            query=query, location=location,
            radius_meters=radius, max_results=max_results,
        )
    except QuotaExceededError as e:
        _broadcast(run_id, {"type": "error", "message": str(e)})
        run["status"] = "error"
        update_search_run(run_id, 0, "error")
        return
    except Exception as e:
        _broadcast(run_id, {"type": "error", "message": f"Search failed: {e}"})
        run["status"] = "error"
        update_search_run(run_id, 0, "error")
        return

    # Filter out 100% solid duplicate businesses before processing
    new_businesses = []
    for b in businesses:
        if is_business_already_processed(b["place_id"], b.get("name", "")):
            _broadcast(run_id, {
                "type": "skipped",
                "name": b.get("name", "Unknown"),
                "reason": "duplicate",
                "message": f"Skipping duplicate: {b.get('name')} (already processed in CRM)"
            })
        else:
            new_businesses.append(b)
    businesses = new_businesses

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

    # Step 2: Immediately store every found business in CRM + link to run
    for b in businesses:
        upsert_business({
            "place_id": b["place_id"],
            "name": b["name"],
            "address": b["address"],
            "phone": b.get("phone"),
            "category": b.get("category"),
            "website": b.get("website"),
            "rating": b.get("rating"),
            "review_count": b.get("review_count"),
            "approval_status": "pending",
            "send_status": "not_sent",
        })
        link_business_to_run(run_id, b["place_id"])

    # Step 3: Process each business through the enrichment pipeline
    with get_checkpointer_cm() as checkpointer:
        graph_app = build_graph(checkpointer)

        for i, business in enumerate(businesses):
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

    # In sniper mode, the pipeline finishes on its own. It doesn't pause.
    _broadcast(run_id, {
        "type": "drafted",
        "place_id": place_id,
        "name": name,
        "lead_score": score,
        "has_pitch": True,
    })


# ── Unsubscribe endpoint (public — no auth required) ────────────────────

@app.get("/api/unsubscribe/{place_id}")
async def handle_unsubscribe(place_id: str):
    """One-click unsubscribe endpoint linked in every outgoing email."""
    result = unsubscribe_business(place_id)
    name = result["name"] if result else "Unknown"
    logger.info(f"Unsubscribed: {name} (place_id={place_id})")
    # Return a simple, styled confirmation page
    return Response(
        content=f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Unsubscribed</title></head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    display: flex; justify-content: center; align-items: center; min-height: 100vh;
    background: #f5f5f5; margin: 0; color: #333;">
<div style="text-align: center; max-width: 400px; padding: 40px; background: white;
    border-radius: 12px; box-shadow: 0 2px 12px rgba(0,0,0,0.08);">
    <div style="font-size: 48px; margin-bottom: 16px;">✅</div>
    <h1 style="font-size: 20px; margin: 0 0 12px;">You've been unsubscribed</h1>
    <p style="color: #666; font-size: 14px; line-height: 1.5;">
        You won't receive any more emails from us. Sorry for the interruption.
    </p>
</div>
</body></html>""",
        media_type="text/html",
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
    import uvicorn
    print("\n  🗺️  Maps Outreach Agent (Sniper Mode)")
    print("  Dashboard: http://localhost:8000\n")
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")

