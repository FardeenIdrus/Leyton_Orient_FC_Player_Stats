"""Playing-style labels (owner + Head of Recruitment's 24 styles, 2026-10-23).

STYLE, NOT QUALITY. A style is what a player TRIES and WHERE he plays: attempts (successful +
unsuccessful + neutral), shares of his own actions, and pitch locations. A poor playmaker still
attempts a playmaker's passes. Quality metrics appear only where no alternative exists and are
flagged (aerial duels won; Impect records no failed dribbles).

Verified on 2025/26 before these rules were written (3,356 rated players, 7 leagues): every
unflagged signal correlates under 0.3 with the Performance rating, no two signals of a style
over 0.7, coverage 100% in every league.

The rule: each style's FIT is the average percentile of its signals, within league + season +
position over 450+ minute players. Every player gets his best-fitting style --
  Strong  fit >= 70 and no signal below 50
  Leans   best fit >= 50 otherwise
  none    below average at every style -> "No standout style"
-- plus any other style he is Strong in. Wingers are labelled twice: WHERE and WHAT.
"""

import pandas as pd
import pytest

from lofc.model import club_framework as cf
from lofc.model import styles as st


# --- signals: attempts, shares, locations -----------------------------------------------

def _totals(**cols):
    return pd.DataFrame({k: [v] for k, v in cols.items()}, index=[1])


def test_pass_attempts_count_every_outcome():
    """A completed, an intercepted and a pressured pass are all ATTEMPTS. Counting only
    successful ones would let quality decide the style."""
    t = _totals(SUCCESSFUL_PASSES_BY_ACTION_DIAGONAL_PASS=6.0,
                UNSUCCESSFUL_PASSES_BY_ACTION_DIAGONAL_PASS=3.0,
                NEUTRAL_PASSES_BY_ACTION_DIAGONAL_PASS=1.0)
    assert st.attempts(t, "_BY_ACTION_DIAGONAL_PASS").iloc[0] == 10.0


def test_a_missing_outcome_column_counts_as_zero():
    t = _totals(SUCCESSFUL_PASSES_BY_ACTION_DIAGONAL_PASS=6.0,
                UNSUCCESSFUL_PASSES_BY_ACTION_DIAGONAL_PASS=3.0)
    assert st.attempts(t, "_BY_ACTION_DIAGONAL_PASS").iloc[0] == 9.0


def test_a_poor_passer_and_a_good_one_with_the_same_attempts_get_the_same_share():
    good = _totals(SUCCESSFUL_PASSES=40.0, UNSUCCESSFUL_PASSES=0.0, NEUTRAL_PASSES=0.0,
                   SUCCESSFUL_PASSES_BY_ACTION_DIAGONAL_PASS=10.0)
    poor = _totals(SUCCESSFUL_PASSES=20.0, UNSUCCESSFUL_PASSES=20.0, NEUTRAL_PASSES=0.0,
                   SUCCESSFUL_PASSES_BY_ACTION_DIAGONAL_PASS=4.0,
                   UNSUCCESSFUL_PASSES_BY_ACTION_DIAGONAL_PASS=6.0)
    share = lambda t: st.SIGNALS["long_pass_attempt_share"](t, pd.Series([900.0], index=[1]))
    assert share(good).iloc[0] == share(poor).iloc[0] == 0.25


def test_duels_contested_count_won_and_lost_per_90():
    t = _totals(WON_AERIAL_DUELS=4.0, LOST_AERIAL_DUELS=6.0)
    assert st.SIGNALS["aerial_contested_p90"](t, pd.Series([450.0], index=[1])).iloc[0] == 2.0


def test_a_share_with_nothing_to_share_is_unknown_not_zero():
    t = _totals(OFFENSIVE_TOUCHES=0.0, SHOT_AT_GOAL_NUMBER=0.0)
    assert pd.isna(st.SIGNALS["np_shots_per_touch"](t, pd.Series([900.0], index=[1])).iloc[0])


# --- the rules ------------------------------------------------------------------------------

