"""Per-metric Performance weights, by position and archetype (formula meeting; the club's
workbook "LOFC - what goes into each rating - Weightings to be assigned 5", owner 2026-11-02).

Each metric is tagged High / Mid / Low; one weight per tier within a table; every table sums
to exactly 1 (exact fractions, so no rounding drift). Physical has NO weights yet -- it stays
an equal-weight average, and the 57% Performance / 43% Physical split is unchanged.

Taken from the workbook as written, except five tables whose tiers were applied unevenly
(owner: "ensure the weighting is accurate"). Each keeps its tier RATIO, scaled to sum to 1:
  Goalkeeper                      High:Mid:Low 9:5:4 (one High was 0.20 beside 0.225s)
  Full Back / Attacking           High:Mid 5:3 (Pressures 0.07 beside 0.075s)
  Full Back / Progressive Build   High:Mid 2:1 (two Mids 0.05 beside 0.045s)
  Centre Forward                  High:Mid:Low 14:7:3 (Ball wins 0.02 beside 0.015s)
  Winger / Crossing & Creative    the All Metrics weights without Dribble & carry value,
                                  rescaled in proportion (the workbook added +0.003 to each)

Generated once from the workbook; edit here, never at run time. `tests/test_performance_
weights.py` holds every table to its metric list, to a sum of 1 and to one weight per tier.
"""

from __future__ import annotations

from fractions import Fraction

