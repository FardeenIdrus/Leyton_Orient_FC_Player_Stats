"""Assembling one player's report. In-memory sqlite; no live Postgres, no network.

The report is read by people who cannot interrogate it -- the chairman and the manager --
so these tests pin the things that would mislead them: a band shown when nobody decided, a
percentile with no stated peer group, an absent measurement rendered as a real value.
"""

import datetime as dt

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from lofc.model import scout_scores
from lofc.report import data
from lofc.store import assessments as store_assess
from lofc.store.models import (Base, Player, PlayerMetricNeutral, PlayerScorecard, User)

KEY = dict(player_id=1, competition_id=4, season_id=318)


def _neutral(player_id, name, position="Central Mid", minutes=2100.0, **metrics):
    base = dict(player_id=player_id, competition_id=4, season_id=318,
                player_name=name, team_name="A Club", position_group=position,
                minutes=minutes, rankable=minutes >= 450)
    base.update(metrics)
    return PlayerMetricNeutral(**base)


@pytest.fixture()
def engine():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        s.add(Player(player_id=1, player_name="A Player", birth_date=dt.date(2001, 6, 1),
                     foot="right", height_cm=182, nationality="England",
                     contract_until=dt.date(2027, 6, 30)))
        # player 2 deliberately has no bio at all
        s.add(Player(player_id=2, player_name="B Player"))
        s.add(User(id=1, username="scout1", full_name="Scout One", role="scout",
                   password_hash="x"))
        s.add(User(id=2, username="hor", full_name="Head Of Rec",
                   role="head_of_recruitment", password_hash="x"))
        for pid, name in ((1, "A Player"), (2, "B Player")):
            s.add(_neutral(pid, name, goals_p90=0.4, assists_p90=0.2,
                           pass_completion_pct=80.0, turnovers_p90=1.2,
                           pass_value_p90=0.5, deep_progressions_p90=4.0))
            s.add(PlayerScorecard(player_id=pid, competition_id=4, season_id=318,
                                  position_group="Central Mid", archetype="All Metrics",
                                  performance_band=4.1, physical_band=3.6,
                                  objective_composite=3.9, objective_weight_covered=0.64,
                                  veto=False, below_min_composite=False))
        s.commit()
    return engine


def _assess(engine, *, dimension=scout_scores.PSYCHOLOGICAL, band=4.0,
            status="submitted", **narrative):
    return store_assess.save(engine, **KEY, dimension=dimension, author_id=1, band=band,
                             notes=None, criterion_scores={}, criterion_passes={},
                             screening_failed=False, status=status, **narrative)


def test_stamp_is_data_only_with_no_assessment(engine):
    """A player scouted before a fixture has no assessment. That is an ordinary report,
    not a blocked one."""
    r = data.build(engine, 1, 4, 318)
    assert r.stamp == data.STAMP_DATA_ONLY
    assert r.narrative is None


def test_stamp_is_provisional_for_a_submitted_assessment(engine):
    _assess(engine, summary="Reads the game well.")
    r = data.build(engine, 1, 4, 318)
    assert r.stamp == data.STAMP_PROVISIONAL
    assert r.narrative.summary == "Reads the game well."
    assert r.narrative.assessor == "Scout One"


def test_stamp_is_final_for_a_signed_off_assessment(engine):
    aid = _assess(engine, summary="Reads the game well.")
    store_assess.sign_off(engine, aid, approver_id=2, now=dt.datetime(2026, 8, 28, 12))
    r = data.build(engine, 1, 4, 318)
    assert r.stamp == data.STAMP_FINAL
    assert r.narrative.approver == "Head Of Rec"


def test_a_conflict_produces_no_band(engine):
    """Decision 17: two unsigned assessments that disagree score nothing. The report must
    not present a band as though somebody decided."""
    _assess(engine, band=4.0)
    _assess(engine, band=2.0)
    r = data.build(engine, 1, 4, 318)
    assert r.dimension_bands.get("Psychological") is None


def test_comparison_text_names_league_season_position_and_threshold(engine):
    """A percentile with no stated peer group is meaningless to a chairman."""
    r = data.build(engine, 1, 4, 318)
    for token in ("League One", "25/26", "Central Mid", "450"):
        assert token in r.comparison_text, f"{token!r} missing from {r.comparison_text!r}"


def test_absent_bio_fields_are_none_not_zero(engine):
    """A player with no recorded height is not 0cm."""
    r = data.build(engine, 2, 4, 318)
    assert r.height_cm is None
    assert r.foot is None
    assert r.age is None


def test_rank_and_peer_count_are_within_league_season_and_position(engine):
    r = data.build(engine, 1, 4, 318)
    assert r.rank >= 1
    assert r.peer_count >= r.rank


def test_unknown_player_raises_rather_than_returning_an_empty_report(engine):
    """An empty report is worse than an error -- it looks like a player with no data."""
    with pytest.raises(ValueError, match="999999"):
        data.build(engine, 999999, 4, 318)
