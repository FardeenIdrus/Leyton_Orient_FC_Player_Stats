"""Which metrics can be shown as a season total, and how (owner, 2026-10-12).

A total is shown only where adding up makes sense:
  * counts -> whole number;
  * value metrics (xG, xA, PxT goal-threat values) -> 2 decimals, so 0.69 does not read "1";
  * ratios / percentages (Impect `kind == "ratio"`) -> none;
  * every physical metric -> none: speeds, rates and timings cannot be added up, and the
    distances' minutes basis is SkillCorner's tracked minutes, not the Impect minutes the
    card holds (Josh Walker 25/26: 888 tracked vs 1,031 played), so a total would overstate.
"""

from __future__ import annotations

import math

from lofc.ingest.impect_map import IMPECT_MAP
from lofc.ingest.skillcorner_map import SKILLCORNER_MAP

NO_TOTAL = "—"

PHYSICAL = {m.name for m in SKILLCORNER_MAP}
RATIOS = {m.name for m in IMPECT_MAP if m.kind == "ratio"}
VALUE_METRICS = {
    "xg_p90", "np_xg_p90", "xa_p90", "np_xg_xa_p90", "post_shot_xg_p90", "packing_xg_p90",
    "xg_overperformance_p90", "shot_threat_p90", "pass_value_p90", "dribble_carry_value_p90",
    "defensive_value_p90", "on_ball_value_p90", "gk_gsaa_p90",
}


def has_total(metric: str) -> bool:
    return not (metric in PHYSICAL or metric in RATIOS or metric.endswith("_pct"))


def season_total(metric: str, per90: float | None, minutes: float | None) -> str:
    """The season total as shown on screen, or '—' where a total makes no sense."""
    if not has_total(metric) or per90 is None or not minutes:
        return NO_TOTAL
    try:
        value = float(per90)
    except (TypeError, ValueError):
        return NO_TOTAL
    if math.isnan(value):
        return NO_TOTAL
    total = value * float(minutes) / 90.0
    # counts round half up, the one rule for whole numbers (owner 2026-11-09); round() is
    # half to even
    return f"{total:,.2f}" if metric in VALUE_METRICS else f"{math.floor(total + 0.5):,}"
