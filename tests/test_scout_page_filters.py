"""Scout reports has its OWN League / Max age / Foot filters (owner, 2026-10-12: not the
sidebar). Same rules as the rest of the platform: an unknown age is kept by an age cap;
"Left"/"Right" include two-footed players. League = where he plays THIS season, else last."""

import datetime as dt

import pandas as pd

from lofc.dashboard.tabs.scout_reports import filter_reports

TODAY = dt.date(2026, 10, 12)


def _frame():
    return pd.DataFrame({
        "player_name": ["A", "B", "C", "D"],
        "league": ["League One", "League Two", None, "League One"],
        "birth_date": pd.to_datetime(["2004-01-01", "1994-01-01", None, "1999-06-01"]),
        "foot": ["Left", "Right", "Both", "Right"],
        "player_id": [1, 2, None, 4],
    })


def names(f):
    return f["player_name"].tolist()


def test_league():
    assert names(filter_reports(_frame(), league="League One")) == ["A", "D"]


def test_max_age_keeps_unknown_ages():
    assert names(filter_reports(_frame(), max_age=25, today=TODAY)) == ["A", "C"]


def test_left_foot_includes_both():
    assert names(filter_reports(_frame(), foot="Left")) == ["A", "C"]


def test_all_means_no_filter():
    assert len(filter_reports(_frame(), league="All", foot="All", max_age=None)) == 4
