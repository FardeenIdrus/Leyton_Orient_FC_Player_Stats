"""The club's 1-5 composite scorecard, computed per player from the framework in
`club_framework.py`.

Pipeline per player (all within position group + league):
  1. every framework metric -> a direction-aware percentile (higher percentile = better;
     lower-is-better metrics are inverted first);
  2. percentile -> a 1-5 band (club-anchored: median->3, 70th->4);
  3. equal-weight average of the bands in a dimension -> that dimension's 1-5 score
     (metrics with no data drop out, so a missing metric never deflates the score);
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

import pandas as pd

from lofc.model import club_framework as cf

KEY = ["player_id", "competition_id", "season_id", "position_group"]

# Decision 15: assessed_composite is real data (Performance, Physical) plus human judgement
# (Psychological, Medical) -- deliberately NOT cf.DATA_DIMENSIONS, which also carries the
# modelled Financial and Resale dimensions. Money stays out of every ranking-shaped number
# in the platform; do not "complete" this list later.
ASSESSED_DIMENSIONS = [cf.PERFORMANCE, cf.PHYSICAL] + cf.SCOUT_DIMENSIONS


def metric_percentiles(neutral: pd.DataFrame) -> pd.DataFrame:
    """Direction-aware percentile (0-100) per metric, within competition + season + position
    group, over rankable players only. Lower-is-better metrics are inverted so a high percentile
    always means 'good'. Returns one row per player keyed by KEY, one column per metric.

    Season is part of the grouping so a call on an unfiltered two-season frame still ranks each
    player within his own season (the live path pre-filters to one season, so this is a guard)."""
    df = neutral[neutral["rankable"]].copy() if "rankable" in neutral.columns else neutral.copy()
    metric_cols = [c for c in df.columns if c not in set(KEY) | {"rankable", "minutes", "name",
                                                                  "team_name", "player_name", "id"}]
    group = df.groupby(["competition_id", "season_id", "position_group"])
    out = df[KEY].copy()
    for m in metric_cols:
        pct = group[m].rank(pct=True) * 100.0
        if m in cf.LOWER_IS_BETTER:
            pct = 100.0 - pct
        out[m] = pct
    return out.set_index(KEY)


def _dimension_band(row: pd.Series, metrics: list[str]) -> tuple[float | None, int, int]:
    """Equal-weight average of the 1-5 bands over the present metrics in a dimension.
    Returns (band or None, n_present, n_total)."""
    bands = [cf.band(row[m]) for m in metrics if m in row.index and pd.notna(row[m])]
    n_total = len(metrics)
    if not bands:
        return None, 0, n_total
    return round(sum(bands) / len(bands), 2), len(bands), n_total


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
        perf_band, np_, nt_ = _dimension_band(row, _resolved_performance(position, archetype))
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
    return round(val, 2), round(present_w, 2)
