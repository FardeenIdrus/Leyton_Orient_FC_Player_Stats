"""Leyton Orient's real recruitment framework, encoded from the club's two documents:
`LOFC - Position Archetype.docx` and `Impect Data - Positional Metrics.xlsx`.

This is the single source of truth for WHAT the club measures and HOW it weights it. The
scoring engine (`scorecard.py`) turns it into the club's 1-5 composite per player.

THE FRAMEWORK (from the docx)
  A player is scored 1-5 on seven dimensions, combined as a weighted average:
    Performance/Technical, Physical, Psychological, Medical Risk, Financial Fit, Resale.
  Composite < 3.0 = do not proceed; any single dimension < 2.0 = automatic veto.
  Per-metric bar (from the club's own thresholds): Minimum = > league median (50th pct),
  Elite = > 70th percentile.

FIVE DECISIONS resolved objectively from the club's own numbers (documented in the UI),
so the club did not have to be asked (the 5th is at DIMENSION_WEIGHTS below: the outfield
weights sum to 110% in the doc, so we normalise each position to 1.0):

  1. Per-metric weight WITHIN a dimension -> EQUAL. The club lists metrics as a flat set of
     "key indicators" with no individual weights; equal weight adds no unstated preference.

  2. Percentile -> 1-5 band -> LINEAR, anchored on the club's own two thresholds
     (median = "Minimum Standard", 70th = "Elite"): band = 3 + (percentile - 50) / 20,
     clamped to [1, 5]. So a league-median player scores exactly 3.0 (their stated minimum
     composite) and a bottom-third dimension falls below 2.0 (their stated veto). Nothing
     is arbitrary -- both anchors are the club's.

  3. GK Physical -> folded into Performance (50%), per the GK archetype table (the
     position-specific spec beats the generic worked example, and a keeper's physical
     output is far less decision-relevant than an outfielder's).

  4. Psych/Medical/Financial/Resale -> automate what is genuinely data-driven, collect what
     is not. Financial Fit and Resale Potential are computed from data we already hold
     (value, wage, ceiling, age, contract) and are overridable; Psychological and Medical
     are human judgements entered by a scout. The composite is shown in two honest tiers:
     a data composite (renormalised over the dimensions data can score) and a full composite
     once the scout dimensions are entered. Players with no market value (Scottish/PL2) are
     never excluded -- Financial/Resale simply drop out and the composite renormalises.

Positions: the club sheets use 9 labels; we map them onto the platform's 8 position groups.
Defensive Mid and Central Mid share the club's "Centre Midfield" list (archetype
sub-profiles are Phase 2). Full Back = the identical Left/Right Back list; Winger = the
identical Left/Right Winger list.
"""

from __future__ import annotations

from lofc.ingest.skillcorner_map import LOWER_IS_BETTER as _SC_LOWER

# --- the seven dimensions -------------------------------------------------------------
PERFORMANCE = "Performance"   # "Technical" for outfielders in the docx; the on-ball/defensive metrics
PHYSICAL = "Physical"         # SkillCorner tracking
PSYCHOLOGICAL = "Psychological"
MEDICAL = "Medical Risk"
FINANCIAL = "Financial Fit"
RESALE = "Resale Potential"

DATA_DIMENSIONS = [PERFORMANCE, PHYSICAL, FINANCIAL, RESALE]   # scored from data
SCOUT_DIMENSIONS = [PSYCHOLOGICAL, MEDICAL]                     # entered by a human

# --- per-position dimension weights (from the docx archetype tables) ------------------
# Decision 5 (a club-document inconsistency, resolved objectively): the outfield tables
# list weights that sum to 110% (Performance 40 + Physical 30 + Psych 10 + Medical 15 +
# Financial 10 + Resale 5), while GK sums correctly to 100%. Rather than guess which number
# is a typo, we NORMALISE each position's weights to sum to 1.0 -- assumption-free, and it
# preserves the club's intended relative emphasis exactly. (GK normalisation is a no-op.)
# The raw as-authored numbers are kept below for traceability.
_RAW_WEIGHTS: dict[str, dict[str, float]] = {
    "Goalkeeper": {PERFORMANCE: 0.50, PSYCHOLOGICAL: 0.20, MEDICAL: 0.15,
                   FINANCIAL: 0.10, RESALE: 0.05},   # sums to 1.00
}
_RAW_OUTFIELD = {PERFORMANCE: 0.40, PHYSICAL: 0.30, PSYCHOLOGICAL: 0.10,
                 MEDICAL: 0.15, FINANCIAL: 0.10, RESALE: 0.05}   # sums to 1.10 (club quirk)
