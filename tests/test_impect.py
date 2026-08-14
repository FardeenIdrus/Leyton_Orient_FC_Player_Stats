"""Tests for the Impect ingest + validation logic. No network, no database.

Covers the parts that would silently corrupt results if wrong: the env target
parsing, the average*matchShare season-total reconstruction, and the player
matching (Transfermarkt id first, birth-date+name fallback, and the guard that
a shared birthday with a different name is NOT a match).
"""

import pandas as pd
import pytest

from lofc.config import (DEFAULT_IMPECT_TARGETS, Settings, parse_impect_targets)
from lofc.model.impect_check import aggregate_players, compare_goals, match_to_ours


# --- config / target parsing ---------------------------------------------------

def test_default_targets_cover_three_seasons_of_seven_leagues():
    """8 EFL (StatsBomb-mapped) + 6 added, for 2024/25-2025/26, plus all 7 leagues for the
    live 2026/27 season."""
    labels = [t.label for t in DEFAULT_IMPECT_TARGETS]
    assert len(DEFAULT_IMPECT_TARGETS) == 21
    historical = [t for t in DEFAULT_IMPECT_TARGETS if t.season_id in {317, 318}]
    efl = [t for t in historical if t.sb_competition_id is not None]
    added = [t for t in historical if t.sb_competition_id is None]
    assert len(efl) == 8 and len(added) == 6
    assert any("Scottish Premiership" in l for l in labels)
    assert any("Premier League 2" in l for l in labels)


def test_live_season_covers_every_league_on_the_impect_spine():
    """A league missing from the live season would silently stop updating in-season."""
    live = [t for t in DEFAULT_IMPECT_TARGETS if t.season_id == 319]
    assert len(live) == 7
    assert {t.competition_id for t in live} == {3, 4, 5, 65, 901, 902, 903}
    # There is no StatsBomb 2026/27, so every live target must be Impect-spined.
    assert all(t.spine_source == "impect" for t in live)
    assert all(t.sb_competition_id is None for t in live)


def test_efl_targets_are_statsbomb_spined_with_keys_from_statsbomb():
    efl = [t for t in DEFAULT_IMPECT_TARGETS if t.sb_competition_id is not None]
    assert all(t.spine_source == "statsbomb" for t in efl)
    # our internal keys default to the StatsBomb ids for EFL leagues
    assert all(t.competition_id == t.sb_competition_id
               and t.season_id == t.sb_season_id for t in efl)


def test_added_leagues_are_impect_spined_with_minted_keys():
    """The non-EFL leagues added in Phase 11 (historical seasons only; the live 2026/27
    season is covered by its own test, where the EFL is Impect-spined too)."""
    added = [t for t in DEFAULT_IMPECT_TARGETS
             if t.sb_competition_id is None and t.season_id in {317, 318}]
    assert all(t.spine_source == "impect" for t in added)
    # minted competition ids in the 900s, season ids reuse the EFL era convention
    assert all(t.competition_id in {901, 902, 903} for t in added)
    assert all(t.season_id in {317, 318} for t in added)
    assert {t.competition_id for t in added} == {901, 902, 903}   # 3 leagues x 2 seasons


def test_competition_name_strips_the_season():
    t = next(x for x in DEFAULT_IMPECT_TARGETS if x.label == "Scottish Premiership 2025/26")
    assert t.competition_name == "Scottish Premiership"


def test_parse_impect_targets_keeps_known_statsbomb_mapping():
    # A known iteration id (League One 25/26 = 1465) keeps its SB mapping.
    targets = parse_impect_targets("1465:League One 2025/26")
    assert targets[0].iteration_id == 1465
    assert targets[0].sb_competition_id == 4 and targets[0].sb_season_id == 318


def test_parse_impect_targets_unknown_id_has_no_mapping():
    targets = parse_impect_targets("999999:Some New League 2025/26")
    assert targets[0].sb_competition_id is None


