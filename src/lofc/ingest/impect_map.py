"""The Impect -> our-internal-names metric map (single source of truth).

Each entry says how one of our provider-neutral metric names is produced from
Impect's columns. Kinds:
  - "rate"  : a per-90 value. numer = (col, +1/-1) pairs summed, then divided by
              minutes and x90 (e.g. xg_overperformance = GOALS minus SHOT_XG, per 90).
  - "ratio" : a 0..1 proportion. numer and denom are each (col, +1/-1) pairs summed,
              then numer/denom (e.g. gk_shot_stopping_pct = GSAA / post-shot xG faced).
  - "none"  : Impect has no equivalent (the StatsBomb-only defensive/pressing set);
              produced from StatsBomb instead, never from Impect.

Confidence: "direct" (exact Impect column), "native" (Impect's own metric, no
StatsBomb twin), "derived" (computed), "analogue" (Impect measures the concept a
different way, e.g. its PxT stands in for StatsBomb on-ball value).

Impect KPIs are averages per full match played, so a season total is
value * matchShare; our per-90 then divides the season total by real minutes
(playDuration seconds / 60) and x90. That conversion lives in impect_translate,
driven by this map. Verified against the licence columns on 2026-07-10.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class MetricMap:
    name: str                 # our internal, provider-neutral name
    kind: str                 # "rate" | "ratio" | "none"
    confidence: str           # "direct" | "native" | "derived" | "analogue" | "none"
    club_metric: str          # the club-document name this serves (or "")
    numer: tuple = ()         # (col, +1/-1) pairs, summed. rate: the whole value.
                               # ratio: the numerator.
    denom: tuple = ()         # ratio only: (col, +1/-1) pairs, summed = the denominator.
    note: str = ""


def _r(col):  # a single positive column, signed-pair form
    return ((col, 1),)


IMPECT_MAP: list[MetricMap] = [
    # --- Attacking output (rates) ---
    MetricMap("goals_p90", "rate", "direct", "Goals", _r("GOALS")),
    MetricMap("np_xg_p90", "rate", "derived", "NP xG",
              (("SHOT_XG", 1), ("SHOT_XG_BY_ACTION_PENALTY_KICK", -1)),
              note="total shot xG minus penalty-kick xG = genuine non-penalty xG. Fixes the "
                   "earlier penalties-included flaw (corr 0.981 vs StatsBomb np_xg)"),
    MetricMap("shots_p90", "rate", "direct", "NP Shots", _r("SHOT_AT_GOAL_NUMBER")),
    MetricMap("xa_p90", "rate", "direct", "Open Play xG Assisted", _r("EXPECTED_GOAL_ASSISTS"),
              note="Impect expected goal assists = xA (NOT EXPECTED_SHOT_ASSISTS, which is a count)"),
    MetricMap("assists_p90", "rate", "direct", "Assists", _r("ASSISTS")),
    MetricMap("key_passes_p90", "rate", "direct", "Chances created", _r("SHOT_ASSISTS")),
    MetricMap("xg_overperformance_p90", "rate", "derived", "Over/Under Performance",
              (("GOALS", 1), ("SHOT_XG", -1))),
    MetricMap("touches_in_box_p90", "rate", "derived", "Touches In Box",
              _r("OFFENSIVE_TOUCHES_IN_PITCH_POSITION_OPPONENT_BOX")),
    MetricMap("open_play_assists_p90", "rate", "direct", "Open Play Assists",
              _r("ASSISTS_AT_PHASE_IN_POSSESSION"),
              note="assists credited while the team was already in open-play possession"),
    MetricMap("np_xg_xa_p90", "rate", "derived", "NP xG + xA",
              (("SHOT_XG", 1), ("SHOT_XG_BY_ACTION_PENALTY_KICK", -1), ("EXPECTED_GOAL_ASSISTS", 1)),
              note="np_xg_p90 + xa_p90 combined: penalty-kick xG is subtracted so this matches the "
                   "non-penalty np_xg_p90 (an earlier version summed penalty-inclusive SHOT_XG, which "
                   "inflated penalty-takers)"),
    MetricMap("post_shot_xg_p90", "rate", "native", "(finishing quality)", _r("POSTSHOT_XG"),
              note="values shots on target by where they crossed the line, not just shot location; "
                   "high value = quality strikes, not just volume"),
    MetricMap("shot_threat_p90", "rate", "native", "(shot threat)", _r("PXT_SHOT"),
              note="goal-threat value generated purely from shooting (Impect's PxT model)"),
    # --- Migrated from StatsBomb (Phase B: validated per-player against the StatsBomb
    #     value on the same League One 25/26 players before adoption) ---
    MetricMap("passes_p90", "rate", "direct", "(passing volume)",
              (("SUCCESSFUL_PASSES", 1), ("UNSUCCESSFUL_PASSES", 1), ("NEUTRAL_PASSES", 1)),
              note="all pass attempts incl. Impect's 'neutral' outcomes (corr 0.984 vs StatsBomb, "
                   "same scale)"),
    MetricMap("np_goals_p90", "rate", "derived", "Non-penalty goals",
              (("GOALS", 1), ("GOALS_BY_ACTION_PENALTY_KICK", -1)),
              note="goals minus penalty-kick goals (corr 0.999 vs StatsBomb)"),
    MetricMap("xg_p90", "rate", "direct", "(xG incl. penalties)", _r("SHOT_XG"),
              note="total shot xG including penalties, same convention as the StatsBomb "
                   "all-shots xg (corr 0.984)"),
    MetricMap("blocks_p90", "rate", "analogue", "Blocks/Shot numerator",
              _r("DEFENSIVE_TOUCHES_BY_ACTION_BLOCK"),
              note="defensive touches coded as blocks (corr 0.885 vs StatsBomb Block events; "
                   "reads ~30% lower -- Impect codes fewer touches as blocks; percentiles "
                   "absorb the scale)"),
    MetricMap("clearances_p90", "rate", "derived", "Clearances",
              (("SUCCESSFUL_PASSES_BY_ACTION_CLEARANCE", 1),
               ("UNSUCCESSFUL_PASSES_BY_ACTION_CLEARANCE", 1),
               ("NEUTRAL_PASSES_BY_ACTION_CLEARANCE", 1)),
              note="Impect models clearances as pass-type actions; all outcomes summed "
                   "(corr 0.74 vs StatsBomb Clearance events, identical scale -- coding "
                   "differences, same concept)"),
    # --- Passing / possession (rates + ratios) ---
    MetricMap("passes_completed_p90", "rate", "direct", "(passing base)", _r("SUCCESSFUL_PASSES")),
    MetricMap("passes_into_box_p90", "rate", "derived", "OP Passes Into Box",
              _r("SUCCESSFUL_PASSES_TO_PITCH_POSITION_OPPONENT_BOX")),
    MetricMap("pass_completion_pct", "ratio", "derived", "Passing%",
              numer=_r("SUCCESSFUL_PASSES"), denom=(("SUCCESSFUL_PASSES", 1), ("UNSUCCESSFUL_PASSES", 1))),
    MetricMap("goal_conversion_pct", "ratio", "derived", "Goal Conversion Ratio",
              numer=_r("GOALS"), denom=_r("SHOT_AT_GOAL_NUMBER")),
    MetricMap("xg_per_shot", "ratio", "derived", "xG/Shot",
              numer=_r("SHOT_XG"), denom=_r("SHOT_AT_GOAL_NUMBER")),
    # --- On-ball value (Impect PxT is the analogue of StatsBomb OBV) ---
    MetricMap("pass_value_p90", "rate", "analogue", "Pass OBV", _r("PXT_PASS"),
              note="Impect PxT stands in for on-ball value"),
    MetricMap("dribble_carry_value_p90", "rate", "analogue", "Dribble & Carry OBV", _r("PXT_DRIBBLE")),
    MetricMap("defensive_value_p90", "rate", "analogue", "Defensive Action OBV",
              (("PXT_BALL_WIN", 1), ("PXT_BLOCK", 1))),
    MetricMap("on_ball_value_p90", "rate", "analogue", "OBV",
              (("PXT_PASS", 1), ("PXT_DRIBBLE", 1), ("PXT_BALL_WIN", 1),
               ("PXT_BLOCK", 1), ("PXT_SHOT", 1))),
    # --- Impect-native (new capability, no StatsBomb equivalent) ---
    MetricMap("packing_bypassed_opponents_p90", "rate", "native", "(packing)", _r("BYPASSED_OPPONENTS")),
    MetricMap("packing_bypassed_defenders_p90", "rate", "native", "(packing)", _r("BYPASSED_DEFENDERS")),
    MetricMap("packing_xg_p90", "rate", "native", "(packing xG)", _r("PACKING_XG")),
    # --- Duels / defending ---
    MetricMap("ground_duels_won_p90", "rate", "direct", "(tackle analogue)", _r("WON_GROUND_DUELS")),
    MetricMap("ball_wins_p90", "rate", "native", "(Impect ball wins)", _r("BALL_WIN_NUMBER"),
              note="Impect def: regains that take >=1 opponent out of the game (packing-weighted). "
                   "NOT StatsBomb ball recoveries: corr only 0.14, so ball recoveries stays a gap"),
    MetricMap("turnovers_p90", "rate", "direct", "Turnovers", _r("BALL_LOSS_NUMBER")),
    MetricMap("off_ball_receiving_p90", "rate", "native", "(off-ball receiving)",
              _r("BYPASSED_OPPONENTS_RECEIVING"),
              note="opponents taken out of the game by RECEIVING a pass (movement into space), "
                   "not by playing one; a StatsBomb blind spot"),
    MetricMap("pressures_p90", "rate", "analogue", "Pressures", _r("NUMBER_OF_PRESSES"),
              note="Impect def: press = attacking the ball carrier to win it, or within 1m of them. "
                   "Strong match to StatsBomb pressures (corr 0.91, similar scale)"),
    MetricMap("counterpressures_p90", "rate", "analogue", "Counterpressures",
              _r("NUMBER_OF_PRESSES_COUNTER_PRESS"),
              note="Impect def: presses on the opponent's passes while they are in attacking "
                   "transition. Populated for 94% of players; no StatsBomb column to cross-check"),
    MetricMap("deep_progressions_p90", "rate", "analogue", "Deep Progressions",
              _r("BYPASSED_OPPONENTS_TO_PITCH_POSITION_FINAL_THIRD"),
              note="opponents bypassed into the final third (counts opponents, not passes/carries); "
                   "corr 0.81 with StatsBomb passes-into-final-third"),
    MetricMap("aerial_win_pct", "ratio", "derived", "Aerial Win%",
              numer=_r("WON_AERIAL_DUELS"), denom=(("WON_AERIAL_DUELS", 1), ("LOST_AERIAL_DUELS", 1))),
    MetricMap("ground_duel_win_pct", "ratio", "derived", "Tack/Dribbled Past%",
              numer=_r("WON_GROUND_DUELS"), denom=(("WON_GROUND_DUELS", 1), ("LOST_GROUND_DUELS", 1)),
              note="duel win% is the nearest thing to challenge/tackle %"),
    # --- Goalkeeper ---
    MetricMap("gk_conceded_p90", "rate", "direct", "Goals conceded", _r("CONCEDED_GOALS")),
    MetricMap("gk_gsaa_p90", "rate", "derived", "Goals Saved Above Average",
              (("CONCEDED_POSTSHOT_XG", 1), ("CONCEDED_GOALS", -1)),
              note="post-shot xG faced minus goals conceded, per 90"),
    MetricMap("gk_shot_stopping_pct", "ratio", "derived", "Shot Stopping%",
              numer=(("CONCEDED_POSTSHOT_XG", 1), ("CONCEDED_GOALS", -1)), denom=_r("CONCEDED_POSTSHOT_XG"),
              note="club def: 'GSAA as a % of shots faced'. Impect has no shots-faced COUNT, so "
                   "built as GSAA / post-shot xG faced (goals prevented as a share of the xG "
                   "value of on-target shots faced) -- same intent, xG-weighted denominator "
                   "instead of a raw count. Distinct from save_pct: this is quality-of-save, "
                   "save_pct is volume-of-save."),
    # --- Club-framework additions: the four metrics confirmed with the club as the Impect
    #     stand-ins for StatsBomb-only club metrics. Raw KPI columns confirmed present in
    #     every pull. ---
    MetricMap("gk_catches_p90", "rate", "direct", "Claims",
              _r("BALL_WIN_NUMBER_BY_ACTION_CATCH"),
              note="keeper catches (possession regains via catch); the Impect stand-in for the "
                   "club's Claims/CCAA% (a claim-rate metric Impect does not expose)"),
    MetricMap("defensive_touches_outside_box_p90", "rate", "derived", "Goalkeeper Aggressive Distance",
              (("DEFENSIVE_TOUCHES", 1), ("DEFENSIVE_TOUCHES_IN_PITCH_POSITION_OWN_BOX", -1)),
              note="defensive touches outside the own box = a sweeper-keeper proxy for the club's "
                   "'aggressive distance' (Impect has no tracking-based distance, but scopes "
                   "defensive touches by pitch position)"),
    MetricMap("cross_bypassed_opponents_p90", "rate", "native", "Successful Box Cross%",
              (("BYPASSED_OPPONENTS_BY_ACTION_HIGH_CROSS", 1),
               ("BYPASSED_OPPONENTS_BY_ACTION_LOW_CROSS", 1)),
              note="opponents taken out of the game by crossing (high + low crosses combined); the "
                   "Impect stand-in for crossing effectiveness (it has no cross-completion %)"),
    MetricMap("dribble_count_p90", "rate", "native", "Dribbles",
              _r("BYPASSED_OPPONENTS_NUMBER_BY_ACTION_DRIBBLE"),
              note="count of dribble actions that bypass an opponent; the actual dribble-count the "
                   "club asked for alongside dribble & carry value"),
    # --- No Impect equivalent (confirmed via the KPI-definitions API + magnitude checks;
    #     produced from StatsBomb, not Impect) ---
    MetricMap("tackles_p90", "none", "none", "(tackle count)",
              note="no tackle count in Impect; nearest is won ground duels (corr 0.72, ~2x scale) "
                   "-- DELIBERATELY NOT remapped: a 'Tackles' number that is actually duels won "
                   "would mislead; ground_duels_won_p90 is the honestly-named successor at cutoff"),
    MetricMap("interceptions_p90", "none", "none", "Interceptions",
              note="BALL_WIN_NUMBER_BY_ACTION_INTERCEPTION exists but is regains-via-interception "
                   "(corr 0.68, ~5x scale vs StatsBomb Interception events) -- a different "
                   "instrument, deliberately not remapped; ball_wins_p90 family is the successor"),
    MetricMap("ball_recoveries_p90", "none", "none", "Ball recoveries",
              note="both candidates fail: BALL_WIN_NUMBER corr 0.12, LOOSE_BALL_REGAIN corr 0.24 "
                   "-- Impect does not measure this concept; ball_wins_p90 is the successor"),
    MetricMap("gk_saves_p90", "none", "none", "Saves",
              note="SHOT_AT_GOAL_NUMBER_SAVED is SHOOTER-context (a player's OWN shots saved by the "
                   "opponent keeper), confirmed zero for every real goalkeeper in the data. "
                   "BALL_WIN_NUMBER_BY_ACTION_SAVE looked right overall but keeper-only corr is "
                   "0.62: a save is a ball WIN only if the keeper keeps possession, so parried "
                   "saves are missed. No genuine save-count in Impect; gk_gsaa_p90 / "
                   "gk_shot_stopping_pct are the successors at cutoff."),
    MetricMap("save_pct", "none", "none", "Save%",
              note="saves/(saves+conceded) from BALL_WIN_BY_SAVE reaches only corr 0.58 keeper-only "
                   "(same parried-save undercount as gk_saves_p90). Kept on our event aggregate; "
                   "gk_shot_stopping_pct is the successor."),
    MetricMap("pressures_opp_half_p90", "none", "none", "Pressures in Opposing Half",
              note="Impect splits presses by context (build-up / between-lines / counter), not by pitch half"),
    MetricMap("aggressive_actions_p90", "none", "none", "Aggressive Actions",
              note="a StatsBomb composite (tackle+pressure+foul within 2s); no single Impect KPI"),
    MetricMap("padj_tackles_interceptions_p90", "none", "none", "PAdj Tackles & Interceptions",
              note="Impect has no possession adjustment (could be computed by us)"),
    MetricMap("padj_pressures_p90", "none", "none", "PAdj Pressures", note="no possession adjustment"),
    MetricMap("xg_buildup_p90", "none", "none", "xGBuildup",
              note="Impect PACKING_XG/PxT are different value models (non-shot / goal-threat), "
                   "not StatsBomb's possession-chain xG buildup"),
    MetricMap("pressured_pass_pct", "none", "none", "Pressured Pass%",
              note="SUCCESSFUL_PASSES def factors pressure in, but no clean under-pressure pass ratio KPI"),
    MetricMap("successful_box_cross_pct", "none", "none", "Successful Box Cross%",
              note="derivable from Impect LOW_CROSS/HIGH_CROSS action types; not built yet"),
]


def impect_columns_used() -> set[str]:
    """Every Impect column the map references (for verification)."""
    used: set[str] = set()
    for m in IMPECT_MAP:
        if m.kind == "rate":
            used.update(c for c, _ in m.numer)
        elif m.kind == "ratio":
            used.update(c for c, _ in m.numer)
            used.update(c for c, _ in m.denom)
    return used


def mappable() -> list[MetricMap]:
    return [m for m in IMPECT_MAP if m.kind != "none"]


def gaps() -> list[MetricMap]:
    return [m for m in IMPECT_MAP if m.kind == "none"]
