"""Group players by playing style within each position (across all leagues).

Style, not quality. To stop the clustering from just separating good players from bad,
we first centre each player on their own average percentile, so what is left is their
relative strengths (what they do more of than the rest of their game). We then reduce
the correlated metrics with PCA and run k-means, choosing the number of clusters by
silhouette score. Each cluster gets an auto-generated label from its standout metrics.

Limitation: this gives a hard, single label per player. A player who is 70% poacher,
30% presser is forced into one. A soft model (Gaussian mixture) is the documented next
step. See docs/methodology.md.

Run with:  python -m lofc.model.archetypes
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler

from lofc.model.normalise import compute_percentiles_wide
from lofc.model.score import POSITION_ROLE, ROLE_METRICS
from lofc.store.load import _records, _upsert, get_engine
from lofc.store.models import Archetype

K_RANGE = range(2, 7)
# Silhouette differences this small are noise, not a verdict: prefer the richest
# split (largest k) whose score sits within this tolerance of the best. In practice
# this widens the attacking positions to three styles and leaves the rest at two.
K_TOLERANCE = 0.02
PCA_VARIANCE = 0.90
RANDOM_STATE = 42  # fixed so cluster assignments are identical across runs

# Readable names for the auto-generated cluster labels.
PRETTY = {
    "np_xg_p90": "shot threat", "np_goals_p90": "goals", "xg_p90": "shot threat",
    "shots_p90": "shooting", "assists_p90": "assists", "xa_p90": "chance creation",
    "key_passes_p90": "key passes", "passes_p90": "passing volume",
    "passes_completed_p90": "completed passes", "progressive_passes_p90": "progressive passing",
    "passes_into_final_third_p90": "final-third passing", "passes_into_box_p90": "passing into the box",
    "dribbles_p90": "dribbling", "dribbles_completed_p90": "dribbling",
    "carries_p90": "ball carrying", "progressive_carries_p90": "driving forward",
    "pressures_p90": "pressing", "tackles_p90": "tackling", "interceptions_p90": "interceptions",
    "blocks_p90": "blocks", "clearances_p90": "clearances", "ball_recoveries_p90": "ball recoveries",
    "gk_saves_p90": "shot-stopping volume", "pass_completion_pct": "pass accuracy",
    "dribble_success_pct": "dribble success", "save_pct": "save percentage",
}


def _pretty(metric: str) -> str:
    return PRETTY.get(metric, metric)


def _style_features(percentiles: pd.DataFrame, metrics: list[str]) -> pd.DataFrame:
    """Relative-strength profile: each player's percentiles minus their own mean.

    This removes overall quality, leaving what a player does *relatively* more of.
    """
    # A rare undefined percentile (e.g. a player with no passes) becomes neutral 50.
    block = percentiles[metrics].fillna(50.0)
    return block.sub(block.mean(axis=1), axis=0)


def _label_cluster(percentiles: pd.DataFrame, metrics: list[str], member_mask) -> str:
    """Name a cluster from the metrics where it stands out most from the position average."""
    overall = percentiles[metrics].mean()
    cluster_mean = percentiles[metrics][member_mask].mean()
    diff = (cluster_mean - overall).sort_values(ascending=False)

    highs = [_pretty(m) for m in diff.index[:2]]
    low = _pretty(diff.index[-1])
    # De-duplicate (two metrics can map to the same readable name, e.g. dribbling).
    highs = list(dict.fromkeys(highs))
    return f"High {' & '.join(highs)}, low {low}"


def cluster_position(percentiles: pd.DataFrame, position: str) -> pd.DataFrame:
    """Cluster one position's players by style. Returns rows for the archetypes table."""
    metrics = [m for m in ROLE_METRICS[POSITION_ROLE[position]] if m in percentiles.columns]

    out = percentiles.reset_index()[["player_id", "competition_id", "season_id", "position_group"]].copy()
    # Too few players to cluster meaningfully: one group.
    if len(percentiles) < 5:
        out["cluster_id"] = 0
        out["cluster_label"] = "All-round (small sample)"
        out["distance_to_centroid"] = 0.0
        out.attrs["chosen_k"] = 1
        out.attrs["silhouettes"] = {}
        return out

    features = _style_features(percentiles, metrics)

    scaled = StandardScaler().fit_transform(features)
    components = PCA(n_components=PCA_VARIANCE, random_state=RANDOM_STATE).fit_transform(scaled)

    # Score every k, then choose the largest k within K_TOLERANCE of the best
    # silhouette (k must stay below the number of players): near-tied scores
    # should not force the coarsest split.
    max_k = min(max(K_RANGE), len(percentiles) - 1)
    fits = {}
    silhouettes = {}
    for k in range(2, max_k + 1):
        model = KMeans(n_clusters=k, random_state=RANDOM_STATE, n_init=10)
        labels = model.fit_predict(components)
        silhouettes[k] = round(float(silhouette_score(components, labels)), 3)
        fits[k] = {"model": model, "labels": labels}
    top_score = max(silhouettes.values())
    chosen_k = max(k for k, score in silhouettes.items() if score >= top_score - K_TOLERANCE)
    best = {"k": chosen_k, **fits[chosen_k]}

    labels = best["labels"]
    centroids = best["model"].cluster_centers_
    distances = np.linalg.norm(components - centroids[labels], axis=1)
    cluster_names = {c: _label_cluster(percentiles, metrics, labels == c) for c in range(best["k"])}

    out = percentiles.reset_index()[["player_id", "competition_id", "season_id", "position_group"]].copy()
    out["cluster_id"] = labels
    out["cluster_label"] = [cluster_names[c] for c in labels]
    out["distance_to_centroid"] = distances.round(3)
    out.attrs["chosen_k"] = best["k"]
    out.attrs["silhouettes"] = silhouettes
    return out


def cluster_all(metrics: pd.DataFrame) -> pd.DataFrame:
    """Cluster every position group (pooling all leagues) and stack the results."""
    wide = compute_percentiles_wide(metrics).reset_index().set_index(
        ["player_id", "competition_id", "season_id", "position_group"]
    )
    results = []
    for position in sorted(wide.index.get_level_values("position_group").unique()):
        block = wide[wide.index.get_level_values("position_group") == position]
        result = cluster_position(block, position)
        print(f"  {position}: {len(result)} players, k={result.attrs['chosen_k']} "
              f"(silhouettes {result.attrs['silhouettes']})")
        results.append(result)
    return pd.concat(results, ignore_index=True)


def main() -> None:
    engine = get_engine()
    metrics = pd.read_sql("SELECT * FROM player_season_metrics", engine)

    archetypes = cluster_all(metrics)
    # Fully derived: clear first so re-targeting the competitions never leaves
    # orphan league rows behind.
    with engine.begin() as conn:
        conn.execute(Archetype.__table__.delete())
    n = _upsert(engine, Archetype.__table__, _records(archetypes),
                ["player_id", "competition_id", "season_id"])
    print(f"\narchetypes: upserted {n}")


if __name__ == "__main__":
    main()
