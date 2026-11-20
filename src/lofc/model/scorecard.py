"""The club's 1-5 composite scorecard, computed per player from the framework in
`club_framework.py`.

Pipeline per player (all within position group + league):
  1. every framework metric -> a direction-aware percentile (higher percentile = better;
     lower-is-better metrics are inverted first);
  2. percentile -> a 1-5 band (club-anchored: median->3, 70th->4);
  3. average of the bands in a dimension -> that dimension's 1-5 score: Performance
     weighted by the club's per-metric weights (`performance_weights`, 2026-11-02),
     Physical equal-weighted (metrics with no data drop out and the remaining weights are
     rescaled, so a missing metric never deflates the score);
  4. weighted average of the dimension scores -> a composite, renormalised over the
     dimensions actually present (so a player with no market value, hence no
     Financial/Resale, still gets a composite and stays in the ranking).

THREE composites, kept as separate columns so modelled money and human judgement never
distort the headline order:
  * objective_composite -- Performance + Physical only. Built entirely on real Impect +
    SkillCorner data. This is the DEFAULT ranking (the shortlist's RANK_COLUMN).
  * full_composite -- adds the MODELLED Financial + Resale dimensions. Clearly labelled as
    part-modelled; never used to rank.
  * assessed_composite -- Performance + Physical + Psychological + Medical (Decision 15).
    Adds human scout judgement but DELIBERATELY EXCLUDES Financial + Resale, even when
    both are present for the same player -- see ASSESSED_DIMENSIONS below, which must
    never be "completed" to include them. NULL unless a player has BOTH Psychological and
    Medical (Decision 9): one scout dimension present is not a partial assessment.

Performance and Physical come from the metric table here. Financial and Resale are computed
from valuation/age/wage data (financial_resale.py) and passed in. Psychological and Medical
are human scout inputs (scout_scores.py), passed in the same way; a player with no
assessment simply has no assessed_composite -- objective_composite and full_composite are
computed exactly as if scout_bands were never passed.

GATES ARE ADVISORY ONLY. The club framework's "composite < 3.0 = do not proceed" and
"dimension < 2.0 = veto" are computed and surfaced as flags for transparency, but NEVER
exclude a player from the ranking -- the platform must not be aggressive about excluding
players. Filtering stays opt-in (the affordability toggle), and every league's players
remain in the list.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

import pandas as pd

from lofc.model import club_framework as cf
from lofc.model import performance_weights as pw

KEY = ["player_id", "competition_id", "season_id", "position_group"]

# Decision 15: assessed_composite is real data (Performance, Physical) plus human judgement
# (Psychological, Medical) -- deliberately NOT cf.DATA_DIMENSIONS, which also carries the
# modelled Financial and Resale dimensions. Money stays out of every ranking-shaped number
# in the platform; do not "complete" this list later.
ASSESSED_DIMENSIONS = [cf.PERFORMANCE, cf.PHYSICAL] + cf.SCOUT_DIMENSIONS

# --- the midfield fallback pool (owner-approved 2026-11-16) -------------------------------
# A Defensive / Central / Attacking Mid whose own league-season pool is below
# MIN_PEERS_FOR_RANKING is rated against every rankable midfielder of that league-season
# combined: his PERCENTILES come from the combined pool, his metrics and weights stay his own
# position's. Why: early in a season many midfield pools are thin (on 2026-11-16 Lyall
# Cameron was the only rankable Scottish Premiership Central Mid -- alone in a pool, every
# percentile is 50.0 by construction, so every band 3.00). If the
# combined pool is also below the floor he stays not rated. Every pool already at the floor,
# and every non-midfield pool, is untouched.
MIDFIELD_POSITIONS = ("Defensive Mid", "Central Mid", "Attacking Mid")
POOL_POSITION = "position"          # rated within his own position group (the normal case)
POOL_MIDFIELD = "midfield"          # rated within all midfielders of his league-season
MIDFIELD_POOL_TAG = "Rated against all midfielders"


def pool_assignment(counts: dict) -> dict:
    """{(competition_id, season_id, position_group): own pool size} -> {same key: (scope,
    size of the pool he is rated in)}. A thin midfield group moves to the combined midfield
    pool of its league-season when that pool reaches MIN_PEERS_FOR_RANKING; nothing else
    moves."""
    combined: dict = {}
    for (comp, season, pos), n in counts.items():
        if pos in MIDFIELD_POSITIONS:
            combined[(comp, season)] = combined.get((comp, season), 0) + int(n)
    out = {}
    for key, n in counts.items():
        comp, season, pos = key
        both = combined.get((comp, season), 0)
        if (pos in MIDFIELD_POSITIONS and int(n) < MIN_PEERS_FOR_RANKING
                and both >= MIN_PEERS_FOR_RANKING):
            out[key] = (POOL_MIDFIELD, both)
        else:
            out[key] = (POOL_POSITION, int(n))
    return out


def _rankable(neutral: pd.DataFrame) -> pd.DataFrame:
    return neutral[neutral["rankable"]].copy() if "rankable" in neutral.columns else neutral.copy()


def _group_counts(df: pd.DataFrame) -> dict:
    if len(df) == 0:
        return {}
    return df.groupby(["competition_id", "season_id", "position_group"]).size().to_dict()


def metric_percentiles(neutral: pd.DataFrame) -> pd.DataFrame:
    """Direction-aware percentile (0-100) per metric, within competition + season + position
    group, over rankable players only. Lower-is-better metrics are inverted so a high percentile
    always means 'good'. Returns one row per player keyed by KEY, one column per metric.

    Midfield fallback: a thin Defensive / Central / Attacking Mid group takes its percentiles
    from the combined midfield pool of its league-season (`pool_assignment`); every other row
    is exactly the per-position computation.

    Season is part of the grouping so a call on an unfiltered two-season frame still ranks each
    player within his own season (the live path pre-filters to one season, so this is a guard)."""
    df = _rankable(neutral)
    metric_cols = [c for c in df.columns if c not in set(KEY) | {"rankable", "minutes", "name",
                                                                  "team_name", "player_name", "id"}]
    group = df.groupby(["competition_id", "season_id", "position_group"])
    pools = pool_assignment(_group_counts(df))
    keys = list(zip(df["competition_id"], df["season_id"], df["position_group"]))
    fallback = pd.Series([pools[k][0] == POOL_MIDFIELD for k in keys], index=df.index,
                         dtype=bool)
    mids = df[df["position_group"].isin(MIDFIELD_POSITIONS)]
    mid_group = mids.groupby(["competition_id", "season_id"]) if fallback.any() else None
    out = df[KEY].copy()
    for m in metric_cols:
        # MID-RANK, not rank/n. pandas' `rank(pct=True)` returns rank / n with ranks
        # running 1..n, so the scale runs 100/n .. 100 and its mean is 50 + 50/n -- never
        # 50. Through the club's band formula that lifted every rating, and by MORE in a
        # small pool: measured on 2025/26, pools under 30 players averaged 3.14 against
        # 3.01 for pools of 100+, with pool size correlating -0.725 with mean rating.
        #
        # That matters because 3.00 is the club's Minimum Standard, defined as the league
        # median. A pool whose median player scores 3.30 has moved the bar the whole
        # framework is anchored on -- and a Scottish Championship central midfielder (6 in
        # the pool) was scored a third of a band above a League Two centre back for no
        # footballing reason.
        #
        # (rank - 0.5) / n is symmetric about 50 and averages exactly 50 at every pool
        # size. Ordering is untouched; only the clamp boundaries at bands 1 and 5 move,
        # which shifts a handful of players near them by a place or two.
        # The divisor is how many players HAVE this metric, not how many are in the pool.
        # Physical metrics are absent for 318 outfielders and every goalkeeper, so this is
        # the ordinary case: dividing by the pool size would rank four players inside a pool
        # of ten at 5/15/25/35 instead of 12.5/37.5/62.5/87.5 -- a band of 1.0 for all four.
        pct = (group[m].rank() - 0.5).div(group[m].transform("count")) * 100.0
        if mid_group is not None:
            # Same formula over the combined midfield pool, taken ONLY for the thin groups'
            # rows: a full pool's percentiles are never touched.
            both = (mid_group[m].rank() - 0.5).div(mid_group[m].transform("count")) * 100.0
            pct = pct.where(~fallback, both.reindex(df.index))
        if m in cf.LOWER_IS_BETTER:
            pct = 100.0 - pct
        out[m] = pct
    return out.set_index(KEY)


def _dimension_band(row: pd.Series, metrics: list[str],
                    weights: dict[str, float] | None = None) -> tuple[float | None, int, int]:
    """Average of the 1-5 bands over the present metrics in a dimension -- weighted by the
    club's per-metric weights where given (Performance, `performance_weights`), equal
    otherwise (Physical). A missing metric drops out and the remaining weights are rescaled.
    Returns (band or None, n_present, n_total)."""
    present = [m for m in metrics if m in row.index and pd.notna(row[m])]
    n_total = len(metrics)
    if not present:
        return None, 0, n_total
    w = {m: (weights.get(m, 0.0) if weights else 1.0) for m in present}
    total = sum(w.values())
    if total <= 0:
        return None, 0, n_total
    return round(sum(cf.band(row[m]) * w[m] for m in present) / total, 2), len(present), n_total


def _resolved_performance(position: str, archetype: str = cf.DEFAULT_ARCHETYPE) -> list[str]:
    """Unique stored metrics for a position's Performance dimension, for the given archetype
    ('All Metrics' = the full list). De-duplicated because several club-intended metrics can
    collapse onto the same Impect successor (e.g. both 'counterpressures' and 'pressures in
    opposing half' -> counterpressures): we hold ONE measurement, so it counts once."""
    seen, out = set(), []
    for m in cf.performance_metrics_for_archetype(position, archetype):
        live = cf.resolve_metric(m)
        if live and live not in seen:
            seen.add(live)
            out.append(live)
    return out


def build_scorecards(neutral: pd.DataFrame,
                     financial_resale: pd.DataFrame | None = None,
                     archetype_by_position: dict[str, str] | None = None,
                     scout_bands: pd.DataFrame | None = None) -> pd.DataFrame:
    """One scorecard row per rankable player: each data dimension's 1-5 band, the data
    composite, and the gate flags.

    financial_resale: optional frame keyed by (player_id, competition_id, season_id) with
    'financial_band' and 'resale_band' (1-5). Where absent, those dimensions drop out and
    the composite renormalises -- players with no market value are never excluded.

    scout_bands: optional frame keyed the same way, from `scout_scores.resolve_bands`, with
    'psychological_band' and 'medical_band'. Decision 9: a player enters the assessed
    composite only when BOTH are present -- one dimension alone is not a partial assessment.
    """
    pcts = metric_percentiles(neutral)
    pools = pool_assignment(_group_counts(pcts.reset_index()[KEY]))
    fr = None
    if financial_resale is not None and not financial_resale.empty:
        fr = financial_resale.set_index(["player_id", "competition_id", "season_id"])
    scout = None
    if scout_bands is not None and not scout_bands.empty:
        scout = scout_bands.set_index(["player_id", "competition_id", "season_id"])
    archetype_by_position = archetype_by_position or {}

    records = []
    for key, row in pcts.iterrows():
        player_id, competition_id, season_id, position = key
        weights = cf.DIMENSION_WEIGHTS.get(position)
        if not weights:
            continue

        dim_bands: dict[str, float] = {}
        coverage: dict[str, tuple[int, int]] = {}

        archetype = archetype_by_position.get(position, cf.DEFAULT_ARCHETYPE)
        perf_band, np_, nt_ = _dimension_band(row, _resolved_performance(position, archetype),
                                              pw.weights_for(position, archetype))
        if perf_band is not None:
            dim_bands[cf.PERFORMANCE] = perf_band
            coverage[cf.PERFORMANCE] = (np_, nt_)

        phys_metrics = cf.PHYSICAL_METRICS.get(position, [])
        if phys_metrics:
            phys_band, np_, nt_ = _dimension_band(row, phys_metrics)
            if phys_band is not None:
                dim_bands[cf.PHYSICAL] = phys_band
                coverage[cf.PHYSICAL] = (np_, nt_)

        if fr is not None and (player_id, competition_id, season_id) in fr.index:
            frow = fr.loc[(player_id, competition_id, season_id)]
            if pd.notna(frow.get("financial_band")):
                dim_bands[cf.FINANCIAL] = round(float(frow["financial_band"]), 2)
            if pd.notna(frow.get("resale_band")):
                dim_bands[cf.RESALE] = round(float(frow["resale_band"]), 2)

        psychological = medical = None
        if scout is not None and (player_id, competition_id, season_id) in scout.index:
            srow = scout.loc[(player_id, competition_id, season_id)]
            if pd.notna(srow.get("psychological_band")):
                psychological = round(float(srow["psychological_band"]), 2)
            if pd.notna(srow.get("medical_band")):
                medical = round(float(srow["medical_band"]), 2)
        # Decision 9: both, or neither. One dimension is not a partial assessment.
        if psychological is not None and medical is not None:
            dim_bands[cf.PSYCHOLOGICAL] = psychological
            dim_bands[cf.MEDICAL] = medical

        # Objective composite (default ranking): real-data dimensions only.
        objective, obj_w = _composite(dim_bands, weights, [cf.PERFORMANCE, cf.PHYSICAL])
        # Full composite: adds the modelled Financial + Resale dimensions.
        full, full_w = _composite(dim_bands, weights, cf.DATA_DIMENSIONS)
        # Assessed composite: Performance + Physical + Psychological + Medical (Decision 15) --
        # deliberately excludes Financial/Resale even when they are present in dim_bands.
        assessed, assessed_w = (None, 0.0)
        if cf.PSYCHOLOGICAL in dim_bands and cf.MEDICAL in dim_bands:
            assessed, assessed_w = _composite(
                dim_bands, weights, ASSESSED_DIMENSIONS)

        record = {
            "player_id": player_id, "competition_id": competition_id, "season_id": season_id,
            "position_group": position,
            "performance_band": dim_bands.get(cf.PERFORMANCE),
            "physical_band": dim_bands.get(cf.PHYSICAL),
            "financial_band": dim_bands.get(cf.FINANCIAL),
            "resale_band": dim_bands.get(cf.RESALE),
            "psychological_band": dim_bands.get(cf.PSYCHOLOGICAL),
            "medical_band": dim_bands.get(cf.MEDICAL),
            "objective_composite": objective,
            "objective_weight_covered": obj_w,
            "full_composite": full,
            "full_weight_covered": full_w,
            "assessed_composite": assessed,
            "assessed_weight_covered": assessed_w,
            # Advisory only -- surfaced for transparency, never used to exclude a player.
            "veto": any(b < cf.VETO_BAND for b in dim_bands.values()),
            "below_min_composite": objective is not None and objective < cf.MIN_COMPOSITE,
            # The pool his percentiles came from: POOL_POSITION (his own position group) or
            # POOL_MIDFIELD (the midfield fallback), and how many players it holds.
            "peer_pool": pools[(competition_id, season_id, position)][0],
            "peer_pool_size": pools[(competition_id, season_id, position)][1],
        }
        records.append(record)

    return pd.DataFrame(records)


def _composite(dim_bands: dict[str, float], weights: dict[str, float],
               dims: list[str]) -> tuple[float | None, float]:
    """Weighted average of the given dimensions' bands, renormalised over the weight
    actually present. Returns (composite or None, weight_covered)."""
    present = {d: dim_bands[d] for d in dims if d in dim_bands}
    present_w = sum(weights[d] for d in present if d in weights)
    if present_w <= 0:
        return None, 0.0
    val = sum(present[d] * weights[d] for d in present if d in weights) / present_w
    return _round2(val), round(present_w, 2)


def _round2(value: float) -> float:
    """Two decimals, exact halves UP. 65 : 35 of two 2-dp bands often lands exactly on a half
    (0.65 x 3.10 + 0.35 x 3.00 = 3.065); Python's round() would send it whichever way binary
    floating point happens to store it (round(3.035, 2) = 3.03, round(3.065, 2) = 3.07). The
    value is first taken to 9 dp to drop that float noise, then rounded half up. Under the old
    4 : 3 split no composite could land on a half, so every stored rating is unchanged by it."""
    return float(Decimal(f"{value:.9f}").quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


# A percentile is a rank within a peer group, so it is only as meaningful as that group is
# large. Early in a season the pools are tiny: on 2026-09-07, five matches in, 13 of the
# 36 position-league pools held FEWER THAN FIVE rankable players and 34 players sat in
# one. A composite built on three peers is not a weak signal, it is an arbitrary one --
# whoever happens to be present decides the ranking.
#
# This is the floor below which a composite must not be presented as a ranking. It does
# not stop the number being computed or stored; it tells the interface to say so.
MIN_PEERS_FOR_RANKING = 10


def _pool_table(scorecards) -> dict:
    """(competition_id, season_id, position_group) -> (scope, size) of the pool each group was
    RATED in. The stored `peer_pool` / `peer_pool_size` (written by the scoring run) win, so a
    frame holding one position only still knows a combined midfield pool; rows without them
    (scored before the columns existed) are counted with the same rule (`pool_assignment`)."""
    if scorecards is None or len(scorecards) == 0:
        return {}
    out = pool_assignment(_group_counts(scorecards))
    if {"peer_pool", "peer_pool_size"} <= set(scorecards.columns):
        stored = scorecards.dropna(subset=["peer_pool", "peer_pool_size"])
        if len(stored):
            first = (stored.groupby(["competition_id", "season_id", "position_group"])
                           [["peer_pool", "peer_pool_size"]].first())
            for key, r in first.iterrows():
                out[key] = (str(r["peer_pool"]), int(r["peer_pool_size"]))
    return out


def peer_pool_sizes(scorecards):
    """(competition_id, season_id, position_group) -> how many players are in the pool that
    group was rated in: its own size, or the combined midfield pool's for a thin midfield
    group (`pool_assignment`)."""
    return {k: size for k, (_scope, size) in _pool_table(scorecards).items()}


def peer_pool_scopes(scorecards):
    """(competition_id, season_id, position_group) -> POOL_POSITION or POOL_MIDFIELD."""
    return {k: scope for k, (scope, _size) in _pool_table(scorecards).items()}


def pool_is_thin(pool_size) -> bool:
    """True when a composite from this pool should not be read as a ranking."""
    if pool_size is None:
        return True
    return int(pool_size) < MIN_PEERS_FOR_RANKING


def with_peer_counts(frame, pool_sizes):
    """`frame` plus a `peer_count` column: how many players share each row's peer pool.

    The count comes from the UNFILTERED scorecard set for the season, never from the frame
    being annotated -- a peer pool is a property of the data, not of whatever the sidebar
    currently shows. Narrowing to one league or raising the minutes slider must not make a
    player look less comparable than he is.

    A row whose pool is unknown (no scorecard) gets NaN, which `pool_is_thin` already treats
    as thin: absence of evidence is not evidence of a usable pool.

    Returns a copy; the caller's frame is never mutated.
    """
    out = frame.copy()
    if len(out) == 0:
        out["peer_count"] = pd.Series(dtype="float64")
        return out
    keys = list(zip(out["competition_id"], out["season_id"], out["position_group"]))
    out["peer_count"] = pd.Series([pool_sizes.get(k) for k in keys], index=out.index,
                                  dtype="float64")
    return out


def rank_in_pool(scorecards, player_id: int, competition_id: int, season_id: int,
                 position_group: str,
                 column: str = "objective_composite") -> tuple[int | None, int]:
    """(rank, pool size) for one player among his real peers -- same league, same season,
    same position group -- ranked on `column`, best first.

    WHY THE POOL IS SCOPED THIS WAY. A composite is a percentile within exactly this group
    (`metric_percentiles` groups by the same three keys), so it is the only group a rank can
    honestly be quoted against. Ranking across leagues would imply a cross-league comparison
    the model never makes: on 25/26, stacking every league into one centre-forward list put
    Wakeling 2nd and Burrowes 3rd when each is FIRST in his own division.

    TIES SHARE A RANK ('min' method). Two identical composites are not first and second --
    nothing in the data separates them, and ordering them would be an artefact of row order.

    Returns `(None, n)` for a player with no scored row in that pool: the pool size is still
    a fact worth reporting, and None is not zero.

    MIDFIELD FALLBACK: a player rated against all midfielders (`POOL_MIDFIELD`) gets
    `(None, n)` too. His own position holds fewer than MIN_PEERS_FOR_RANKING, so a rank among
    them would be a ranking from a thin pool; and a rank among all midfielders would order
    players scored on different metrics and weights.
    """
    if scorecards is None or len(scorecards) == 0:
        return None, 0
    if position_group in MIDFIELD_POSITIONS:
        league = scorecards[(scorecards["competition_id"] == competition_id)
                            & (scorecards["season_id"] == season_id)]
        if peer_pool_scopes(league).get(
                (competition_id, season_id, position_group)) == POOL_MIDFIELD:
            own = league[league["position_group"] == position_group]
            return None, int(own[column].notna().sum())
    pool = scorecards[(scorecards["competition_id"] == competition_id)
                      & (scorecards["season_id"] == season_id)
                      & (scorecards["position_group"] == position_group)]
    pool = pool[pool[column].notna()]
    if pool.empty:
        return None, 0
    ranks = pool[column].rank(ascending=False, method="min")
    mine = pool["player_id"] == player_id
    rank = int(ranks[mine].iloc[0]) if mine.any() else None
    return rank, len(pool)
