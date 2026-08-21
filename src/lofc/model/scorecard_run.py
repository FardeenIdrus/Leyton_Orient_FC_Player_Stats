"""Persist the club's 1-5 recruitment composite to `player_scorecards`.

The scorecard (model/scorecard.py) is the platform's LIVE ranking model, but it was computed
only inside the dashboard. That left the offline shortlist pipeline and the BI layer reading
the retired Quality/Fit model -- two different rankings for the same players. This step writes
the composite to the database so every consumer reads the same numbers.

What it writes: one row per player-season PER ARCHETYPE.
  * 'All Metrics' (the full-profile default) for every scored player;
  * plus one row per club archetype for the positions that have them (Full Back, Winger),
    so the lens is queryable in BI, not just in the dashboard sidebar.

Scoring is WITHIN season + league + position group. `build_scorecards` groups by season
itself, so the whole neutral table can be scored in one pass and both seasons stay separate.

Three composites are stored side by side, deliberately:
  * objective_composite -- Performance + Physical, 100% real Impect + SkillCorner data. This
    is what the shortlist ranks on.
  * full_composite -- adds the MODELLED Financial + Resale (wage grid + valuation regression,
    a screening prior, NOT decision-grade). Kept in its own column so nothing reading the
    objective ranking is contaminated by modelled money.
  * assessed_composite -- Performance + Physical + Psychological + Medical (Decision 15).
    Adds human scout judgement (from `scout_assessments`, resolved via
    `scout_scores.resolve_bands`) but DELIBERATELY EXCLUDES Financial + Resale -- money
    stays out of this column too. NULL unless a player has both scout dimensions
    (Decision 9); with `scout_assessments` empty, every row's assessed_composite is NULL,
    which is expected, not a bug.

Fully derived, so it is clear-then-insert: a re-run rebuilds the table exactly and
re-targeting the competitions never leaves orphan rows behind. Idempotent.

Run with:  python -m lofc.model.scorecard_run

IMPORTANT 3: `assessed_composite` has a second write path -- `model/assessed_refresh.py`,
triggered by `store.assessments.save` and `store.assessments.sign_off` -- that keeps a single
player-season's stored composite in step with its assessments without waiting for this whole
pipeline stage to re-run. Both callers of that refresh swallow its failures on purpose (the
assessment itself must never be lost to a refresh error), which means a refresh CAN silently
not happen, leaving a player's `assessed_composite` stale or NULL even though `resolve_bands`
would produce a band for them right now. `--reconcile-assessed` (see `reconcile_assessed`
below) is the recovery path for that: it re-runs the per-player refresh for every player-season
that has a scoring assessment, cheaply, without rebuilding the rest of the table.
"""

from __future__ import annotations

import argparse

import pandas as pd

from lofc.model import assessed_refresh
from lofc.model import club_framework as cf
from lofc.model.financial_resale import financial_resale_bands
from lofc.model.scorecard import build_scorecards
from lofc.model.scout_scores import resolve_bands
from lofc.store.load import _records, _upsert, get_engine
from lofc.store.models import PlayerScorecard

CONFLICT = ["player_id", "competition_id", "season_id", "archetype"]

STORED_COLUMNS = [
    "player_id", "competition_id", "season_id", "position_group", "archetype",
    "performance_band", "physical_band", "financial_band", "resale_band",
    "psychological_band", "medical_band",
    "objective_composite", "objective_weight_covered",
    "full_composite", "full_weight_covered",
    "assessed_composite", "assessed_weight_covered",
    "veto", "below_min_composite",
]


def archetype_jobs() -> list[tuple[str, dict[str, str]]]:
    """(archetype label, archetype_by_position) pairs to score.

    The default scores every position on its full metric list. Each additional job re-scores
    ONE position on one archetype's subset; only that position's rows are kept from it.
    """
    jobs: list[tuple[str, dict[str, str]]] = [(cf.DEFAULT_ARCHETYPE, {})]
    for position, archetypes in cf.ARCHETYPE_DROPS.items():
        for name in archetypes:
            jobs.append((name, {position: name}))
    return jobs


