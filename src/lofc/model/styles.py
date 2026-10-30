"""Playing-style labels: WHAT a player tries and WHERE he plays -- and, since 2026-10-30, a
few outcomes the Head of Recruitment asked for.

The Head of Recruitment's 24 styles (owner, 2026-10-23), plus Dribbler for attacking
midfielders, Goalscorer for wingers and his additions of 2026-10-30 (Playing_Profiles_Tweaks_2). A poor playmaker
still ATTEMPTS a playmaker's passes, so most signals are attempts (successful + unsuccessful
+ neutral), shares of the player's own actions, or pitch locations. The owner accepted the
additions WITH their quality signals (assists, xA, goals, xG, carry value, line-breaking
passes, receptions): every signal that measures success is named in QUALITY_SIGNALS and
flagged on the reference page and in the glossary.

Closest Impect metrics, where the request had no exact match (checked against Impect's
catalogue, 2026-10-30): "short passes" -> low passes (Impect: a flat pass, any length; it has
no pass length); "line-breaking passes" -> passes that bypass opponents (completed only);
"received passes" -> receptions that bypass opponents (Impect counts no other receptions);
"attempted dribbles" -> successful dribbles (Impect records no failed dribble count);
"ball carry value" -> PxT Dribbles; "non-penalty / open-play assists" -> assists outside set
pieces (Impect has no penalty split for assists); "open-play xA" -> all xA (no split).

Why not Impect's own 32 player profiles: measured on 2025/26, several track quality -- Deep-
Lying Playmaker correlates 0.69 with our Performance rating, Ball-Playing CB 0.61.

Pure: no database, no Streamlit. `style_run` computes and stores the signals; the dashboard
applies `assign_styles`, so a threshold change is instant.
"""

from __future__ import annotations

import pandas as pd

from lofc.model.scorecard import MIN_PEERS_FOR_RANKING

KEY = ["player_id", "competition_id", "season_id", "position_group"]

# Best fit at or above STRONG (and no signal below FLOOR) is a clear style; a best fit at or
# above FLOOR otherwise "leans". The club's own lines: 70th = Elite, 50th = Minimum Standard.
STRONG = 70.0
FLOOR = 50.0

NO_STYLE = "No standout style"
NOT_ENOUGH = "Not enough minutes"


def attempts(totals: pd.DataFrame, suffix: str) -> pd.Series:
    """Passes TRIED: successful + unsuccessful + neutral (received under high pressure)."""
    zero = pd.Series(0.0, index=totals.index)
    return sum((totals[c] if c in totals.columns else zero)
               for c in (f"{o}_PASSES{suffix}" for o in ("SUCCESSFUL", "UNSUCCESSFUL", "NEUTRAL")))


def _share(num: pd.Series, den: pd.Series) -> pd.Series:
    """num / den, unknown (not zero) where there is nothing to share."""
    return num / den.where(den > 0)


def _p90(total: pd.Series, minutes: pd.Series) -> pd.Series:
    return total * 90.0 / minutes.where(minutes > 0)


def _col(t: pd.DataFrame, name: str) -> pd.Series:
    return t[name] if name in t.columns else pd.Series(0.0, index=t.index)


def _sum(t: pd.DataFrame, names: list[str]) -> pd.Series:
    return sum(_col(t, n) for n in names)


def _touches(t, zones):      # offensive touches in Impect's packing zones
    return _sum(t, [f"OFFENSIVE_TOUCHES_IN_PACKING_ZONE_{z}" for z in zones])


def _receptions(t, suffixes):  # progressive receptions (opponents bypassed, receiver's view)
    return _sum(t, [f"BYPASSED_OPPONENTS_RECEIVING_NUMBER_{s}" for s in suffixes])


_OT = "OFFENSIVE_TOUCHES"
_REC = "BYPASSED_OPPONENTS_RECEIVING_NUMBER"

