"""Group the club's per-position metrics into the handful of categories a reader can hold
in their head.

NOTHING HERE IS INVENTED. Every member is one of the club's own Performance metrics as
resolved to its live Impect successor by `scorecard._resolved_performance`. The grouping is
presentation -- a way to say "he progresses well but presses little" without making the
reader average sixteen bars themselves. It is not a new model and produces no new score;
`tests/test_report_categories.py` asserts every member is a metric the scoring layer
actually resolves, so a category can never drift into measuring something the club did not
ask for.

A category is the MEAN of its members' percentiles, renormalised over the members actually
present, so a metric with no data drops out rather than counting as zero -- the same rule
`scorecard._composite` already applies to dimensions.

Metrics deliberately left out of every category (they still appear in the report's bar
chart, which shows the full resolved list): Goals for the two central-midfield groups, and
Touches in box for a Centre Back. Both are real and worth seeing, but a one-metric category
is a bar with a heading, not a summary.
"""

from __future__ import annotations

# Metrics where a HIGH percentile is BAD. A player in the 90th percentile for turnovers is
# poor at retention, not good at it, so the percentile is flipped before it enters a
# category. Without this the Retention category would reward giving the ball away.
INVERTED: frozenset[str] = frozenset({"turnovers_p90"})

CATEGORIES: dict[str, dict[str, list[str]]] = {
    "Goalkeeper": {
        "Shot stopping": ["gk_gsaa_p90", "gk_shot_stopping_pct"],
        "Claiming": ["gk_catches_p90"],
        "Sweeping": ["defensive_touches_outside_box_p90"],
        "Distribution": ["pass_value_p90", "packing_bypassed_opponents_p90"],
    },
    "Centre Back": {
        "Defending": ["ball_wins_p90", "defensive_value_p90", "blocks_p90"],
        "Duels": ["aerial_win_pct", "ground_duel_win_pct"],
        "Pressing": ["counterpressures_p90", "pressures_p90"],
        "Progression": ["packing_bypassed_opponents_p90", "deep_progressions_p90",
                        "pass_value_p90"],
        "Retention": ["pass_completion_pct", "turnovers_p90"],
    },
    "Full Back": {
        "Defending": ["ball_wins_p90", "defensive_value_p90"],
        "Duels": ["aerial_win_pct", "ground_duel_win_pct"],
        "Pressing": ["counterpressures_p90", "pressures_p90"],
        "Progression": ["packing_bypassed_opponents_p90", "deep_progressions_p90",
                        "pass_value_p90", "dribble_carry_value_p90", "dribble_count_p90"],
        "Creation": ["assists_p90", "open_play_assists_p90", "xa_p90",
                     "passes_into_box_p90", "cross_bypassed_opponents_p90",
                     "touches_in_box_p90"],
        "Retention": ["pass_completion_pct", "turnovers_p90"],
        "Scoring": ["goals_p90", "np_xg_p90", "np_xg_xa_p90"],
    },
    "Defensive Mid": {
        "Progression": ["packing_bypassed_opponents_p90", "deep_progressions_p90",
                        "pass_value_p90", "dribble_carry_value_p90"],
        "Creation": ["xa_p90", "passes_into_box_p90", "assists_p90",
                     "open_play_assists_p90"],
        "Retention": ["pass_completion_pct", "turnovers_p90"],
        "Pressing": ["counterpressures_p90", "pressures_p90", "ball_wins_p90"],
        "Duels": ["ground_duel_win_pct", "aerial_win_pct"],
    },
    
    #-----
    "Central Mid": {
        "Progression": ["packing_bypassed_opponents_p90", "deep_progressions_p90",
                        "pass_value_p90", "dribble_carry_value_p90"],
        "Creation": ["xa_p90", "passes_into_box_p90", "assists_p90",
                     "open_play_assists_p90"],
        "Retention": ["pass_completion_pct", "turnovers_p90"],
        "Pressing": ["counterpressures_p90", "pressures_p90", "ball_wins_p90"],
        "Duels": ["ground_duel_win_pct", "aerial_win_pct"],
    },
    "Attacking Mid": {
        "Scoring": ["goals_p90", "shots_p90", "np_xg_p90", "np_xg_xa_p90"],
        "Creation": ["assists_p90", "open_play_assists_p90", "xa_p90",
                     "passes_into_box_p90", "cross_bypassed_opponents_p90",
                     "touches_in_box_p90"],
        "Progression": ["packing_bypassed_opponents_p90", "deep_progressions_p90",
                        "on_ball_value_p90", "pass_value_p90", "dribble_carry_value_p90",
                        "dribble_count_p90"],
        "Retention": ["pass_completion_pct", "turnovers_p90"],
        "Pressing": ["counterpressures_p90", "pressures_p90", "ball_wins_p90"],
    },
    "Winger": {
        "Scoring": ["goals_p90", "shots_p90", "np_xg_p90", "np_xg_xa_p90"],
        "Creation": ["assists_p90", "open_play_assists_p90", "xa_p90",
                     "passes_into_box_p90", "cross_bypassed_opponents_p90",
                     "touches_in_box_p90"],
        "Progression": ["packing_bypassed_opponents_p90", "deep_progressions_p90",
                        "on_ball_value_p90", "pass_value_p90", "dribble_carry_value_p90",
                        "dribble_count_p90"],
        "Retention": ["pass_completion_pct", "turnovers_p90"],
        "Pressing": ["counterpressures_p90", "pressures_p90", "ball_wins_p90"],
    },
    "Centre Forward": {
        "Scoring": ["goals_p90", "shots_p90", "np_xg_p90", "goal_conversion_pct",
                    "xg_overperformance_p90", "xg_per_shot"],
        "Creation": ["assists_p90", "open_play_assists_p90", "xa_p90",
                     "passes_into_box_p90", "cross_bypassed_opponents_p90",
                     "touches_in_box_p90"],
        "Progression": ["packing_bypassed_opponents_p90", "deep_progressions_p90",
                        "on_ball_value_p90", "pass_value_p90", "dribble_carry_value_p90",
                        "dribble_count_p90"],
        "Retention": ["pass_completion_pct", "turnovers_p90"],
        "Pressing": ["counterpressures_p90", "pressures_p90", "ball_wins_p90"],
        "Aerial": ["aerial_win_pct"],
    },
}

