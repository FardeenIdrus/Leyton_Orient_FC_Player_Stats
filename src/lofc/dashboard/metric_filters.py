"""Metric sliders for the Players page: which metrics get one, and how they filter.

Pure: no Streamlit, no database. The page renders the sliders and passes their values in.

Performance -> a MINIMUM-PERCENTILE slider for every metric the position is scored on, read
from the same percentiles the composite uses (within league + season + position).
Physical -> a few RAW per-90 sliders per position. Raw because km/h and metres mean the
same in every league; a percentile would not.

PHYSICAL_SLIDERS was chosen from 2025/26 per-90 data (2026-10-04): the metrics on which each
position sits furthest above the outfield average, plus top speed where pace defines the
role. Coverage is 88%+ for every one. Placeholder until the Head of Recruitment names his
own -- edit the lists, nothing else changes. Distance and metres-per-minute are never paired:
per 90 they are one measurement (r = 1.00).
"""

from __future__ import annotations

import pandas as pd

from lofc.model.scorecard import _resolved_performance

PHYSICAL_SLIDERS: dict[str, list[str]] = {
    "Goalkeeper": [],
    "Centre Back": ["psv99_kmh", "distance_p90", "medium_accel_count_p90"],
    "Full Back": ["psv99_kmh", "hsr_distance_p90", "sprint_distance_p90"],
    "Defensive Mid": ["distance_p90", "running_distance_p90", "medium_decel_count_p90"],
    "Central Mid": ["meters_per_minute", "running_distance_p90", "hsr_distance_p90"],
    "Attacking Mid": ["meters_per_minute", "hsr_distance_p90", "cod_count_p90"],
    "Winger": ["psv99_kmh", "sprint_distance_p90", "explosive_accel_to_sprint_p90"],
    "Centre Forward": ["psv99_kmh", "sprint_count_p90", "high_accel_count_p90"],
}

# metric -> (label, display format). Labels are the glossary's names (glossary_data.PHYSICAL)
# with a unit, so a metric has one name on every page.
_SLIDER_UNITS = {"psv99_kmh": "km/h", "distance_p90": "m per 90",
                 "running_distance_p90": "m per 90", "hsr_distance_p90": "m per 90",
                 "sprint_distance_p90": "m per 90"}
_FORMATS = {"psv99_kmh": "%.1f", "sprint_count_p90": "%.1f", "high_accel_count_p90": "%.1f",
            "explosive_accel_to_sprint_p90": "%.1f"}


def _slider_label(metric: str) -> str:
    from lofc.dashboard.glossary_data import PHYSICAL
    name = PHYSICAL[metric][0]
    if metric in _SLIDER_UNITS:
        unit = _SLIDER_UNITS[metric]
        return f"{name[:-1]}, {unit})" if name.endswith(")") else f"{name} ({unit})"
    return f"{name} per 90" if metric != "meters_per_minute" else name


PHYSICAL_LABELS: dict[str, tuple[str, str]] = {
    m: (_slider_label(m), _FORMATS.get(m, "%.0f"))
    for m in sorted({x for v in PHYSICAL_SLIDERS.values() for x in v})}

PCT_KEY = ["player_id", "competition_id", "season_id", "position_group"]
RAW_KEY = ["player_id", "competition_id"]


def performance_slider_metrics(position: str, archetype: str) -> list[str]:
    """The stored metrics the position's Performance dimension is scored on, in order."""
    return _resolved_performance(position, archetype)


def apply_metric_filters(pool: pd.DataFrame, pcts: pd.DataFrame, raw: pd.DataFrame,
                         pct_mins: dict[str, float], raw_mins: dict[str, float]
                         ) -> tuple[pd.DataFrame, int]:
    """Keep players at or above every ACTIVE minimum. Returns (filtered pool, how many were
    excluded for having no value on an active filter).

    Active = a percentile minimum above 0, or any raw minimum passed in (the page passes a
    raw minimum only once its slider has moved off the floor). Pool columns and row order
    are preserved."""
    pct_active = {m: v for m, v in pct_mins.items() if v and v > 0}
    if not pct_active and not raw_mins:
        return pool, 0

    frame = pool
    if pct_active:
        frame = frame.merge(pcts[PCT_KEY + list(pct_active)], on=PCT_KEY, how="left")
    if raw_mins:
        frame = frame.merge(raw[RAW_KEY + list(raw_mins)].drop_duplicates(RAW_KEY),
                            on=RAW_KEY, how="left")
    needed = list(pct_active) + list(raw_mins)
    missing = frame[needed].isna().any(axis=1)
    keep = ~missing
    for m, v in pct_active.items():
        keep &= frame[m] >= v
    for m, v in raw_mins.items():
        keep &= frame[m] >= v
    out = pool[keep.to_numpy()]
    return out, int(missing.sum())
