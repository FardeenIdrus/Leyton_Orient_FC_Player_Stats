"""The two data-driven scout dimensions: Financial Fit and Resale Potential (1-5).

Decision 4 of the club-framework build: these two dimensions have data-driven key
indicators (Financial = fee, wages, contract; Resale = age curve, market trajectory), so
a computed band is more consistent than a human eyeballing them. They are overridable and
clearly labelled as modelled. Psychological and Medical, which need human judgement, are
NOT computed here -- they are scout inputs.

Each dimension is a blend of two signals, each percentile-ranked within position + league,
averaged, then mapped to a 1-5 band by the same club-anchored rule the other dimensions use
(median -> 3.0). Ranking within group keeps the bands comparable to Performance/Physical.

  Financial Fit  = wage headroom (how far under the club's wage ceiling the player sits)
                   + undervaluation (how far below fair value he is priced). Cheaper and
                   better-value = higher fit for a budget club.
  Resale Potential = youth (younger = more sell-on runway) + market value (a valuable young
                   asset resells best).

A player with no market value or wage (Scottish/PL2 coverage) gets NaN here, so the
dimension drops out of his composite and he stays in the ranking on the dimensions we can
score -- players are never excluded for missing price data.
"""

from __future__ import annotations

import pandas as pd

from lofc.constrain.filters import build_candidates
from lofc.model.club_framework import band

KEY = ["player_id", "competition_id", "season_id"]


def _pct_within(df: pd.DataFrame, col: str) -> pd.Series:
    """Percentile (0-100) of a column within competition + season + position group. Season is
    part of the grouping so these modelled bands are ranked within one season, exactly like the
    Performance/Physical bands -- otherwise a player would be ranked against a two-season pool."""
    return df.groupby(["competition_id", "season_id", "position_group"])[col].rank(pct=True) * 100.0


def _band_of_mean(*pcts: pd.Series) -> pd.Series:
    """Average the given percentile series (ignoring NaN) and map to a 1-5 band. NaN only
    when every component is NaN (no data at all for the dimension)."""
    stacked = pd.concat(pcts, axis=1)
    mean_pct = stacked.mean(axis=1, skipna=True)
    return mean_pct.map(lambda p: band(p) if pd.notna(p) else pd.NA)


def financial_resale_bands(engine, wage_ceiling_multiplier: float = 1.0) -> pd.DataFrame:
    """Financial Fit and Resale Potential bands (1-5) per player, from valuation/age/wage
    data. Keyed by (player_id, competition_id, season_id)."""
    cand = build_candidates(engine, wage_ceiling_multiplier, all_leagues=True).copy()

    # Financial: wage headroom + undervaluation (both higher = better fit).
    cand["_wage_headroom"] = (cand["wage_ceiling_gbp"] - cand["estimated_weekly_wage_gbp"]) \
        / cand["wage_ceiling_gbp"]
    fin_head = _pct_within(cand, "_wage_headroom")
    fin_uval = _pct_within(cand, "undervaluation_pct") if "undervaluation_pct" in cand.columns \
        else pd.Series(pd.NA, index=cand.index)
    cand["financial_band"] = _band_of_mean(fin_head, fin_uval)

    # Resale: youth (younger = better) + market value (higher = better).
    cand["_youth"] = -cand["age"]
    res_youth = _pct_within(cand, "_youth")
    res_value = _pct_within(cand, "market_value_eur")
    cand["resale_band"] = _band_of_mean(res_youth, res_value)

    out = cand[KEY + ["financial_band", "resale_band"]].copy()
    for c in ("financial_band", "resale_band"):
        out[c] = pd.to_numeric(out[c], errors="coerce").round(2)
    return out
