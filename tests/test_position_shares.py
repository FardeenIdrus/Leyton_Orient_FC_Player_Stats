"""How a player's minutes split across position groups.

Display data, never scoring. The point is that the platform assigns ONE position group
per player-season and scores against that group's peers -- true for most players, thin
for a utility player. These tests pin the arithmetic and the things that would make the
split misleading on a report a chairman reads.
"""

import pandas as pd
import pytest

from lofc.model.position_shares import shares_from_frame


def _row(player=1, position="CENTRAL_MIDFIELD", seconds=0.0):
    return {"playerId": player, "position": position, "playDuration": seconds}


def test_two_sided_positions_combine_into_one_group():
    """LEFT_WINGER + RIGHT_WINGER is one group, not two entries reading 50% each."""
    out = shares_from_frame(pd.DataFrame([
        _row(position="LEFT_WINGER", seconds=3600.0),
        _row(position="RIGHT_WINGER", seconds=1800.0)]))
    assert len(out) == 1
    assert out.at[0, "position_group"] == "Winger"
    assert out.at[0, "minutes"] == pytest.approx(90.0)
    assert out.at[0, "share"] == pytest.approx(1.0)


def test_shares_are_fractions_of_the_players_own_minutes():
    out = shares_from_frame(pd.DataFrame([
        _row(position="LEFT_WINGBACK_DEFENDER", seconds=3600.0),   # 60 min
        _row(position="ATTACKING_MIDFIELD", seconds=1800.0)]))     # 30 min
    got = dict(zip(out.position_group, out.share))
    assert got["Full Back"] == pytest.approx(2 / 3)
    assert got["Attacking Mid"] == pytest.approx(1 / 3)


def test_shares_sum_to_one_per_player():
    out = shares_from_frame(pd.DataFrame([
        _row(player=1, position="CENTER_FORWARD", seconds=1000.0),
        _row(player=1, position="LEFT_WINGER", seconds=2000.0),
        _row(player=2, position="GOALKEEPER", seconds=5400.0)]))
    sums = out.groupby("playerId")["share"].sum()
    assert sums.round(9).eq(1.0).all()


def test_rows_are_ordered_largest_share_first():
    """A report reads the first row as 'his position'. Order is part of the meaning."""
    out = shares_from_frame(pd.DataFrame([
        _row(position="CENTRAL_MIDFIELD", seconds=600.0),
        _row(position="CENTER_FORWARD", seconds=3600.0)]))
    assert list(out.position_group) == ["Centre Forward", "Central Mid"]


def test_an_unmapped_position_is_kept_as_unknown_not_dropped():
    """Dropping it would make the remaining shares sum to 1 and hide the gap."""
    out = shares_from_frame(pd.DataFrame([
        _row(position="SOMETHING_NEW", seconds=1800.0),
        _row(position="CENTRAL_MIDFIELD", seconds=1800.0)]))
    assert set(out.position_group) == {"Unknown", "Central Mid"}
    assert out.share.sum() == pytest.approx(1.0)


def test_a_player_with_no_minutes_is_dropped_rather_than_dividing_by_zero():
    out = shares_from_frame(pd.DataFrame([_row(seconds=0.0)]))
    assert out.empty


def test_empty_input_returns_the_empty_shape():
    out = shares_from_frame(pd.DataFrame(columns=["playerId", "position", "playDuration"]))
    assert out.empty
    assert list(out.columns) == ["playerId", "position_group", "minutes", "share",
                                 "goals", "assists"]


# --- goals and assists per position ----------------------------------------------------
# These NEVER change a score. A player's metrics stay whole-season across every position;
# splitting them was rejected because 23% of all goals and assists in the platform are
# earned outside the assigned position. These exist so a report can say where the output
# came from while the profile stays whole.

def _grow(player=1, position="CENTRAL_MIDFIELD", seconds=0.0, share=0.0, goals=0.0,
          assists=0.0):
    return {"playerId": player, "position": position, "playDuration": seconds,
            "matchShare": share, "GOALS": goals, "ASSISTS": assists}


def test_goals_are_attributed_to_the_position_they_were_scored_in():
    """Impect ships a per-90 rate per position row; count = rate x matchShare."""
    out = shares_from_frame(pd.DataFrame([
        _grow(position="LEFT_WINGER", seconds=3600.0, share=1.0, goals=2.0),
        _grow(position="LEFT_WINGBACK_DEFENDER", seconds=3600.0, share=1.0, goals=0.0)]))
    got = dict(zip(out.position_group, out.goals))
    assert got["Winger"] == pytest.approx(2.0)
    assert got["Full Back"] == pytest.approx(0.0)


def test_position_goals_sum_to_the_players_season_total():
    """The split must reconcile: it explains the headline number, never contradicts it."""
    out = shares_from_frame(pd.DataFrame([
        _grow(position="ATTACKING_MIDFIELD", seconds=1800.0, share=2.81, goals=0.712),
        _grow(position="RIGHT_WINGER", seconds=1800.0, share=0.42, goals=4.755)]))
    assert out.goals.sum() == pytest.approx(4.0, abs=0.01)


def test_goals_are_absent_not_zero_when_the_source_lacks_them():
    """A frame with no GOALS column means unknown. Zero would claim he scored none."""
    out = shares_from_frame(pd.DataFrame([
        _row(position="LEFT_WINGER", seconds=3600.0)]))
    assert out["goals"].isna().all()
