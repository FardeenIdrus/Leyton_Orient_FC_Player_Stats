"""The SkillCorner physical-metric definition (single source of truth).

The mirror of impect_map / statsbomb_season for the physical layer: it names the
24 physical metrics we keep and maps each to its raw SkillCorner column, so the
physical set is defined explicitly in code rather than being "whatever the API
returned". Internal names reuse the earlier squad-only loader's convention where
they overlap, so the existing skillcorner_player_season table and dashboard stay
consistent.

Units note: SkillCorner's `_full_all` columns are per-full-match-played averages
(a match runs ~95-100 min), so the `_p90` suffix here means "per match played",
close to but not exactly per-90 -- kept for naming consistency, documented here.
Speeds are km/h; times are seconds; distances are metres.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PhysicalMetric:
    name: str            # our internal name
    source: str          # the raw SkillCorner column
    description: str


SKILLCORNER_MAP: list[PhysicalMetric] = [
    # --- Volume / work rate ---
    PhysicalMetric("distance_p90", "total_distance_full_all", "Total distance covered per match (m)"),
    PhysicalMetric("meters_per_minute", "total_metersperminute_full_all", "Metres per minute (work rate)"),
    PhysicalMetric("running_distance_p90", "running_distance_full_all", "Running distance, 15-20 km/h (m)"),
    PhysicalMetric("hsr_distance_p90", "hsr_distance_full_all", "High-speed-running distance, 20-25 km/h (m)"),
    PhysicalMetric("sprint_distance_p90", "sprint_distance_full_all", "Sprint distance, >25 km/h (m)"),
    PhysicalMetric("hi_distance_p90", "hi_distance_full_all", "High-intensity distance (m)"),
    # --- Effort counts ---
    PhysicalMetric("hsr_count_p90", "hsr_count_full_all", "High-speed-running efforts"),
    PhysicalMetric("sprint_count_p90", "sprint_count_full_all", "Sprint efforts"),
    PhysicalMetric("hi_count_p90", "hi_count_full_all", "High-intensity efforts"),
    PhysicalMetric("cod_count_p90", "cod_count_full_all", "Changes of direction"),
    # --- Top speed ---
    PhysicalMetric("psv99_kmh", "psv99", "Peak sprint speed, 99th percentile (km/h)"),
    PhysicalMetric("top5_psv99_kmh", "psv99_top5", "Peak sprint speed, average of top 5 (km/h)"),
    # --- Accelerations / decelerations ---
    PhysicalMetric("medium_accel_count_p90", "medaccel_count_full_all", "Medium accelerations"),
    PhysicalMetric("high_accel_count_p90", "highaccel_count_full_all", "High accelerations"),
    PhysicalMetric("medium_decel_count_p90", "meddecel_count_full_all", "Medium decelerations"),
    PhysicalMetric("high_decel_count_p90", "highdecel_count_full_all", "High decelerations"),
    PhysicalMetric("explosive_accel_to_hsr_p90", "explacceltohsr_count_full_all",
                   "Explosive accelerations leading into high-speed running"),
    PhysicalMetric("explosive_accel_to_sprint_p90", "explacceltosprint_count_full_all",
                   "Explosive accelerations leading into a sprint"),
    # --- Explosiveness / agility (timing tests, seconds; lower is better) ---
    PhysicalMetric("time_to_hsr", "timetohsr_top3", "Time to reach high-speed running, top-3 avg (s)"),
    PhysicalMetric("time_to_hsr_post_cod", "timetohsrpostcod_top3",
                   "Time to HSR after a change of direction, top-3 avg (s)"),
    PhysicalMetric("time_to_sprint", "timetosprint_top3", "Time to reach sprint, top-3 avg (s)"),
    PhysicalMetric("time_to_sprint_post_cod", "timetosprintpostcod_top3",
                   "Time to sprint after a change of direction, top-3 avg (s)"),
    PhysicalMetric("agility_505_90", "timeto505around90_top3", "505 agility test, 90-degree turn (s)"),
    PhysicalMetric("agility_505_180", "timeto505around180_top3", "505 agility test, 180-degree turn (s)"),
]

# metrics where a lower value is BETTER (the timing tests), so scoring must invert them.
LOWER_IS_BETTER = {m.name for m in SKILLCORNER_MAP if m.name.startswith(("time_to_", "agility_"))}


def skillcorner_columns_used() -> set[str]:
    """Every raw SkillCorner column the map references (for verification)."""
    return {m.source for m in SKILLCORNER_MAP}