def test_parse_impect_targets_rejects_malformed():
    with pytest.raises(ValueError):
        parse_impect_targets("1465")          # no label
    with pytest.raises(ValueError):
        parse_impect_targets("abc:League")    # non-integer id
    with pytest.raises(ValueError):
        parse_impect_targets("   ")           # nothing usable


def test_impect_targets_override_via_env(monkeypatch):
    monkeypatch.delenv("IMPECT_ITERATIONS", raising=False)
    s = Settings(_env_file=None, impect_iterations="1465:League One 2025/26")
    assert [t.iteration_id for t in s.impect_targets] == [1465]
    # Unset falls back to the full default set (3 seasons across the seven leagues).
    assert len(Settings(_env_file=None).impect_targets) == len(DEFAULT_IMPECT_TARGETS)


def test_impect_authenticated_needs_both_credentials(monkeypatch):
    # The running container has real IMPECT_* vars; strip them so the assertion
    # about "no credentials -> not authenticated" holds everywhere.
    for var in ("IMPECT_USERNAME", "IMPECT_PASSWORD", "IMPECT_ITERATIONS"):
        monkeypatch.delenv(var, raising=False)
    assert Settings(_env_file=None).impect_authenticated is False
    assert Settings(_env_file=None, impect_username="u").impect_authenticated is False
    assert Settings(_env_file=None, impect_username="u",
                    impect_password="p").impect_authenticated is True


# --- season-total reconstruction ----------------------------------------------

def _impect_frame(rows):
    """Minimal landed-frame shape: one row per player-position."""
    return pd.DataFrame(rows)


def test_aggregate_sums_average_times_matchshare_across_positions():
    # A player who split a season between two positions. Season goals =
    # 0.6*30 + 0.0*5 = 18; the dominant position is the one with more matchShare.
    frame = _impect_frame([
        {"playerId": 1, "playerName": "Test Striker", "squadName": "Club",
         "birthdate": "2000-01-01", "transfermarktId": "555", "position": "CENTER_FORWARD",
         "matchShare": 30.0, "GOALS": 0.6, "ASSISTS": 0.1, "SHOT_XG": 0.5},
        {"playerId": 1, "playerName": "Test Striker", "squadName": "Club",
         "birthdate": "2000-01-01", "transfermarktId": "555", "position": "LEFT_WINGER",
         "matchShare": 5.0, "GOALS": 0.0, "ASSISTS": 0.0, "SHOT_XG": 0.0},
    ])
    players = aggregate_players(frame)
    assert len(players) == 1
    row = players.iloc[0]
    assert row["total_goals"] == pytest.approx(18.0)
    assert row["total_assists"] == pytest.approx(3.0)
    assert row["dominant_position"] == "CENTER_FORWARD"   # 30 > 5 matchShare
    assert row["tm_player_id"] == 555


# --- matching ------------------------------------------------------------------

def _ours():
    return pd.DataFrame([
        {"player_id": 100, "player_name": "Dominic Ballard",
         "birth_date": "2005-04-01", "tm_player_id": 555},
        {"player_id": 200, "player_name": "Someone Else",
         "birth_date": "1999-09-09", "tm_player_id": None},
    ])


def test_match_prefers_transfermarkt_id():
    impect = pd.DataFrame([{"playerId": 1, "player_name": "Dom Ballard",
                            "birth_date": pd.Timestamp("2005-04-01"), "tm_player_id": 555}])
    out = match_to_ours(impect, _ours())
    assert out.at[0, "player_id"] == 100
    assert out.at[0, "matched_via"] == "tm_id"


def test_match_falls_back_to_dob_and_name():
    # No TM id, but birth date + a close name should still match player 200.
    impect = pd.DataFrame([{"playerId": 2, "player_name": "Someone Else",
                            "birth_date": pd.Timestamp("1999-09-09"), "tm_player_id": None}])
    out = match_to_ours(impect, _ours())
    assert out.at[0, "player_id"] == 200
    assert out.at[0, "matched_via"] == "dob_name"