for _pos in ("Centre Back", "Full Back", "Defensive Mid", "Central Mid",
             "Attacking Mid", "Winger", "Centre Forward"):
    _RAW_WEIGHTS[_pos] = dict(_RAW_OUTFIELD)


def _normalise(weights: dict[str, float]) -> dict[str, float]:
    total = sum(weights.values())
    return {dim: round(w / total, 4) for dim, w in weights.items()}


DIMENSION_WEIGHTS: dict[str, dict[str, float]] = {
    pos: _normalise(w) for pos, w in _RAW_WEIGHTS.items()
}

# --- the club's Performance metric list per position (internal metric names) ----------
# Taken verbatim (resolved to our names) from the Impect positional workbook's Input sheet.
# Some are StatsBomb-era concepts Impect has no exact twin for; CLUB_SUCCESSOR (below) maps
# each to the metric the platform actually stores, per the decisions agreed with the club.
PERFORMANCE_METRICS: dict[str, list[str]] = {
    "Goalkeeper": [
        "xg_buildup_p90", "gk_aggressive_distance", "gk_gsaa_p90", "gk_shot_stopping_pct",
        "long_ball_pct", "pressured_pass_pct", "gk_claims_pct", "save_pct",
    ],
    "Centre Back": [
        "aggressive_actions_p90", "aerial_win_pct", "ground_duel_win_pct",
        "padj_tackles_interceptions_p90", "counterpressures_p90", "padj_pressures_p90",
        "pressures_opp_half_p90", "defensive_value_p90", "touches_in_box_p90",
        "pass_completion_pct", "pressured_pass_pct", "deep_progressions_p90",
        "pass_value_p90", "turnovers_p90", "xg_buildup_p90", "blocks_p90",
    ],
    "Full Back": [
        "aggressive_actions_p90", "aerial_win_pct", "ground_duel_win_pct",
        "padj_tackles_interceptions_p90", "counterpressures_p90", "padj_pressures_p90",
        "pressures_opp_half_p90", "defensive_value_p90", "assists_p90",
        "open_play_assists_p90", "xa_p90", "goals_p90", "passes_into_box_p90",
        "touches_in_box_p90", "successful_box_cross_pct", "pass_completion_pct",
        "pressured_pass_pct", "deep_progressions_p90", "pass_value_p90",
        "dribble_carry_value_p90", "turnovers_p90", "dribble_success_pct",
        "dribbles_p90", "np_xg_p90", "np_xg_xa_p90",
    ],
    # Defensive Mid and Central Mid share the club's single "Centre Midfield" list
    # (archetype sub-profiles are Phase 2).
    "Defensive Mid": [
        "aggressive_actions_p90", "aerial_win_pct", "padj_tackles_interceptions_p90",
        "counterpressures_p90", "padj_pressures_p90", "xa_p90", "passes_into_box_p90",
        "pass_completion_pct", "pressured_pass_pct", "deep_progressions_p90",
        "pass_value_p90", "dribble_carry_value_p90", "turnovers_p90", "xg_buildup_p90",
        "assists_p90", "open_play_assists_p90", "goals_p90",
    ],
    "Central Mid": [
        "aggressive_actions_p90", "aerial_win_pct", "padj_tackles_interceptions_p90",
        "counterpressures_p90", "padj_pressures_p90", "xa_p90", "passes_into_box_p90",
        "pass_completion_pct", "pressured_pass_pct", "deep_progressions_p90",
        "pass_value_p90", "dribble_carry_value_p90", "turnovers_p90", "xg_buildup_p90",
        "assists_p90", "open_play_assists_p90", "goals_p90",
    ],
    "Attacking Mid": [
        "aggressive_actions_p90", "counterpressures_p90", "padj_pressures_p90",
        "pressures_opp_half_p90", "assists_p90", "open_play_assists_p90", "xa_p90",
        "goals_p90", "shots_p90", "np_xg_p90", "passes_into_box_p90", "touches_in_box_p90",
        "successful_box_cross_pct", "pass_completion_pct", "pressured_pass_pct",
        "deep_progressions_p90", "on_ball_value_p90", "pass_value_p90",
        "dribble_carry_value_p90", "dribbles_p90", "turnovers_p90", "xg_buildup_p90",
        "dribble_success_pct", "np_xg_xa_p90",
    ],
    "Winger": [
        "aggressive_actions_p90", "counterpressures_p90", "padj_pressures_p90",
        "pressures_opp_half_p90", "assists_p90", "open_play_assists_p90", "xa_p90",
        "goals_p90", "shots_p90", "np_xg_p90", "passes_into_box_p90", "touches_in_box_p90",
        "successful_box_cross_pct", "pass_completion_pct", "pressured_pass_pct",
        "deep_progressions_p90", "on_ball_value_p90", "pass_value_p90",
        "dribble_carry_value_p90", "dribbles_p90", "turnovers_p90", "xg_buildup_p90",
        "dribble_success_pct", "np_xg_xa_p90",
    ],
    "Centre Forward": [
        "aggressive_actions_p90", "counterpressures_p90", "padj_pressures_p90",
        "pressures_opp_half_p90", "assists_p90", "open_play_assists_p90", "xa_p90",
        "goals_p90", "shots_p90", "np_xg_p90", "passes_into_box_p90", "touches_in_box_p90",
        "successful_box_cross_pct", "pass_completion_pct", "pressured_pass_pct",
        "deep_progressions_p90", "on_ball_value_p90", "pass_value_p90",
        "dribble_carry_value_p90", "dribbles_p90", "turnovers_p90", "xg_buildup_p90",
        "aerial_win_pct", "goal_conversion_pct", "xg_overperformance_p90", "xg_per_shot",
    ],
}

