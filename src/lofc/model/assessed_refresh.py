"""Close the seam between a saved scout assessment and the ranking it should feed.

`store.assessments.save` inserts one row into `scout_assessments`. The composite a recruiter
can opt into ranking on lives in `player_scorecards.assessed_composite`, which used to be
written only by the pipeline's scorecard stage (`model/scorecard.py`). Nothing recomputed it
after a save, so a scout could complete both dimensions, see the badge on the profile, tick
"Rank on assessed composite" -- and their player would still show `assessed_composite = NULL`
and vanish from that list.

`refresh_for_player` closes that gap without touching the pipeline: `performance_band` and
`physical_band` are already stored on each `player_scorecards` row, so refreshing one
player-season needs no percentile recomputation and no metric tables. It reads those stored
bands, resolves the scout bands via `scout_scores.resolve_bands` (never re-derives that rule),
and calls `scorecard._composite` -- the exact function the pipeline calls -- so the two paths
can never drift apart.

This module writes ONLY: `psychological_band`, `medical_band`, `assessed_composite`,
`assessed_weight_covered`, `veto`. `objective_composite` is the platform's default ranking and
`full_composite` is the money-inclusive composite; neither may ever move because a human
entered a judgement, so the UPDATE below names no other column -- not even to write back an
unchanged value.
"""

from __future__ import annotations

import pandas as pd
from sqlalchemy import select

from lofc.model import club_framework as cf
from lofc.model import scout_scores
from lofc.model.scorecard import ASSESSED_DIMENSIONS, _composite
from lofc.store.models import PlayerScorecard

_S = PlayerScorecard.__table__


def _band(value) -> float | None:
    return None if value is None or pd.isna(value) else float(value)


def refresh_for_player(engine, player_id: int, competition_id: int, season_id: int) -> int:
    """Recompute `assessed_composite` (and the columns it depends on) for every
    `player_scorecards` row of one player-season -- one row per archetype.

    Returns the number of rows updated (0 if the player has no scorecard row at all, e.g.
    too few minutes to be rankable -- not an error).
    """
    # Local import: store.assessments calls refresh_for_player after a save, and this
    # function needs store.assessments.load_all to read the assessments back. Importing
    # either module at top level in both directions would cycle, so this one stays local.
    from lofc.store import assessments as store_assess

    all_assessments = store_assess.load_all(engine)
    mine = all_assessments[
        (all_assessments["player_id"] == player_id) &
        (all_assessments["competition_id"] == competition_id) &
        (all_assessments["season_id"] == season_id)]
    resolved = scout_scores.resolve_bands(mine)

    psychological = medical = None
    if not resolved.empty:
        winner = resolved.iloc[0]
        psychological = _band(winner.get("psychological_band"))
        medical = _band(winner.get("medical_band"))

    if psychological is None and medical is None:
        # Nothing scores for this player-season (no assessment, or only drafts) -- a true
        # no-op, not an update that writes back the same NULLs.
        return 0

    updated = 0
    with engine.begin() as conn:
        rows = conn.execute(
            select(_S.c.id, _S.c.position_group, _S.c.performance_band, _S.c.physical_band,
                   _S.c.financial_band, _S.c.resale_band)
            .where(_S.c.player_id == player_id, _S.c.competition_id == competition_id,
                   _S.c.season_id == season_id)
        ).fetchall()

        for row in rows:
            weights = cf.DIMENSION_WEIGHTS.get(row.position_group)
            if not weights:
                continue

            # Each row's OWN stored bands -- performance_band differs by archetype, so this
            # must not be hoisted out of the loop and reused across rows.
            dim_bands: dict[str, float] = {}
            if row.performance_band is not None:
                dim_bands[cf.PERFORMANCE] = row.performance_band
            if row.physical_band is not None:
                dim_bands[cf.PHYSICAL] = row.physical_band
            if row.financial_band is not None:
                dim_bands[cf.FINANCIAL] = row.financial_band
            if row.resale_band is not None:
                dim_bands[cf.RESALE] = row.resale_band
            # Decision 9: both scout dimensions, or neither -- one alone is not a partial
            # assessment.
            if psychological is not None and medical is not None:
                dim_bands[cf.PSYCHOLOGICAL] = psychological
                dim_bands[cf.MEDICAL] = medical

            assessed, assessed_w = (None, 0.0)
            if cf.PSYCHOLOGICAL in dim_bands and cf.MEDICAL in dim_bands:
                assessed, assessed_w = _composite(dim_bands, weights, ASSESSED_DIMENSIONS)

            # Advisory only -- matches build_scorecards: any dimension present, from any
            # source, below VETO_BAND flags the row. Never excludes a player from a list.
            veto = any(b < cf.VETO_BAND for b in dim_bands.values())

            conn.execute(
                _S.update().where(_S.c.id == row.id).values(
                    psychological_band=psychological,
                    medical_band=medical,
                    assessed_composite=assessed,
                    assessed_weight_covered=assessed_w,
                    veto=veto))
            updated += 1

    return updated
