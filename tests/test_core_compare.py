"""`lofc.core.compare`: the Compare page's logic, lifted out of `dashboard/tabs/compare.py` so the
web page and Streamlit run the same code. Pure tests (no database, no Streamlit runtime)."""
import math

import pandas as pd
import pytest

from lofc.core import compare as C
from lofc.dashboard.tabs import compare as T


def test_streamlit_page_uses_the_lifted_functions():
    """tabs/compare.py re-exports the core functions (one implementation, not two)."""
    for name in ("default_candidates", "fill_default_slots", "sanitize_slots", "same_position",
                 "season_change", "change_style", "compare_row", "summary_extras",
                 "physical_radar_inputs", "no_physical_caption", "UP_STYLE", "DOWN_STYLE",
                 "NEUTRAL_STYLE"):
        assert getattr(T, name) is getattr(C, name), name


@pytest.mark.parametrize("text,now,sub,tone", [
    ("3.41 → 3.68 (+0.27)", "3.68", "+0.27 vs 3.41", "up"),
    ("3.68 → 3.41 (-0.27)", "3.41", "-0.27 vs 3.68", "down"),
    ("3.41 (League Two) → 3.41 (0.00)", "3.41", "no change vs 3.41 (League Two)", "neutral"),
    ("3.68", "3.68", None, None),
    ("3.41 → —", "—", "was 3.41", "neutral"),
    ("4.49 (—)", "4.49", "—", "neutral"),
    ("—", "—", None, None),
    ("1,234", "1,234", None, None),
])
def test_change_parts_reads_the_cell_the_way_the_streamlit_table_does(text, now, sub, tone):
    p = C.change_parts(text)
    assert (p["now"], p["sub"], p["tone"]) == (now, sub, tone)


def test_value_cell_html_is_built_from_change_parts_unchanged():
    """The Streamlit cell for every case above (byte-for-byte what it was before the lift)."""
    assert T._value_cell("3.41 → 3.68 (+0.27)") == (
        '<td><span class="v">3.68</span><span class="ch" style="color: #1a9850; font-weight: 600">'
        '+0.27 vs 3.41</span></td>')
    assert T._value_cell("4.49 (—)") == (
        '<td><span class="v">4.49</span><span class="ch" style="color: #888888">—</span></td>')
    assert T._value_cell("3.68") == '<td><span class="v">3.68</span></td>'
    assert T._value_cell("a<b") == '<td><span class="v">a&lt;b</span></td>'


def test_minutes_round_half_up():
    r = pd.Series({"player_id": 1, "player_name": "A", "team_name": "X", "league": "League Two",
                   "age": 24.0, "minutes": 1234.5, "objective_composite": 3.0,
                   "performance_band": 3.0, "physical_band": 3.0})
    assert C.compare_row(r, None)["Minutes"] == "1,235"
    r2 = r.copy()
    r2["minutes"] = 1233.5
    assert C.compare_row(r2, None)["Minutes"] == "1,234"


def test_summary_attributes_order_and_presence():
    rows = [{"Age": "1", "Overall": "3", "Scout verdicts": "—", "Overall trend": "x"},
            {"Minutes": "9"}]
    assert C.summary_attributes(rows) == ["Age", "Minutes", "Overall", "Overall trend", "Scout verdicts"]


def _cands():
    return pd.DataFrame([
        {"player_id": 1, "competition_id": 7, "season_id": 318, "player_name": "Thin Man",
         "team_name": "A", "position_group": "Winger", "league": "Small League", "minutes": 900.0},
    ])


def _cards(n_peers):
    rows = [{"player_id": 100 + i, "competition_id": 7, "season_id": 318,
             "position_group": "Winger", "archetype": "All Metrics", "objective_composite": 3.0}
            for i in range(n_peers - 1)]
    rows.append({"player_id": 1, "competition_id": 7, "season_id": 318, "position_group": "Winger",
                 "archetype": "All Metrics", "objective_composite": 4.9,
                 "performance_band": 4.8, "physical_band": 4.7})
    return pd.DataFrame(rows)


