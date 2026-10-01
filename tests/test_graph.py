import graph as g


def build(monkeypatch, quality):
    seen = []

    def node(name, update=None):
        def f(state):
            seen.append(name)
            return update or {}
        return f

    monkeypatch.setattr(g, "check_website", node("check_website", {"website_quality": quality}))
    monkeypatch.setattr(g, "audit_site", node("audit_site"))
    monkeypatch.setattr(g, "find_email", node("find_email"))
    monkeypatch.setattr(g, "find_socials", node("find_socials"))
    monkeypatch.setattr(g, "score_lead", node("score_lead"))
    monkeypatch.setattr(g, "analyze_business", node("analyze_business", {"analysis": "x"}))
    monkeypatch.setattr(g, "generate_pitch", node("generate_pitch", {"pitch_subject": "s", "pitch_body": "b"}))
    monkeypatch.setattr(g, "save_to_crm", node("save_to_crm"))
    app = g.build_graph()
    app.invoke({"place_id": "p1", "name": "n"})
    return seen


def test_prospect_gets_pitch(monkeypatch):
    seen = build(monkeypatch, "none")
    assert seen == ["check_website", "audit_site", "find_email", "find_socials", "score_lead",
                    "analyze_business", "generate_pitch", "save_to_crm"]


def test_good_site_is_saved_without_pitch(monkeypatch):
    seen = build(monkeypatch, "good")
    assert "generate_pitch" not in seen and seen[-1] == "save_to_crm"


def test_unknown_site_is_saved_without_pitch_or_llm_spend(monkeypatch):
    seen = build(monkeypatch, "unknown")
    assert "analyze_business" not in seen and "generate_pitch" not in seen
    assert seen[-1] == "save_to_crm"
