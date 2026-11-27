"""Fixtures page user data (owner 2026-11-27, phase 5): scout assignments, games added by hand,
and confirmed scout-report links -- which the automatic linking stage must keep."""
import datetime

import pandas as pd
import sqlalchemy as sa
from sqlalchemy.pool import StaticPool

from lofc.store import fixtures as st
from lofc.store.models import Base


def _engine():
    e = sa.create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(e)
    return e


def test_assign_replaces_and_clears():
    e = _engine()
    st.assign(e, "m:1", 5, by=2)
    st.assign(e, "m:1", 7, by=2)
    st.assign(e, "x:3", 5, by=2)
    assert st.assignments(e) == {"m:1": 7, "x:3": 5}
    st.assign(e, "m:1", None, by=2)
    assert st.assignments(e) == {"x:3": 5}


def test_manual_games_in_a_window_and_removed_by_id():
    e = _engine()
    when = datetime.datetime(2026, 12, 1, 19, 45)
    i = st.add_manual(e, when, "EFL Trophy", "Cambridge United", "Brighton U21", 10, None, by=3)
    st.add_manual(e, datetime.datetime(2027, 3, 1, 15), None, "A", "B", None, None, by=3)
    got = st.manual_between(e, datetime.datetime(2026, 11, 27), datetime.datetime(2026, 12, 11))
    assert list(got["id"]) == [i] and got.iloc[0]["home_squad_id"] == 10 and pd.isna(got.iloc[0]["away_squad_id"])
    st.remove_manual(e, i)
    assert st.manual_between(e, datetime.datetime(2026, 11, 27), datetime.datetime(2026, 12, 11)).empty


def test_link_report_and_relink_keeps_it():
    from lofc.model import scout_report_link as srl
    from lofc.store.models import ScoutReport
    e = _engine()
    with e.begin() as c:
        c.execute(sa.insert(ScoutReport.__table__).values(submission_id="s1", player_name="Jordan Gabriel",
                                                          linkable=True, name_from_report=False))
        c.execute(sa.text("INSERT INTO players (player_id, player_name) VALUES (34605, 'Jordan Lawrence-Gabriel')"))
    st.link_report(e, "s1", 34605, by=1)
    assert st.report_links(e) == {"s1": 34605}
    srl.relink(e)                                   # the sync re-resolves every report
    got = pd.read_sql("SELECT player_id FROM scout_reports WHERE submission_id = 's1'", e)
    assert int(got.iloc[0]["player_id"]) == 34605
