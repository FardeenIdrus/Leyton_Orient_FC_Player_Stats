"""The league registry (owner, 2026-10-26): one line per COMPETITION, everything else derived.

Before: 21 hand-typed ImpectTarget entries (one per league per season, ids chosen by hand),
league names repeated in report/data.py and the dashboard, season labels in four modules.
Adding 25+ competitions that way means ~75 more hand-typed entries and many places to miss.

After: `leagues.LEAGUES` lists each competition once; the seasons come from Impect's own
catalogue (getIterations), ids follow fixed rules, and names/labels are read from here.
The existing 7 competitions KEEP their ids, so no stored row changes -- pinned below by
reproducing today's 21 targets exactly.
"""

import pytest

from lofc import leagues as L
from lofc.config import DEFAULT_IMPECT_TARGETS


# --- seasons: one rule instead of four lookup tables ----------------------------------

@pytest.mark.parametrize("label,season_id", [("24/25", 317), ("25/26", 318), ("26/27", 319),
                                             ("27/28", 320), ("23/24", 316)])
def test_season_ids_follow_one_rule(label, season_id):
    assert L.season_id_for(label) == season_id


def test_season_labels_long_and_short():
    assert L.season_label(318) == "2025/26"
    assert L.season_label(318, short=True) == "25/26"
    assert L.season_label(320) == "2027/28"


@pytest.mark.parametrize("label,season_id", [("2024", 317), ("2025", 318), ("2026", 319)])
def test_a_calendar_year_season_is_the_season_starting_that_year(label, season_id):
    """Owner, 2026-10-26: "2026" (Mar-Nov, being played now) files under 2026/27, the live
    season; "2025" under 2025/26. Japan's switch from "2025" to "26/27" stays consistent."""
    assert L.season_id_for(label) == season_id


@pytest.mark.parametrize("bad", ["spring", "25/27", "2025/26", "", "19999"])
def test_other_season_labels_are_refused(bad):
    with pytest.raises(ValueError):
        L.season_id_for(bad)


# --- competitions -------------------------------------------------------------------------

def test_the_seven_original_competitions_keep_their_ids():
    ids = {c.name: c.competition_id for c in L.LEAGUES if c.competition_id < L.NEW_ID_BASE}
    assert ids == {"Championship": 3, "League One": 4, "League Two": 5, "National League": 65,
                   "Scottish Premiership": 901, "Scottish Championship": 902,
                   "Premier League 2": 903}


def test_competition_ids_and_impect_ids_are_unique():
    assert len({c.competition_id for c in L.LEAGUES}) == len(L.LEAGUES)
    assert len({c.impect_competition_id for c in L.LEAGUES}) == len(L.LEAGUES)


def test_a_new_competition_gets_its_id_by_rule():
    assert L.new_competition_id(8) == 10_008          # Impect's Premier League
    assert L.new_competition_id(8) not in {c.competition_id for c in L.LEAGUES}


def test_league_names_come_from_the_registry():
    assert L.league_name(4) == "League One"
    assert L.league_name(903) == "Premier League 2"
    assert L.league_name(12345) == "Competition 12345"


# --- targets from Impect's catalogue -------------------------------------------------------

def _row(iteration, comp_id, comp_name, season):
    return {"id": iteration, "competitionId": comp_id, "competitionName": comp_name,
            "season": season}


# The licence catalogue as Impect returned it on 2026-10-26, for our 7 competitions,
# plus seasons and competitions that must be IGNORED.
CATALOGUE = [
    _row(1022, 41, "Championship", "24/25"), _row(1410, 41, "Championship", "25/26"),
    _row(2114, 41, "Championship", "26/27"), _row(728, 41, "Championship", "23/24"),
    _row(1023, 133, "League One", "24/25"), _row(1465, 133, "League One", "25/26"),
    _row(2117, 133, "League One", "26/27"),
    _row(1021, 180, "League Two", "24/25"), _row(1464, 180, "League Two", "25/26"),
    _row(2120, 180, "League Two", "26/27"),
    _row(1062, 341, "National League", "24/25"), _row(1511, 341, "National League", "25/26"),
    _row(2125, 341, "National League", "26/27"),
    _row(1033, 35, "Scottish Premiership", "24/25"), _row(1400, 35, "Scottish Premiership", "25/26"),
    _row(2156, 35, "Scottish Premiership", "26/27"),
    _row(1221, 281, "Scottish Championship", "24/25"),
    _row(1474, 281, "Scottish Championship", "25/26"),
    _row(2157, 281, "Scottish Championship", "26/27"),
    _row(1076, 52, "Premier League 2", "24/25"), _row(1529, 52, "Premier League 2", "25/26"),
    _row(2232, 52, "Premier League 2", "26/27"),
    _row(1381, 8, "Premier League", "25/26"),            # licensed, not in the registry
    _row(1241, 189, "Irish Premier Division", "2025"),   # in the registry since 2026-10-26
    _row(1514, 40, "EFL Cup", "25/26"),                  # licensed, deliberately left out
]


