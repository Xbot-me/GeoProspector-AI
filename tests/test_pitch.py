from nodes import pitch_generator as pg


def test_parse_full_format():
    text = "LANGUAGE: English\nSUBJECTS:\nQuestion about Joe's\nJoe's on Google\nHello\nBODY:\nHi Joe,\n\nHello there."
    lang, subs, body = pg.parse_response(text)
    assert lang == "English"
    assert subs == ["Question about Joe's", "Joe's on Google", "Hello"]
    assert body == "Hi Joe,\n\nHello there."


def test_parse_legacy_single_subject():
    lang, subs, body = pg.parse_response("LANGUAGE: Spanish\nSUBJECT: Hola\nBODY:\nCuerpo")
    assert lang == "Spanish" and subs == ["Hola"] and body == "Cuerpo"


def test_parse_garbage_falls_back_to_whole_text():
    lang, subs, body = pg.parse_response("just some text")
    assert lang == "English" and subs == [] and body == "just some text"


def test_pick_subject_prefers_plain_named_short():
    opts = ["1. AMAZING OFFER FOR YOU!", "- Quick question about Joe's Plumbing", "A very long and rambling subject line that goes on and on"]
    assert pg.pick_subject(opts, "Joe's Plumbing") == "Quick question about Joe's Plumbing"


def test_pick_subject_empty_uses_fallback():
    assert "Joe's" in pg.pick_subject([], "Joe's")
    assert pg.pick_subject([], "") == "Quick question"


def test_clean_body_removes_ai_tics():
    out = pg.clean_body("Great reviews — really!  \n\n\n\nCall me – anytime!")
    assert "—" not in out and "–" not in out and "!" not in out
    assert "\n\n\n" not in out


def test_signature_appended_once():
    body = pg._append_signature("Hi there.")
    assert body.endswith(pg.SENDER_SIGNATURE)
    assert pg._append_signature(body) == body


def test_signature_replaces_placeholder():
    out = pg._append_signature("Thanks,\n[Your Name]")
    assert "[Your Name]" not in out and pg.SENDER_WEBSITE in out


def test_examples_skip_comments(tmp_path):
    f = tmp_path / "e.txt"
    f.write_text("# a comment\nSubject: hi\n# another\nBody")
    assert pg.load_examples(f) == "Subject: hi\nBody"


def test_examples_missing_file(tmp_path):
    assert pg.load_examples(tmp_path / "nope.txt") == ""


def test_shipped_examples_load_and_are_clean():
    ex = pg.load_examples()
    assert "Subject:" in ex and "—" not in ex and "!" not in ex


STATE = {"name": "Joe's Plumbing", "address": "Boise, ID", "category": "plumber", "website_quality": "none",
         "rating": 4.8, "review_count": 212, "analysis": "- loses calls"}


def test_prompt_contains_finding_and_rules():
    p = pg.build_prompt(STATE)
    assert "no website listed" in p and "212 Google reviews" in p
    assert "No em dashes" in p and "Under 120 words" in p
    assert "Do NOT promise a free website or mockup" in p


def test_prompt_mockup_only_when_enabled(monkeypatch):
    monkeypatch.setattr(pg, "OFFER_FREE_MOCKUP", True)
    assert "free, no-obligation homepage mockup" in pg.build_prompt(STATE)


def test_prompt_language_modes(monkeypatch):
    assert "Write the whole email in English" in pg.build_prompt(STATE)
    monkeypatch.setattr(pg, "OUTREACH_LANGUAGE", "auto")
    assert "primary local language" in pg.build_prompt(STATE)


def test_prompt_measured_finding_for_slow_site():
    s = dict(STATE, website_quality="outdated", pagespeed_score=28, pagespeed_lcp="7.1 s")
    p = pg.build_prompt(s)
    assert "28/100" in p and "7.1 s" in p and "modernizing" in p


def test_generate_requires_key():
    import pytest
    with pytest.raises(RuntimeError):
        pg.generate_pitch(STATE)


def test_generate_end_to_end_with_fake_model(monkeypatch):
    class R:
        text = ("LANGUAGE: English\nSUBJECTS:\nQuestion about Joe's Plumbing\nHi\nHello again\nBODY:\n"
                "Hi Joe — your 212 reviews are great!\n\nCan I send ideas?")

    class M:
        def generate_content(self, model, contents):
            assert "no website listed" in contents
            return R()

    class C:
        models = M()

    monkeypatch.setattr(pg, "_client", C())
    out = pg.generate_pitch(STATE)
    assert out["pitch_subject"] == "Question about Joe's Plumbing"
    assert "—" not in out["pitch_body"] and "!" not in out["pitch_body"]
    assert out["pitch_body"].endswith(pg.SENDER_SIGNATURE)
    assert out["email_language"] == "English"
