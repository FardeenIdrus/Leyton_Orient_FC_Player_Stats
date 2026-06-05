"""Within-position, within-league percentile normalisation.

A raw per-90 number means nothing on its own: 2.5 tackles is great for a winger and
ordinary for a defensive mid. So we rank each player against their positional peers in
the same league. A percentile of 90 means "better than 90% of peers".

Only rankable players (450+ minutes) are ranked, so a small sample cannot distort the
distribution or top the chart.
"""

from __future__ import annotations

import pandas as pd

from lofc.store.models import PER90_COLUMNS

# Higher-is-better metrics we rank. Ratios join the per-90 rates. goals_conceded is
# left out on purpose: lower is better there, so we rank save_pct instead.
DISPLAY_METRICS = PER90_COLUMNS + ["pass_completion_pct", "dribble_success_pct", "save_pct"]

KEY_COLUMNS = ["player_id", "competition_id", "season_id", "position_group"]


def compute_percentiles_wide(metrics: pd.DataFrame) -> pd.DataFrame:
    """Percentile (0-100) per metric, ranked within competition + position group.

    Returns one row per rankable player, indexed by the key columns, with one column
    per metric. A metric that is undefined for a position (e.g. save_pct for outfield
    players) comes back as NaN and is dropped downstream.
    """
    df = metrics[metrics["rankable"]].copy()
    group = df.groupby(["competition_id", "position_group"])

    out = df[KEY_COLUMNS].copy()
    for metric in DISPLAY_METRICS:
        # rank(pct=True) gives 0..1 within each group; average ties; ->0..100.
        out[metric] = group[metric].rank(pct=True) * 100.0
    return out.set_index(KEY_COLUMNS)


def to_long(wide: pd.DataFrame) -> pd.DataFrame:
    """Reshape the wide percentile frame to one row per player-metric for storage."""
    long = wide.reset_index().melt(
        id_vars=KEY_COLUMNS, var_name="metric", value_name="percentile"
    )
    long = long.dropna(subset=["percentile"])
    long["percentile"] = long["percentile"].round(1)
    return long
