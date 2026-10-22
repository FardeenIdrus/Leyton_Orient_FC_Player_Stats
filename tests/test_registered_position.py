"""P18 -- Squads & loans: a squad member who has played in neither season shows the position
Transfermarkt lists for him, marked "(registered)".

Measured 2026-10-22 on the server's data: 3,783 squad rows; 2,974 positioned from this
season, 385 from last season, 424 blank. Impect cannot fill them -- verified against its API
the same day: its player list knows players who have not played (788 vs 520 in one league)
but carries NO position field; Impect positions come only from matches.

Owner's rules (2026-10-22):
  1. Impect wins where both exist (this season, then last season, then Transfermarkt).
  2. Left / Right Midfield -> Winger.
  3. Second Striker -> Centre Forward.
  4. "Midfielder" / "Defender" -> blank: too vague to name a group.
"""

import pandas as pd
import pytest

from lofc.dashboard.tabs.squads import (
    _bare_position,
    filter_by_position,
    position_options,
    registered_position,
    with_registered_position,
)


@pytest.mark.parametrize("tm,group", [
    ("Goalkeeper", "Goalkeeper"),
    ("Centre-Back", "Centre Back"),
    ("Left-Back", "Full Back"),
    ("Right-Back", "Full Back"),
    ("Defensive Midfield", "Defensive Mid"),
    ("Central Midfield", "Central Mid"),
    ("Attacking Midfield", "Attacking Mid"),
    ("Left Winger", "Winger"),
    ("Right Winger", "Winger"),
    ("Left Midfield", "Winger"),          # rule 2
    ("Right Midfield", "Winger"),         # rule 2
    ("Centre-Forward", "Centre Forward"),
    ("Striker", "Centre Forward"),
    ("Second Striker", "Centre Forward"),  # rule 3
])
def test_every_transfermarkt_position_maps_to_one_of_our_groups(tm, group):
    assert registered_position(tm) == group


@pytest.mark.parametrize("vague", ["Midfielder", "Defender"])
def test_vague_positions_stay_blank(vague):
    """Rule 4: naming a group the source did not state would be a guess."""
    assert registered_position(vague) is None


@pytest.mark.parametrize("missing", [None, float("nan"), "", "Something new"])
def test_unknown_or_missing_stays_blank(missing):
    assert registered_position(missing) is None


def test_every_mapped_group_is_one_the_platform_uses():
    from lofc.model import club_framework as cf
    for tm in ["Goalkeeper", "Centre-Back", "Left-Back", "Defensive Midfield",
               "Central Midfield", "Attacking Midfield", "Left Winger", "Left Midfield",
               "Centre-Forward", "Striker", "Second Striker"]:
        assert registered_position(tm) in cf.PERFORMANCE_METRICS


def _frame():
    return pd.DataFrame({
        "player_name": ["Plays now", "Played last season", "Never played", "Vague"],
        "position_group": ["Winger", "Centre Back (last season)", None, None],
        "tm_position": ["Centre-Forward", "Left-Back", "Centre-Back", "Midfielder"],
    })


def test_impect_wins_and_only_blanks_are_filled():
    """Rule 1. This season and last season are untouched; only the blank is filled."""
    out = with_registered_position(_frame())
    assert out["position_group"].tolist()[:3] == [
        "Winger", "Centre Back (last season)", "Centre Back (registered)"]
    assert pd.isna(out["position_group"].iloc[3])


def test_the_caller_frame_is_not_mutated():
    frame = _frame()
    with_registered_position(frame)
    assert frame["position_group"].isna().sum() == 2


def test_a_frame_without_the_scrape_column_is_returned_unchanged():
    frame = _frame().drop(columns=["tm_position"])
    assert with_registered_position(frame).equals(frame)


def test_the_filter_and_the_dropdown_treat_registered_as_the_bare_position():
    out = with_registered_position(_frame()).rename(columns={"position_group": "Position"})
    assert _bare_position("Centre Back (registered)") == "Centre Back"
    assert position_options(out) == ["All", "Centre Back", "Winger"]
    assert filter_by_position(out, "Centre Back")["player_name"].tolist() == [
        "Played last season", "Never played"]