# name -> f(season totals, minutes). Totals are Impect per-match values x matchShare, summed
# over a player's position rows -- the same rebuild impect_translate uses for per-90 metrics.
SIGNALS = {
    # where he is on the ball
    "touch_box_share": lambda t, m: _share(_col(t, "OFFENSIVE_TOUCHES_IN_PITCH_POSITION_OPPONENT_BOX"), _col(t, _OT)),
    "touch_wide_share": lambda t, m: _share(_touches(t, ["WL", "WR"]), _col(t, _OT)),
    "touch_advanced_wide_share": lambda t, m: _share(_touches(t, ["WL", "WR", "IBWL", "IBWR"]), _col(t, _OT)),
    "touch_am_share": lambda t, m: _share(_touches(t, ["AM"]), _col(t, _OT)),
    "touch_fb_zone_share": lambda t, m: _share(_touches(t, ["FBL", "FBR"]), _col(t, _OT)),
    # where he receives (share of his progressive receptions)
    "rec_in_behind_share": lambda t, m: _share(_receptions(t, ["TO_PACKING_ZONE_IB", "TO_PACKING_ZONE_IBWL", "TO_PACKING_ZONE_IBWR"]), _col(t, _REC)),
    "rec_central_share": lambda t, m: _share(_receptions(t, ["TO_LANE_CENTER", "TO_LANE_LEFT_HALF_SPACE", "TO_LANE_RIGHT_HALF_SPACE"]), _col(t, _REC)),
    "rec_btl_share": lambda t, m: _share(_receptions(t, ["BY_ACTION_AVAILABILITY_BTL"]), _col(t, _REC)),
    "rec_wide_share": lambda t, m: _share(_receptions(t, ["BY_ACTION_AVAILABILITY_OUT_WIDE"]), _col(t, _REC)),
    "rec_deep_run_share": lambda t, m: _share(_receptions(t, ["BY_ACTION_AVAILABILITY_FDR"]), _col(t, _REC)),
    "rec_holdup_share": lambda t, m: _share(_receptions(t, ["BY_ACTION_HOLD_UP_PLAY"]), _col(t, _REC)),
    # what he tries with the ball
    "long_pass_attempt_share": lambda t, m: _share(attempts(t, "_BY_ACTION_DIAGONAL_PASS") + attempts(t, "_BY_ACTION_CHIPPED_PASS"), attempts(t, "")),
    "forward_pass_attempt_share": lambda t, m: _share(attempts(t, "_TO_PITCH_POSITION_FINAL_THIRD") + attempts(t, "_TO_PITCH_POSITION_OPPONENT_BOX"), attempts(t, "")),
    "box_pass_attempts_per_touch": lambda t, m: _share(attempts(t, "_TO_PITCH_POSITION_OPPONENT_BOX"), _col(t, _OT)),
    "cross_attempts_per_touch": lambda t, m: _share(attempts(t, "_BY_ACTION_LOW_CROSS") + attempts(t, "_BY_ACTION_HIGH_CROSS"), _col(t, _OT)),
    "low_pass_attempt_share": lambda t, m: _share(attempts(t, "_BY_ACTION_LOW_PASS"), attempts(t, "")),
    "line_breaking_pass_share": lambda t, m: _share(_col(t, "BYPASSED_OPPONENTS_NUMBER") - _col(t, "BYPASSED_OPPONENTS_NUMBER_BY_ACTION_DRIBBLE"), attempts(t, "")),
    "np_shots_per_touch": lambda t, m: _share(_col(t, "SHOT_AT_GOAL_NUMBER") - _col(t, "SHOT_AT_GOAL_NUMBER_BY_ACTION_PENALTY_KICK"), _col(t, _OT)),
    "dribbles_per_touch": lambda t, m: _share(_col(t, "BYPASSED_OPPONENTS_NUMBER_BY_ACTION_DRIBBLE"), _col(t, _OT)),
    # what comes of it (outcomes the Head of Recruitment asked for, 2026-10-30), per 90
    "assists_non_set_piece_p90": lambda t, m: _p90(_col(t, "ASSISTS") - _col(t, "ASSISTS_AT_PHASE_SET_PIECE"), m),
    "xa_p90": lambda t, m: _p90(_col(t, "EXPECTED_GOAL_ASSISTS"), m),
    "receptions_bypassing_p90": lambda t, m: _p90(_col(t, "BYPASSED_OPPONENTS_RECEIVING_NUMBER"), m),
    "carry_value_p90": lambda t, m: _p90(_col(t, "PXT_DRIBBLE"), m),
    "np_goals_p90": lambda t, m: _p90(_col(t, "GOALS") - _col(t, "GOALS_BY_ACTION_PENALTY_KICK"), m),
    "np_xg_p90": lambda t, m: _p90(_col(t, "SHOT_XG") - _col(t, "SHOT_XG_BY_ACTION_PENALTY_KICK"), m),
    # what he does without the ball (involvement, per 90)
    "defensive_touches_p90": lambda t, m: _p90(_col(t, "DEFENSIVE_TOUCHES"), m),
    "ground_contested_p90": lambda t, m: _p90(_col(t, "WON_GROUND_DUELS") + _col(t, "LOST_GROUND_DUELS"), m),
    "aerial_contested_p90": lambda t, m: _p90(_col(t, "WON_AERIAL_DUELS") + _col(t, "LOST_AERIAL_DUELS"), m),
    "aerial_won_share": lambda t, m: _share(_col(t, "WON_AERIAL_DUELS"), _col(t, "WON_AERIAL_DUELS") + _col(t, "LOST_AERIAL_DUELS")),
    "presses_p90": lambda t, m: _p90(_col(t, "NUMBER_OF_PRESSES"), m),
    "presses_build_up_p90": lambda t, m: _p90(_col(t, "NUMBER_OF_PRESSES_BUILD_UP"), m),
    "counter_presses_p90": lambda t, m: _p90(_col(t, "NUMBER_OF_PRESSES_COUNTER_PRESS"), m),
}

