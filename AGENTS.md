# AGENTS.md

## Stack
- Docker, Docker Compose, Python 3.11 (pip, FastAPI, LangGraph, Uvicorn, PostgreSQL / SQLite)

## Context files
- See `.ai/architecture.md` for a generated architecture map.
- See `.ai/context-index.json` for the ranked file index (machine-readable).

## Build & Test Commands
- **Local Dev Server**: `./venv/bin/python -m uvicorn app:app --reload --port 8000`
- **Docker Build & Deploy**: `docker compose build --no-cache && docker compose up -d`
- **Python Syntax Check**: `./venv/bin/python -c "import app, db, auto_campaign"`

## Conventions & Rules
- **Catalog Location**: Curated target catalog dataset lives at [`catalog/target_catalog.json`](file:///Users/xbot-me/Desktop/github-projects/maps-outreach-agent/catalog/target_catalog.json). Do NOT move it into `data/` because `maps_outreach_data:/app/data` is a mounted Docker volume.
- **Database Auto-Migrations**: New columns must be declared in `_ALL_FIELDS` and `_MIGRATION_COLUMNS` in [`db.py`](file:///Users/xbot-me/Desktop/github-projects/maps-outreach-agent/db.py) so `init_db()` auto-migrates them safely via `ALTER TABLE businesses ADD COLUMN IF NOT EXISTS`.
- **Deduplication Policy**: [`is_business_already_processed()`](file:///Users/xbot-me/Desktop/github-projects/maps-outreach-agent/db.py#L383) only skips leads that have actually been sent (`send_status == 'sent'`) or unsubscribed (`send_status == 'unsubscribed'`). Uncontacted leads are never skipped as duplicates.
- **Error Telemetry**: Pipeline exceptions in `_run_pipeline_thread` must be broadcast as `{"type": "error", "message": ...}` to the WebSocket feed rather than silently masked as `"complete"`.
