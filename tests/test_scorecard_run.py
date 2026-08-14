"""Tests for persisting the club composite to `player_scorecards` (model/scorecard_run).

The point of the persisted table is that the offline shortlist and the BI layer read exactly
the numbers the dashboard shows, so the tests assert that equivalence: stored == live, one row
per player-season per archetype, and the archetype rows scoped to their own position.
Small fixtures, no database.
"""

import pandas as pd

from lofc.model import club_framework as cf
from lofc.model import scorecard
from lofc.model.scorecard_run import STORED_COLUMNS, archetype_jobs, build_all


def _neutral():
    """Full Backs, Wingers and Centre Forwards with one scored metric each."""
    rows = []
    for i in range(6):
        rows.append({"player_id": i, "competition_id": 4, "season_id": 318,
                     "position_group": "Full Back", "rankable": True,
                     "aerial_win_pct": float(i), "pass_completion_pct": float(6 - i)})
    for i in range(6):
        rows.append({"player_id": 100 + i, "competition_id": 4, "season_id": 318,
                     "position_group": "Centre Forward", "rankable": True,
                     "np_xg_p90": float(i)})
    for i in range(6):
        rows.append({"player_id": 200 + i, "competition_id": 4, "season_id": 318,
                     "position_group": "Winger", "rankable": True,
                     "np_xg_p90": float(i), "pass_completion_pct": float(6 - i)})
    return pd.DataFrame(rows)


def test_jobs_cover_the_default_plus_every_club_archetype():
    labels = [label for label, _ in archetype_jobs()]
    assert labels[0] == cf.DEFAULT_ARCHETYPE
    expected = 1 + sum(len(a) for a in cf.ARCHETYPE_DROPS.values())
    assert len(labels) == expected
    assert "Attacking" in labels and "Direct & 1v1 Specialist" in labels


def test_every_player_gets_exactly_one_default_row():
    neutral = _neutral()
    frame = build_all(neutral, financial_resale=None)
    default = frame[frame["archetype"] == cf.DEFAULT_ARCHETYPE]
    keys = ["player_id", "competition_id", "season_id"]
    assert len(default) == len(neutral)
    assert not default.duplicated(keys).any()
    assert list(frame.columns) == STORED_COLUMNS


def test_archetype_rows_only_cover_their_own_position():
    """An 'Attacking' row must exist for Full Backs and for nobody else — otherwise the
    dashboard's archetype lens would silently pick up unrelated positions."""
    frame = build_all(_neutral(), financial_resale=None)
    attacking = frame[frame["archetype"] == "Attacking"]
    assert set(attacking["position_group"]) == {"Full Back"}
    direct = frame[frame["archetype"] == "Direct & 1v1 Specialist"]
    assert set(direct["position_group"]) == {"Winger"}
    # Centre Forward has a single club profile: it appears only under the default.
    cf_rows = frame[frame["position_group"] == "Centre Forward"]
    assert set(cf_rows["archetype"]) == {cf.DEFAULT_ARCHETYPE}


def test_no_duplicate_rows_on_the_storage_key():
    """(player, competition, season, archetype) is the table's unique key."""
    frame = build_all(_neutral(), financial_resale=None)
    key = ["player_id", "competition_id", "season_id", "archetype"]
    assert not frame.duplicated(key).any()


def test_stored_values_match_a_live_scorecard_run():
    """The persisted default rows must equal what build_scorecards produces live — that
    equivalence is the whole reason the table exists."""
    neutral = _neutral()
    live = scorecard.build_scorecards(neutral)
    stored = build_all(neutral, financial_resale=None)
    stored = stored[stored["archetype"] == cf.DEFAULT_ARCHETYPE]

    keys = ["player_id", "competition_id", "season_id"]
    merged = live.merge(stored, on=keys, suffixes=("_live", "_db"))
    assert len(merged) == len(live)
    for col in ["objective_composite", "performance_band", "physical_band", "full_composite"]:
        pd.testing.assert_series_equal(
            merged[f"{col}_live"], merged[f"{col}_db"], check_names=False)


def test_archetype_row_differs_from_the_default_for_that_position():
    """The lens must actually re-score, not just relabel the same numbers."""
    frame = build_all(_neutral(), financial_resale=None)
    key = ["player_id", "competition_id", "season_id"]
    default = (frame[frame["archetype"] == cf.DEFAULT_ARCHETYPE]
               .set_index(key)["performance_band"])
    attacking = (frame[frame["archetype"] == "Attacking"]
                 .set_index(key)["performance_band"])
    common = default.index.intersection(attacking.index)
    assert len(common) > 0
    assert not default.loc[common].equals(attacking.loc[common])


def test_scout_bands_reach_build_scorecards_through_build_all():
    """Kills the failure mode where build_all stops forwarding scout_bands to
    build_scorecards: main() would still resolve real assessments from the database, but the
    persisted table would silently carry a NULL assessed_composite for everyone regardless,
    with no test failure to flag it."""
    neutral = _neutral()
    scout_bands = pd.DataFrame([{"player_id": 0, "competition_id": 4, "season_id": 318,
                                 "psychological_band": 3.8, "medical_band": 3.0}])
    frame = build_all(neutral, financial_resale=None, scout_bands=scout_bands)
    default = frame[frame["archetype"] == cf.DEFAULT_ARCHETYPE].set_index(
        ["player_id", "competition_id", "season_id"])
    assert pd.notna(default.loc[(0, 4, 318), "assessed_composite"])
