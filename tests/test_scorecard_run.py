"""Tests for persisting the club composite to `player_scorecards` (model/scorecard_run).

The point of the persisted table is that the offline shortlist and the BI layer read exactly
the numbers the dashboard shows, so the tests assert that equivalence: stored == live, one row
per player-season per archetype, and the archetype rows scoped to their own position.
Small fixtures, no database.
"""

import pandas as pd
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from lofc.model import assessed_refresh
from lofc.model import club_framework as cf
from lofc.model import scorecard
from lofc.model import scout_scores
from lofc.model.scorecard_run import STORED_COLUMNS, archetype_jobs, build_all, reconcile_assessed
from lofc.store import assessments as store_assess
from lofc.store.models import Base, Player, PlayerScorecard, User


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


# --- reconcile_assessed (IMPORTANT 3) -------------------------------------------------


KEY = dict(player_id=1, competition_id=4, season_id=318)


def _assessed_engine():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Player(player_id=1, player_name="A Player"))
        session.add(User(id=1, username="scout1", full_name="Scout One", role="scout",
                         password_hash="x"))
        session.add(PlayerScorecard(
            **KEY, position_group="Centre Back", archetype="All Metrics",
            performance_band=4.0, physical_band=3.0,
            objective_composite=3.57, objective_weight_covered=0.64,
            assessed_composite=None, assessed_weight_covered=0.0,
            veto=False, below_min_composite=False))
        session.commit()
    return engine


def test_reconcile_assessed_is_a_no_op_with_no_scoring_assessments():
    assert reconcile_assessed(_assessed_engine()) == 0


def test_reconcile_assessed_repairs_a_composite_left_stale_by_a_swallowed_refresh_failure(monkeypatch):
    """IMPORTANT 3, reproduced structurally: both callers of `refresh_for_player`
    (`store.assessments.save` and `.sign_off`) swallow its failures so a committed assessment
    is never lost -- which means a refresh CAN silently not happen, exactly as it did not for
    players 42516 and 80945 on the live database. This is the recovery path: re-running the
    refresh later, without anyone re-running the whole pipeline, must repair it."""
    engine = _assessed_engine()

    def boom(*args, **kwargs):
        raise RuntimeError("refresh exploded")

    with monkeypatch.context() as m:
        m.setattr(assessed_refresh, "refresh_for_player", boom)
        store_assess.save(engine, **KEY, dimension=scout_scores.PSYCHOLOGICAL, author_id=1,
                          band=4.0, notes=None, criterion_scores={}, criterion_passes={},
                          screening_failed=False, status="submitted")
        store_assess.save(engine, **KEY, dimension=scout_scores.MEDICAL, author_id=1,
                          band=3.0, notes=None, criterion_scores={}, criterion_passes={},
                          screening_failed=False, status="submitted")

    with Session(engine) as session:
        # Both assessments are on the record, but the refresh never ran -- stale, not fixed.
        assert session.scalar(select(PlayerScorecard)).assessed_composite is None

    updated = reconcile_assessed(engine)
    assert updated == 1

    with Session(engine) as session:
        row = session.scalar(select(PlayerScorecard))
        assert row.assessed_composite is not None
        assert row.psychological_band == 4.0
        assert row.medical_band == 3.0
        # The reconcile route touches only assessed_refresh's own columns -- never the
        # objective ranking.
        assert row.objective_composite == 3.57


def test_reconcile_assessed_ignores_drafts():
    engine = _assessed_engine()
    store_assess.save(engine, **KEY, dimension=scout_scores.PSYCHOLOGICAL, author_id=1,
                      band=4.0, notes=None, criterion_scores={}, criterion_passes={},
                      screening_failed=False, status="draft")
    assert reconcile_assessed(engine) == 0