def _key(t):
    return (t.iteration_id, t.label, t.sb_competition_id, t.sb_season_id, t.competition_id,
            t.season_id, t.spine_source)


def test_the_catalogue_reproduces_todays_21_targets_exactly():
    """THE safety test: nothing about the existing leagues changes."""
    original = {3, 4, 5, 65, 901, 902, 903}
    derived = [t for t in L.targets_from_catalogue(CATALOGUE) if t.competition_id in original]
    assert sorted(map(_key, derived)) == sorted(map(_key, DEFAULT_IMPECT_TARGETS))


def test_seasons_before_the_first_season_are_ignored():
    assert 728 not in {t.iteration_id for t in L.targets_from_catalogue(CATALOGUE)}


def test_competitions_not_in_the_registry_are_ignored():
    ids = {t.iteration_id for t in L.targets_from_catalogue(CATALOGUE)}
    assert 1381 not in ids and 1514 not in ids and 1241 in ids


def test_a_new_season_arrives_without_a_code_change():
    rows = CATALOGUE + [_row(2999, 133, "League One", "27/28")]
    new = next(t for t in L.targets_from_catalogue(rows) if t.iteration_id == 2999)
    assert (new.competition_id, new.season_id, new.label, new.spine_source) == \
        (4, 320, "League One 2027/28", "impect")


def test_a_new_competition_needs_one_registry_line():
    extra = L.Competition("Premier League", impect_competition_id=8,
                          competition_id=L.new_competition_id(8))
    t = L.targets_from_catalogue(CATALOGUE, leagues=L.LEAGUES + [extra])
    pl = next(x for x in t if x.iteration_id == 1381)
    assert (pl.competition_id, pl.season_id, pl.label, pl.spine_source) == \
        (10_008, 318, "Premier League 2025/26", "impect")


def test_an_excluded_competition_is_skipped():
    off = [L.Competition(c.name, c.impect_competition_id, c.competition_id,
                         c.statsbomb_seasons, include=(c.name != "League Two"))
           for c in L.LEAGUES]
    ids = {t.competition_id for t in L.targets_from_catalogue(CATALOGUE, leagues=off)}
    assert 5 not in ids


# --- wiring: everything reads the registry ---------------------------------------------

def test_settings_derive_targets_from_the_landed_catalogue(tmp_path, monkeypatch):
    import json
    from lofc.config import Settings
    from lofc.ingest import impect as impect_ingest
    cat = tmp_path / "iterations.json"
    cat.write_text(json.dumps(CATALOGUE + [_row(2999, 133, "League One", "27/28")]))
    monkeypatch.setattr(impect_ingest, "iterations_catalogue_path", lambda: cat)
    ids = {t.iteration_id for t in Settings(_env_file=None).impect_targets}
    assert 2999 in ids and 1241 in ids and len(ids) == 23   # 21 + Irish 2025 + League One 27/28


def test_without_a_catalogue_the_previous_list_is_the_fallback(tmp_path, monkeypatch):
    from lofc.config import Settings
    from lofc.ingest import impect as impect_ingest
    monkeypatch.setattr(impect_ingest, "iterations_catalogue_path", lambda: tmp_path / "none.json")
    assert Settings(_env_file=None).impect_targets == DEFAULT_IMPECT_TARGETS


def test_the_dashboard_and_report_name_leagues_and_seasons_from_the_registry():
    from lofc.dashboard.seasons import season_name_for
    from lofc.report import data as report_data
    assert season_name_for(320) == "2027/28"
    assert report_data.league_name(903) == "Premier League 2"
    assert report_data.season_short(318) == "25/26"


def test_an_id_that_is_not_a_season_is_not_dressed_up_as_one():
    """999 is not a season: show the raw id, never an invented '2706/07'."""
    assert not L.is_season_id(999) and L.is_season_id(318)
    from lofc.dashboard.seasons import season_name_for
    assert season_name_for(999) == "999"


