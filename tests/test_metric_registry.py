"""Tests for the unified metric registry + the neutral-layer merge. No network/DB."""

import pandas as pd
import pytest

from lofc.model import metric_registry as reg
from lofc.model.build_neutral import SPINE_IDENTITY, combine


# --- registry ------------------------------------------------------------------

def test_registry_counts_and_uniqueness():
    names = [s.name for s in reg.REGISTRY]
    assert len(reg.REGISTRY) == 91
    assert len(names) == len(set(names))
    assert len(reg.names_for(reg.IMPECT)) == 45   # 36 + 5 Phase B migrations + 4 club-framework
    assert len(reg.names_for(reg.SB_ADVANCED)) == 12
    assert len(reg.names_for(reg.SB_COMPUTED)) == 10  # 15 - 5 migrated to Impect
    assert len(reg.names_for(reg.SKILLCORNER)) == 24


def test_every_metric_has_an_explicit_derivation():
    for s in reg.REGISTRY:
        assert s.derivation and len(s.derivation) > 20, f"{s.name} lacks a real derivation"


def test_overlap_winners_match_registry_sources():
    for name, rule in reg.OVERLAP_RESOLUTION.items():
        assert reg.BY_NAME[name].source == rule["winner"]
        # a superseded source must never also be the registry source for that name
        assert reg.BY_NAME[name].source not in rule["superseded"]


def test_computed_derivations_cite_the_counting_code():
    for s in reg.REGISTRY:
        if s.source == reg.SB_COMPUTED:
            assert "events.py" in s.derivation or "player_season.py" in s.derivation, \
                f"{s.name}: computed metric must cite where it is computed"


def test_lower_is_better_only_on_timing_metrics():
    flagged = {s.name for s in reg.REGISTRY if s.lower_is_better}
    assert flagged == {"time_to_hsr", "time_to_hsr_post_cod", "time_to_sprint",
                       "time_to_sprint_post_cod", "agility_505_90", "agility_505_180"}


# --- combine (pure merge) ------------------------------------------------------

def _spine():
    rows = []
    for pid, name in [(1, "Player One"), (2, "Player Two")]:
        row = {"player_id": pid, "competition_id": 4, "season_id": 318,
               "player_name": name, "team_name": "Club", "position_group": "Centre Forward",
               "minutes": 1800, "rankable": True}
        for c in reg.names_for(reg.SB_COMPUTED):
            row[c] = 1.0
        rows.append(row)
    return pd.DataFrame(rows)


def test_combine_keeps_one_row_per_spine_player_and_fills_by_source():
    impect = pd.DataFrame([{"player_id": 1, "goals_p90": 0.5, "packing_xg_p90": 0.2}])
    sc = pd.DataFrame([{"player_id": 2, "psv99_kmh": 33.1}])
    out = combine(_spine(), impect, None, sc)          # advanced source unavailable

    assert len(out) == 2                                # no fan-out, spine preserved
    assert list(out.columns) == SPINE_IDENTITY + [s.name for s in reg.REGISTRY]
    # player 1 has Impect values, player 2 does not
    assert out.loc[out.player_id == 1, "goals_p90"].iloc[0] == 0.5
    assert pd.isna(out.loc[out.player_id == 2, "goals_p90"].iloc[0])
    # physical filled for player 2 only
    assert out.loc[out.player_id == 2, "psv99_kmh"].iloc[0] == 33.1
    assert pd.isna(out.loc[out.player_id == 1, "psv99_kmh"].iloc[0])
    # the unavailable advanced source is all-blank but the columns exist
    assert out["xg_buildup_p90"].isna().all()
    # computed metrics came straight off the spine
    assert (out["tackles_p90"] == 1.0).all()


def test_combine_dedupes_a_source_side_duplicate():
    dup = pd.DataFrame([{"player_id": 1, "goals_p90": 0.5},
                        {"player_id": 1, "goals_p90": 0.9}])
    out = combine(_spine(), dup, None, None)
    assert len(out) == 2                                # still one row per spine player


# --- the neutral DB table stays in lockstep with the registry --------------------

def test_neutral_table_columns_match_registry():
    from lofc.store.models import PlayerMetricNeutral
    cols = set(PlayerMetricNeutral.__table__.columns.keys())
    for s in reg.REGISTRY:
        assert s.name in cols, f"registry metric {s.name} missing from player_metrics_neutral"
    # identity + keys + all 91 metrics, nothing else unexplained
    identity = {"id", "player_id", "competition_id", "season_id", "player_name",
                "team_name", "position_group", "minutes", "rankable"}
    assert cols == identity | {s.name for s in reg.REGISTRY}