# Plain-English names, for the Style lab and the glossary. One name per signal.
SIGNAL_LABELS = {
    "touch_box_share": "Share of his touches in the box",
    "touch_wide_share": "Share of his touches in wide zones",
    "touch_advanced_wide_share": "Share of his touches in advanced wide zones",
    "touch_am_share": "Share of his touches in the attacking-mid zone",
    "touch_fb_zone_share": "Share of his touches in the full-back zone",
    "rec_in_behind_share": "Share of his receptions in behind",
    "rec_central_share": "Share of his receptions in central lanes",
    "rec_btl_share": "Share of his receptions between the lines",
    "rec_wide_share": "Share of his receptions out wide",
    "rec_deep_run_share": "Share of his receptions from deep runs",
    "rec_holdup_share": "Share of his receptions as hold-up play",
    "long_pass_attempt_share": "Long and diagonal passes, share of his attempts",
    "forward_pass_attempt_share": "Passes into the final third, share of his attempts",
    "box_pass_attempts_per_touch": "Passes into the box attempted, per touch",
    "cross_attempts_per_touch": "Crosses attempted, per touch",
    "low_pass_attempt_share": "Low passes, share of his attempts",
    "line_breaking_pass_share": "Passes that bypass opponents, share of his attempts",
    "np_shots_per_touch": "Non-penalty shots, per touch",
    "dribbles_per_touch": "Successful dribbles, per touch",
    "assists_non_set_piece_p90": "Assists outside set pieces per 90",
    "xa_p90": "Expected assists (xA) per 90",
    "receptions_bypassing_p90": "Receptions that bypass opponents per 90",
    "carry_value_p90": "Ball carry value (PxT) per 90",
    "np_goals_p90": "Non-penalty goals per 90",
    "np_xg_p90": "Non-penalty xG per 90",
    "defensive_touches_p90": "Defensive touches per 90",
    "ground_contested_p90": "Ground duels contested per 90",
    "aerial_contested_p90": "Aerial duels contested per 90",
    "aerial_won_share": "Aerial duels won, share",
    "presses_p90": "Presses per 90",
    "presses_build_up_p90": "Presses on the opponent's build-up per 90",
    "counter_presses_p90": "Counter-presses per 90",
}