def test_match_rejects_same_birthday_different_name():
    # Same birthday as player 200 but an unrelated name: must NOT match.
    impect = pd.DataFrame([{"playerId": 3, "player_name": "Totally Different",
                            "birth_date": pd.Timestamp("1999-09-09"), "tm_player_id": None}])
    out = match_to_ours(impect, _ours())
    assert pd.isna(out.at[0, "player_id"])


def test_compare_goals_counts_within_one():
    matched = pd.DataFrame([
        {"player_id": 100, "player_name": "A", "total_goals": 23.0, "total_shot_xg": 18.0},
        {"player_id": 200, "player_name": "B", "total_goals": 10.0, "total_shot_xg": 9.0},
    ])
    sb = pd.DataFrame([
        {"player_id": 100, "goals": 23, "xg": 18.5},   # exact
        {"player_id": 200, "goals": 11, "xg": 8.5},    # within one (playoff goal)
    ])
    res = compare_goals(matched, sb)
    assert res["players_compared"] == 2
    assert res["goals_exact_pct"] == pytest.approx(50.0)
    assert res["goals_within_one_pct"] == pytest.approx(100.0)


def test_match_rescues_day_month_swapped_birthdate():
    # The Luke Harris case: identical name, provider has 04 Mar where we have 03 Apr.
    ours = pd.DataFrame([{"player_id": 300, "player_name": "Luke Harris",
                          "birth_date": "2005-04-03", "tm_player_id": None}])
    impect = pd.DataFrame([{"playerId": 9, "player_name": "Luke Harris",
                            "birth_date": pd.Timestamp("2005-03-04"), "tm_player_id": None}])
    out = match_to_ours(impect, ours)
    assert out.at[0, "player_id"] == 300
    assert out.at[0, "matched_via"] == "dob_swap"


def test_swap_rescue_requires_exact_name():
    # Swapped date but a DIFFERENT name must NOT match (date evidence alone is weak).
    ours = pd.DataFrame([{"player_id": 300, "player_name": "Luke Harris",
                          "birth_date": "2005-04-03", "tm_player_id": None}])
    impect = pd.DataFrame([{"playerId": 9, "player_name": "Lucas Harrison",
                            "birth_date": pd.Timestamp("2005-03-04"), "tm_player_id": None}])
    out = match_to_ours(impect, ours)
    assert pd.isna(out.at[0, "player_id"])


def test_swap_rescue_skips_impossible_swaps():
    # Day 25 cannot be a month: no swap candidate exists, and nothing crashes.
    ours = pd.DataFrame([{"player_id": 300, "player_name": "Some Player",
                          "birth_date": "2001-06-25", "tm_player_id": None}])
    impect = pd.DataFrame([{"playerId": 9, "player_name": "Some Player",
                            "birth_date": pd.Timestamp("2001-25-06", errors="ignore")
                            if False else pd.Timestamp("2001-06-25"), "tm_player_id": None}])
    # same date matches normally via dob_name; force a mismatch year to test the guard
    impect["birth_date"] = pd.Timestamp("2002-06-25")
    out = match_to_ours(impect, ours)
    assert pd.isna(out.at[0, "player_id"])


def test_exact_name_league_rescue_matches_dob_disagreement():
    # Ethan Pye: same name, same league, but providers disagree on DOB entirely.
    ours = pd.DataFrame([{"player_id": 400, "player_name": "Ethan Pye",
                          "birth_date": "2002-11-07", "tm_player_id": None}])
    impect = pd.DataFrame([{"playerId": 9, "player_name": "Ethan Pye",
                            "birth_date": pd.Timestamp("2003-11-27"), "tm_player_id": None}])
    idx = {"ethan pye": 400}
    out = match_to_ours(impect, ours, league_name_index=idx)
    assert out.at[0, "player_id"] == 400
    assert out.at[0, "matched_via"] == "name_league"