# Two categories per position that best separate its genuine styles, for the report's
# scatter. Both axes are category percentiles, so the plot is in the same units as the
# strips beneath it and a reader is not switching scales mid-page.
SCATTER_AXES: dict[str, tuple[str, str]] = {
    "Goalkeeper": ("Distribution", "Shot stopping"),
    "Centre Back": ("Progression", "Defending"),
    "Full Back": ("Creation", "Defending"),
    "Defensive Mid": ("Progression", "Pressing"),
    "Central Mid": ("Progression", "Pressing"),
    "Attacking Mid": ("Creation", "Scoring"),
    "Winger": ("Creation", "Scoring"),
    "Centre Forward": ("Creation", "Scoring"),
}



def category_score(percentiles: dict[str, float], position: str,
                   category: str) -> float | None:
    """The mean percentile across a category's members, or None if none are measurable.

    Raises KeyError for an unknown position or category -- a player must never be scored
    against categories that do not exist for his position, and returning None there would
    be indistinguishable from "we hold no data for him".

    Returns None, never 0.0, when nothing is measurable: a category we cannot measure is
    not a category the player scored zero in.
    """
    members = CATEGORIES[position][category]
    present = [(100.0 - percentiles[m]) if m in INVERTED else percentiles[m]
               for m in members if percentiles.get(m) is not None]
    if not present:
        return None
    return round(sum(present) / len(present), 1)


def category_scores(percentiles: dict[str, float], position: str) -> dict[str, float]:
    """Every measurable category for a position, in the order they are declared above.

    Unmeasurable categories are OMITTED rather than zeroed, so the report simply does not
    draw a strip it has no data for.
    """
    out: dict[str, float] = {}
    for category in CATEGORIES[position]:
        score = category_score(percentiles, position, category)
        if score is not None:
            out[category] = score
    return out