# --- the club's Physical list (SkillCorner), shared by every outfield position ---------
# GK has no Physical dimension (folded into Performance, decision 3), so gets an empty list.
_OUTFIELD_PHYSICAL = [
    "distance_p90", "meters_per_minute", "hsr_count_p90", "hsr_distance_p90",
    "sprint_count_p90", "sprint_distance_p90", "psv99_kmh", "top5_psv99_kmh",
]
PHYSICAL_METRICS: dict[str, list[str]] = {
    pos: ([] if pos == "Goalkeeper" else list(_OUTFIELD_PHYSICAL))
    for pos in DIMENSION_WEIGHTS
}

# --- club-intended metric -> the metric the platform actually STORES -------------------
# The club framework leans on StatsBomb-era concepts Impect has no exact twin for. Per the
# decisions confirmed with the club, each maps to its Impect successor. All four one-time
# additions below are now ingested (impect_map entries + migration + rebuild); any target
# still absent from a player's data simply drops out of the equal-weight average.
CLUB_SUCCESSOR: dict[str, str] = {
    "gk_aggressive_distance": "defensive_touches_outside_box_p90",
    "gk_claims_pct": "gk_catches_p90",
    "successful_box_cross_pct": "cross_bypassed_opponents_p90",      # high + low cross
    "dribbles_p90": "dribble_count_p90",                             # actual dribble count
    "save_pct": "gk_shot_stopping_pct",
    "xg_buildup_p90": "pass_value_p90",
    "pressured_pass_pct": "packing_bypassed_opponents_p90",          # bypassed opponents
    "aggressive_actions_p90": "ball_wins_p90",
    "padj_tackles_interceptions_p90": "ground_duel_win_pct",
    "padj_pressures_p90": "pressures_p90",
    "pressures_opp_half_p90": "counterpressures_p90",
    "dribble_success_pct": "dribble_carry_value_p90",
    "long_ball_pct": "",   # no Impect equivalent; drops out of the average
}
# All four one-time additions are now ingested and live (kept as a record; nothing pending).
PENDING_INGEST: set[str] = set()

