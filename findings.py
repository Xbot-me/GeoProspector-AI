"""
Plain-language description of the single most useful, verifiable thing we
found about a lead's web presence. Shared by the email drafter and the call
sheet so both lead with the same concrete fact.
"""


def describe_finding(state: dict) -> str:
    quality = state.get("website_quality")
    score = state.get("pagespeed_score")
    lcp = state.get("pagespeed_lcp")
    notes = state.get("website_notes") or ""

    if quality == "outdated" and score is not None:
        extra = f" and the main content takes {lcp} to appear" if lcp else ""
        return f"On a phone their website scores {score}/100 on Google PageSpeed{extra}."
    if quality == "outdated":
        return f"Their website has a visible problem: {notes}."
    if quality == "dead":
        return f"The website listed on their Google profile does not load ({notes})."
    if quality == "social_only":
        return "Their Google profile links to a social media or directory page instead of a website of their own."
    return "Their Google profile has no website listed, so customers who want to look them up or book online hit a dead end."
