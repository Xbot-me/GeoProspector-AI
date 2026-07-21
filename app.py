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
import csv
import io
import json
import logging
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from threading import Thread

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from db import (
    get_all_leads, get_all_runs, get_business, get_businesses_for_run,
    init_db, link_business_to_run, save_search_run, update_search_run,
    upsert_business,
)
from graph import build_graph, get_checkpointer_cm
from nodes.places_search import search_businesses
from quota import QuotaExceededError
from config import MIN_LEAD_SCORE, GEMINI_API_KEY, GEMINI_MODEL

from google import genai
_gemini_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

logger = logging.getLogger(__name__)

# ── In-memory run tracking ──────────────────────────────────────────────
# Maps run_id -> {"status", "events": [...], "stats": {}}
_runs: dict[str, dict] = {}

# Maps run_id -> list of WebSocket connections listening to it
_ws_clients: dict[str, list[WebSocket]] = {}

STATIC_DIR = Path(__file__).parent / "static"


# ── Lifespan ────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Maps Outreach Agent", lifespan=lifespan)


# ── Static file serving ─────────────────────────────────────────────────
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
async def index():
    return FileResponse(str(STATIC_DIR / "index.html"))


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
async def start_search(payload: dict):
    """Start a pipeline run in the background."""
    query = payload.get("query", "").strip()
    location = payload.get("location", "").strip()
    radius = int(payload.get("radius", 5000))
    max_results = int(payload.get("max_results", 15))

    if not query or not location:
        return {"error": "query and location are required"}

    run_id = uuid.uuid4().hex[:12]

    # Persist the search run to DB immediately
    save_search_run(run_id, query, location, radius, max_results)

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
    _broadcast(run_id, {"type": "status", "message": "Searching Google Maps..."})

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

    _broadcast(run_id, {
        "type": "processing",
        "place_id": place_id,
        "name": name,
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
        run["stats"]["emails_found"] += 1

    # In sniper mode, the pipeline finishes on its own. It doesn't pause.
    _broadcast(run_id, {
        "type": "drafted",
        "place_id": place_id,
        "name": name,
        "lead_score": score,
        "has_pitch": True,
    })


# ── Entry point ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    print("\n  🗺️  Maps Outreach Agent (Sniper Mode)")
    print("  Dashboard: http://localhost:8000\n")
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