def test_exact_name_league_rescue_skips_ambiguous_names():
    # The same name twice among the unmatched Impect rows -> refuse both.
    ours = pd.DataFrame([{"player_id": 400, "player_name": "John Smith",
                          "birth_date": "2002-11-07", "tm_player_id": None}])
    impect = pd.DataFrame([
        {"playerId": 9, "player_name": "John Smith", "birth_date": pd.Timestamp("2003-11-27"), "tm_player_id": None},
        {"playerId": 10, "player_name": "John Smith", "birth_date": pd.Timestamp("2001-01-01"), "tm_player_id": None},
    ])
    out = match_to_ours(impect, ours, league_name_index={"john smith": 400})
    assert out["player_id"].isna().all()


def test_exact_name_league_rescue_off_by_default():
    # Without the index (e.g. the validation report), no name-only matching happens.
    ours = pd.DataFrame([{"player_id": 400, "player_name": "Ethan Pye",
                          "birth_date": "2002-11-07", "tm_player_id": None}])
    impect = pd.DataFrame([{"playerId": 9, "player_name": "Ethan Pye",
                            "birth_date": pd.Timestamp("2003-11-27"), "tm_player_id": None}])
    out = match_to_ours(impect, ours)
    assert pd.isna(out.at[0, "player_id"])


def test_dob_surname_rescue_matches_nickname_same_dob():
    # Isaac "Tanto" Olaofe: exact same DOB, same surname, forename is a known-as
    # the fuzzy name test misses. No league index needed — this stage is unguarded
    # by the index, it stands on DOB + surname uniqueness.
    ours = pd.DataFrame([{"player_id": 500, "player_name": "Isaac Olaofe",
                          "birth_date": "1999-11-21", "tm_player_id": None}])
    impect = pd.DataFrame([{"playerId": 9, "player_name": "Tanto Olaofe",
                            "birth_date": pd.Timestamp("1999-11-21"), "tm_player_id": None}])
    out = match_to_ours(impect, ours)
    assert out.at[0, "player_id"] == 500
    assert out.at[0, "matched_via"] == "dob_surname"


def _rescue_fixture(ours_rows, prov_rows):
    """Build the (result, by_dob, ours) inputs the rescue helper expects."""
    from lofc.model.valuation import _norm
    ours = pd.DataFrame(ours_rows)
    ours["nname"] = ours["player_name"].map(_norm)
    ours["birth_date"] = pd.to_datetime(ours["birth_date"]).dt.date
    by_dob = {}
    for i, r in enumerate(ours.itertuples()):
        by_dob.setdefault(r.birth_date, []).append(i)
    result = pd.DataFrame(prov_rows)
    result["player_id"] = pd.NA
    result["matched_via"] = pd.NA
    return result, by_dob, ours


def test_dob_surname_rescue_refuses_our_side_twins():
    # Two of OUR players share the exact DOB and surname (twins Michael & Matthew
    # Craig). A provider row on that DOB+surname must match NEITHER — our-side
    # uniqueness fails (2 candidates), so a wrong merge is refused; left NULL.
    from lofc.model.impect_check import _dob_surname_rescue
    result, by_dob, ours = _rescue_fixture(
        [{"player_id": 601, "player_name": "Michael Craig", "birth_date": "2003-04-16"},
         {"player_id": 602, "player_name": "Matthew Craig", "birth_date": "2003-04-16"}],
        [{"player_name": "Cammy Craig", "birth_date": pd.Timestamp("2003-04-16")}])
    _dob_surname_rescue(result, "player_name", by_dob, ours)
    assert result["player_id"].isna().all()


