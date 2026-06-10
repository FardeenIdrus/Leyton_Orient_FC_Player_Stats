"""Phase 4: read the stored metrics, compute percentiles and scores, write them back.

Reads player_season_metrics and identity_profiles from Postgres, ranks every rankable
player against their positional peers in each league, builds the performance and fit
scores, and upserts player_percentiles and player_scores. Idempotent.

Run with:  python -m lofc.model.run
"""

from __future__ import annotations

import pandas as pd

from lofc.model.normalise import compute_percentiles_wide, to_long
from lofc.model.score import compute_scores
from lofc.store.load import _records, _upsert, get_engine
from lofc.store.models import PlayerPercentile, PlayerScore


def _spot_check(scores: pd.DataFrame, names: pd.DataFrame) -> None:
    """Print the top players in a few groups so the result can be eyeballed."""
    named = scores.merge(names, on=["player_id", "competition_id", "season_id"], how="left")
    # Eyeball the first configured league present in the data, whichever era that is.
    comp_id = int(named["competition_id"].min())
    league = named[named["competition_id"] == comp_id]
    label = names[names["competition_id"] == comp_id]["competition_name"].iloc[0] \
        if "competition_name" in names.columns else f"competition {comp_id}"

    def top(position, by):
        cols = ["player_name", "team_name", "performance_score", "fit_score"]
        rows = league[league["position_group"] == position].sort_values(by, ascending=False).head(5)
        print(f"\nTop 5 {position} in the {label} by {by}:")
        print(rows[cols].to_string(index=False))

    top("Centre Forward", "performance_score")
    top("Centre Forward", "fit_score")
    top("Defensive Mid", "performance_score")


def main() -> None:
    engine = get_engine()
    metrics = pd.read_sql("SELECT * FROM player_season_metrics", engine)
    identity = pd.read_sql("SELECT position_group, metric, weight FROM identity_profiles", engine)

    wide = compute_percentiles_wide(metrics)
    percentiles = to_long(wide)
    scores = compute_scores(wide, identity)

    # Fully derived from the metrics table: clear first so re-targeting the
    # competitions never leaves orphan league rows behind.
    with engine.begin() as conn:
        conn.execute(PlayerPercentile.__table__.delete())
        conn.execute(PlayerScore.__table__.delete())
    n_pct = _upsert(engine, PlayerPercentile.__table__, _records(percentiles),
                    ["player_id", "competition_id", "season_id", "metric"])
    n_scores = _upsert(engine, PlayerScore.__table__, _records(scores),
                       ["player_id", "competition_id", "season_id"])

    print(f"player_percentiles: upserted {n_pct}")
    print(f"player_scores: upserted {n_scores}")

    names = metrics[["player_id", "competition_id", "season_id", "player_name",
                     "team_name", "competition_name"]]
    _spot_check(scores, names)


if __name__ == "__main__":
    main()
