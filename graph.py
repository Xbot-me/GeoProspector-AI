"""
Builds the per-business LangGraph pipeline (Sniper Workflow):

  check_website
       |
       +---(good website)---> save_to_crm_skip -> END
       |
       +---(prospect)---> find_email -> find_socials -> score_lead -> analyze_business
                                                                             |
                                                                             v
                                                                      generate_pitch
                                                                             |
                                                                             v
                                                                       save_to_crm
                                                                             |
                                                                             v
                                                                            END

The pipeline no longer pauses for human approval or attempts to send emails.
It runs start-to-finish for all prospects, drafting pitches and saving to CRM
so the user can manually review and contact them via the dashboard.
"""
from langgraph.graph import END, StateGraph

from nodes.business_analyzer import analyze_business
from nodes.crm_writer import save_to_crm
from nodes.email_finder import find_email
from nodes.lead_scorer import score_lead
from nodes.pitch_generator import generate_pitch
from nodes.social_finder import find_socials
from nodes.website_check import check_website
from state import BusinessState


def _route_after_score(state: BusinessState) -> str:
    """Skip pitch generation if website is good, but keep all extracted data."""
    if state.get("website_quality") == "good":
        return "save_to_crm_skip"
    return "analyze_business"


def build_graph(checkpointer=None):
    graph = StateGraph(BusinessState)

    graph.add_node("check_website", check_website)
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
    graph.add_edge("check_website", "find_email")
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