# Metrics where a LOWER raw value is better, so their percentile must be inverted before
# banding. Turnovers (ball losses) from the performance set; plus any lower-is-better
# SkillCorner physical metric (the club's physical list is all higher-is-better, but guard).
LOWER_IS_BETTER = {"turnovers_p90"} | set(_SC_LOWER)

# --- percentile -> 1-5 band (decision 2), anchored on the club's own thresholds --------
def band(percentile: float) -> float:
    """Map a 0-100 percentile to the club's 1-5 dimension band. Median (50) -> 3.0
    (minimum standard); 70th -> 4.0 (elite); linear, clamped to [1, 5]."""
    return max(1.0, min(5.0, 3.0 + (percentile - 50.0) / 20.0))


MIN_COMPOSITE = 3.0     # club: composite below this = do not proceed
VETO_BAND = 2.0         # club: any single dimension below this = automatic veto


def resolve_metric(club_metric: str) -> str:
    """The metric the platform stores for a club-intended metric ('' if none)."""
    return CLUB_SUCCESSOR.get(club_metric, club_metric)


def performance_metrics_live(position: str) -> list[tuple[str, str]]:
    """(club-intended, stored) metric pairs for a position's Performance dimension,
    dropping any with no stored equivalent (e.g. long_ball_pct)."""
    out = []
    for m in PERFORMANCE_METRICS.get(position, []):
        live = resolve_metric(m)
        if live:
            out.append((m, live))
    return out


# --- Archetype sub-profiles (an optional emphasis lens, opt-in) -----------------------
# Within a position, an archetype scores the Performance dimension on a SUBSET of the
# position's metrics, so a recruiter can rank players AS a specific type ("Attacking full
# back"). An archetype = the full PERFORMANCE_METRICS list MINUS the capabilities that
# archetype's column drops in the club's positional workbook. "All Metrics" is the default
# (the full list); the all-round composite always stays visible alongside.
#
# Only Full Back and Winger have archetypes derivable cleanly from the club sheet (their
# archetype columns are a clean include/exclude of the base list). Midfield's three club
# archetypes are genuinely different lists that the workbook does not fully specify, so they
# are NOT invented here (that would re-introduce made-up scoring); a midfield split awaits
# the club's per-archetype metric lists. GK/CB/CF have a single profile by design.
ARCHETYPE_DROPS: dict[str, dict[str, set[str]]] = {
    "Full Back": {
        # drops the deep-defending capabilities (Intercepting, Defend aerial, Win 2nd balls)
        "Attacking": {"padj_tackles_interceptions_p90", "aerial_win_pct", "aggressive_actions_p90"},
        # drops the attacking / carrying capabilities (carrying, dribbling, crossing, box, shots)
        "Progressive Build & Recovery": {
            "dribble_carry_value_p90", "dribble_success_pct", "dribbles_p90", "np_xg_p90",
            "passes_into_box_p90", "touches_in_box_p90", "successful_box_cross_pct"},
    },
    "Winger": {
        # drops safe-possession ("keep the ball") + crossing
        "Direct & 1v1 Specialist": {
            "pass_completion_pct", "pressured_pass_pct", "turnovers_p90", "successful_box_cross_pct"},
        # drops solo ball-carrying
        "Crossing & Creative Threat": {"dribble_carry_value_p90"},
    },
}

DEFAULT_ARCHETYPE = "All Metrics"


def archetypes_for(position: str) -> list[str]:
    """Archetype names for a position, always led by 'All Metrics' (the default, full list)."""
    return [DEFAULT_ARCHETYPE] + list(ARCHETYPE_DROPS.get(position, {}).keys())


def performance_metrics_for_archetype(position: str, archetype: str) -> list[str]:
    """The club-intended Performance metrics for a position's archetype. 'All Metrics'
    (or an unknown archetype) returns the full list."""
    base = PERFORMANCE_METRICS.get(position, [])
    drop = ARCHETYPE_DROPS.get(position, {}).get(archetype, set())
    return [m for m in base if m not in drop]
