"""Live bugs found 2026-11-06 (TASKS 2.28-2.30): wrong archetype row in Season by season,
mixed rating types across seasons, "63th", minutes rounding, assists source, captions."""

import inspect

import pandas as pd

from lofc.dashboard import compare_tables as ct, detail_section, loaders
from lofc.dashboard.tabs import compare as cmp, players


# --- 2.29a: Season by season always uses the All Metrics row ----------------------------
def test_season_score_uses_all_metrics_not_the_first_archetype_row():
    scores = pd.DataFrame([
        {"player_id": 1, "competition_id": 5, "season_id": 318, "archetype": "Direct & 1v1",
         "objective_composite": 3.43, "performance_band": 3.85, "physical_band": 2.86},
        {"player_id": 1, "competition_id": 5, "season_id": 318, "archetype": "All Metrics",
         "objective_composite": 3.41, "performance_band": 3.82, "physical_band": 2.86},
    ])
    rows = pd.DataFrame([{"player_id": 1, "competition_id": 5, "season_id": 318}])
    out = players.attach_season_scores(rows, scores)
    assert out["Score"].iloc[0] == 3.41 and out["Performance"].iloc[0] == 3.82
    assert out["Physical"].iloc[0] == 2.86


# --- 2.30: Overall only where the season has a physical band ----------------------------
def test_season_overall_is_blank_only_in_a_season_with_no_physical_data():
    """Season-level: 2024/25 (317) has no physical band for anyone. A player-season with no
    physical band inside a season that HAS physical data still shows its Overall."""
    rows = pd.DataFrame({"season_id": [317, 318, 318], "Score": [4.07, 3.41, 3.30],
                         "Performance": [4.07, 3.82, 3.30], "Physical": [float("nan"), 2.86, float("nan")]})
    out = players.season_rating_columns(rows, no_physical_seasons=[317])
    assert pd.isna(out["Overall"].iloc[0])
    assert list(out["Overall"].iloc[1:]) == [3.41, 3.30]
    assert list(out["Performance"]) == [4.07, 3.82, 3.30]


def test_compare_row_changes_only_between_seasons_with_the_same_parts():
    prev = pd.DataFrame([{"player_id": 1, "prev_composite": 4.07, "prev_physical": float("nan"),
                          "prev_performance": 4.07, "prev_league": "League One"}])
    now = pd.Series({"player_id": 1, "competition_id": 2, "season_id": 318, "player_name": "P",
                     "team_name": "T", "league": "League One", "objective_composite": 3.41,
                     "performance_band": 3.82, "physical_band": 2.86})
    row = cmp.compare_row(now, prev)
    assert row["Performance"] == "4.07 → 3.82 (-0.25)"
    assert row["Overall"] == "3.41 (—)" and row["Physical"] == "2.86 (—)"
    html = cmp.comparison_html([row])
    assert "—</span>" in html and "(—)" not in html


def test_compare_row_full_comparison_when_both_seasons_have_physical():
    prev = pd.DataFrame([{"player_id": 1, "prev_composite": 3.0, "prev_physical": 2.0,
                          "prev_performance": 3.5, "prev_league": "League One"}])
    now = pd.Series({"player_id": 1, "competition_id": 2, "season_id": 319, "player_name": "P",
                     "team_name": "T", "league": "League One", "objective_composite": 3.5,
                     "performance_band": 3.6, "physical_band": 2.5})
    row = cmp.compare_row(now, prev)
    assert row["Overall"] == "3.00 → 3.50 (+0.50)" and row["Physical"] == "2.00 → 2.50 (+0.50)"


def test_rating_trend_rows_show_dash_where_absent():
    by_season = {317: (4.07, 4.07, float("nan")), 318: (3.41, 3.82, 2.86), 319: (None, None, None)}
    rows = ct.rating_trend_rows(by_season, [317, 318, 319], no_physical_seasons=[317])
    assert rows["Overall trend"] == "24/25 — · 25/26 3.41 · 26/27 —"
    assert rows["Performance trend"] == "24/25 4.07 · 25/26 3.82 · 26/27 —"
    assert rows["Physical trend"] == "24/25 — · 25/26 3.00".replace("3.00", "2.86") + " · 26/27 —"


def test_trend_overall_shows_for_unphysical_player_in_a_season_with_physical_data():
    by_season = {318: (3.30, 3.30, float("nan"))}
    rows = ct.rating_trend_rows(by_season, [318], no_physical_seasons=[317])
    assert rows["Overall trend"] == "25/26 3.30" and rows["Physical trend"] == "25/26 —"


def test_trend_rows_keep_league_context_when_it_differs():
    by_season = {317: (3.2, 3.2, None, "League Two"), 318: (3.5, 3.6, 2.9, "League One")}
    rows = ct.rating_trend_rows(by_season, [317, 318], no_physical_seasons=[317],
                                current_league="League One")
    assert rows["Performance trend"] == "24/25 3.20 (L2) · 25/26 3.60"
    assert rows["Overall trend"] == "24/25 — · 25/26 3.50"


def test_comparison_note_names_seasons_without_physical_by_data():
    hist = pd.DataFrame({"season_id": [317, 317, 318, 318],
                         "objective_composite": [4.0, 3.0, 3.4, 3.2],
                         "physical_band": [None, None, 2.8, None]})
    assert ct.seasons_without_physical(hist) == [317]
    assert ct.comparison_note(["2024/25"]) == "— = no comparison possible. 2024/25 has no physical data."
    assert ct.comparison_note([]) == "— = no comparison possible."


