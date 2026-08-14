"""The unified metric registry: every metric the platform uses, with explicit provenance.

ONE entry per final metric (87 total), each recording:
  - source      : which provider supplies it (exactly one — conflicts are resolved
                  here, at definition time, never at runtime)
  - derivation  : EXACTLY how the number is produced — the raw column for a rename,
                  the formula for anything we compute or derive ourselves
  - club_metric : the club-framework stat it serves, where applicable

Assembled FROM the four per-source definition files (which stay the truth for their
own source): impect_map.py (41 after the Phase B migrations), statsbomb_season.py (12),
the event-derived set defined below + models.PER90_COLUMNS (10 remaining), and
skillcorner_map.py (24). This file adds the cross-source view: one place that answers
"which metric, from where, derived how".

Overlap resolution is explicit in OVERLAP_RESOLUTION: where two sources could supply
the same metric, the winner is recorded there and only the winner enters the registry.

Run `python -m lofc.model.metric_registry` to print the full inventory.
"""

from __future__ import annotations

from dataclasses import dataclass

from lofc.ingest.impect_map import IMPECT_MAP, mappable
from lofc.ingest.skillcorner_map import LOWER_IS_BETTER, SKILLCORNER_MAP
from lofc.ingest.statsbomb_season import STATSBOMB_GAP_MAP

# The four sources. Every registry entry carries exactly one.
IMPECT = "impect"
SB_ADVANCED = "statsbomb_advanced"    # StatsBomb Season-Player-Stats endpoint (pre-computed)
SB_COMPUTED = "statsbomb_computed"    # computed by US from raw StatsBomb match events
SKILLCORNER = "skillcorner"


@dataclass(frozen=True)
class MetricSpec:
    name: str
    source: str
    derivation: str          # explicit: raw column, or the exact formula
    club_metric: str = ""    # the club-framework stat this serves ("" = platform extra)
    confidence: str = ""     # impect only: direct/derived/analogue/native
    lower_is_better: bool = False


# ---------------------------------------------------------------------------
# Overlap resolution (explicit, decided at definition time).
# A metric listed here can be produced by more than one source; ONLY the winner
# appears in the registry. Rationale: Impect is the primary provider (club
# direction); the StatsBomb advanced endpoint beats our own event counting where
# both exist (it is StatsBomb's own maintained computation).
# ---------------------------------------------------------------------------
OVERLAP_RESOLUTION: dict[str, dict] = {
    # metric                     winner        also available from
    "goals_p90":                {"winner": IMPECT, "superseded": [SB_COMPUTED]},
    "np_xg_p90":                {"winner": IMPECT, "superseded": [SB_COMPUTED]},
    "shots_p90":                {"winner": IMPECT, "superseded": [SB_COMPUTED]},
    "assists_p90":              {"winner": IMPECT, "superseded": [SB_COMPUTED]},
    "xa_p90":                   {"winner": IMPECT, "superseded": [SB_COMPUTED]},
    "key_passes_p90":           {"winner": IMPECT, "superseded": [SB_COMPUTED]},
    "passes_completed_p90":     {"winner": IMPECT, "superseded": [SB_COMPUTED]},
    "passes_into_box_p90":      {"winner": IMPECT, "superseded": [SB_COMPUTED]},
    "pass_completion_pct":      {"winner": IMPECT, "superseded": [SB_COMPUTED]},
    "pressures_p90":            {"winner": IMPECT, "superseded": [SB_COMPUTED]},
    "dribbles_p90":             {"winner": SB_ADVANCED, "superseded": [SB_COMPUTED]},
    "dribble_success_pct":      {"winner": SB_ADVANCED, "superseded": [SB_COMPUTED]},
    # Phase B migrations: validated per-player vs the StatsBomb value before adoption
    # (correlations in impect_map notes). tackles/interceptions/ball_recoveries/gk are
    # deliberately NOT migrated -- Impect measures different concepts there (see the
    # "none" tier of impect_map for evidence and the honestly-named successors).
    "passes_p90":               {"winner": IMPECT, "superseded": [SB_COMPUTED]},
    "np_goals_p90":             {"winner": IMPECT, "superseded": [SB_COMPUTED]},
    "xg_p90":                   {"winner": IMPECT, "superseded": [SB_COMPUTED]},
    "blocks_p90":               {"winner": IMPECT, "superseded": [SB_COMPUTED]},
    "clearances_p90":           {"winner": IMPECT, "superseded": [SB_COMPUTED]},
}