def test_the_head_of_recruitments_26_styles():
    """His list names DM and CM separately with the same three styles; they share a group.
    24 styles, plus Dribbler for attacking midfielders and Goalscorer for wingers
    (2026-10-30)."""
    outfield = [p for p in cf.PERFORMANCE_METRICS if p != "Goalkeeper"]
    assert sum(len(s) for p in outfield
               for s in st.STYLES[st.style_group(p)].values()) == 26


def test_every_outfield_position_has_a_style_group_and_goalkeepers_none():
    outfield = [p for p in cf.PERFORMANCE_METRICS if p != "Goalkeeper"]
    assert all(st.style_group(p) in st.STYLES for p in outfield)
    assert st.style_group("Goalkeeper") not in st.STYLES


def test_defensive_and_central_midfielders_are_one_style_group():
    """Impect labels a two-man midfield as two defensive midfielders; central midfield is
    only the middle of a three. In 2026/27 that left 31 rated central midfielders across 7
    leagues -- every league pool under the floor (owner, 2026-10-23). Style labels only:
    the ratings still score DM and CM on their own metric lists."""
    assert st.style_group("Defensive Mid") == st.style_group("Central Mid") == "Central midfield"
    assert st.style_group("Attacking Mid") == "Attacking Mid"


def test_defensive_and_central_midfielders_are_compared_together():
    frame = pd.DataFrame({"player_id": range(12), "competition_id": 4, "season_id": 318,
                          "position_group": ["Defensive Mid"] * 6 + ["Central Mid"] * 6,
                          "rankable": True, "touch_box_share": [0.01 * i for i in range(12)]})
    out = st.signal_percentiles(frame)
    assert out["touch_box_share"].notna().all()           # 6 + 6 clears the floor of 10
    assert out["touch_box_share"].max() == pytest.approx(100 * 11.5 / 12)


def test_every_signal_a_style_uses_exists():
    for groups in st.STYLES.values():
        for styles in groups.values():
            for signals in styles.values():
                assert signals and all(s in st.SIGNALS for s in signals)


def test_wingers_are_labelled_by_where_and_by_what():
    assert list(st.STYLES["Winger"]) == ["Where", "What"]
    assert set(st.STYLES["Winger"]["Where"]) == {"In behind", "Pocket", "Wide"}
    assert set(st.STYLES["Winger"]["What"]) == {"1v1", "Creator", "Goalscorer"}


def test_a_goalscoring_winger_uses_the_centre_forward_scorers_signals():
    """Requested by the Head of Recruitment; owner approved the Scorer's 4 signals."""
    assert st.STYLES["Winger"]["What"]["Goalscorer"] == \
        st.STYLES["Centre Forward"]["Style"]["Scorer"]


def test_quality_signals_are_declared():
    """Every signal that measures success is named, so the reference page flags it and
    nobody adds one by accident. The Head of Recruitment's additions of 2026-10-30 were
    accepted with their quality signals (owner's decision)."""
    assert st.QUALITY_SIGNALS == {
        "aerial_won_share", "dribbles_per_touch", "assists_non_set_piece_p90", "xa_p90",
        "line_breaking_pass_share", "receptions_bypassing_p90", "carry_value_p90",
        "np_goals_p90", "np_xg_p90"}


# --- the Head of Recruitment's additions (Playing_Profiles_Tweaks_2, 2026-10-30) -----------

def _s(sig, minutes=900.0, **cols):
    return st.SIGNALS[sig](_totals(**cols), pd.Series([minutes], index=[1])).iloc[0]


@pytest.mark.parametrize("group,style,signals", [
    ("Full Back", "Attacking", ["touch_advanced_wide_share", "box_pass_attempts_per_touch",
                                "cross_attempts_per_touch", "assists_non_set_piece_p90",
                                "xa_p90"]),
    ("Centre Back", "Ball-playing", ["forward_pass_attempt_share", "low_pass_attempt_share",
                                     "line_breaking_pass_share"]),
    ("Central midfield", "Destroyer", ["ground_contested_p90", "defensive_touches_p90",
                                       "presses_p90", "counter_presses_p90"]),
    ("Central midfield", "Playmaker", ["forward_pass_attempt_share", "receptions_bypassing_p90",
                                       "low_pass_attempt_share", "line_breaking_pass_share"]),
    ("Attacking Mid", "Dribbler", ["dribbles_per_touch", "carry_value_p90"]),
    ("Winger", "Creator", ["box_pass_attempts_per_touch", "cross_attempts_per_touch", "xa_p90",
                           "touch_box_share", "assists_non_set_piece_p90"]),
    ("Centre Forward", "Scorer", ["np_shots_per_touch", "touch_box_share", "np_goals_p90",
                                  "np_xg_p90"]),
])
def test_the_styles_carry_the_requested_signals(group, style, signals):
    styles = {s: v for g in st.STYLES[group].values() for s, v in g.items()}
    assert styles[style] == signals



