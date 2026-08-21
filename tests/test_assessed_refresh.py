"""Refreshing assessed_composite after an assessment is saved.

The defect this closes: saving an assessment wrote scout_assessments but nothing recomputed
player_scorecards.assessed_composite, so a completed assessment never reached the ranking.
"""

import datetime as dt

import pandas as pd
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from lofc.model import assessed_refresh
from lofc.model import club_framework as cf
from lofc.model import scout_scores
from lofc.store import assessments as store_assess
from lofc.store.models import Base, Player, PlayerScorecard, User

KEY = dict(player_id=1, competition_id=4, season_id=318)


@pytest.fixture()
def engine():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Player(player_id=1, player_name="A Player"))
        session.add(User(id=1, username="scout1", full_name="Scout One", role="scout",
                         password_hash="x"))
        session.add(PlayerScorecard(
            **KEY, position_group="Centre Back", archetype="All Metrics",
            performance_band=4.0, physical_band=3.0,
            financial_band=2.5, resale_band=3.5,
            objective_composite=3.57, objective_weight_covered=0.64,
            full_composite=3.40, full_weight_covered=0.77,
            assessed_composite=None, assessed_weight_covered=0.0,
            veto=False, below_min_composite=False))
        session.commit()
    return engine


def _save(engine, dimension, band, status="submitted"):
    return store_assess.save(engine, **KEY, dimension=dimension, author_id=1, band=band,
                             notes=None, criterion_scores={}, criterion_passes={},
                             screening_failed=False, status=status)


def test_refresh_is_a_no_op_with_no_assessments(engine):
    assert assessed_refresh.refresh_for_player(engine, **KEY) == 0
    with Session(engine) as session:
        row = session.scalar(select(PlayerScorecard))
        assert row.assessed_composite is None


def test_one_dimension_alone_does_not_produce_a_composite(engine):
    """Decision 9: both, or neither. One dimension is not a partial assessment."""
    _save(engine, scout_scores.PSYCHOLOGICAL, 4.0)
    assessed_refresh.refresh_for_player(engine, **KEY)
    with Session(engine) as session:
        row = session.scalar(select(PlayerScorecard))
        assert row.psychological_band == 4.0
        assert row.assessed_composite is None


def test_both_dimensions_produce_a_composite(engine):
    _save(engine, scout_scores.PSYCHOLOGICAL, 4.0)
    _save(engine, scout_scores.MEDICAL, 3.0)
    assert assessed_refresh.refresh_for_player(engine, **KEY) == 1
    with Session(engine) as session:
        row = session.scalar(select(PlayerScorecard))
        assert row.assessed_composite is not None
        assert row.psychological_band == 4.0
        assert row.medical_band == 3.0


def test_the_composite_matches_the_pipeline_formula(engine):
    """Computed with the same _composite the pipeline uses, over the row's OWN stored bands."""
    from lofc.model.scorecard import ASSESSED_DIMENSIONS, _composite
    _save(engine, scout_scores.PSYCHOLOGICAL, 4.0)
    _save(engine, scout_scores.MEDICAL, 3.0)
    assessed_refresh.refresh_for_player(engine, **KEY)
    expected, expected_w = _composite(
        {cf.PERFORMANCE: 4.0, cf.PHYSICAL: 3.0, cf.PSYCHOLOGICAL: 4.0, cf.MEDICAL: 3.0},
        cf.DIMENSION_WEIGHTS["Centre Back"], ASSESSED_DIMENSIONS)
    with Session(engine) as session:
        row = session.scalar(select(PlayerScorecard))
        assert row.assessed_composite == expected
        assert row.assessed_weight_covered == expected_w


def test_the_default_ranking_is_never_written(engine):
    """The single most important test here. objective_composite is THE ranking; no human
    assessment may move it. full_composite and the data bands are equally off limits."""
    _save(engine, scout_scores.PSYCHOLOGICAL, 1.0)
    _save(engine, scout_scores.MEDICAL, 1.0)
    assessed_refresh.refresh_for_player(engine, **KEY)
    with Session(engine) as session:
        row = session.scalar(select(PlayerScorecard))
        assert row.objective_composite == 3.57
        assert row.objective_weight_covered == 0.64
        assert row.full_composite == 3.40
        assert row.full_weight_covered == 0.77
        assert row.performance_band == 4.0
        assert row.physical_band == 3.0
        assert row.financial_band == 2.5
        assert row.resale_band == 3.5
        assert row.below_min_composite is False


def test_a_draft_never_reaches_the_composite(engine):
    _save(engine, scout_scores.PSYCHOLOGICAL, 4.0, status="draft")
    _save(engine, scout_scores.MEDICAL, 3.0, status="draft")
    assessed_refresh.refresh_for_player(engine, **KEY)
    with Session(engine) as session:
        assert session.scalar(select(PlayerScorecard)).assessed_composite is None


