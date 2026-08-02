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
    upsert_business, record_email_open,
    get_email_logs, clear_email_logs, is_business_already_processed,
    unsubscribe_business, add_to_suppression, get_suppression_list, record_email_sent, retry_failed_emails,
)
from email_sender import send_email
from auto_campaign import get_next_campaign_target
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


STATIC_DIR = Path(__file__).parent / "static"


# ── Lifespan ────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
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


@app.post("/api/email-logs/retry-failed")
async def retry_failed_endpoint():
    count = retry_failed_emails()
    _scheduler_state["last_error"] = None
    # Recalculate scheduled count
    pending = get_pending_auto_send_leads(limit=100)
    _scheduler_state["scheduled_count"] = len(pending)
    return {"success": True, "requeued_count": count, "scheduled_count": len(pending)}


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
    """Suggest a fresh target location + niche using the curated 118-location catalog first, Gemini fallback second."""
    target = get_next_campaign_target()
    
    # Check if target from catalog is un-executed
    try:
        with get_conn() as conn:
            rows = conn.execute("SELECT query, location FROM search_runs").fetchall()
            executed = {(r["query"].lower().strip(), r["location"].lower().strip()) for r in rows}
    except Exception:
        executed = set()

    target_key = (target["query"].lower().strip(), target["location"].lower().strip())
    if target_key not in executed:
        return {"query": target["query"], "location": target["location"]}

    # Entire catalog exhausted -> Fallback to Gemini prompt
    if _gemini_client:
        recent_list = list(executed)[-10:] if executed else []
        prompt = (
            "I run a web design agency building sites for local business owners. "
            "Suggest ONE specific city in the US, UK, Canada, Australia, or Europe. "
            f"CRITICAL: Do NOT suggest any of these already searched locations: {json.dumps(recent_list)}. "
            "Format output as raw JSON with no markdown:\n"
            '{"query": "local businesses", "location": "Austin, Texas, USA"}'
        )
        try:
            resp = _gemini_client.models.generate_content(model=GEMINI_MODEL, contents=prompt)
            text = resp.text.strip()
            if text.startswith("```json"): text = text[7:]
            if text.startswith("```"): text = text[3:]
            if text.endswith("```"): text = text[:-3]
            data = json.loads(text.strip())
            if data.get("query") and data.get("location"):
                return data
        except Exception as e:
            logger.warning(f"Gemini target suggestion fallback: {e}")

    return {"query": target["query"], "location": target["location"]}


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


@app.post("/api/leads/{place_id}/build-kit")
async def build_outreach_kit_endpoint(place_id: str):
    """Generate an outreach kit (analysis, mockup prompt, email draft) for a single lead."""
    from nodes.outreach_kit_generator import generate_outreach_kit
    biz = get_business(place_id)
    if not biz:
        return Response(status_code=404, content="Lead not found")
    
    try:
        kit = generate_outreach_kit(biz)
        biz.update(kit)
        upsert_business(biz)
        return biz
    except Exception as e:
        logger.error(f"Error generating outreach kit for {place_id}: {e}")
        return Response(status_code=500, content=f"Error generating kit: {str(e)}")


@app.post("/api/leads/{place_id}/status")
async def update_lead_status(place_id: str, payload: dict):
    """Manually update lead status (e.g. 'sent' or 'not_sent') or draft content."""
    status = payload.get("status")  # 'sent' or 'not_sent' or 'rejected'
    
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
                place_id = business["place_id"]
                name = business["name"]

                # Check if already contacted/sent
                if is_business_already_processed(place_id, name):
                    _broadcast(run_id, {
                        "type": "skipped",
                        "name": name,
                        "reason": "duplicate",
                        "message": f"Already contacted: {name}"
                    })
                    continue

                # Check if already enriched in CRM (has lead_score or website_quality)
                existing = get_business(place_id)
                if existing and existing.get("lead_score") is not None:
                    quality = existing.get("website_quality")
                    score = existing.get("lead_score")
                    email = existing.get("email")

                    if quality == "good":
                        run["stats"]["good_website"] += 1
                    else:
                        run["stats"]["qualified"] += 1
                        if email:
                            run["stats"]["emails_found"] += 1

                    _broadcast(run_id, {
                        "type": "drafted",
                        "place_id": place_id,
                        "name": name,
                        "lead_score": score,
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
        logger.error(f"Error during pipeline execution for run {run_id}: {e}")
        run["status"] = "complete"  # Still mark complete if leads were saved
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

