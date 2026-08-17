"""Reading and writing assessments. In-memory sqlite; no live Postgres, no network."""

import datetime as dt

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from lofc.model import scout_scores
from lofc.store import assessments as store_assess
from lofc.store.models import Base, Player, ScoutAssessment, ScoutCriterionScore, User

NOW = dt.datetime(2026, 8, 14, 12, 0)


@pytest.fixture()
def engine():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Player(player_id=1, player_name="A Player"))
        session.add(User(id=1, username="scout1", full_name="Scout One", role="scout",
                         password_hash="x"))
        session.add(User(id=2, username="hor", full_name="Head Of Rec",
                         role="head_of_recruitment", password_hash="x"))
        session.commit()
    return engine


def _save(engine, **overrides):
    kwargs = dict(player_id=1, competition_id=4, season_id=318,
                  dimension=scout_scores.PSYCHOLOGICAL, author_id=1, band=4.0,
                  notes="solid character", criterion_scores={"composure": 4},
                  criterion_passes={}, screening_failed=False, status="submitted")
    kwargs.update(overrides)
    return store_assess.save(engine, **kwargs)


def test_save_writes_the_assessment_and_returns_its_id(engine):
    assessment_id = _save(engine)
    with Session(engine) as session:
        row = session.get(ScoutAssessment, assessment_id)
        assert row.band == 4.0
        assert row.status == "submitted"
        assert row.author_id == 1


def test_save_writes_the_criterion_scores(engine):
    assessment_id = _save(engine, criterion_scores={"composure": 4, "leadership": 2})
    with Session(engine) as session:
        rows = session.scalars(select(ScoutCriterionScore)
                               .where(ScoutCriterionScore.assessment_id == assessment_id)).all()
        assert {r.criterion_key: r.score for r in rows} == {"composure": 4, "leadership": 2}


def test_save_writes_criterion_passes_as_passed_not_score(engine):
    """Psychological criteria carry `score`; medical screening criteria carry `passed`.
    Exactly one of the two is set per row."""
    assessment_id = _save(engine, dimension=scout_scores.MEDICAL, criterion_scores={},
                          criterion_passes={"no-acl": True, "no-hamstring": False},
                          screening_failed=True)
    with Session(engine) as session:
        rows = session.scalars(select(ScoutCriterionScore)
                               .where(ScoutCriterionScore.assessment_id == assessment_id)).all()
        assert {r.criterion_key: r.passed for r in rows} == {"no-acl": True,
                                                             "no-hamstring": False}
        assert all(r.score is None for r in rows)


def test_save_leaves_the_band_unclamped_when_screening_failed(engine):
    """Decision 13, pinned at the storage boundary: a failed screening criterion WARNS and
    never changes the assessor's number. A clamp inserted into `save` (e.g. capping band to
    2.0 whenever screening_failed is True) would be the platform silently overruling the
    better-informed party -- the exact failure mode Decision 13 exists to rule out. The band
    must round-trip through the database exactly as the assessor entered it."""
    assessment_id = _save(engine, dimension=scout_scores.MEDICAL, band=4.0,
                          criterion_scores={}, criterion_passes={"no-acl": False},
                          screening_failed=True, status="submitted")
    with Session(engine) as session:
        row = session.get(ScoutAssessment, assessment_id)
        assert row.band == 4.0
        assert row.screening_failed is True


def test_two_assessors_both_keep_their_rows(engine):
    """Nothing is overwritten or averaged away: disagreement between two assessors must stay
    visible on the profile. Guards against a unique constraint being added."""
    first = _save(engine, band=4.0)
    second = _save(engine, band=2.0)
    assert first != second
    frame = store_assess.load_for_player(engine, 1, 4, 318)
    assert sorted(frame["band"].tolist()) == [2.0, 4.0]


def test_load_for_player_carries_the_authors_name_and_role(engine):
    """Decision 16: the role is a RECORD, displayed beside the band so a reader can see that
    a scout entered a medical judgement. It is useless if the load does not carry it."""
    _save(engine, dimension=scout_scores.MEDICAL)
    frame = store_assess.load_for_player(engine, 1, 4, 318)
    assert frame["author_name"].tolist() == ["Scout One"]
    assert frame["author_role"].tolist() == ["scout"]


def test_load_for_player_returns_empty_frame_with_columns_for_no_assessments(engine):
    frame = store_assess.load_for_player(engine, 99999, 4, 318)
    assert frame.empty
    for column in ("dimension", "band", "status", "author_name"):
        assert column in frame.columns


def test_sign_off_records_approver_and_time_and_changes_status(engine):
    assessment_id = _save(engine)
    store_assess.sign_off(engine, assessment_id, approver_id=2, now=NOW)
    with Session(engine) as session:
        row = session.get(ScoutAssessment, assessment_id)
        assert row.status == "signed_off"
        assert row.approved_by == 2
        assert row.approved_at == NOW


def test_sign_off_refuses_a_draft(engine):
    """A draft has not been submitted for review; approving one would put an incomplete
    assessment into the record as reviewed."""
    assessment_id = _save(engine, status="draft", band=None)
    with pytest.raises(ValueError):
        store_assess.sign_off(engine, assessment_id, approver_id=2, now=NOW)


def test_sign_off_refuses_an_already_signed_off_assessment(engine):
    """Two reviewers can work the sign-off queue at once, or one person can double-click
    before the page reruns -- the second sign_off call must raise, not silently re-approve
    or overwrite the first approver. tabs/signoff.py catches exactly this ValueError and
    shows it as a message rather than letting it crash the page."""
    assessment_id = _save(engine)
    store_assess.sign_off(engine, assessment_id, approver_id=2, now=NOW)
    with pytest.raises(ValueError):
        store_assess.sign_off(engine, assessment_id, approver_id=2, now=NOW)


def test_pending_signoff_lists_submitted_only(engine):
    submitted = _save(engine)
    _save(engine, status="draft", band=None)
    signed = _save(engine, band=3.0)
    store_assess.sign_off(engine, signed, approver_id=2, now=NOW)
    frame = store_assess.pending_signoff(engine)
    assert frame["id"].tolist() == [submitted]


def test_load_all_returns_the_columns_resolve_bands_consumes(engine):
    """The contract with model/scout_scores.resolve_bands. If these column names drift, the
    scorecard rebuild silently stops seeing assessments."""
    _save(engine)
    frame = store_assess.load_all(engine)
    for column in ("player_id", "competition_id", "season_id", "dimension", "band",
                   "status", "updated_at"):
        assert column in frame.columns


def test_load_all_output_flows_through_resolve_bands(engine):
    """End-to-end on the real resolver rather than a mock: a submitted assessment must
    actually produce a band."""
    _save(engine, dimension=scout_scores.PSYCHOLOGICAL, band=4.0)
    _save(engine, dimension=scout_scores.MEDICAL, band=3.0)
    resolved = scout_scores.resolve_bands(store_assess.load_all(engine))
    assert len(resolved) == 1
    assert resolved.iloc[0]["psychological_band"] == 4.0
    assert resolved.iloc[0]["medical_band"] == 3.0