QUALITY_SIGNALS = {"aerial_won_share", "dribbles_per_touch", "assists_non_set_piece_p90",
                   "xa_p90", "line_breaking_pass_share", "receptions_bypassing_p90",
                   "carry_value_p90", "np_goals_p90", "np_xg_p90"}


def _att(suffix: str) -> list[str]:
    return [f"{o}_PASSES{suffix}" for o in ("SUCCESSFUL", "UNSUCCESSFUL", "NEUTRAL")]


_ATTEMPTS = "(Successful + Unsuccessful + Neutral Passes)"
_TOUCHES = "Offensive Touches"
_REC_NAME = "Bypassed Opponents Receiving Number"

# signal -> (how it is built, in Impect's own names; the Impect columns whose definitions the
# glossary shows). The only words that are ours are the arithmetic.
SIGNAL_SOURCES: dict[str, tuple[str, list[str]]] = {
    "touch_box_share": (f"{_TOUCHES} · Opponent Box ÷ {_TOUCHES}",
                        ["OFFENSIVE_TOUCHES_IN_PITCH_POSITION_OPPONENT_BOX", _OT]),
    "touch_wide_share": (f"{_TOUCHES} · Wide zones (left + right) ÷ {_TOUCHES}",
                         ["OFFENSIVE_TOUCHES_IN_PACKING_ZONE_WL", "OFFENSIVE_TOUCHES_IN_PACKING_ZONE_WR", _OT]),
    "touch_advanced_wide_share": (f"{_TOUCHES} · Wide + In-Behind Wide zones ÷ {_TOUCHES}",
                                  ["OFFENSIVE_TOUCHES_IN_PACKING_ZONE_WL", "OFFENSIVE_TOUCHES_IN_PACKING_ZONE_IBWL", _OT]),
    "touch_am_share": (f"{_TOUCHES} · Attacking Midfield zone ÷ {_TOUCHES}",
                       ["OFFENSIVE_TOUCHES_IN_PACKING_ZONE_AM", _OT]),
    "touch_fb_zone_share": (f"{_TOUCHES} · Full-back zones ÷ {_TOUCHES}",
                            ["OFFENSIVE_TOUCHES_IN_PACKING_ZONE_FBL", _OT]),
    "rec_in_behind_share": (f"{_REC_NAME} · In-Behind zones ÷ {_REC_NAME}",
                            [f"{_REC}_TO_PACKING_ZONE_IB", _REC]),
    "rec_central_share": (f"{_REC_NAME} · Centre + half-space lanes ÷ {_REC_NAME}",
                          [f"{_REC}_TO_LANE_CENTER", f"{_REC}_TO_LANE_LEFT_HALF_SPACE", _REC]),
    "rec_btl_share": (f"{_REC_NAME} · Between the lines ÷ {_REC_NAME}",
                      [f"{_REC}_BY_ACTION_AVAILABILITY_BTL", _REC]),
    "rec_wide_share": (f"{_REC_NAME} · Out wide ÷ {_REC_NAME}",
                       [f"{_REC}_BY_ACTION_AVAILABILITY_OUT_WIDE", _REC]),
    "rec_deep_run_share": (f"{_REC_NAME} · Deep runs ÷ {_REC_NAME}",
                           [f"{_REC}_BY_ACTION_AVAILABILITY_FDR", _REC]),
    "rec_holdup_share": (f"{_REC_NAME} · Hold-up play ÷ {_REC_NAME}",
                         [f"{_REC}_BY_ACTION_HOLD_UP_PLAY", _REC]),
    "long_pass_attempt_share": (f"{_ATTEMPTS} · Diagonal + Chipped ÷ {_ATTEMPTS}",
                                _att("_BY_ACTION_DIAGONAL_PASS")[:1] + _att("_BY_ACTION_CHIPPED_PASS")[:1] + _att("")),
    "forward_pass_attempt_share": (f"{_ATTEMPTS} · Final Third + Opponent Box ÷ {_ATTEMPTS}",
                                   _att("_TO_PITCH_POSITION_FINAL_THIRD")[:1] + _att("")),
    "box_pass_attempts_per_touch": (f"{_ATTEMPTS} · Opponent Box ÷ {_TOUCHES}",
                                    _att("_TO_PITCH_POSITION_OPPONENT_BOX")[:1] + _att("") + [_OT]),
    "cross_attempts_per_touch": (f"{_ATTEMPTS} · Low Cross + High Cross ÷ {_TOUCHES}",
                                 _att("_BY_ACTION_LOW_CROSS")[:1] + _att("_BY_ACTION_HIGH_CROSS")[:1] + _att("") + [_OT]),
    "low_pass_attempt_share": (f"{_ATTEMPTS} · Low Pass ÷ {_ATTEMPTS}",
                               _att("_BY_ACTION_LOW_PASS")[:1] + _att("")),
    "line_breaking_pass_share": (f"(Bypassed Opponents Number − Bypassed Opponents Number · Dribble) ÷ {_ATTEMPTS}",
                                 ["BYPASSED_OPPONENTS_NUMBER", "BYPASSED_OPPONENTS_NUMBER_BY_ACTION_DRIBBLE"] + _att("")),
    "np_shots_per_touch": (f"(Total Shots − Total Shots · Penalty) ÷ {_TOUCHES}",
                           ["SHOT_AT_GOAL_NUMBER", "SHOT_AT_GOAL_NUMBER_BY_ACTION_PENALTY_KICK", _OT]),
    "dribbles_per_touch": (f"Bypassed Opponents Number · Dribble ÷ {_TOUCHES}",
                           ["BYPASSED_OPPONENTS_NUMBER_BY_ACTION_DRIBBLE", _OT]),
    "assists_non_set_piece_p90": ("(Assists − Assists · Set Piece Phase), per 90",
                                  ["ASSISTS", "ASSISTS_AT_PHASE_SET_PIECE"]),
    "xa_p90": ("Expected Goal Assists, per 90", ["EXPECTED_GOAL_ASSISTS"]),
    "receptions_bypassing_p90": (f"{_REC_NAME}, per 90", [_REC]),
    "carry_value_p90": ("Dribbles (PxT), per 90", ["PXT_DRIBBLE"]),
    "np_goals_p90": ("(Goals − Goals · Penalty), per 90",
                     ["GOALS", "GOALS_BY_ACTION_PENALTY_KICK"]),
    "np_xg_p90": ("(Shot-based xG − Shot-based xG · Penalty), per 90",
                  ["SHOT_XG", "SHOT_XG_BY_ACTION_PENALTY_KICK"]),
    "defensive_touches_p90": ("Defensive Touches, per 90", ["DEFENSIVE_TOUCHES"]),
    "ground_contested_p90": ("(Won Ground Duels + Lost Ground Duels), per 90",
                             ["WON_GROUND_DUELS", "LOST_GROUND_DUELS"]),
    "aerial_contested_p90": ("(Won Aerial Duels + Lost Aerial Duels), per 90",
                             ["WON_AERIAL_DUELS", "LOST_AERIAL_DUELS"]),
    "aerial_won_share": ("Won Aerial Duels ÷ (Won Aerial Duels + Lost Aerial Duels)",
                         ["WON_AERIAL_DUELS", "LOST_AERIAL_DUELS"]),
    "presses_p90": ("Number of presses, per 90", ["NUMBER_OF_PRESSES"]),
    "presses_build_up_p90": ("Number of presses in build-up, per 90", ["NUMBER_OF_PRESSES_BUILD_UP"]),
    "counter_presses_p90": ("Number of presses in counter press, per 90",
                            ["NUMBER_OF_PRESSES_COUNTER_PRESS"]),
}