def test_dob_surname_rescue_refuses_provider_side_duplicates():
    # ONE of our players, but the provider lists TWO rows on that DOB+surname.
    # Provider-side uniqueness fails, so neither grabs our player; both left NULL.
    from lofc.model.impect_check import _dob_surname_rescue
    result, by_dob, ours = _rescue_fixture(
        [{"player_id": 500, "player_name": "Isaac Olaofe", "birth_date": "1999-11-21"}],
        [{"player_name": "Tanto Olaofe", "birth_date": pd.Timestamp("1999-11-21")},
         {"player_name": "Kwabena Olaofe", "birth_date": pd.Timestamp("1999-11-21")}])
    _dob_surname_rescue(result, "player_name", by_dob, ours)
    assert result["player_id"].isna().all()


def test_override_matches_by_impect_player_id_regardless_of_dob_or_name():
    # The curated-override stage: DOB disagrees AND names look unrelated, but a
    # human-verified (impect_player_id -> our_player_id) row is supplied. Rob/Robert
    # Apter: club affiliation matched across separate season-rows, but the automatic
    # stages can't safely act on that alone (see the CSV evidence column).
    ours = pd.DataFrame([{"player_id": 800, "player_name": "Robert Apter",
                          "birth_date": "2003-04-23", "tm_player_id": None}])
    impect = pd.DataFrame([{"playerId": 74076, "player_name": "Rob Apter",
                            "birth_date": pd.Timestamp("2003-01-16"), "tm_player_id": None}])
    overrides = pd.DataFrame([{"our_player_id": 800, "impect_player_id": 74076}])
    out = match_to_ours(impect, ours, overrides=overrides)
    assert out.at[0, "player_id"] == 800
    assert out.at[0, "matched_via"] == "override"


def test_override_does_not_apply_to_unlisted_players():
    # A playerId not in the override table falls through to the normal stages
    # (here: no match, since DOB and name both disagree).
    ours = pd.DataFrame([{"player_id": 800, "player_name": "Robert Apter",
                          "birth_date": "2003-04-23", "tm_player_id": None}])
    impect = pd.DataFrame([{"playerId": 999999, "player_name": "Someone Unrelated",
                            "birth_date": pd.Timestamp("1980-01-01"), "tm_player_id": None}])
    overrides = pd.DataFrame([{"our_player_id": 800, "impect_player_id": 74076}])
    out = match_to_ours(impect, ours, overrides=overrides)
    assert pd.isna(out.at[0, "player_id"])


def test_override_absent_by_default():
    # Without an overrides frame (the default), no override matching happens —
    # existing callers (e.g. the standalone impect_check report) are unaffected.
    ours = pd.DataFrame([{"player_id": 800, "player_name": "Robert Apter",
                          "birth_date": "2003-04-23", "tm_player_id": None}])
    impect = pd.DataFrame([{"playerId": 74076, "player_name": "Rob Apter",
                            "birth_date": pd.Timestamp("2003-01-16"), "tm_player_id": None}])
    out = match_to_ours(impect, ours)
    assert pd.isna(out.at[0, "player_id"])


def test_load_overrides_returns_empty_frame_when_file_missing(monkeypatch, tmp_path):
    from lofc.model import impect_check
    monkeypatch.setattr(impect_check, "OVERRIDES_PATH", tmp_path / "does_not_exist.csv")
    df = impect_check.load_overrides()
    assert df.empty
    assert list(df.columns) == ["our_player_id", "impect_player_id"]


def test_dob_surname_rescue_refuses_when_dob_differs():
    # Surname matches but the birth date does not: this stage requires an EXACT DOB,
    # so it must NOT fire (that looser case is left to a curated override, not a rule).
    ours = pd.DataFrame([{"player_id": 700, "player_name": "Adama Sidibeh",
                          "birth_date": "1998-03-27", "tm_player_id": None}])
    impect = pd.DataFrame([{"playerId": 9, "player_name": "A. Sidibeh",
                            "birth_date": pd.Timestamp("1998-06-25"), "tm_player_id": None}])
    out = match_to_ours(impect, ours)
    assert pd.isna(out.at[0, "player_id"])
