"""Impect detail data: zones, lanes, receptions by availability, and Impect's own scores.

DISPLAY ONLY -- nothing here reaches the composite. Stored long (one row per player x metric)
in player_detail_metrics, so adding a zone family needs no migration.

Per 90 follows impect_translate exactly: Impect reports per-match averages per POSITION row;
season total = sum(value x matchShare); per 90 = total / minutes x 90.

Scores are already rates, one per position row, and a short row is extreme (9 minutes of
central midfield scored 8.74 IMPECT on 2025/26 League One). So a season score is the
MINUTES-WEIGHTED mean across a player's rows, never a single row.
"""

import json
from pathlib import Path

import pandas as pd
import pytest

from lofc.ingest import impect_detail as d


def _averages():
    # player 1: two position rows; player 2: one row.
    return pd.DataFrame({
        "playerId": [1, 1, 2],
        "matchShare": [2.0, 1.0, 3.0],
        "playDuration": [180 * 60, 90 * 60, 270 * 60],        # seconds
        "OFFENSIVE_TOUCHES_IN_PACKING_ZONE_IB": [3.0, 6.0, 1.0],
        "BYPASSED_OPPONENTS_RECEIVING_NUMBER_BY_ACTION_AVAILABILITY_BTL": [2.0, 0.0, 4.0],
    })


def test_metric_names_are_namespaced_and_unique():
    names = [m.name for m in d.DETAIL_METRICS]
    assert len(names) == len(set(names))
    assert all(n.split(".")[0] in {"zone", "lane", "avail", "score"} for n in names)


def test_every_zone_family_covers_all_eleven_zones_and_five_lanes():
    assert len(d.ZONES) == 11 and len(d.LANES) == 5
    for family in d.ZONE_FAMILIES:
        zone_rows = [m for m in d.DETAIL_METRICS if m.name.startswith(f"zone.{family}.")]
        lane_rows = [m for m in d.DETAIL_METRICS if m.name.startswith(f"lane.{family}.")]
        assert len(zone_rows) == 11
        assert len(lane_rows) in (0, 5)


def test_fdr_is_stored_as_receptions_from_deep_runs():
    """Impect's catalogue (context.label): FDR = 'Availability From Deep Runs' -- receiving
    behind the opponent's defensive chain. Found 2026-10-09; needed by the in-behind profiles."""
    m = next(m for m in d.DETAIL_METRICS if m.name == "avail.receptions.FDR")
    assert m.source == "BYPASSED_OPPONENTS_RECEIVING_NUMBER_BY_ACTION_AVAILABILITY_FDR"
    assert "deep runs" in m.label.lower()


def test_counts_are_rebuilt_per_90_and_as_season_totals():
    out = d.translate_detail(_averages()).set_index(["playerId", "metric"])
    # player 1: total = 3*2 + 6*1 = 12 over 270 minutes -> 4.0 per 90
    row = out.loc[(1, "zone.touches.IB")]
    assert row["total"] == pytest.approx(12.0)
    assert row["value_p90"] == pytest.approx(4.0)
    # player 2: total = 4*3 = 12 over 270 minutes
    assert out.loc[(2, "avail.receptions.BTL"), "value_p90"] == pytest.approx(4.0)


def test_a_column_missing_from_the_file_produces_no_rows_not_zeros():
    out = d.translate_detail(_averages())
    assert not out["metric"].str.startswith("zone.xg.").any()


def test_scores_are_the_minutes_weighted_mean_across_positions():
    scores = pd.DataFrame({
        "playerId": [7, 7],
        "playDuration": [9 * 60, 891 * 60],
        "IMPECT_SCORE_PACKING": [8.74, 0.30],
    })
    out = d.translate_scores(scores).set_index(["playerId", "metric"])
    assert out.loc[(7, "score.impect"), "value_p90"] == pytest.approx((8.74 * 9 + 0.30 * 891) / 900)
    assert pd.isna(out.loc[(7, "score.impect"), "total"])


def test_scores_with_no_minutes_are_dropped():
    scores = pd.DataFrame({"playerId": [7], "playDuration": [0], "IMPECT_SCORE_PACKING": [1.0]})
    assert d.translate_scores(scores).empty


RAW = Path("/app/data/raw/impect")


@pytest.mark.skipif(not (RAW / "kpi_definitions.json").exists(),
                    reason="licensed raw data not present")
def test_every_impect_column_named_exists_in_impects_catalogue():
    """A typo in a template would otherwise produce silently empty zones."""
    k = json.loads((RAW / "kpi_definitions.json").read_text())
    k = k if isinstance(k, list) else k.get("data", k)
    known = {row["name"] for row in k}
    for m in d.DETAIL_METRICS:
        if not m.name.startswith("score."):
            assert m.source in known, m.source