def test_a_low_scout_band_trips_the_advisory_veto(engine):
    """Matches build_scorecards: any dimension below VETO_BAND flags the row. Advisory only --
    it marks a player, it never removes them from a list."""
    _save(engine, scout_scores.PSYCHOLOGICAL, 1.5)
    _save(engine, scout_scores.MEDICAL, 3.0)
    assessed_refresh.refresh_for_player(engine, **KEY)
    with Session(engine) as session:
        assert session.scalar(select(PlayerScorecard)).veto is True


def test_every_archetype_row_is_refreshed_from_its_own_bands(engine):
    """player_scorecards is unique on (player, competition, season, ARCHETYPE). Each row's
    performance_band differs, so each composite must come from that row's own bands -- not be
    computed once and copied across."""
    with Session(engine) as session:
        session.add(PlayerScorecard(
            **KEY, position_group="Centre Back", archetype="Ball Playing",
            performance_band=2.0, physical_band=3.0,
            objective_composite=2.43, objective_weight_covered=0.64,
            veto=False, below_min_composite=True))
        session.commit()

    _save(engine, scout_scores.PSYCHOLOGICAL, 4.0)
    _save(engine, scout_scores.MEDICAL, 3.0)
    assert assessed_refresh.refresh_for_player(engine, **KEY) == 2

    with Session(engine) as session:
        rows = {r.archetype: r for r in session.scalars(select(PlayerScorecard)).all()}
        assert rows["All Metrics"].assessed_composite != rows["Ball Playing"].assessed_composite
        assert rows["All Metrics"].objective_composite == 3.57
        assert rows["Ball Playing"].objective_composite == 2.43


def test_signed_off_wins_over_a_newer_submitted_assessment(engine):
    """Delegated to resolve_bands; pinned here so the refresh path cannot diverge from it."""
    first = _save(engine, scout_scores.PSYCHOLOGICAL, 5.0)
    store_assess.sign_off(engine, first, approver_id=1, now=dt.datetime(2026, 8, 17, 12, 0))
    _save(engine, scout_scores.PSYCHOLOGICAL, 2.0)
    _save(engine, scout_scores.MEDICAL, 3.0)
    assessed_refresh.refresh_for_player(engine, **KEY)
    with Session(engine) as session:
        assert session.scalar(select(PlayerScorecard)).psychological_band == 5.0


def test_a_missing_scorecard_row_is_not_an_error(engine):
    """A player with an assessment but no scorecard row (not rankable, too few minutes) must
    not raise -- there is simply nothing to update."""
    _save(engine, scout_scores.PSYCHOLOGICAL, 4.0)
    _save(engine, scout_scores.MEDICAL, 3.0)
    assert assessed_refresh.refresh_for_player(engine, player_id=999,
                                               competition_id=4, season_id=318) == 0


def test_save_triggers_the_refresh(engine):
    """The seam this task exists to close: saving the second dimension must leave a composite
    behind without anyone running the pipeline."""
    store_assess.save(engine, **KEY, dimension=scout_scores.PSYCHOLOGICAL, author_id=1,
                      band=4.0, notes=None, criterion_scores={}, criterion_passes={},
                      screening_failed=False, status="submitted")
    store_assess.save(engine, **KEY, dimension=scout_scores.MEDICAL, author_id=1,
                      band=3.0, notes=None, criterion_scores={}, criterion_passes={},
                      screening_failed=False, status="submitted")
    with Session(engine) as session:
        assert session.scalar(select(PlayerScorecard)).assessed_composite is not None


def test_signing_off_recomputes_the_composite(engine):
    """The defect this closes: sign-off decides WHICH assessment scores, so the stored
    composite must be recomputed there. Previously the badge read approved while the number
    was the one that was not approved."""
    author = _save(engine, scout_scores.PSYCHOLOGICAL, 5.0)  # scout A
    _save(engine, scout_scores.PSYCHOLOGICAL, 2.0)            # scout B -- disagreement
    _save(engine, scout_scores.MEDICAL, 3.0)
    assessed_refresh.refresh_for_player(engine, **KEY)
    with Session(engine) as session:
        row = session.scalar(select(PlayerScorecard))
        # Two unsigned Psychological assessments disagree -- Decision 17: conflict, no band.
        assert row.psychological_band is None
        assert row.assessed_composite is None

    store_assess.sign_off(engine, author, approver_id=1, now=dt.datetime(2026, 8, 17, 12, 0))

    with Session(engine) as session:
        row = session.scalar(select(PlayerScorecard))
        assert row.psychological_band == 5.0
        assert row.assessed_composite is not None


def test_a_conflicted_dimension_leaves_the_composite_null_after_a_refresh(engine):
    """Decision 9 plus Decision 17 together: a contested dimension has no scoring band, and
    a missing band on either dimension means no assessed composite -- not a silent pick of
    one of the two disagreeing scouts."""
    _save(engine, scout_scores.PSYCHOLOGICAL, 4.0)
    _save(engine, scout_scores.MEDICAL, 5.0)   # scout A
    _save(engine, scout_scores.MEDICAL, 1.0)   # scout B -- disagreement, unsigned
    assessed_refresh.refresh_for_player(engine, **KEY)
    with Session(engine) as session:
        row = session.scalar(select(PlayerScorecard))
        assert row.psychological_band == 4.0
        assert row.medical_band is None
        assert row.assessed_composite is None