def test_long_passes_left_ball_playing_and_playmaker():
    """Low passes pull against long passes (r -0.53 CB, -0.60 CM on 2025/26): with both, 14
    of 671 centre backs and 9 of 668 midfielders were Strong. Owner kept low passes and
    dropped long passes (2026-10-30)."""
    for group, style in (("Centre Back", "Ball-playing"), ("Central midfield", "Playmaker")):
        styles = {s: v for g in st.STYLES[group].values() for s, v in g.items()}
        assert "long_pass_attempt_share" not in styles[style]


def test_cross_attempts_count_low_and_high_crosses_of_every_outcome_per_touch():
    v = _s("cross_attempts_per_touch", OFFENSIVE_TOUCHES=100.0,
           SUCCESSFUL_PASSES_BY_ACTION_LOW_CROSS=2.0, UNSUCCESSFUL_PASSES_BY_ACTION_LOW_CROSS=3.0,
           NEUTRAL_PASSES_BY_ACTION_HIGH_CROSS=1.0, UNSUCCESSFUL_PASSES_BY_ACTION_HIGH_CROSS=4.0)
    assert v == pytest.approx(0.10)


def test_assists_leave_out_set_pieces():
    assert _s("assists_non_set_piece_p90", 450.0, ASSISTS=5.0,
              ASSISTS_AT_PHASE_SET_PIECE=1.0) == pytest.approx(0.8)


def test_xa_is_expected_goal_assists_per_90():
    assert _s("xa_p90", 450.0, EXPECTED_GOAL_ASSISTS=1.5) == pytest.approx(0.3)


def test_low_passes_are_a_share_of_all_attempts():
    v = _s("low_pass_attempt_share", SUCCESSFUL_PASSES=60.0, UNSUCCESSFUL_PASSES=30.0,
           NEUTRAL_PASSES=10.0, SUCCESSFUL_PASSES_BY_ACTION_LOW_PASS=50.0,
           UNSUCCESSFUL_PASSES_BY_ACTION_LOW_PASS=20.0)
    assert v == pytest.approx(0.70)


def test_line_breaking_passes_leave_out_dribbles():
    """Impect's 'Bypassed Opponents Number' counts passes AND dribbles; only passes count."""
    v = _s("line_breaking_pass_share", SUCCESSFUL_PASSES=40.0, UNSUCCESSFUL_PASSES=10.0,
           BYPASSED_OPPONENTS_NUMBER=15.0, BYPASSED_OPPONENTS_NUMBER_BY_ACTION_DRIBBLE=5.0)
    assert v == pytest.approx(0.20)


def test_receptions_carry_value_are_per_90():
    assert _s("receptions_bypassing_p90", 450.0,
              BYPASSED_OPPONENTS_RECEIVING_NUMBER=20.0) == pytest.approx(4.0)
    assert _s("carry_value_p90", 450.0, PXT_DRIBBLE=0.5) == pytest.approx(0.1)


def test_scorer_signals_leave_out_penalties():
    assert _s("np_shots_per_touch", OFFENSIVE_TOUCHES=100.0, SHOT_AT_GOAL_NUMBER=12.0,
              SHOT_AT_GOAL_NUMBER_BY_ACTION_PENALTY_KICK=2.0) == pytest.approx(0.10)
    assert _s("np_goals_p90", 450.0, GOALS=6.0,
              GOALS_BY_ACTION_PENALTY_KICK=2.0) == pytest.approx(0.8)
    assert _s("np_xg_p90", 450.0, SHOT_XG=3.0,
              SHOT_XG_BY_ACTION_PENALTY_KICK=0.76) == pytest.approx(0.448)