def test_pick_row_prefers_the_pool_then_the_season_and_can_blank_a_thin_pool():
    pool = pd.DataFrame([{"player_id": 1, "competition_id": 7, "season_id": 318,
                          "objective_composite": 3.3, "position_group": "Winger"}])
    row, reason = C.pick_row((1, 7, 318), pool, lambda s: _cands(), lambda s: _cards(5))
    assert row["objective_composite"] == 3.3 and reason == "ok"
    empty = pool.iloc[0:0]
    row, reason = C.pick_row((1, 7, 318), empty, lambda s: _cands(), lambda s: _cards(5))
    assert reason == "not_rated" and row["objective_composite"] == 4.9      # Streamlit today
    row, reason = C.pick_row((1, 7, 318), empty, lambda s: _cands(), lambda s: _cards(5),
                             blank_unrated=True)
    assert reason == "not_rated"
    assert all(math.isnan(row[c]) for c in ("objective_composite", "performance_band", "physical_band"))
    assert row["peer_count"] == 5
    assert C.pick_row((9, 7, 318), empty, lambda s: _cands(), lambda s: _cards(5)) == (None, "not_found")


def test_not_rated_caption_names_the_pool_size():
    assert C.not_rated_caption("not_rated", 8, 900, "Winger", "League Two") == \
        "Not rated: only 8 Wingers in League Two with 450+ minutes (needs 10)."
    assert C.not_rated_caption("not_rated", float("nan"), 900) == \
        "Not rated: too few peers in his league and position"
    assert C.not_rated_caption("ok", 30, 900) is None


def test_vs_text_groups_players_by_pool():
    assert C.vs_text("Winger", "League Two", None) == "League Two Wingers"
    assert C.vs_text("Winger", "Celtic League", 8) == "8 Celtic League Wingers"
    assert C.vs_sub([("A", "League Two Wingers"), ("B", "League Two Wingers")]) == "League Two Wingers"
    assert C.vs_sub([("A", "League Two Wingers"), ("B", "8 SPL Wingers"), ("C", "League Two Wingers")]) == \
        "League Two Wingers (A, C) · 8 SPL Wingers (B)"


def test_physical_radar_metrics_keep_keys_and_inputs_keep_labels():
    s = pd.Series({"distance_p90": 50.0, "hsr_count_p90": 60.0, "sprint_count_p90": 70.0,
                   "top5_psv99_kmh": 80.0})
    keys, traces, missing = C.physical_radar_metrics({"A": s, "B": None}, "Winger")
    assert keys and all(k in C.PHYS_RADAR_LABEL for k in keys) and missing == ["B"]
    axes, traces2, missing2 = C.physical_radar_inputs({"A": s, "B": None}, "Winger")
    assert axes == [C.PHYS_RADAR_LABEL[k] for k in keys] and traces2 == traces and missing2 == missing


def test_slot_defaults_and_sanitising_live_in_core():
    state = {"cmp_a": "X", "cmp_c": "Y"}
    C.sanitize_slots(state, ["P0", "P1"])
    assert "cmp_a" not in state and state["cmp_c"] == C.NONE_OPTION
    C.fill_default_slots(state, ["P0", "P1"])
    assert (state["cmp_a"], state["cmp_b"]) == ("P0", "P1")


def test_default_candidates_same_with_a_kept_lookup():
    idx = pd.DataFrame({"player_id": [1, 2, 3, 4], "competition_id": [5, 5, 6, 5],
                        "season_id": [318] * 4, "label": ["A", "B", "C", "D"],
                        "position_group": ["Winger", "Winger", "Centre Back", "Winger"]})
    pool = pd.DataFrame({"player_id": [4, 9], "competition_id": [5, 5], "season_id": [318, 318]})
    want = ["D", "A", "B"]
    assert C.default_candidates(pool, idx, "Winger") == want
    assert C.default_candidates(pool, idx, "Winger", C.index_lookup(idx)) == want


# ---- one season per slot (owner 2026-11-20): honesty when the slots' league or season differ ---
def _now(**kw):
    base = {"player_id": 1, "competition_id": 4, "season_id": 319, "player_name": "P",
            "team_name": "T", "league": "League One", "objective_composite": 3.68,
            "performance_band": 3.50, "physical_band": 4.10}
    base.update(kw)
    return pd.Series(base)


def _prev(league):
    return pd.DataFrame([{"player_id": 1, "prev_composite": 3.41, "prev_physical": 4.50,
                          "prev_performance": 3.40, "prev_league": league}])