# (position, archetype) -> metric -> (tier, weight)
WEIGHTS: dict[tuple[str, str], dict[str, tuple[str, Fraction]]] = {
    ('Goalkeeper', 'All Metrics'): {
        'pass_value_p90': ('Mid', Fraction(5, 41)),   # 0.1220
        'defensive_touches_outside_box_p90': ('Low', Fraction(4, 41)),   # 0.0976
        'gk_gsaa_p90': ('High', Fraction(9, 41)),   # 0.2195
        'gk_shot_stopping_pct': ('High', Fraction(9, 41)),   # 0.2195
        'packing_bypassed_opponents_p90': ('Mid', Fraction(5, 41)),   # 0.1220
        'gk_catches_p90': ('High', Fraction(9, 41)),   # 0.2195
    },
    ('Centre Back', 'All Metrics'): {
        'ball_wins_p90': ('High', Fraction(1, 10)),   # 0.1000
        'aerial_win_pct': ('High', Fraction(1, 10)),   # 0.1000
        'ground_duel_win_pct': ('High', Fraction(1, 10)),   # 0.1000
        'counterpressures_p90': ('Low', Fraction(9, 200)),   # 0.0450
        'pressures_p90': ('Mid', Fraction(13, 200)),   # 0.0650
        'defensive_value_p90': ('High', Fraction(1, 10)),   # 0.1000
        'touches_in_box_p90': ('Mid', Fraction(13, 200)),   # 0.0650
        'pass_completion_pct': ('Mid', Fraction(13, 200)),   # 0.0650
        'packing_bypassed_opponents_p90': ('Mid', Fraction(13, 200)),   # 0.0650
        'deep_progressions_p90': ('Mid', Fraction(13, 200)),   # 0.0650
        'pass_value_p90': ('Mid', Fraction(13, 200)),   # 0.0650
        'turnovers_p90': ('Mid', Fraction(13, 200)),   # 0.0650
        'blocks_p90': ('High', Fraction(1, 10)),   # 0.1000
    },
    ('Full Back', 'All Metrics'): {
        'ball_wins_p90': ('Mid', Fraction(1, 25)),   # 0.0400
        'aerial_win_pct': ('Mid', Fraction(1, 25)),   # 0.0400
        'ground_duel_win_pct': ('High', Fraction(3, 50)),   # 0.0600
        'counterpressures_p90': ('High', Fraction(3, 50)),   # 0.0600
        'pressures_p90': ('High', Fraction(3, 50)),   # 0.0600
        'defensive_value_p90': ('Mid', Fraction(1, 25)),   # 0.0400
        'assists_p90': ('Mid', Fraction(1, 25)),   # 0.0400
        'open_play_assists_p90': ('Mid', Fraction(1, 25)),   # 0.0400
        'xa_p90': ('High', Fraction(3, 50)),   # 0.0600
        'goals_p90': ('Mid', Fraction(1, 25)),   # 0.0400
        'passes_into_box_p90': ('Mid', Fraction(1, 25)),   # 0.0400
        'touches_in_box_p90': ('Mid', Fraction(1, 25)),   # 0.0400
        'cross_bypassed_opponents_p90': ('Mid', Fraction(1, 25)),   # 0.0400
        'pass_completion_pct': ('Mid', Fraction(1, 25)),   # 0.0400
        'packing_bypassed_opponents_p90': ('High', Fraction(3, 50)),   # 0.0600
        'deep_progressions_p90': ('High', Fraction(3, 50)),   # 0.0600
        'pass_value_p90': ('Mid', Fraction(1, 25)),   # 0.0400
        'dribble_carry_value_p90': ('Mid', Fraction(1, 25)),   # 0.0400
        'turnovers_p90': ('Mid', Fraction(1, 25)),   # 0.0400
        'dribble_count_p90': ('Mid', Fraction(1, 25)),   # 0.0400
        'np_xg_p90': ('Mid', Fraction(1, 25)),   # 0.0400
        'np_xg_xa_p90': ('Mid', Fraction(1, 25)),   # 0.0400
    },
    ('Full Back', 'Attacking'): {
        'counterpressures_p90': ('High', Fraction(5, 67)),   # 0.0746
        'pressures_p90': ('High', Fraction(5, 67)),   # 0.0746
        'defensive_value_p90': ('Mid', Fraction(3, 67)),   # 0.0448
        'assists_p90': ('Mid', Fraction(3, 67)),   # 0.0448
        'open_play_assists_p90': ('Mid', Fraction(3, 67)),   # 0.0448
        'xa_p90': ('High', Fraction(5, 67)),   # 0.0746
        'goals_p90': ('Mid', Fraction(3, 67)),   # 0.0448
        'passes_into_box_p90': ('Mid', Fraction(3, 67)),   # 0.0448
        'touches_in_box_p90': ('Mid', Fraction(3, 67)),   # 0.0448
        'cross_bypassed_opponents_p90': ('Mid', Fraction(3, 67)),   # 0.0448
        'pass_completion_pct': ('Mid', Fraction(3, 67)),   # 0.0448
        'packing_bypassed_opponents_p90': ('High', Fraction(5, 67)),   # 0.0746
        'deep_progressions_p90': ('High', Fraction(5, 67)),   # 0.0746
        'pass_value_p90': ('Mid', Fraction(3, 67)),   # 0.0448
        'dribble_carry_value_p90': ('Mid', Fraction(3, 67)),   # 0.0448
        'turnovers_p90': ('Mid', Fraction(3, 67)),   # 0.0448
        'dribble_count_p90': ('Mid', Fraction(3, 67)),   # 0.0448
        'np_xg_p90': ('Mid', Fraction(3, 67)),   # 0.0448
        'np_xg_xa_p90': ('Mid', Fraction(3, 67)),   # 0.0448
    },
    ('Full Back', 'Progressive Build & Recovery'): {
        'ball_wins_p90': ('Mid', Fraction(1, 22)),   # 0.0455
        'aerial_win_pct': ('Mid', Fraction(1, 22)),   # 0.0455
        'ground_duel_win_pct': ('High', Fraction(1, 11)),   # 0.0909
        'counterpressures_p90': ('High', Fraction(1, 11)),   # 0.0909
        'pressures_p90': ('High', Fraction(1, 11)),   # 0.0909
        'defensive_value_p90': ('Mid', Fraction(1, 22)),   # 0.0455
        'assists_p90': ('Mid', Fraction(1, 22)),   # 0.0455
        'open_play_assists_p90': ('Mid', Fraction(1, 22)),   # 0.0455
        'xa_p90': ('High', Fraction(1, 11)),   # 0.0909
        'goals_p90': ('Mid', Fraction(1, 22)),   # 0.0455
        'pass_completion_pct': ('Mid', Fraction(1, 22)),   # 0.0455
        'packing_bypassed_opponents_p90': ('High', Fraction(1, 11)),   # 0.0909
        'deep_progressions_p90': ('High', Fraction(1, 11)),   # 0.0909
        'pass_value_p90': ('Mid', Fraction(1, 22)),   # 0.0455
        'turnovers_p90': ('Mid', Fraction(1, 22)),   # 0.0455
        'np_xg_xa_p90': ('Mid', Fraction(1, 22)),   # 0.0455
    },
    ('Defensive Mid', 'All Metrics'): {
        'ball_wins_p90': ('High', Fraction(1, 10)),   # 0.1000
        'aerial_win_pct': ('Mid', Fraction(1, 20)),   # 0.0500
        'ground_duel_win_pct': ('High', Fraction(1, 10)),   # 0.1000
        'counterpressures_p90': ('High', Fraction(1, 10)),   # 0.1000
        'pressures_p90': ('High', Fraction(1, 10)),   # 0.1000
        'xa_p90': ('Low', Fraction(1, 50)),   # 0.0200
        'passes_into_box_p90': ('Low', Fraction(1, 50)),   # 0.0200
        'pass_completion_pct': ('High', Fraction(1, 10)),   # 0.1000
        'packing_bypassed_opponents_p90': ('High', Fraction(1, 10)),   # 0.1000
        'deep_progressions_p90': ('Mid', Fraction(1, 20)),   # 0.0500
        'pass_value_p90': ('High', Fraction(1, 10)),   # 0.1000
        'dribble_carry_value_p90': ('Mid', Fraction(1, 20)),   # 0.0500
        'turnovers_p90': ('Mid', Fraction(1, 20)),   # 0.0500
        'assists_p90': ('Low', Fraction(1, 50)),   # 0.0200
        'open_play_assists_p90': ('Low', Fraction(1, 50)),   # 0.0200
        'goals_p90': ('Low', Fraction(1, 50)),   # 0.0200
    },
    ('Central Mid', 'All Metrics'): {
        'ball_wins_p90': ('High', Fraction(7, 100)),   # 0.0700
        'aerial_win_pct': ('Mid', Fraction(1, 25)),   # 0.0400
        'ground_duel_win_pct': ('High', Fraction(7, 100)),   # 0.0700
        'counterpressures_p90': ('Mid', Fraction(1, 25)),   # 0.0400
        'pressures_p90': ('High', Fraction(7, 100)),   # 0.0700
        'xa_p90': ('Mid', Fraction(1, 25)),   # 0.0400
        'passes_into_box_p90': ('Mid', Fraction(1, 25)),   # 0.0400
        'pass_completion_pct': ('Mid', Fraction(1, 25)),   # 0.0400
        'packing_bypassed_opponents_p90': ('High', Fraction(7, 100)),   # 0.0700
        'deep_progressions_p90': ('High', Fraction(7, 100)),   # 0.0700
        'pass_value_p90': ('High', Fraction(7, 100)),   # 0.0700
        'dribble_carry_value_p90': ('Mid', Fraction(1, 25)),   # 0.0400
        'turnovers_p90': ('Mid', Fraction(1, 25)),   # 0.0400
        'assists_p90': ('Mid', Fraction(1, 25)),   # 0.0400
        'open_play_assists_p90': ('Mid', Fraction(1, 25)),   # 0.0400
        'goals_p90': ('Mid', Fraction(1, 25)),   # 0.0400
        'shots_p90': ('Mid', Fraction(1, 25)),   # 0.0400
        'dribble_count_p90': ('Mid', Fraction(1, 25)),   # 0.0400
        'touches_in_box_p90': ('High', Fraction(7, 100)),   # 0.0700
        'cross_bypassed_opponents_p90': ('Low', Fraction(3, 100)),   # 0.0300
    },
    ('Attacking Mid', 'All Metrics'): {
        'ball_wins_p90': ('Mid', Fraction(7, 200)),   # 0.0350
        'counterpressures_p90': ('High', Fraction(3, 50)),   # 0.0600
        'pressures_p90': ('High', Fraction(3, 50)),   # 0.0600
        'assists_p90': ('High', Fraction(3, 50)),   # 0.0600
        'open_play_assists_p90': ('High', Fraction(3, 50)),   # 0.0600
        'xa_p90': ('High', Fraction(3, 50)),   # 0.0600
        'goals_p90': ('High', Fraction(3, 50)),   # 0.0600
        'shots_p90': ('High', Fraction(3, 50)),   # 0.0600
        'np_xg_p90': ('High', Fraction(3, 50)),   # 0.0600
        'passes_into_box_p90': ('High', Fraction(3, 50)),   # 0.0600
        'touches_in_box_p90': ('High', Fraction(3, 50)),   # 0.0600
        'cross_bypassed_opponents_p90': ('Mid', Fraction(7, 200)),   # 0.0350
        'pass_completion_pct': ('Low', Fraction(3, 200)),   # 0.0150
        'packing_bypassed_opponents_p90': ('High', Fraction(3, 50)),   # 0.0600
        'deep_progressions_p90': ('High', Fraction(3, 50)),   # 0.0600
        'on_ball_value_p90': ('Mid', Fraction(7, 200)),   # 0.0350
        'pass_value_p90': ('Low', Fraction(3, 200)),   # 0.0150
        'dribble_carry_value_p90': ('Mid', Fraction(7, 200)),   # 0.0350
        'dribble_count_p90': ('Mid', Fraction(7, 200)),   # 0.0350
        'turnovers_p90': ('Low', Fraction(3, 200)),   # 0.0150
        'np_xg_xa_p90': ('High', Fraction(3, 50)),   # 0.0600
    },
    ('Winger', 'All Metrics'): {
        'ball_wins_p90': ('Low', Fraction(7, 400)),   # 0.0175
        'counterpressures_p90': ('High', Fraction(3, 50)),   # 0.0600
        'pressures_p90': ('High', Fraction(3, 50)),   # 0.0600
        'assists_p90': ('High', Fraction(3, 50)),   # 0.0600
        'open_play_assists_p90': ('High', Fraction(3, 50)),   # 0.0600
        'xa_p90': ('High', Fraction(3, 50)),   # 0.0600
        'goals_p90': ('High', Fraction(3, 50)),   # 0.0600
        'shots_p90': ('High', Fraction(3, 50)),   # 0.0600
        'np_xg_p90': ('High', Fraction(3, 50)),   # 0.0600
        'passes_into_box_p90': ('High', Fraction(3, 50)),   # 0.0600
        'touches_in_box_p90': ('Mid', Fraction(3, 100)),   # 0.0300
        'cross_bypassed_opponents_p90': ('Mid', Fraction(3, 100)),   # 0.0300
        'pass_completion_pct': ('Low', Fraction(7, 400)),   # 0.0175
        'packing_bypassed_opponents_p90': ('Mid', Fraction(3, 100)),   # 0.0300
        'deep_progressions_p90': ('High', Fraction(3, 50)),   # 0.0600
        'on_ball_value_p90': ('High', Fraction(3, 50)),   # 0.0600
        'pass_value_p90': ('Low', Fraction(7, 400)),   # 0.0175
        'dribble_carry_value_p90': ('High', Fraction(3, 50)),   # 0.0600
        'dribble_count_p90': ('High', Fraction(3, 50)),   # 0.0600
        'turnovers_p90': ('Low', Fraction(7, 400)),   # 0.0175
        'np_xg_xa_p90': ('High', Fraction(3, 50)),   # 0.0600
    },
    ('Winger', 'Direct & 1v1 Specialist'): {
        'ball_wins_p90': ('Low', Fraction(1, 40)),   # 0.0250
        'counterpressures_p90': ('High', Fraction(13, 200)),   # 0.0650
        'pressures_p90': ('High', Fraction(13, 200)),   # 0.0650
        'assists_p90': ('High', Fraction(13, 200)),   # 0.0650
        'open_play_assists_p90': ('High', Fraction(13, 200)),   # 0.0650
        'xa_p90': ('High', Fraction(13, 200)),   # 0.0650
        'goals_p90': ('High', Fraction(13, 200)),   # 0.0650
        'shots_p90': ('High', Fraction(13, 200)),   # 0.0650
        'np_xg_p90': ('High', Fraction(13, 200)),   # 0.0650
        'passes_into_box_p90': ('High', Fraction(13, 200)),   # 0.0650
        'touches_in_box_p90': ('Mid', Fraction(1, 25)),   # 0.0400
        'deep_progressions_p90': ('High', Fraction(13, 200)),   # 0.0650
        'on_ball_value_p90': ('High', Fraction(13, 200)),   # 0.0650
        'pass_value_p90': ('Low', Fraction(1, 40)),   # 0.0250
        'dribble_carry_value_p90': ('High', Fraction(13, 200)),   # 0.0650
        'dribble_count_p90': ('High', Fraction(13, 200)),   # 0.0650
        'np_xg_xa_p90': ('High', Fraction(13, 200)),   # 0.0650
    },
    ('Winger', 'Crossing & Creative Threat'): {
        'ball_wins_p90': ('Low', Fraction(7, 376)),   # 0.0186
        'counterpressures_p90': ('High', Fraction(3, 47)),   # 0.0638
        'pressures_p90': ('High', Fraction(3, 47)),   # 0.0638
        'assists_p90': ('High', Fraction(3, 47)),   # 0.0638
        'open_play_assists_p90': ('High', Fraction(3, 47)),   # 0.0638
        'xa_p90': ('High', Fraction(3, 47)),   # 0.0638
        'goals_p90': ('High', Fraction(3, 47)),   # 0.0638
        'shots_p90': ('High', Fraction(3, 47)),   # 0.0638
        'np_xg_p90': ('High', Fraction(3, 47)),   # 0.0638
        'passes_into_box_p90': ('High', Fraction(3, 47)),   # 0.0638
        'touches_in_box_p90': ('Mid', Fraction(3, 94)),   # 0.0319
        'cross_bypassed_opponents_p90': ('Mid', Fraction(3, 94)),   # 0.0319
        'pass_completion_pct': ('Low', Fraction(7, 376)),   # 0.0186
        'packing_bypassed_opponents_p90': ('Mid', Fraction(3, 94)),   # 0.0319
        'deep_progressions_p90': ('High', Fraction(3, 47)),   # 0.0638
        'on_ball_value_p90': ('High', Fraction(3, 47)),   # 0.0638
        'pass_value_p90': ('Low', Fraction(7, 376)),   # 0.0186
        'dribble_count_p90': ('High', Fraction(3, 47)),   # 0.0638
        'turnovers_p90': ('Low', Fraction(7, 376)),   # 0.0186
        'np_xg_xa_p90': ('High', Fraction(3, 47)),   # 0.0638
    },
    ('Centre Forward', 'All Metrics'): {
        'ball_wins_p90': ('Low', Fraction(3, 199)),   # 0.0151
        'counterpressures_p90': ('High', Fraction(14, 199)),   # 0.0704
        'pressures_p90': ('High', Fraction(14, 199)),   # 0.0704
        'assists_p90': ('Low', Fraction(3, 199)),   # 0.0151
        'open_play_assists_p90': ('Mid', Fraction(7, 199)),   # 0.0352
        'xa_p90': ('Mid', Fraction(7, 199)),   # 0.0352
        'goals_p90': ('High', Fraction(14, 199)),   # 0.0704
        'shots_p90': ('High', Fraction(14, 199)),   # 0.0704
        'np_xg_p90': ('High', Fraction(14, 199)),   # 0.0704
        'passes_into_box_p90': ('Low', Fraction(3, 199)),   # 0.0151
        'touches_in_box_p90': ('High', Fraction(14, 199)),   # 0.0704
        'cross_bypassed_opponents_p90': ('Low', Fraction(3, 199)),   # 0.0151
        'pass_completion_pct': ('Low', Fraction(3, 199)),   # 0.0151
        'packing_bypassed_opponents_p90': ('Mid', Fraction(7, 199)),   # 0.0352
        'deep_progressions_p90': ('Mid', Fraction(7, 199)),   # 0.0352
        'on_ball_value_p90': ('Mid', Fraction(7, 199)),   # 0.0352
        'pass_value_p90': ('Low', Fraction(3, 199)),   # 0.0151
        'dribble_carry_value_p90': ('Low', Fraction(3, 199)),   # 0.0151
        'dribble_count_p90': ('Low', Fraction(3, 199)),   # 0.0151
        'turnovers_p90': ('Mid', Fraction(7, 199)),   # 0.0352
        'aerial_win_pct': ('Mid', Fraction(7, 199)),   # 0.0352
        'goal_conversion_pct': ('High', Fraction(14, 199)),   # 0.0704
        'xg_overperformance_p90': ('High', Fraction(14, 199)),   # 0.0704
        'xg_per_shot': ('High', Fraction(14, 199)),   # 0.0704
    },}


def weights_for(position: str, archetype: str) -> dict[str, float] | None:
    """metric -> weight for a position's Performance (archetype falls back to All Metrics);
    None where the club has set no weights (then the average stays equal)."""
    table = WEIGHTS.get((position, archetype)) or WEIGHTS.get((position, "All Metrics"))
    return {m: float(w) for m, (_, w) in table.items()} if table else None
