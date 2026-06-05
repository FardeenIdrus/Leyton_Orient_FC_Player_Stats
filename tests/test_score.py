"""Tests for percentile normalisation and the two scores. Small fixtures, no database."""

import numpy as np
import pandas as pd

from lofc.model.normalise import DISPLAY_METRICS, compute_percentiles_wide, to_long
from lofc.model.score import KEY_COLUMNS, ROLE_METRICS, compute_scores


def _metric_row(player_id, position, **overrides):
    """A player_season_metrics-shaped row with every display metric at 0 by default."""
    row = {m: 0.0 for m in DISPLAY_METRICS}
    row.update({"player_id": player_id, "competition_id": 2, "season_id": 27,
                "position_group": position, "rankable": True})
    row.update(overrides)
    return row


def test_percentiles_rank_within_group():
    df = pd.DataFrame([_metric_row(i, "Centre Forward", np_xg_p90=float(i)) for i in range(4)])
    wide = compute_percentiles_wide(df)
    # values 0,1,2,3 -> 25th, 50th, 75th, 100th percentile.
    assert sorted(wide["np_xg_p90"].tolist()) == [25.0, 50.0, 75.0, 100.0]


def test_only_rankable_players_are_ranked():
    df = pd.DataFrame([
        _metric_row(1, "Centre Forward", np_xg_p90=1.0),
        {**_metric_row(2, "Centre Forward", np_xg_p90=9.0), "rankable": False},
    ])
    wide = compute_percentiles_wide(df)
    assert len(wide) == 1
    assert wide.index.get_level_values("player_id").tolist() == [1]


def test_to_long_drops_undefined_metrics():
    # save_pct undefined (NaN) for outfield players -> should not appear in the long table.
    rows = [_metric_row(i, "Centre Forward", np_xg_p90=float(i), save_pct=np.nan) for i in range(3)]
    long = to_long(compute_percentiles_wide(pd.DataFrame(rows)))
    assert "save_pct" not in set(long["metric"])
    assert "np_xg_p90" in set(long["metric"])


def test_scores_are_mean_and_weighted_sum():
    # One centre forward: np_xg at 80th, pressing at 40th, every other attacker stat at 50th.
    cols = ROLE_METRICS["attacker"]
    data = {m: [50.0] for m in cols}
    data["np_xg_p90"] = [80.0]
    data["pressures_p90"] = [40.0]
    idx = pd.MultiIndex.from_tuples([(1, 2, 27, "Centre Forward")], names=KEY_COLUMNS)
    wide = pd.DataFrame(data, index=idx)

    identity = pd.DataFrame([
        {"position_group": "Centre Forward", "metric": "np_xg_p90", "weight": 0.5},
        {"position_group": "Centre Forward", "metric": "pressures_p90", "weight": 0.5},
    ])
    scores = compute_scores(wide, identity)

    # performance = mean(80, 40, and seven 50s) = 470/9 = 52.2
    assert scores["performance_score"].iloc[0] == 52.2
    # fit = 0.5*80 + 0.5*40 = 60
    assert scores["fit_score"].iloc[0] == 60.0


def test_ranks_are_best_first():
    cols = ROLE_METRICS["attacker"]
    rows = []
    idx = []
    for pid, level in [(1, 90.0), (2, 50.0), (3, 10.0)]:
        rows.append({m: level for m in cols})
        idx.append((pid, 2, 27, "Centre Forward"))
    wide = pd.DataFrame(rows, index=pd.MultiIndex.from_tuples(idx, names=KEY_COLUMNS))
    identity = pd.DataFrame([{"position_group": "Centre Forward", "metric": "np_xg_p90", "weight": 1.0}])
    scores = compute_scores(wide, identity).set_index("player_id")
    # Player 1 (highest) ranks 1st on both.
    assert scores.loc[1, "performance_rank"] == 1
    assert scores.loc[3, "performance_rank"] == 3