def build_all(neutral: pd.DataFrame, financial_resale: pd.DataFrame | None,
              scout_bands: pd.DataFrame | None = None) -> pd.DataFrame:
    """Every scorecard row to store: the default for all positions, plus the archetype rows."""
    frames = []
    for label, by_position in archetype_jobs():
        sc = build_scorecards(neutral, financial_resale=financial_resale,
                              archetype_by_position=by_position, scout_bands=scout_bands)
        if by_position:
            # An archetype job re-scores one position; the other positions are unchanged, so
            # keep only the position this archetype belongs to (avoids duplicate default rows).
            position = next(iter(by_position))
            sc = sc[sc["position_group"] == position]
        if sc.empty:
            continue
        frames.append(sc.assign(archetype=label))
    if not frames:
        return pd.DataFrame(columns=STORED_COLUMNS)
    return pd.concat(frames, ignore_index=True)[STORED_COLUMNS]


def reconcile_assessed(engine) -> int:
    """Recovery path for IMPORTANT 3: re-run `assessed_refresh.refresh_for_player` for every
    player-season that has at least one scoring (submitted/signed_off) assessment.

    A small, targeted repair, not a second scorecard rebuild: it touches only the columns
    `assessed_refresh` already owns (psychological_band, medical_band, assessed_composite,
    assessed_weight_covered, veto) for the player-seasons that could plausibly have drifted,
    and never recomputes `objective_composite` or `full_composite` -- those stay exactly
    `main()`'s to write. Safe to run at any time; a player-season already in step is simply
    written back unchanged.
    """
    assessments = pd.read_sql(
        "SELECT DISTINCT player_id, competition_id, season_id FROM scout_assessments "
        "WHERE status IN ('submitted', 'signed_off')", engine)
    updated = 0
    for row in assessments.itertuples(index=False):
        updated += assessed_refresh.refresh_for_player(
            engine, player_id=row.player_id, competition_id=row.competition_id,
            season_id=row.season_id)
    return updated


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--reconcile-assessed", action="store_true",
        help="Re-run the assessed_composite refresh for every player-season with a scoring "
             "assessment, without rebuilding the rest of player_scorecards -- recovers from a "
             "save/sign-off whose refresh silently failed (IMPORTANT 3).")
    args = parser.parse_args()
    engine = get_engine()

    if args.reconcile_assessed:
        updated = reconcile_assessed(engine)
        print(f"assessed_composite reconcile: refreshed {updated:,} player_scorecards row(s)")
        return

    neutral = pd.read_sql("SELECT * FROM player_metrics_neutral", engine)
    if neutral.empty:
        raise SystemExit("player_metrics_neutral is empty: run build_neutral --write first.")

    # Financial/Resale need valuations + the wage tables; missing ones simply come back NaN and
    # renormalise out, so a player is never excluded for having no price.
    financial_resale = financial_resale_bands(engine)

    # Psychological/Medical are human scout inputs; resolve_bands returns an empty (but
    # correctly-columned) frame when scout_assessments has no scoring rows, which
    # build_scorecards treats identically to "no assessments exist yet" (Decision 9).
    assessments = pd.read_sql(
        "SELECT player_id, competition_id, season_id, dimension, band, status, updated_at "
        "FROM scout_assessments", engine)
    scout_bands = resolve_bands(assessments)

    frame = build_all(neutral, financial_resale, scout_bands)

    with engine.begin() as conn:                       # fully derived -> clear then insert
        conn.execute(PlayerScorecard.__table__.delete())
    written = _upsert(engine, PlayerScorecard.__table__, _records(frame), CONFLICT)

    default = frame[frame["archetype"] == cf.DEFAULT_ARCHETYPE]
    print(f"player_scorecards: wrote {written:,} rows "
          f"({len(default):,} default '{cf.DEFAULT_ARCHETYPE}' + "
          f"{written - len(default):,} archetype rows)")
    for season_id, group in default.groupby("season_id"):
        scored = group["objective_composite"].notna().sum()
        money = group["financial_band"].notna().sum()
        print(f"  season {season_id}: {len(group):,} players | {scored:,} with an objective "
              f"composite | {money:,} with a (modelled) financial band")


if __name__ == "__main__":
    main()
