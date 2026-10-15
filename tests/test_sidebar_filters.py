"""The sidebar filters, as one function every page applies.

Found 2026-10-02: Squads & loans honoured NONE of the sidebar -- "Left foot" changed nothing
there. The Players page applied the filters inline in app.py, so any other page had to
re-implement them or, in practice, ignore them. This is the shared implementation; the rules
are the Players page's, unchanged:
  * an unknown age is KEPT (the cap excludes only known-older players);
  * Left/Right includes two-footed players; an unknown foot is excluded once a foot is set;
  * an unknown contract date is excluded by a contract horizon (it cannot be judged);
  * loan status uses `loan_mask`.
A column a page does not have is a filter that page cannot apply -- passed as None.
"""

import pandas as pd

from lofc.dashboard.seasons import CONTRACT_EXPIRED, LOAN_NOT, LOAN_ON_NOW
from lofc.dashboard.sidebar_filters import SidebarFilters, apply_sidebar_filters

TODAY = pd.Timestamp("2026-10-02")


def _frame():
    return pd.DataFrame({
        "name": ["A", "B", "C", "D"],
        "age": [22.0, 31.0, None, 25.0],
        "league": ["League One", "League Two", "League One", "PL2"],
        "foot": ["left", "right", "both", None],
        "contract_until": pd.to_datetime(["2027-06-30", "2026-06-30", None, "2029-06-30"]),
        "on_loan": [True, False, False, False],
        "loan_ends": pd.to_datetime(["2027-05-31", None, None, None]),
    })


COLS = dict(age="age", league="league", foot="foot", contract="contract_until",
            on_loan="on_loan", loan_ends="loan_ends")


def names(out):
    return out["name"].tolist()


def test_defaults_filter_nothing():
    assert names(apply_sidebar_filters(_frame(), SidebarFilters(), today=TODAY, **COLS)) == \
        ["A", "B", "C", "D"]


def test_age_cap_keeps_unknown_ages():
    out = apply_sidebar_filters(_frame(), SidebarFilters(max_age=30), today=TODAY, **COLS)
    assert names(out) == ["A", "C", "D"]


def test_leagues():
    out = apply_sidebar_filters(_frame(), SidebarFilters(leagues=("League One",)),
                                today=TODAY, **COLS)
    assert names(out) == ["A", "C"]


def test_left_foot_includes_two_footed_and_drops_unknown():
    out = apply_sidebar_filters(_frame(), SidebarFilters(foot="Left"), today=TODAY, **COLS)
    assert names(out) == ["A", "C"]


def test_contract_horizon_drops_unknown_dates():
    out = apply_sidebar_filters(
        _frame(), SidebarFilters(contract_horizon="Out of contract summer 2027"),
        today=TODAY, **COLS)
    assert names(out) == ["A"]


def test_expired_contracts():
    out = apply_sidebar_filters(_frame(), SidebarFilters(contract_horizon=CONTRACT_EXPIRED),
                                today=TODAY, **COLS)
    assert names(out) == ["B"]


def test_loan_status():
    on = apply_sidebar_filters(_frame(), SidebarFilters(loan=LOAN_ON_NOW), today=TODAY, **COLS)
    off = apply_sidebar_filters(_frame(), SidebarFilters(loan=LOAN_NOT), today=TODAY, **COLS)
    assert names(on) == ["A"] and names(off) == ["B", "C", "D"]


def test_a_missing_column_skips_only_that_filter():
    cols = dict(COLS, foot=None)
    out = apply_sidebar_filters(_frame(), SidebarFilters(foot="Left", max_age=30),
                                today=TODAY, **cols)
    assert names(out) == ["A", "C", "D"]


def test_input_is_not_mutated_and_columns_kept():
    frame = _frame()
    out = apply_sidebar_filters(frame, SidebarFilters(max_age=30), today=TODAY, **COLS)
    assert len(frame) == 4 and list(out.columns) == list(frame.columns)