def test_every_signal_has_a_label_and_impect_sources():
    for sig in st.SIGNALS:
        assert st.SIGNAL_LABELS.get(sig), sig
        built, columns = st.SIGNAL_SOURCES[sig]
        assert built and columns, sig


def test_every_source_column_is_in_impects_catalogue():
    import csv
    with open("data/reference/impect_definitions.csv") as f:
        known = {r["column"] for r in csv.DictReader(f)}
    for sig, (_, columns) in st.SIGNAL_SOURCES.items():
        assert set(columns) <= known, (sig, set(columns) - known)


# --- percentiles ----------------------------------------------------------------------------

def _pool(values, rankable=None, n=None):  # noqa: E302
    n = n or len(values)
    return pd.DataFrame({"player_id": range(n), "competition_id": 4, "season_id": 318,
                         "position_group": "Winger", "rankable": rankable or [True] * n,
                         "rec_in_behind_share": values})


def test_percentiles_are_mid_rank_within_the_pool():
    out = st.signal_percentiles(_pool([0.1 * i for i in range(10)]))
    assert out["rec_in_behind_share"].tolist() == pytest.approx([5.0 + 10 * i for i in range(10)])


def test_players_under_450_minutes_get_no_percentile_and_are_not_in_anyones_pool():
    frame = _pool([0.1 * i for i in range(11)], rankable=[True] * 10 + [False])
    out = st.signal_percentiles(frame).set_index("player_id")
    assert pd.isna(out.loc[10, "rec_in_behind_share"])
    assert out["rec_in_behind_share"].max() == 95.0


def test_a_pool_under_the_ranking_floor_gets_no_percentiles():
    """Same floor as the ratings: a percentile among four players means nothing."""
    out = st.signal_percentiles(_pool([0.1, 0.2, 0.3, 0.4]))
    assert out["rec_in_behind_share"].isna().all()


# --- assignment -----------------------------------------------------------------------------

def _pcts(position, **pcts):
    row = {"player_id": 1, "competition_id": 4, "season_id": 318, "position_group": position}
    return pd.DataFrame([{**row, **pcts}])


def _label(position, **pcts):
    return st.assign_styles(_pcts(position, **pcts))["style_label"].iloc[0]


MID = dict(ground_contested_p90=40, defensive_touches_p90=40, forward_pass_attempt_share=40,
           long_pass_attempt_share=40, touch_box_share=40, presses_p90=40,
           counter_presses_p90=40, receptions_bypassing_p90=40, low_pass_attempt_share=40,
           line_breaking_pass_share=40)
PM = dict(receptions_bypassing_p90=75, low_pass_attempt_share=75, line_breaking_pass_share=75)


def test_a_clear_fit_is_strong():
    assert _label("Central Mid", **{**MID, **PM, "forward_pass_attempt_share": 85,
                                    "long_pass_attempt_share": 75}) == "Playmaker"


def test_a_strong_average_with_one_signal_below_the_median_is_only_leans():
    assert _label("Central Mid", **{**MID, **PM, "forward_pass_attempt_share": 99,
                                    "low_pass_attempt_share": 45}) == "Leans Playmaker"


def test_a_middling_best_fit_leans():
    assert _label("Central Mid", **{**MID, "forward_pass_attempt_share": 62,
                                    "long_pass_attempt_share": 58, "receptions_bypassing_p90": 60,
                                    "low_pass_attempt_share": 60,
                                    "line_breaking_pass_share": 60}) == "Leans Playmaker"


def test_below_average_at_every_style_has_no_standout_style():
    assert _label("Central Mid", **MID) == "No standout style"


def test_a_second_strong_style_is_added():
    assert _label("Central Mid", **{**MID, **PM, "forward_pass_attempt_share": 90,
                                    "long_pass_attempt_share": 88, "touch_box_share": 80,
                                    "defensive_touches_p90": 75}) == "Playmaker · Box-to-box"


