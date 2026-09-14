"""Squads & loans: filter by position, and carry this season's rating where it is trustworthy.

POSITION FILTER. The page listed 3,783 registered squad members with filters for League, Club
and loan/contract status but none for position, so "every centre back in League Two" meant
scrolling. Players whose position falls back to last season (labelled "(last season)" in the
column) are INCLUDED: a new signing who has not featured yet still has a known position, and
he is exactly who a January search is for. The column already marks which is which.

THIS SEASON'S SCORE, GATED. A live-season composite exists only for players past 450 minutes,
and only means something when enough of their league-position peers are past it too. The same
floor the Players page enforces applies here -- otherwise this page would reintroduce the
pool-of-one problem removed from the ranking, where a player alone in his pool scores 4.90 by
construction. Blank means "not yet rankable", not "missing".
"""

import pandas as pd

from lofc.dashboard.tabs.squads import filter_by_position, this_season_score

SQUAD = pd.DataFrame([
    {"Player": "A", "Position": "Centre Back", "player_id": 1, "competition_id": 5, "season_id": 319},
    {"Player": "B", "Position": "Centre Back (last season)", "player_id": 2, "competition_id": 5, "season_id": 319},
    {"Player": "C", "Position": "Winger", "player_id": 3, "competition_id": 5, "season_id": 319},
    {"Player": "D", "Position": None, "player_id": 4, "competition_id": 5, "season_id": 319},
])


# --- position filter -------------------------------------------------------------------

def test_all_returns_everyone():
    assert len(filter_by_position(SQUAD, "All")) == 4


def test_filtering_keeps_only_that_position():
    assert list(filter_by_position(SQUAD, "Centre Back")["Player"]) == ["A", "B"]


def test_a_last_season_fallback_is_included():
    """A registered signing who has not featured yet is exactly the January target."""
    assert "B" in list(filter_by_position(SQUAD, "Centre Back")["Player"])


def test_a_player_with_no_known_position_is_excluded_when_filtering():
    assert "D" not in list(filter_by_position(SQUAD, "Centre Back")["Player"])


def test_the_options_are_the_bare_positions_without_the_fallback_suffix():
    """"Centre Back" and "Centre Back (last season)" must not appear as two choices."""
    from lofc.dashboard.tabs.squads import position_options
    assert position_options(SQUAD) == ["All", "Centre Back", "Winger"]


# --- this season's score, gated ---------------------------------------------------------

SCORES = pd.DataFrame([
    {"player_id": 1, "competition_id": 5, "season_id": 319, "position_group": "Centre Back",
     "objective_composite": 3.50},
    {"player_id": 3, "competition_id": 5, "season_id": 319, "position_group": "Winger",
     "objective_composite": 4.90},
])
# Centre Back pool = 12 (rankable), Winger pool = 1 (not)
POOLS = {(5, 319, "Centre Back"): 12, (5, 319, "Winger"): 1}


def test_a_healthy_pool_carries_its_score():
    out = this_season_score(SQUAD, SCORES, POOLS)
    assert out.loc[out["Player"] == "A", "This season"].iloc[0] == 3.50


def test_a_thin_pool_is_blank_not_shown():
    """The 4.90-from-a-pool-of-one case: withheld here exactly as on the Players page."""
    out = this_season_score(SQUAD, SCORES, POOLS)
    assert pd.isna(out.loc[out["Player"] == "C", "This season"].iloc[0])


def test_a_player_with_no_score_is_blank():
    out = this_season_score(SQUAD, SCORES, POOLS)
    assert pd.isna(out.loc[out["Player"] == "B", "This season"].iloc[0])


def test_an_empty_frame_still_declares_the_column():
    out = this_season_score(pd.DataFrame(columns=["player_id", "competition_id", "season_id"]),
                            SCORES, POOLS)
    assert "This season" in out.columns


def test_the_caller_frame_is_not_mutated():
    this_season_score(SQUAD, SCORES, POOLS)
    assert "This season" not in SQUAD.columns


def test_the_season_is_passed_in_not_inferred_from_the_frame():
    """The squad frame is built from the Transfermarkt scrape and carries NO season column --
    it is a registered-squad list, not a set of appearances. Relying on one raised KeyError
    against the real frame while passing against fixtures that happened to have it."""
    squad_no_season = SQUAD.drop(columns=["season_id"])
    out = this_season_score(squad_no_season, SCORES, POOLS, season_id=319)
    assert out.loc[out["Player"] == "A", "This season"].iloc[0] == 3.50
    assert "season_id" not in out.columns, "helper column leaked into the table"