# --- 2026-10-09: names, families and units aligned with Impect's own platform -------------

def test_zone_names_are_impects_own():
    """Taken from the `context.label` of Impect's KPI catalogue. "IB" is In-Behind, not the box."""
    assert d.ZONE_LABELS["IB"] == "In-Behind Central Zone"
    assert d.ZONE_LABELS["IBWL"] == "In-Behind Wide Left Zone"
    assert d.ZONE_LABELS["CB"] == "Centre-Back Zone"
    assert set(d.ZONE_LABELS) == set(d.ZONES)


@pytest.mark.skipif(not (RAW / "kpi_definitions.json").exists(),
                    reason="licensed raw data not present")
def test_zone_names_match_the_catalogue_exactly():
    k = json.loads((RAW / "kpi_definitions.json").read_text())
    k = k if isinstance(k, list) else k.get("data", k)
    ctx = {r["context"]["name"]: r["context"]["label"] for r in k
           if r.get("context") and "PACKING_ZONE" in r["name"]}
    for code, label in d.ZONE_LABELS.items():
        assert ctx[code] == label


def test_bypass_families_keep_their_direction():
    for fam in ("bypassed_opponents_from", "bypassed_opponents_to",
                "bypassed_defenders_from", "bypassed_defenders_to",
                "bypassed_opponents_receiving_to", "bypassed_defenders_receiving_to"):
        assert fam in d.ZONE_FAMILIES
    assert "_FROM_PACKING_ZONE_" in d.ZONE_FAMILIES["bypassed_opponents_from"][0]
    assert "_TO_PACKING_ZONE_" in d.ZONE_FAMILIES["bypassed_opponents_to"][0]


def test_total_touches_is_offensive_plus_defensive():
    """Verified on the raw data: equal in every zone checked (Josh Walker 25/26, AM 73+15=88)."""
    frame = pd.DataFrame({"playerId": [1], "matchShare": [2.0], "playDuration": [180 * 60],
                          "OFFENSIVE_TOUCHES_IN_PACKING_ZONE_AM": [3.0],
                          "DEFENSIVE_TOUCHES_IN_PACKING_ZONE_AM": [1.0]})
    out = d.translate_detail(frame).set_index("metric")
    assert out.loc["zone.total_touches.AM", "total"] == pytest.approx(8.0)


def test_matches_are_stored_for_the_per_match_unit():
    """Impect's 'Absolute' is per match: season total / sum(matchShare)."""
    out = d.translate_detail(_averages()).set_index(["playerId", "metric"])
    assert out.loc[(1, "meta.matches"), "total"] == pytest.approx(3.0)


def test_per_position_scores_are_kept_alongside_the_combined_one():
    """Impect scores each position separately; the card shows that breakdown under the
    combined tile, so nothing is hidden and each row can be checked against Impect."""
    scores = pd.DataFrame({
        "playerId": [7, 7], "position": ["CENTER_FORWARD", "RIGHT_WINGER"],
        "playDuration": [992 * 60, 18 * 60],
        "OFFENSIVE_IMPECT_SCORE_PACKING": [0.73, -0.06],
        "DEFENSIVE_IMPECT_SCORE_PACKING": [0.10, 0.20]})
    out = d.translate_scores(scores).set_index(["playerId", "metric"])
    assert out.loc[(7, "score_pos.offensive.CENTER_FORWARD"), "value_p90"] == pytest.approx(0.73)
    assert out.loc[(7, "score_pos.defensive.RIGHT_WINGER"), "value_p90"] == pytest.approx(0.20)
    assert out.loc[(7, "score_pos.minutes.CENTER_FORWARD"), "value_p90"] == pytest.approx(992)


def test_same_position_at_two_clubs_gives_one_minutes_weighted_row():
    """A mid-season mover has one Impect row per club per position; the stored table allows
    one value per player per metric, so the two are combined by minutes."""
    scores = pd.DataFrame({
        "playerId": [7, 7], "position": ["RIGHT_WINGER", "RIGHT_WINGER"],
        "playDuration": [600 * 60, 300 * 60],
        "OFFENSIVE_IMPECT_SCORE_PACKING": [0.60, 0.30],
        "DEFENSIVE_IMPECT_SCORE_PACKING": [0.10, 0.10]})
    out = d.translate_scores(scores)
    assert not out.duplicated(["playerId", "metric"]).any()
    row = out.set_index("metric").loc["score_pos.offensive.RIGHT_WINGER"]
    assert row["value_p90"] == pytest.approx((0.60 * 600 + 0.30 * 300) / 900)
    assert out.set_index("metric").loc["score_pos.minutes.RIGHT_WINGER", "value_p90"] == 900