# style group -> label group -> style -> signals. Most groups have one label group; wingers
# are labelled twice, WHERE they play and WHAT they do (the Head of Recruitment's wording).
STYLES: dict[str, dict[str, dict[str, list[str]]]] = {
    "Full Back": {"Style": {
        "Attacking": ["touch_advanced_wide_share", "box_pass_attempts_per_touch",
                      "cross_attempts_per_touch", "assists_non_set_piece_p90", "xa_p90"],
        "Defending": ["touch_fb_zone_share", "ground_contested_p90"],
        "Inside": ["rec_central_share", "rec_btl_share"]}},
    "Centre Back": {"Style": {
        "Aerial": ["aerial_contested_p90", "aerial_won_share"],
        # Long passes left Ball-playing and Playmaker (owner, 2026-10-30): they pull against
        # low passes (r -0.53 CB, -0.60 CM), and with both almost nobody was Strong.
        "Ball-playing": ["forward_pass_attempt_share", "low_pass_attempt_share",
                         "line_breaking_pass_share"],
        "Aggressive": ["presses_p90", "ground_contested_p90"]}},
    "Central midfield": {"Style": {
        "Destroyer": ["ground_contested_p90", "defensive_touches_p90", "presses_p90",
                      "counter_presses_p90"],
        "Playmaker": ["forward_pass_attempt_share", "receptions_bypassing_p90",
                      "low_pass_attempt_share", "line_breaking_pass_share"],
        "Box-to-box": ["touch_box_share", "defensive_touches_p90"]}},
    "Attacking Mid": {"Style": {
        "Box-to-box": ["touch_box_share", "defensive_touches_p90"],
        "Runner": ["rec_deep_run_share", "touch_box_share"],
        "Pocket": ["rec_btl_share", "touch_am_share"],
        "Dribbler": ["dribbles_per_touch", "carry_value_p90"]}},
    "Winger": {
        "Where": {"In behind": ["rec_in_behind_share"],
                  "Pocket": ["rec_btl_share", "rec_central_share"],
                  "Wide": ["rec_wide_share", "touch_wide_share"]},
        "What": {"1v1": ["dribbles_per_touch"],
                 "Creator": ["box_pass_attempts_per_touch", "cross_attempts_per_touch",
                             "xa_p90", "touch_box_share", "assists_non_set_piece_p90"],
                 # Requested by the Head of Recruitment; the Scorer's signals (owner, 2026-10-30)
                 "Goalscorer": ["np_shots_per_touch", "touch_box_share", "np_goals_p90",
                                "np_xg_p90"]}},
    "Centre Forward": {"Style": {
        "Target man": ["aerial_contested_p90", "rec_holdup_share"],
        "In behind": ["rec_in_behind_share"],
        "Presser": ["presses_build_up_p90", "counter_presses_p90"],
        "Scorer": ["np_shots_per_touch", "touch_box_share", "np_goals_p90", "np_xg_p90"]}},
}


