"""
Builds the per-business LangGraph pipeline (Sniper Workflow):

  check_website -> audit_site -> find_email -> find_socials -> score_lead
                                                                  |
                       +----(good or unknown website)-------------+
                       |                                          |
                       v                                    (prospect)
                save_to_crm_skip -> END                           |
                                                                  v
                                                          analyze_business
                                                                  |
                                                                  v
                                                          generate_pitch
                                                                  |
                                                                  v
                                                            save_to_crm -> END

audit_site measures live sites with PageSpeed and can turn a "good" site into
a prospect when it is demonstrably slow. "unknown" sites (blocked our check or
timed out) are saved without a pitch so they can be looked at by hand.

The pipeline never sends email. It drafts pitches and saves them to the CRM;
a human approves each one in the dashboard before anything goes out.
"""
from langgraph.graph import END, StateGraph

from nodes.business_analyzer import analyze_business
from nodes.crm_writer import save_to_crm
from nodes.email_finder import find_email
from nodes.lead_scorer import score_lead
from nodes.pitch_generator import generate_pitch
from nodes.site_audit import audit_site
from nodes.social_finder import find_socials
from nodes.website_check import check_website
from state import BusinessState


def _route_after_score(state: BusinessState) -> str:
    """Skip pitch generation if the website is good or could not be checked,
    but keep all extracted data."""
    if state.get("website_quality") in ("good", "unknown"):
        return "save_to_crm_skip"
    return "analyze_business"


def build_graph(checkpointer=None):
    graph = StateGraph(BusinessState)

    graph.add_node("check_website", check_website)
    graph.add_node("audit_site", audit_site)
    graph.add_node("find_email", find_email)
    graph.add_node("find_socials", find_socials)
    graph.add_node("score_lead", score_lead)
    graph.add_node("analyze_business", analyze_business)
    graph.add_node("generate_pitch", generate_pitch)
    graph.add_node("save_to_crm_skip", save_to_crm)
    graph.add_node("save_to_crm", save_to_crm)

    # Entry point
    graph.set_entry_point("check_website")

    # Always enrich everyone
    graph.add_edge("check_website", "audit_site")
    graph.add_edge("audit_site", "find_email")
    graph.add_edge("find_email", "find_socials")
    graph.add_edge("find_socials", "score_lead")

    # Score gate: if good website, skip pitch. Else generate pitch.
    graph.add_conditional_edges(
        "score_lead",
        _route_after_score,
        {"analyze_business": "analyze_business", "save_to_crm_skip": "save_to_crm_skip"},
    )

    # Full pipeline
    graph.add_edge("analyze_business", "generate_pitch")
    graph.add_edge("generate_pitch", "save_to_crm")
    
    # End points
    graph.add_edge("save_to_crm_skip", END)
    graph.add_edge("save_to_crm", END)

    return graph.compile(checkpointer=checkpointer)


from contextlib import contextmanager
from langgraph.checkpoint.postgres import PostgresSaver
from config import DATABASE_URL

@contextmanager
def get_checkpointer_cm():
    """Returns the PostgresSaver context manager and ensures checkpointer tables are initialized."""
    with PostgresSaver.from_conn_string(DATABASE_URL) as checkpointer:
        checkpointer.setup()
        yield checkpointer
