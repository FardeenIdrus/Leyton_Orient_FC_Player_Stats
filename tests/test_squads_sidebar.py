"""Squads & loans applies the sidebar (bug, 2026-10-02: "Left foot" changed nothing here).

Applied: Maximum age, Leagues, Preferred foot, Contract expiry, Loan status -- the facts this
page holds. Not applied, by design: Season (the page is the current squad), Position (the
page has its own, with "All"), Minimum minutes (the page lists registered players who have
not played), Archetype and affordability (no scores or money on this page).
"""

import inspect

import pandas as pd

from lofc.dashboard.seasons import LOAN_ON_NOW
from lofc.dashboard.sidebar_filters import SidebarFilters
from lofc.dashboard.tabs import squads


def _prepared():
    return pd.DataFrame({
        "Player": ["L", "R", "Old"], "Age": [21.0, 24.0, 34.0],
        "League": ["League One", "League Two", "League One"],
        "Foot": ["left", "right", "left"],
        "contract_until": pd.to_datetime(["2027-06-30", "2028-06-30", None]),
        "On loan from": ["Everton FC U21", None, None],
        "loan_ends": pd.to_datetime(["2027-05-31", None, None]),
    })


def test_left_foot_narrows_the_squad_view():
    out = squads.sidebar_view(_prepared(), SidebarFilters(foot="Left"))
    assert out["Player"].tolist() == ["L", "Old"]


def test_age_league_and_loan_apply():
    f = SidebarFilters(max_age=30, leagues=("League One",), loan=LOAN_ON_NOW)
    assert squads.sidebar_view(_prepared(), f)["Player"].tolist() == ["L"]


def test_no_filters_is_a_no_op():
    assert len(squads.sidebar_view(_prepared(), SidebarFilters())) == 3


def test_render_applies_it_to_both_the_squad_and_the_loan_view():
    # the squad view in render, the loans view in core.squads.build_view (2.36)
    from lofc.core import squads as core
    assert "sidebar_view(" in inspect.getsource(squads.render)
    assert "build_view(" in inspect.getsource(squads.render)
    assert "sidebar_view(" in inspect.getsource(core.build_view)