# Positions that share one style group. Impect labels a two-man midfield as two DEFENSIVE
# midfielders and uses central midfield only for the middle of a three, so 2026/27 had 31
# rated central midfielders across 7 leagues -- every league pool under the floor. They have
# the same three styles, so for STYLE they are compared together (owner, 2026-10-23). The
# ratings are untouched: the club framework still scores DM and CM on their own lists.
STYLE_GROUPS = {"Defensive Mid": "Central midfield", "Central Mid": "Central midfield"}


def style_group(position_group: str | None) -> str | None:
    """The style group a position is labelled and compared within."""
    return STYLE_GROUPS.get(position_group, position_group)


def compute_signals(totals: pd.DataFrame, minutes: pd.Series) -> pd.DataFrame:
    """Every signal for every row of `totals` (season totals, index = player)."""
    out = pd.DataFrame({name: f(totals, minutes) for name, f in SIGNALS.items()},
                       index=totals.index)
    return out.replace([float("inf"), float("-inf")], float("nan"))


def signal_percentiles(frame: pd.DataFrame) -> pd.DataFrame:
    """Mid-rank percentile (0-100) of every signal within league + season + style group, over
    450+ minute players -- the convention `scorecard.metric_percentiles` uses. A pool below
    MIN_PEERS_FOR_RANKING gets none: a percentile among four players means nothing."""
    out = frame[KEY].copy()
    rated = frame[frame["rankable"].astype(bool)] if "rankable" in frame.columns else frame
    rated = rated.assign(_style_group=rated["position_group"].map(style_group))
    group = rated.groupby(["competition_id", "season_id", "_style_group"])
    pool = group["player_id"].transform("count")
    for sig in [c for c in SIGNALS if c in frame.columns]:
        pct = (group[sig].rank() - 0.5).div(group[sig].transform("count")) * 100.0
        out[sig] = pct.where(pool >= MIN_PEERS_FOR_RANKING)
    return out


