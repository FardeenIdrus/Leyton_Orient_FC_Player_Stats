"""Tests for archetype clustering. Small synthetic fixtures, no database."""

import pandas as pd

from lofc.model.archetypes import _style_features, cluster_position
from lofc.model.score import KEY_COLUMNS, ROLE_METRICS

ATTACKER_METRICS = ROLE_METRICS["attacker"]


def _wide(rows, position="Centre Forward"):
    """Build a percentile frame: each row overrides a few metrics, the rest sit at 50."""
    data, index = [], []
    for i, overrides in enumerate(rows):
        full = {m: 50.0 for m in ATTACKER_METRICS}
        full.update(overrides)
        data.append(full)
        index.append((i, 2, 27, position))
    return pd.DataFrame(data, index=pd.MultiIndex.from_tuples(index, names=KEY_COLUMNS))


def test_style_features_centre_on_player_mean():
    # One player at 80th for pressing, 20th for shooting, 50th elsewhere -> mean 50.
    feats = _style_features(_wide([{"pressures_p90": 80, "shots_p90": 20}]), ATTACKER_METRICS)
    row = feats.iloc[0]
    assert round(row["pressures_p90"], 1) == 30.0    # 80 - 50
    assert round(row["shots_p90"], 1) == -30.0       # 20 - 50


def test_two_clear_styles_split_into_two_clusters():
    pressers = [{"pressures_p90": 90, "shots_p90": 10} for _ in range(10)]
    shooters = [{"pressures_p90": 10, "shots_p90": 90} for _ in range(10)]
    result = cluster_position(_wide(pressers + shooters), "Centre Forward")

    assert result.attrs["chosen_k"] == 2
    pressers_cluster = set(result.iloc[:10]["cluster_id"])
    shooters_cluster = set(result.iloc[10:]["cluster_id"])
    assert len(pressers_cluster) == 1 and len(shooters_cluster) == 1
    assert pressers_cluster != shooters_cluster


def test_clustering_is_stable_across_runs():
    rows = [{"pressures_p90": 90} for _ in range(8)] + [{"shots_p90": 90} for _ in range(8)]
    first = cluster_position(_wide(rows), "Centre Forward")["cluster_id"].tolist()
    second = cluster_position(_wide(rows), "Centre Forward")["cluster_id"].tolist()
    assert first == second


def test_label_names_the_standout_metric():
    rows = [{"pressures_p90": 95} for _ in range(8)] + [{"pressures_p90": 5} for _ in range(8)]
    labels = set(cluster_position(_wide(rows), "Centre Forward")["cluster_label"])
    assert any("pressing" in label for label in labels)
