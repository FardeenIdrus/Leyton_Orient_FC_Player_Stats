"""P17b -- "On loan only" silently threw away the Position filter.

Reported by the owner: set Position to Centre Forward on Squads, contracts and loans, click
"On loan only", and every position comes back.

The cause is that "On loan only" does not FILTER the squad view -- it REPLACES it with a
separately built loans frame (loanees who have not appeared in league data yet are absent
from the squad frame entirely, so the replacement is right). League and Club were
deliberately re-applied to the replacement. Position never was.

Fixing only that would have produced a second complaint. `loans_frame` sourced position from
the CURRENT season alone, with no "(last season)" fallback, and `filter_by_position`
deliberately excludes rows with no position at all -- so selecting Centre Forward would have
silently dropped 131 of 411 loanees whose position the platform knows perfectly well from
last season. Measured 2026-09-28: position present for 280 of 411 loans today, 359 after
P17's tm_player_id fix, 379 with the fallback. The filter and the fallback are one change.

The suffix carries the fact, per the page's existing rule: an observed position and an
inferred one must not read alike. `_bare_position` already strips it, so one filter covers
both tiers.
"""

import pandas as pd

from lofc.dashboard.tabs.squads import loan_view, with_last_season_position

LOANS = pd.DataFrame([
    {"Player": "A Forward", "Position": "Centre Forward", "League": "League One",
     "Club": "Accrington Stanley"},
    {"Player": "A Winger", "Position": "Winger", "League": "League One",
     "Club": "Accrington Stanley"},
    {"Player": "A Fallback Forward", "Position": "Centre Forward (last season)",
     "League": "League One", "Club": "Crewe Alexandra"},
    {"Player": "A Positionless Loanee", "Position": None, "League": "League Two",
     "Club": "Tranmere Rovers"},
    {"Player": "A Scottish Forward", "Position": "Centre Forward",
     "League": "Scottish Premiership", "Club": "Dundee FC"},
])


def _names(frame):
    return list(frame["Player"])


# --- the defect --------------------------------------------------------------------------

def test_the_position_filter_applies_to_the_loan_view():
    """THE DEFECT. Selecting Centre Forward and then "On loan only" returned everyone."""
    assert _names(loan_view(LOANS, position="Centre Forward")) == [
        "A Forward", "A Fallback Forward", "A Scottish Forward"]


def test_all_returns_every_loanee():
    assert len(loan_view(LOANS, position="All")) == 5


def test_a_last_season_position_is_included_by_the_filter():
    """131 loanees have no current-season position but a known one from last season. A
    filter that drops them has replaced one missing-data complaint with another."""
    assert "A Fallback Forward" in _names(loan_view(LOANS, position="Centre Forward"))


def test_a_loanee_with_no_known_position_is_excluded_from_a_specific_filter():
    """He cannot be asserted into a position group -- the same rule the squad view applies."""
    assert "A Positionless Loanee" not in _names(loan_view(LOANS, position="Centre Forward"))


def test_a_loanee_with_no_known_position_still_appears_under_all():
    assert "A Positionless Loanee" in _names(loan_view(LOANS, position="All"))


# --- the filters that already worked must keep working -----------------------------------

def test_the_league_filter_still_applies():
    assert _names(loan_view(LOANS, league="Scottish Premiership")) == ["A Scottish Forward"]


def test_the_club_filter_still_applies():
    assert _names(loan_view(LOANS, club="Crewe Alexandra")) == ["A Fallback Forward"]


def test_all_three_filters_compose():
    out = loan_view(LOANS, league="League One", club="Accrington Stanley",
                    position="Centre Forward")
    assert _names(out) == ["A Forward"]


def test_an_empty_loans_frame_is_handled():
    assert loan_view(pd.DataFrame(columns=["Player", "Position", "League", "Club"]),
                     position="Centre Forward").empty


def test_the_caller_frame_is_not_mutated():
    loan_view(LOANS, position="Centre Forward")
    assert len(LOANS) == 5


# --- the fallback the filter depends on ---------------------------------------------------

def test_a_current_season_position_wins():
    """Where he has played THIS season is the stronger claim, and carries no suffix."""
    frame = pd.DataFrame([{"position_group": "Winger", "last_position": "Centre Forward"}])
    assert with_last_season_position(frame)["position_group"].iloc[0] == "Winger"


def test_last_seasons_position_fills_the_gap_and_says_so():
    frame = pd.DataFrame([{"position_group": None, "last_position": "Centre Forward"}])
    assert with_last_season_position(frame)["position_group"].iloc[0] == \
        "Centre Forward (last season)"


def test_no_position_either_season_stays_blank():
    """Blank is a fact; a guessed position group changes which peers a reader assumes."""
    frame = pd.DataFrame([{"position_group": None, "last_position": None}])
    assert pd.isna(with_last_season_position(frame)["position_group"].iloc[0])


def test_the_suffix_is_stripped_when_matching():
    """"Centre Forward" and "Centre Forward (last season)" must not be two separate choices."""
    from lofc.dashboard.tabs.squads import filter_by_position, position_options
    frame = pd.DataFrame([{"Position": "Centre Forward (last season)"}])
    assert position_options(frame) == ["All", "Centre Forward"]
    assert len(filter_by_position(frame, "Centre Forward")) == 1


def test_a_frame_with_no_last_position_column_is_left_alone():
    """The squad frame supplies it; a caller that does not must not raise."""
    frame = pd.DataFrame([{"position_group": "Winger"}])
    assert with_last_season_position(frame)["position_group"].iloc[0] == "Winger"


def test_with_last_season_position_does_not_mutate_the_caller():
    frame = pd.DataFrame([{"position_group": None, "last_position": "Winger"}])
    with_last_season_position(frame)
    assert frame["position_group"].iloc[0] is None


# --- the seam: the page must actually USE the filter -------------------------------------

def test_the_loan_branch_of_render_goes_through_loan_view():
    """The bug was not in a filter -- it was a filter that was never called. A pure function
    nothing invokes passes its own tests and fixes nothing, which is the failure mode
    test_display_contract.py exists for.
    """
    import inspect

    from lofc.dashboard.tabs import squads
    source = inspect.getsource(squads.render)
    assert "loan_view(" in source, (
        "render() builds the 'On loan only' view without loan_view(), so the Position "
        "filter is discarded again")