def test_a_new_conflict_clears_the_previously_scored_band(engine):
    """Part C (task 10): a player scored on both dimensions, then a second scout submits a
    conflicting Psychological assessment. psychological_band and assessed_composite must both
    go back to NULL -- not keep reading the value from before the disagreement arrived."""
    _save(engine, scout_scores.PSYCHOLOGICAL, 4.0)
    _save(engine, scout_scores.MEDICAL, 3.0)
    assessed_refresh.refresh_for_player(engine, **KEY)
    with Session(engine) as session:
        assert session.scalar(select(PlayerScorecard)).assessed_composite is not None

    store_assess.save(engine, **KEY, dimension=scout_scores.PSYCHOLOGICAL, author_id=1,
                      band=2.0, notes=None, criterion_scores={}, criterion_passes={},
                      screening_failed=False, status="submitted")   # a second, disagreeing scout
    assessed_refresh.refresh_for_player(engine, **KEY)
    with Session(engine) as session:
        row = session.scalar(select(PlayerScorecard))
        assert row.psychological_band is None
        assert row.assessed_composite is None


def test_a_conflict_on_a_dimension_never_assessed_on_the_other_side_clears_the_stale_band(engine):
    """The exact defect Part C closes. Psychological alone has ever been assessed (single
    submission, Medical untouched -- so `medical` already resolves to None and no composite
    was ever produced). A second, disagreeing Psychological submission then makes BOTH
    `psychological` and `medical` resolve to None on the same refresh call. The old guard
    (`if psychological is None and medical is None: return 0`) treated that as a pure no-op
    and returned before the UPDATE ran, leaving the row's `psychological_band` at its
    earlier, no-longer-true value of 4.0 instead of clearing it to NULL."""
    _save(engine, scout_scores.PSYCHOLOGICAL, 4.0)
    assessed_refresh.refresh_for_player(engine, **KEY)
    with Session(engine) as session:
        row = session.scalar(select(PlayerScorecard))
        assert row.psychological_band == 4.0
        assert row.assessed_composite is None      # Decision 9: Medical untouched, no composite

    _save(engine, scout_scores.PSYCHOLOGICAL, 2.0)   # a second, disagreeing scout
    assessed_refresh.refresh_for_player(engine, **KEY)
    with Session(engine) as session:
        row = session.scalar(select(PlayerScorecard))
        assert row.psychological_band is None
        assert row.medical_band is None
        assert row.assessed_composite is None


def test_stored_band_is_rounded_the_same_way_the_pipeline_rounds_it(engine):
    """MINOR 7: a 3-criterion position (e.g. Goalkeeper) produces raw means like 10/3 =
    3.3333333333333335 routinely. `scorecard.py`'s `build_scorecards` rounds that to 2dp
    before it ever reaches a composite; `assessed_refresh._band` must round identically, or
    the pipeline and a live save/sign-off store two different numbers for the same
    assessment depending on which one last wrote the row."""
    raw_band = 10 / 3
    assert raw_band != round(raw_band, 2)          # the un-rounded value really is different
    _save(engine, scout_scores.PSYCHOLOGICAL, raw_band)
    _save(engine, scout_scores.MEDICAL, 3.0)
    assessed_refresh.refresh_for_player(engine, **KEY)
    with Session(engine) as session:
        row = session.scalar(select(PlayerScorecard))
        assert row.psychological_band == round(raw_band, 2)

        # The pipeline's own rounding, over the same raw input -- must match exactly.
        from lofc.model.scorecard import build_scorecards
        neutral = pd.DataFrame([{
            "player_id": 1, "competition_id": 4, "season_id": 318,
            "position_group": "Centre Back", "rankable": True}])
        scout_bands = pd.DataFrame([{
            "player_id": 1, "competition_id": 4, "season_id": 318,
            "psychological_band": raw_band, "medical_band": 3.0}])
        pipeline_row = build_scorecards(neutral, scout_bands=scout_bands).iloc[0]
        assert pipeline_row["psychological_band"] == row.psychological_band


def test_a_refresh_failure_never_loses_the_assessment(engine, monkeypatch):
    """The save is the user's work; the refresh is derived convenience. If the refresh raises,
    the assessment must still be on the record."""
    def boom(*args, **kwargs):
        raise RuntimeError("refresh exploded")
    monkeypatch.setattr(assessed_refresh, "refresh_for_player", boom)

    assessment_id = store_assess.save(
        engine, **KEY, dimension=scout_scores.PSYCHOLOGICAL, author_id=1, band=4.0,
        notes=None, criterion_scores={}, criterion_passes={}, screening_failed=False,
        status="submitted")
    assert assessment_id
    frame = store_assess.load_for_player(engine, **KEY)
    assert len(frame) == 1