# ---------------------------------------------------------------------------
# The remaining event-computed metrics (source = SB_COMPUTED). Originally 15;
# 5 migrated to Impect in Phase B (passes, np_goals, xg, blocks, clearances --
# see OVERLAP_RESOLUTION). What stays here is what Impect measurably does NOT
# supply (validation correlations in impect_map's "none" tier). Counting happens
# in aggregate/events.py (line refs below); the per-90 division
# (count / minutes x 90) is aggregate/player_season.py:134.
# ---------------------------------------------------------------------------
_P90 = "count / minutes x 90 (player_season.py:134)"
SB_COMPUTED_SPECS: list[MetricSpec] = [
    MetricSpec("tackles_p90", SB_COMPUTED, f'count of Duel events with duel type "Tackle" (events.py:192-194); {_P90}',
               club_metric="(tackle count)"),
    MetricSpec("interceptions_p90", SB_COMPUTED, f"count of Interception events (events.py:184); {_P90}",
               club_metric="Interceptions"),
    MetricSpec("ball_recoveries_p90", SB_COMPUTED, f"count of Ball Recovery events (events.py:190); {_P90}",
               club_metric="Ball recoveries"),
    MetricSpec("carries_p90", SB_COMPUTED, f"count of Carry events (events.py:176); {_P90}"),
    MetricSpec("progressive_carries_p90", SB_COMPUTED,
               f"Carry events moving the ball >= 10m toward goal (end_x - start_x >= 10, events.py:179); {_P90}"),
    MetricSpec("progressive_passes_p90", SB_COMPUTED,
               f"completed passes moving the ball >= 15m toward goal (events.py:150); {_P90}"),
    MetricSpec("passes_into_final_third_p90", SB_COMPUTED,
               f"completed passes from own two-thirds (start_x < 80) ending in the final third (end_x >= 80) (events.py:152); {_P90}"),
    MetricSpec("dribbles_completed_p90", SB_COMPUTED,
               f'Dribble events with outcome "Complete" (events.py:173); {_P90}'),
    MetricSpec("gk_saves_p90", SB_COMPUTED,
               f'Goal Keeper events whose type contains "Saved" (Shot/Penalty Saved, Saved To Post; events.py:195-198); {_P90}'),
    MetricSpec("save_pct", SB_COMPUTED,
               "gk_saves / (gk_saves + goals conceded while the team's main goalkeeper) (player_season.py:138-142)",
               club_metric="Save%"),
]

# Descriptions for the advanced-endpoint metrics (pre-computed by StatsBomb; we
# rename + minutes-weight mid-season movers, statsbomb_season.py:translate_frame).
_ADV_NOTE = {
    "pressures_opp_half_p90": ("Pressures in Opposing Half", ""),
    "aggressive_actions_p90": ("Aggressive Actions", "tackles/pressures/fouls within 2s of an opponent receiving"),
    "padj_tackles_interceptions_p90": ("PAdj Tackles & Interceptions", "possession-adjusted by StatsBomb"),
    "padj_pressures_p90": ("PAdj Pressures", "possession-adjusted by StatsBomb"),
    "xg_buildup_p90": ("xGBuildup", "xG of possessions the player took part in, excluding his shot/assist"),
    "pressured_pass_pct": ("Pressured Pass%", "completion % of passes made under pressure"),
    "successful_box_cross_pct": ("Successful Box Cross%", ""),
    "dribbles_p90": ("Dribbles", "attempted dribbles"),
    "dribble_success_pct": ("Dribble Success", ""),
    "gk_claims_pct": ("Claims", "claimable-cross claim rate vs the average keeper (CCAA)"),
    "gk_aggressive_distance": ("Goalkeeper Aggressive Distance", "avg distance from goal of keeper defensive actions"),
    "long_ball_pct": ("Long Ball%", "long-pass completion %"),
}