def test_the_impect_pull_reads_the_fresh_catalogue_before_choosing_what_to_pull(tmp_path, monkeypatch):
    """A new season must be pulled on the run that first sees it, not a week later."""
    import sys
    import impectPy
    import pandas as pd
    from lofc.ingest import impect as ing
    cat = tmp_path / "iterations.json"
    monkeypatch.setattr(ing, "iterations_catalogue_path", lambda: cat)
    monkeypatch.setattr(ing, "_token", lambda: "t")
    fresh = pd.DataFrame(CATALOGUE + [_row(2999, 133, "League One", "27/28")])
    calls = {"n": 0}

    def flaky_catalogue(token):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ConnectionError("blip")          # transient: must be retried
        return fresh
    monkeypatch.setattr(impectPy, "getIterations", flaky_catalogue)
    monkeypatch.setattr("lofc.ingest.retry.time.sleep", lambda s: None, raising=False)
    pulled = []
    monkeypatch.setattr(ing, "pull_iteration", lambda t, tok, force=False: pulled.append(t.iteration_id) or False)
    monkeypatch.setattr(ing, "pull_scores", lambda t, tok, force=False: False)
    monkeypatch.setattr(sys, "argv", ["impect"])
    ing.main()
    assert 2999 in pulled and calls["n"] == 2


def test_an_unparseable_season_is_skipped_not_fatal(capsys):
    """One competition's odd season label must not stop every other league's run."""
    rows = CATALOGUE + [_row(9999, 41, "Championship", "spring")]
    ids = {t.iteration_id for t in L.targets_from_catalogue(rows)}
    assert 9999 not in ids and len(ids) == 22
    assert "spring" in capsys.readouterr().out


def test_a_damaged_catalogue_falls_back_with_a_warning(tmp_path, monkeypatch, capsys):
    from lofc.config import Settings
    from lofc.ingest import impect as impect_ingest
    cat = tmp_path / "iterations.json"
    cat.write_text("{not json")
    monkeypatch.setattr(impect_ingest, "iterations_catalogue_path", lambda: cat)
    assert Settings(_env_file=None).impect_targets == DEFAULT_IMPECT_TARGETS
    assert "catalogue" in capsys.readouterr().out.lower()


# --- the 18 new competitions (owner, 2026-10-26) ---------------------------------------------

NEW = {348: "A-League Men", 239: "Challenger Pro League", 91: "Fortuna Liga", 15: "Superligaen",
       66: "Ligue 2", 439: "Ligue 3", 233: "Nemzeti Bajnokság", 305: "NIFL Premiership",
       93: "Niké Liga", 168: "South African Premier Division", 243: "Veikkausliiga",
       189: "Irish Premier Division", 97: "J1 League", 262: "J2 League", 96: "K League 1",
       62: "Eliteserien", 47: "Allsvenskan", 56: "USL Championship"}


def test_the_registry_holds_the_7_existing_and_18_new_competitions():
    by_impect = {c.impect_competition_id: c for c in L.LEAGUES}
    assert len(L.LEAGUES) == 25
    for impect_id, name in NEW.items():
        c = by_impect[impect_id]
        assert c.name.startswith(name) and c.competition_id == L.new_competition_id(impect_id)
        assert c.include and not c.statsbomb_seasons


def test_the_efl_cup_is_not_ingested():
    """A cup: few games per player, so almost nobody reaches 450 minutes."""
    assert 40 not in {c.impect_competition_id for c in L.LEAGUES}


def test_japan_switching_from_calendar_to_split_seasons_stays_consistent():
    rows = [_row(1, 97, "J1 League", "2024"), _row(2, 97, "J1 League", "2025"),
            _row(3, 97, "J1 League", "26/27")]
    got = {t.iteration_id: t.season_id for t in L.targets_from_catalogue(rows)}
    assert got == {1: 317, 2: 318, 3: 319}


def test_two_iterations_landing_on_one_season_keep_the_newest_and_warn(capsys):
    """A calendar "2026" and a split "26/27" of one competition would collide on 319."""
    rows = [_row(10, 97, "J1 League", "2026"), _row(11, 97, "J1 League", "26/27")]
    got = [t.iteration_id for t in L.targets_from_catalogue(rows)]
    assert got == [11]
    assert "J1 League" in capsys.readouterr().out