def test_a_winger_gets_a_where_and_a_what():
    w = dict(rec_in_behind_share=20, rec_btl_share=30, rec_central_share=30,
             rec_wide_share=90, touch_wide_share=80, dribbles_per_touch=85,
             box_pass_attempts_per_touch=40, cross_attempts_per_touch=40, xa_p90=40,
             touch_box_share=40, assists_non_set_piece_p90=40)
    assert _label("Winger", **w) == "Wide · 1v1"


def test_a_winger_strong_where_and_nothing_what_shows_only_where():
    w = dict(rec_in_behind_share=95, rec_btl_share=30, rec_central_share=30,
             rec_wide_share=20, touch_wide_share=20, dribbles_per_touch=30,
             box_pass_attempts_per_touch=30, cross_attempts_per_touch=30, xa_p90=30,
             touch_box_share=30, assists_non_set_piece_p90=30)
    assert _label("Winger", **w) == "In behind"


def test_a_player_without_percentiles_is_not_labelled():
    """Under 450 minutes, or a pool under the floor: no style, and the reason is shown."""
    assert _label("Central Mid") == "Not enough minutes"


def test_the_thresholds_are_adjustable():
    """The style lab moves them; nothing else changes."""
    pc = {**MID, "forward_pass_attempt_share": 66, "long_pass_attempt_share": 66,
          "receptions_bypassing_p90": 66, "low_pass_attempt_share": 66,
          "line_breaking_pass_share": 66}
    assert _label("Central Mid", **pc) == "Leans Playmaker"
    loose = st.assign_styles(_pcts("Central Mid", **pc), strong=60)
    assert loose["style_label"].iloc[0] == "Playmaker"


def test_the_fit_and_tier_of_every_style_are_returned_for_the_lab():
    out = st.assign_styles(_pcts("Central Mid", **{**MID, "forward_pass_attempt_share": 85,
                                                   "receptions_bypassing_p90": 80,
                                                   "low_pass_attempt_share": 80,
                                                   "line_breaking_pass_share": 75}))
    assert out["fit.Playmaker"].iloc[0] == 80.0
    assert out["tier"].iloc[0] == "Strong"


def test_goalkeepers_have_no_styles_and_no_label():
    assert pd.isna(_label("Goalkeeper"))


# --- what the Players page needs: pills and the Style filter (Step 4) --------------------

W = dict(rec_in_behind_share=20, rec_btl_share=30, rec_central_share=30,
         rec_wide_share=90, touch_wide_share=80, dribbles_per_touch=60,
         box_pass_attempts_per_touch=40)


def _one(position, **pcts):
    return st.assign_styles(_pcts(position, **pcts)).iloc[0]


def test_strong_and_leans_styles_are_listed_separately():
    row = _one("Winger", **W)
    assert row["strong_styles"] == ["Wide"]
    assert row["leans_styles"] == ["1v1"]


def test_pills_name_each_style_and_mark_leans():
    """The table shows pills; Streamlit draws them all alike, so Leans is said in words."""
    assert st.style_pills(_one("Winger", **W)) == ["Wide", "1v1 (leans)"]


def test_no_standout_style_is_one_pill_and_no_minutes_is_none():
    assert st.style_pills(_one("Central Mid", **MID)) == [st.NO_STYLE]
    assert st.style_pills(_one("Central Mid")) == []


@pytest.mark.parametrize("style,strong_only,expected", [
    ("Wide", False, True), ("Wide", True, True),
    ("1v1", False, True), ("1v1", True, False),       # Leans 1v1: only without "Strong only"
    ("In behind", False, False),
])
def test_the_style_filter(style, strong_only, expected):
    assert st.has_style(_one("Winger", **W), style, strong_only) is expected


def test_the_style_options_for_a_position_follow_its_group():
    assert st.style_options("Winger") == ["In behind", "Pocket", "Wide", "1v1", "Creator",
                                         "Goalscorer"]
    assert st.style_options("Defensive Mid") == ["Destroyer", "Playmaker", "Box-to-box"]
    assert st.style_options("Goalkeeper") == []


def test_a_player_with_no_label_after_the_join_is_handled():
    """The Players list joins labels LEFT: a player without one carries NaN, not a list."""
    row = {"strong_styles": float("nan"), "leans_styles": float("nan"), "style_label": float("nan")}
    assert st.style_pills(row) == []
    assert st.has_style(row, "Wide") is False