def _impect_derivation(m) -> str:
    """Render an impect_map entry's formula as an explicit string."""
    def side(pairs):
        return " ".join(("- " if s < 0 else "+ ") + c for c, s in pairs).lstrip("+ ")
    if m.kind == "rate":
        return (f"per-90 from Impect per-match averages: season total = ({side(m.numer)}) "
                f"x matchShare summed over position rows, / minutes x 90 (impect_translate.py)")
    return (f"season-total ratio from Impect: ({side(m.numer)}) / ({side(m.denom)}) "
            f"(impect_translate.py)")


def build_registry() -> list[MetricSpec]:
    """Assemble the 87-metric registry from the four per-source definitions."""
    specs: list[MetricSpec] = []
    for m in mappable():                                   # 36 from Impect
        specs.append(MetricSpec(m.name, IMPECT, _impect_derivation(m),
                                club_metric=m.club_metric, confidence=m.confidence))
    for name, col in STATSBOMB_GAP_MAP.items():            # 12 from the advanced endpoint
        club, note = _ADV_NOTE.get(name, ("", ""))
        extra = f" — {note}" if note else ""
        specs.append(MetricSpec(name, SB_ADVANCED,
                                f"taken as-is from endpoint column {col} (pre-computed per-90/ratio by "
                                f"StatsBomb){extra}; mid-season movers minutes-weighted "
                                f"(statsbomb_season.py:translate_frame)", club_metric=club))
    specs.extend(SB_COMPUTED_SPECS)                        # 15 computed from events
    for m in SKILLCORNER_MAP:                              # 24 physical
        specs.append(MetricSpec(m.name, SKILLCORNER,
                                f"per-match average from SkillCorner column {m.source}",
                                club_metric=m.description,
                                lower_is_better=m.name in LOWER_IS_BETTER))
    return specs


REGISTRY: list[MetricSpec] = build_registry()
BY_NAME: dict[str, MetricSpec] = {s.name: s for s in REGISTRY}


def names_for(source: str) -> list[str]:
    return [s.name for s in REGISTRY if s.source == source]


def _check() -> None:
    """Registry invariants; import-time so a bad edit fails loudly everywhere."""
    names = [s.name for s in REGISTRY]
    dupes = {n for n in names if names.count(n) > 1}
    assert not dupes, f"duplicate metric names in registry: {dupes}"
    counts = {IMPECT: 45, SB_ADVANCED: 12, SB_COMPUTED: 10, SKILLCORNER: 24}
    for source, expected in counts.items():
        got = len(names_for(source))
        assert got == expected, f"{source}: expected {expected} metrics, got {got}"
    assert len(REGISTRY) == 91, f"expected 91 metrics total, got {len(REGISTRY)}"
    for name, rule in OVERLAP_RESOLUTION.items():
        spec = BY_NAME.get(name)
        assert spec is not None, f"overlap rule for unknown metric {name}"
        assert spec.source == rule["winner"], \
            f"{name}: registry source {spec.source} != declared winner {rule['winner']}"


_check()


def main() -> None:
    print(f"Unified metric registry: {len(REGISTRY)} metrics\n")
    for source in (IMPECT, SB_ADVANCED, SB_COMPUTED, SKILLCORNER):
        block = [s for s in REGISTRY if s.source == source]
        print(f"=== {source} ({len(block)}) ===")
        for s in block:
            flag = "  [lower is better]" if s.lower_is_better else ""
            club = f"  (club: {s.club_metric})" if s.club_metric else ""
            print(f"  {s.name}{club}{flag}")
            print(f"      {s.derivation}")
        print()
    print("Overlap resolution (decided at definition time):")
    for name, rule in OVERLAP_RESOLUTION.items():
        print(f"  {name}: {rule['winner']} wins over {', '.join(rule['superseded'])}")


if __name__ == "__main__":
    main()
