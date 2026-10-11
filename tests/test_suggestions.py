import pytest

import suggestions as sg


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    sg._recent.clear()
    monkeypatch.setattr(sg.llm, "available", lambda: False)


def executed_for(pairs):
    return lambda: ({(sg._norm(n), sg._norm(loc)) for n, loc in pairs}, [f"{n} in {loc}" for n, loc in pairs])


def test_catalog_bundle_never_repeats_searched_niches(monkeypatch):
    done = [(n, "Bend, Oregon, USA") for n in sg.HOME_SERVICE_NICHES[:-1]]
    monkeypatch.setattr(sg, "executed_targets", executed_for(done))
    for _ in range(30):
        s = sg.suggest_bundle()
        assert sg.MIN_NICHES - 1 <= len(s["niches"]) <= sg.MAX_NICHES
        for n in s["niches"]:
            assert (sg._norm(n), sg._norm(s["location"])) not in {(sg._norm(a), sg._norm(b)) for a, b in done}


def test_consecutive_clicks_give_different_bundles(monkeypatch):
    monkeypatch.setattr(sg, "executed_targets", executed_for([]))
    seen = {(s["location"], frozenset(s["niches"])) for s in (sg.suggest_bundle() for _ in range(10))}
    assert len(seen) == 10
    s = sg.suggest_bundle()
    assert s["query"] == ", ".join(s["niches"])


def test_gemini_answer_filtered_against_history(monkeypatch):
    monkeypatch.setattr(sg, "executed_targets", executed_for([("Roofers", "Boise, Idaho, USA")]))
    monkeypatch.setattr(sg.llm, "available", lambda: True)
    monkeypatch.setattr(sg.llm, "generate_json", lambda prompt, temperature=None: {
        "location": "Boise, Idaho, USA", "niches": ["Roofers", "Gutter Installers", "Siding Contractors"]})
    s = sg.suggest_bundle()
    assert s["source"] == "gemini" and s["niches"] == ["Gutter Installers", "Siding Contractors"]


def test_gemini_repeat_or_failure_falls_back_to_catalog(monkeypatch):
    monkeypatch.setattr(sg, "executed_targets", executed_for([("Roofers", "Boise, Idaho, USA")]))
    monkeypatch.setattr(sg.llm, "available", lambda: True)
    monkeypatch.setattr(sg.llm, "generate_json", lambda prompt, temperature=None: {
        "location": "Boise, Idaho, USA", "niches": ["Roofers"]})  # only an already-searched niche
    assert sg.suggest_bundle()["source"] == "catalog"

    def boom(prompt, temperature=None):
        raise RuntimeError("429")
    monkeypatch.setattr(sg.llm, "generate_json", boom)
    assert sg.suggest_bundle()["source"] == "catalog"
