"""
CLI entry point.

Example:
    python main.py --query "coffee shops" --location "Comilla, Bangladesh" \\
        --radius 5000 --max-results 15
"""
import argparse
import sys
import uuid

from langgraph.types import Command

from config import MIN_LEAD_SCORE
from db import already_processed, init_db
from graph import build_graph, get_checkpointer_cm
from nodes.places_search import search_businesses
from quota import QuotaExceededError


# Run-level counters for the summary
_stats = {
    "found": 0,
    "good_website": 0,
    "low_score": 0,
    "qualified": 0,
    "emails_found": 0,
    "approved": 0,
    "sent": 0,
    "skipped_prev": 0,
}


def prompt_for_decision(payload: dict) -> dict:
    print("\n" + "=" * 60)
    print(f"Business:  {payload['name']}")
    print(f"Email:     {payload['email'] or '(none found)'}")
    print(f"Score:     {payload.get('lead_score', '?')}/100")
    print(f"Website:   {payload.get('website_quality', '?')}")
    if payload.get("facebook_url"):
        print(f"Facebook:  {payload['facebook_url']}")
    if payload.get("instagram_url"):
        print(f"Instagram: {payload['instagram_url']}")
    if payload.get("owner_name"):
        print(f"Contact:   {payload['owner_name']}")
    print(f"Subject:   {payload['pitch_subject']}")
    print("-" * 60)
    print(payload["pitch_body"])
    print("=" * 60)

    if not payload["email"]:
        print("No email address found for this business -- can't send by "
              "email. Consider phone/social outreach instead.")
        return {"action": "skip"}

    choice = input("[a]pprove  [e]dit  [r]eject  [s]kip this business: ").strip().lower()

    if choice == "a":
        return {"action": "approve"}
    if choice == "e":
        print("Enter new subject (blank = keep current):")
        new_subject = input("> ").strip()
        print("Enter new body (blank = keep current, single line only for this CLI):")
        new_body = input("> ").strip()
        return {
            "action": "edit",
            "pitch_subject": new_subject or None,
            "pitch_body": new_body or None,
        }
    if choice == "s":
        return {"action": "skip"}
    return {"action": "reject"}


def run_pipeline_for_business(app, business: dict) -> None:
    thread_id = f"biz-{business['place_id']}-{uuid.uuid4().hex[:8]}"
    config = {"configurable": {"thread_id": thread_id}}

    result = app.invoke(business, config=config)

    # Check for early exits (good website or low score)
    quality = result.get("website_quality")
    score = result.get("lead_score")

    if quality == "good":
        _stats["good_website"] += 1
        print(f"  [{business['name']}] -> skipped (good website)")
        return

    if score is not None and score < MIN_LEAD_SCORE:
        _stats["low_score"] += 1
        print(f"  [{business['name']}] -> skipped (score {score} < {MIN_LEAD_SCORE})")
        return

    _stats["qualified"] += 1
    if result.get("email"):
        _stats["emails_found"] += 1

    # If the graph paused on interrupt(), result contains "__interrupt__"
    while "__interrupt__" in result:
        payload = result["__interrupt__"][0].value
        decision = prompt_for_decision(payload)
        result = app.invoke(Command(resume=decision), config=config)

    status = result.get("send_status", "not_sent")
    if status == "sent":
        _stats["sent"] += 1
    if result.get("approval_status") == "approved":
        _stats["approved"] += 1

    print(f"  [{business['name']}] -> {status}")


def _print_summary():
    print("\n")
    print("═" * 50)
    print("  Run Summary")
    print("═" * 50)
    print(f"  Businesses found:      {_stats['found']:>4}")
    print(f"  Already processed:     {_stats['skipped_prev']:>4}  (skipped)")
    print(f"  Have good website:     {_stats['good_website']:>4}  (skipped)")
    print(f"  Low score (< {MIN_LEAD_SCORE}):     {_stats['low_score']:>4}  (skipped)")
    print(f"  Qualified leads:       {_stats['qualified']:>4}")
    print(f"  Emails discovered:     {_stats['emails_found']:>4}")
    print(f"  Pitches approved:      {_stats['approved']:>4}")
    print(f"  Emails sent:           {_stats['sent']:>4}")
    print("═" * 50)


def main():
    parser = argparse.ArgumentParser(description="Find businesses without websites and pitch them.")
    parser.add_argument("--query", required=True, help='e.g. "coffee shops"')
    parser.add_argument("--location", required=True, help='e.g. "Comilla, Bangladesh"')
    parser.add_argument("--radius", type=int, default=5000, help="meters, informational only for Text Search")
    parser.add_argument("--max-results", type=int, default=15)
    args = parser.parse_args()

    init_db()

    try:
        businesses = search_businesses(
            query=args.query,
            location=args.location,
            radius_meters=args.radius,
            max_results=args.max_results,
        )
    except QuotaExceededError as e:
        print(f"Quota guard stopped this run: {e}")
        sys.exit(1)

    _stats["found"] = len(businesses)
    print(f"Found {len(businesses)} businesses. Processing one at a time...\n")

    with get_checkpointer_cm() as checkpointer:
        app = build_graph(checkpointer)

        for business in businesses:
            if already_processed(business["place_id"]):
                _stats["skipped_prev"] += 1
                print(f"  [{business['name']}] already emailed previously, skipping.")
                continue
            run_pipeline_for_business(app, business)

    _print_summary()


if __name__ == "__main__":
    main()