# --- 2.29b ordinals ---------------------------------------------------------------------
def test_ordinal_suffixes():
    got = {n: detail_section.ordinal(n) for n in (1, 2, 3, 4, 11, 12, 13, 21, 22, 23, 63, 100, 101, 111)}
    assert got == {1: "1st", 2: "2nd", 3: "3rd", 4: "4th", 11: "11th", 12: "12th", 13: "13th",
                   21: "21st", 22: "22nd", 23: "23rd", 63: "63rd", 100: "100th", 101: "101st",
                   111: "111th"}


# --- 2.29d minutes ----------------------------------------------------------------------
def test_whole_minutes_rounds_half_up():
    assert players.whole_minutes(3066.7) == 3067
    assert players.whole_minutes(2.5) == 3 and players.whole_minutes(3.5) == 4
    assert players.whole_minutes(3066.4) == 3066


def test_goal_and_assist_totals_round_half_up():
    # 0.5 goals worth of minutes: 90 min at 0.5/90 ... exactly 2.5 -> 3 (half-even gives 2)
    cf = pd.DataFrame([{"player_id": 1, "minutes": 450.0, "goals_p90": 0.5, "assists_p90": 0.5}])
    out = players._current_form_summary(cf, 1)
    assert out["goals"] == 3 and out["assists"] == 3


def test_current_form_minutes_use_the_same_rounding():
    cf = pd.DataFrame([{"player_id": 1, "minutes": 2.5, "goals_p90": 0.0, "assists_p90": 0.0}])
    assert players._current_form_summary(cf, 1)["minutes"] == 3


# --- 2.29c assists: Impect (player_metrics_neutral) is the one source -------------------
def test_trajectory_frame_uses_impect_totals_and_half_up_rounding():
    raw = pd.DataFrame([
        {"player_id": 1, "minutes": 3068.4, "goals": 8, "assists": 4,
         "n_minutes": 3066.7093, "n_goals_p90": 0.2347793, "n_assists_p90": 0.2054360},
        # 450 min at 0.5 per 90 = exactly 2.5 -> 3 (SQL ROUND on double would give 2)
        {"player_id": 2, "minutes": 450.0, "goals": 9, "assists": 9,
         "n_minutes": 450.0, "n_goals_p90": 0.5, "n_assists_p90": 0.5},
        # no combined-table row: keep the older table's figures
        {"player_id": 3, "minutes": 900.0, "goals": 5, "assists": 2,
         "n_minutes": None, "n_goals_p90": None, "n_assists_p90": None},
    ])
    out = loaders.trajectory_from_rows(raw)
    assert list(out["assists"]) == [7, 3, 2] and list(out["goals"]) == [8, 3, 5]
    assert list(out["minutes"]) == [3066.7093, 450.0, 900.0]
    assert not {"n_minutes", "n_goals_p90", "n_assists_p90"} & set(out.columns)


def test_assist_tile_uses_the_impect_figure_even_when_a_raw_total_exists():
    assert players.season_total_count(raw=4, per90=0.2054, minutes=3066.7, prefer_derived=True) == 7
    assert players.season_total_count(raw=4, per90=None, minutes=3066.7, prefer_derived=True) == 4
    # goals keep preferring the raw total, as before
    assert players.season_total_count(raw=8, per90=0.5, minutes=3066.7, prefer_derived=False) == 8
    assert players.season_total_count(raw=None, per90=None, minutes=3066.7, prefer_derived=False) == 0


# --- 2.28a / 2.29 captions --------------------------------------------------------------
def test_tile_notes_have_no_old_provider_name():
    for role in ("goalkeeper", "defender"):
        note = players.empty_tile_note(role)
        assert "statsbomb" not in note.lower() and "no longer published" in note
    assert players.empty_tile_note("goalkeeper").startswith("Save % / Saves: no longer published")
    assert players.empty_tile_note("attacker") is None
    assert "statsbomb" not in players.METRIC_GLOSSARY_NOTE.lower()


def test_current_form_empty_caption_uses_the_live_season_name():
    assert "2027/28" in players.current_form_empty_caption("2027/28")
    assert "2026/27" not in players.current_form_empty_caption("2027/28")


def test_scouts_help_matches_the_cell_value():
    from lofc.dashboard.tabs.scout_reports import scout_consensus
    split = scout_consensus(["Sign", "Don't sign"])
    assert split == scout_consensus(["Sign", "Monitor"])
    assert f"{split} = they disagreed" in players.SCOUTS_HELP
    assert f"{scout_consensus(['Sign'])} = all scouts said Sign" in players.SCOUTS_HELP


def test_card_note_uses_the_shared_wording_and_season_level_data():
    scores = pd.DataFrame({"season_id": [317, 317, 318, 318], "objective_composite": [4.0, 3.0, 3.4, 3.2],
                           "physical_band": [None, None, 2.8, None], "archetype": ["All Metrics"] * 4})
    rows = pd.DataFrame({"season_id": [317, 318]})
    assert players.card_no_physical_seasons(rows, scores) == [317]
    assert (ct.comparison_note(["2024/25"])
            == "— = no comparison possible. 2024/25 has no physical data.")
    assert not hasattr(players, "season_table_note")
