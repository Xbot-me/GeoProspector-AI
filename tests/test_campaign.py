import auto_campaign as ac


def test_default_cities_exclude_opt_in_countries():
    regions = {r.rsplit(",", 1)[-1].strip() for _, r in ac.active_cities()}
    assert regions <= {"USA", "Canada", "Australia"}
    assert regions  # not empty


def test_no_german_spanish_swiss_austrian_targets_by_default():
    cities = {c for c, _ in ac.active_cities()}
    assert not cities & {"Berlin", "Augsburg", "Madrid", "Santander", "Zurich", "Linz"}


def test_countries_are_configurable(monkeypatch):
    monkeypatch.setattr(ac, "OUTREACH_COUNTRIES", ["united kingdom"])
    cities = {c for c, _ in ac.active_cities()}
    assert "Manchester" in cities and "Boise" not in cities


def test_combinations_only_use_active_cities():
    allowed = {f"{c}, {r}" for c, r in ac.active_cities()}
    combos = ac.get_all_target_combinations()
    assert combos and all(c["location"] in allowed for c in combos)