def _group_styles(fits: dict[str, float], ok: dict[str, bool], strong: float,
                  floor: float) -> tuple[list[str], str | None]:
    """(Strong styles by fit, the Leans style) for one label group. A Leans style exists only
    when nothing in the group is Strong."""
    known = {s: f for s, f in fits.items() if pd.notna(f)}
    if not known:
        return [], None
    strongs = sorted((s for s, f in known.items() if f >= strong and ok[s]),
                     key=lambda s: -known[s])
    if strongs:
        return strongs, None
    best = max(known, key=known.get)
    return [], (best if known[best] >= floor else None)


def assign_styles(pcts: pd.DataFrame, strong: float = STRONG,
                  floor: float = FLOOR) -> pd.DataFrame:
    """One row per player: `style_label`, `tier` (Strong / Leans / None) and `fit.<style>`
    for every style of his position, for the style lab.

    Fit = the average percentile of a style's signals. Strong needs fit >= `strong` AND no
    signal below `floor`; otherwise his best fit >= `floor` "leans". Other Strong styles in
    the same group are added; a winger's Where and What are labelled separately."""
    rows = []
    for rec in pcts.to_dict("records"):
        groups = STYLES.get(style_group(rec.get("position_group")))
        row = {k: rec.get(k) for k in KEY}
        if not groups:
            rows.append({**row, "style_label": None, "tier": None,
                         "strong_styles": [], "leans_styles": []})
            continue
        parts, tiers, any_known = [], [], False
        strong_all, leans_all = [], []
        for styles in groups.values():
            fits, ok = {}, {}
            for style, sigs in styles.items():
                vals = [rec.get(s) for s in sigs]
                known = [v for v in vals if v is not None and pd.notna(v)]
                fits[style] = sum(known) / len(known) if len(known) == len(sigs) else float("nan")
                ok[style] = len(known) == len(sigs) and min(known) >= floor
                row[f"fit.{style}"] = fits[style]
            any_known |= any(pd.notna(f) for f in fits.values())
            strongs, leans = _group_styles(fits, ok, strong, floor)
            strong_all += strongs
            if strongs:
                parts.append(" · ".join(strongs))
                tiers.append("Strong")
            elif leans:
                leans_all.append(leans)
                parts.append(f"Leans {leans}")
                tiers.append("Leans")
        row.update(strong_styles=strong_all, leans_styles=leans_all)
        if not any_known:
            row.update(style_label=NOT_ENOUGH, tier=None)
        elif not parts:
            row.update(style_label=NO_STYLE, tier=None)
        else:
            row.update(style_label=" · ".join(parts),
                       tier="Strong" if "Strong" in tiers else "Leans")
        rows.append(row)
    return pd.DataFrame(rows)


def style_options(position_group: str | None) -> list[str]:
    """The styles offered for a position, in label-group order (a winger's Where, then What)."""
    groups = STYLES.get(style_group(position_group), {})
    return [style for styles in groups.values() for style in styles]


def _as_list(value) -> list[str]:
    return list(value) if isinstance(value, (list, tuple)) else []


def style_pills(row) -> list[str]:
    """The table's pills: Strong styles by name, Leans styles marked in words (the table
    draws every pill alike). "No standout style" is one pill; no minutes, none."""
    strong = _as_list(row.get("strong_styles"))
    leans = [f"{s} (leans)" for s in _as_list(row.get("leans_styles"))]
    if strong or leans:
        return strong + leans
    return [NO_STYLE] if row.get("style_label") == NO_STYLE else []


def has_style(row, style: str, strong_only: bool = False) -> bool:
    """The Players page's Style filter: Strong in `style`, or Leans in it unless
    `strong_only`."""
    if style in _as_list(row.get("strong_styles")):
        return True
    return (not strong_only) and style in _as_list(row.get("leans_styles"))