def test_season_change_from_another_league_is_was_x_without_a_delta_or_colour():
    row = C.compare_row(_now(), _prev("League Two"))
    assert row["Overall"] == "3.41 (League Two) → 3.68"
    assert row["Performance"] == "3.40 (League Two) → 3.50"
    assert row["Physical"] == "4.50 (League Two) → 4.10"
    assert C.change_parts(row["Overall"]) == {"now": "3.68", "sub": "was 3.41 (League Two)",
                                              "tone": "neutral"}
    assert C.change_parts(row["Physical"])["sub"] == "was 4.50 (League Two)"


def test_season_change_in_the_same_league_keeps_its_delta_and_colour():
    row = C.compare_row(_now(), _prev("League One"))
    assert row["Overall"] == "3.41 → 3.68 (+0.27)"
    assert C.change_parts(row["Overall"])["tone"] == "up"


def test_mixed_means_any_difference_in_league_or_season():
    a = _now()
    assert not C.mixed([a, _now(player_id=2)])
    assert C.mixed([a, _now(season_id=318)])
    assert C.mixed([a, _now(competition_id=5)])


def test_uncoloured_drops_best_and_worst_and_leaves_the_rows_alone():
    rows = [{"metric": "x", "label": "X", "tier": "High",
             "cells": [{"text": "1", "pct": 90.0, "cls": "best"},
                       {"text": "2", "pct": 10.0, "cls": "worst"}]}]
    out = C.uncoloured(rows)
    assert [c["cls"] for c in out[0]["cells"]] == [None, None]
    assert [c["text"] for c in out[0]["cells"]] == ["1", "2"]
    assert rows[0]["cells"][0]["cls"] == "best"


def test_season_league_heading():
    assert C.season_league("2025/26", "League Two") == "2025/26 · League Two"
    assert C.season_league("2025/26", None) == "2025/26"


def test_season_options_list_only_his_seasons_in_this_position_newest_first():
    by_season = {319: {("Winger", 7): [4]}, 318: {("Winger", 7): [5, 903]},
                 317: {("Centre Back", 7): [5]}}
    seasons = {319: "2026/27", 318: "2025/26", 317: "2024/25"}
    leagues = {4: "League One", 5: "League Two", 903: "Premier League 2"}
    assert C.season_options(7, "Winger", by_season, seasons.get, leagues.get) == [
        {"season": 319, "competition_id": 4, "label": "2026/27 · League One"},
        {"season": 318, "competition_id": 5, "label": "2025/26 · League Two"},
        {"season": 318, "competition_id": 903, "label": "2025/26 · Premier League 2"}]


def test_display_names_add_the_season_when_a_player_is_compared_with_himself():
    a, b = _now(), _now(season_id=318)
    assert C.display_names([a, b]) == ["P (2026/27)", "P (2025/26)"]
    assert C.display_names([a, _now(team_name="U")]) == ["P (T)", "P (U)"]     # unchanged


def test_per_season_frames():
    frames = C.BySeason({318: "a", 319: "b"})
    assert C.per_season(frames, 319) == "b" and C.per_season("plain", 319) == "plain"


def test_orient_line_only_when_every_shown_player_is_league_one_in_its_season():
    l1 = _now()
    assert C.orient_allowed([l1, _now(player_id=2)], 319)
    assert not C.orient_allowed([l1, _now(competition_id=5)], 319)
    assert not C.orient_allowed([l1, _now(season_id=318)], 319)
    assert not C.orient_allowed([_now(season_id=318)] * 2, 319)


def _pool():
    return pd.DataFrame({"player_id": [1, 2, 3, 4, 5],
                         "league": ["League Two", "League One", "Championship", "League One",
                                    "League Two"]})


ORDER = ["Championship", "League One", "League Two"]


def test_opening_league_is_league_one_when_present_else_the_first_chosen():
    assert C.opening_league(_pool(), (), ORDER) == "League One"
    assert C.opening_league(_pool(), ("Championship", "League One"), ORDER) == "League One"
    assert C.opening_league(_pool(), ("League Two", "Championship"), ORDER) == "League Two"
    no_l1 = _pool()[_pool()["league"] != "League One"]
    assert C.opening_league(no_l1, (), ORDER) == "Championship"
    assert C.opening_league(_pool().iloc[0:0], (), ORDER) is None


def test_league_grouped_keeps_the_pool_order_within_each_league_never_across():
    got = C.league_grouped(_pool(), (), ORDER)
    assert got["player_id"].tolist() == [2, 4, 3, 1, 5]        # League One first, then ORDER
    got = C.league_grouped(_pool(), ("League Two", "Championship"), ORDER)
    assert got["player_id"].tolist() == [1, 5, 3, 2, 4]
