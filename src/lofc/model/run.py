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
    pl = named[named["competition_id"] == 2]  # Premier League

    def top(position, by):
        cols = ["player_name", "team_name", "performance_score", "fit_score"]
        rows = pl[pl["position_group"] == position].sort_values(by, ascending=False).head(5)
        print(f"\nTop 5 {position} in the Premier League by {by}:")
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

    n_pct = _upsert(engine, PlayerPercentile.__table__, _records(percentiles),
                    ["player_id", "competition_id", "season_id", "metric"])
    n_scores = _upsert(engine, PlayerScore.__table__, _records(scores),
                       ["player_id", "competition_id", "season_id"])

    print(f"player_percentiles: upserted {n_pct}")
    print(f"player_scores: upserted {n_scores}")

    names = metrics[["player_id", "competition_id", "season_id", "player_name", "team_name"]]
    _spot_check(scores, names)


if __name__ == "__main__":
    main()
