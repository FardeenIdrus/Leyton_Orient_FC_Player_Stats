"""Metric sliders for the Players page: which metrics get one, and how they filter.

Pure: no Streamlit, no database. The page renders the sliders and passes their values in.

Performance -> a MINIMUM-PERCENTILE slider for every metric the position is scored on, read
from the same percentiles the composite uses (within league + season + position).
Physical -> a RAW slider for every SkillCorner physical metric, grouped for the page. Raw
because km/h and metres mean the same in every league; a percentile would not. Higher-is-
better metrics get a MINIMUM, the six lower-is-better ones (time to speed, agility) a MAXIMUM.

Every outfield position gets all of them (owner, 2026-11-02: recruiters want the filters
granular); goalkeepers get none. Distance and metres per minute are one measurement per 90
(r = 1.00) -- both are offered because the owner asked for every metric.
"""

from __future__ import annotations

import math

import pandas as pd

from lofc.model.scorecard import _resolved_performance

PHYSICAL_GROUPS: dict[str, list[str]] = {
    "Distance": ["distance_p90", "meters_per_minute", "running_distance_p90",
                 "hsr_distance_p90", "sprint_distance_p90", "hi_distance_p90"],
    # psv99_kmh (all-match average) is deliberately NOT offered: the Head of Recruitment wants
    # only Top speed = top5_psv99_kmh (tests/test_top_speed.py).
    "Speed": ["top5_psv99_kmh"],
    "Intensity": ["hsr_count_p90", "sprint_count_p90", "hi_count_p90", "cod_count_p90"],
    "Acceleration": ["medium_accel_count_p90", "high_accel_count_p90",
                     "medium_decel_count_p90", "high_decel_count_p90",
                     "explosive_accel_to_hsr_p90", "explosive_accel_to_sprint_p90"],
    "Time to speed": ["time_to_hsr", "time_to_hsr_post_cod", "time_to_sprint",
                      "time_to_sprint_post_cod"],
    "Agility": ["agility_505_90", "agility_505_180"],
}

# Seconds: a SMALLER number is better, so these filter with a maximum.
LOWER_IS_BETTER_PHYSICAL: list[str] = [*PHYSICAL_GROUPS["Time to speed"],
                                       *PHYSICAL_GROUPS["Agility"]]

_ALL_PHYSICAL = [m for ms in PHYSICAL_GROUPS.values() for m in ms]
PHYSICAL_SLIDERS: dict[str, list[str]] = {
    "Goalkeeper": [],
    **{p: list(_ALL_PHYSICAL) for p in
       ["Centre Back", "Full Back", "Defensive Mid", "Central Mid", "Attacking Mid",
        "Winger", "Centre Forward"]},
}

# metric -> (label, display format). Labels are the glossary's names (glossary_data.PHYSICAL)
# with a unit, so a metric has one name on every page.
_M90 = ["distance_p90", "running_distance_p90", "hsr_distance_p90", "sprint_distance_p90",
        "hi_distance_p90"]
_SLIDER_UNITS = {**{m: "m per 90" for m in _M90},
                 **{m: "km/h" for m in PHYSICAL_GROUPS["Speed"]},
                 **{m: "s" for m in LOWER_IS_BETTER_PHYSICAL}}
# Seconds to 2 decimals (they differ by hundredths); km/h and rates per 90 to 1.
_FORMATS = {**{m: "%.2f" for m in LOWER_IS_BETTER_PHYSICAL},
            **{m: "%.1f" for m in PHYSICAL_GROUPS["Speed"]},
            **{m: "%.1f" for m in ["hsr_count_p90", "sprint_count_p90", "hi_count_p90",
                                   "cod_count_p90", "medium_accel_count_p90",
                                   "high_accel_count_p90", "medium_decel_count_p90",
                                   "high_decel_count_p90", "explosive_accel_to_hsr_p90",
                                   "explosive_accel_to_sprint_p90"]}}


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

def slider_bounds(values: pd.Series, fmt: str) -> tuple[float, float, float]:
    """(floor, ceiling, step) for a raw slider, rounded OUT to the display precision so the
    real minimum and maximum are both reachable -- whole-number bounds would floor a 4.37 s
    sprint time to 4 and make every player look equal."""
    step = 0.01 if fmt.endswith("2f") else 0.1 if fmt.endswith("1f") else 1.0
    lo = math.floor(round(float(values.min()) / step, 6)) * step
    hi = math.ceil(round(float(values.max()) / step, 6)) * step
    return round(lo, 2), round(hi, 2), step


PCT_KEY = ["player_id", "competition_id", "season_id", "position_group"]
RAW_KEY = ["player_id", "competition_id"]


def performance_slider_metrics(position: str, archetype: str) -> list[str]:
    """The stored metrics the position's Performance dimension is scored on, in order."""
    return _resolved_performance(position, archetype)


def apply_metric_filters(pool: pd.DataFrame, pcts: pd.DataFrame, raw: pd.DataFrame,
                         pct_mins: dict[str, float], raw_mins: dict[str, float],
                         raw_maxs: dict[str, float] | None = None
                         ) -> tuple[pd.DataFrame, int]:
    """Keep players at or above every ACTIVE minimum and at or below every raw maximum. Returns (filtered pool, how many were
    excluded for having no value on an active filter).

    Active = a percentile minimum above 0, or any raw minimum passed in (the page passes a
    raw minimum or maximum only once its slider has moved off its default). Pool columns and row order
    are preserved."""
    pct_active = {m: v for m, v in pct_mins.items() if v and v > 0}
    raw_maxs = raw_maxs or {}
    if not pct_active and not raw_mins and not raw_maxs:
        return pool, 0

    # The filter values join under PRIVATE names. The pool already carries some metrics
    # raw (assists_p90, xa_p90, np_xg_p90 for the totals); joining a second column of the
    # same name made pandas rename both, and the page died with KeyError 'xa_p90' (found
    # live, 2026-11-02). Private names also make sure a percentile filter reads the
    # percentile, never the pool's raw value.
    pct_cols = {m: f"__pct__{m}" for m in pct_active}
    # A metric can carry both a minimum and a maximum: one join column serves both.
    raw_need = list(dict.fromkeys([*raw_mins, *raw_maxs]))
    raw_cols = {m: f"__raw__{m}" for m in raw_need}
    frame = pool
    if pct_active:
        frame = frame.merge(pcts[PCT_KEY + list(pct_active)].rename(columns=pct_cols),
                            on=PCT_KEY, how="left")
    if raw_need:
        frame = frame.merge(raw[RAW_KEY + raw_need].drop_duplicates(RAW_KEY)
                            .rename(columns=raw_cols), on=RAW_KEY, how="left")
    needed = list(pct_cols.values()) + list(raw_cols.values())
    missing = frame[needed].isna().any(axis=1)
    keep = ~missing
    for m, v in pct_active.items():
        keep &= frame[pct_cols[m]] >= v
    for m, v in raw_mins.items():
        keep &= frame[raw_cols[m]] >= v
    for m, v in raw_maxs.items():
        keep &= frame[raw_cols[m]] <= v
    out = pool[keep.to_numpy()]
    return out, int(missing.sum())
