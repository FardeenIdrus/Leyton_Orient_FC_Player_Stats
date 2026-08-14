"""Tests for the Impect-native identity spine (Phase B2). No network, no database.

Covers the parts that would corrupt the player universe if wrong: reusing an existing
player_id when the Impect player is already ours, minting a deterministic reserved id
when they are new, the position-code mapping, and which rows count as new players."""

import pandas as pd

from lofc.model.impect_spine import (IMPECT_ID_OFFSET, IMPECT_POSITION_GROUPS,
                                     attach_identity, build_spine, new_players)


def _translated(rows):
    """A minimal translate_target-shaped frame (one row per player)."""
    return pd.DataFrame(rows)


def _ours():
    return pd.DataFrame([
        {"player_id": 500, "player_name": "Adama Sidibeh", "birth_date": "1998-06-25",
         "tm_player_id": None},
    ])


def test_position_codes_all_map_to_our_eight_groups():
    groups = set(IMPECT_POSITION_GROUPS.values())
    assert groups == {"Goalkeeper", "Centre Back", "Full Back", "Defensive Mid",
                      "Central Mid", "Attacking Mid", "Winger", "Centre Forward"}
    assert IMPECT_POSITION_GROUPS["LEFT_WINGBACK_DEFENDER"] == "Full Back"
    assert IMPECT_POSITION_GROUPS["CENTER_FORWARD"] == "Centre Forward"


def test_existing_player_reuses_their_id():
    # An Impect player already in our DB (same DOB + name) keeps their real player_id.
    tr = _translated([{"playerId": 999, "player_name": "Adama Sidibeh",
                       "birth_date": pd.Timestamp("1998-06-25"), "position": "CENTER_FORWARD",
                       "minutes": 2000.0, "goals_p90": 0.5}])
    out = attach_identity(tr, _ours())
    assert out.at[0, "player_id"] == 500          # reused, not minted
    assert out.at[0, "matched_via"] == "dob_name"
    assert out.at[0, "position_group"] == "Centre Forward"


def test_new_player_is_minted_in_the_reserved_range():
    # A player NOT in our DB gets a deterministic minted id = offset + Impect id.
    tr = _translated([{"playerId": 12345, "player_name": "Jack Butland",
                       "birth_date": pd.Timestamp("1993-03-10"), "position": "GOALKEEPER",
                       "minutes": 3000.0, "goals_p90": 0.0}])
    out = attach_identity(tr, _ours())
    assert out.at[0, "player_id"] == IMPECT_ID_OFFSET + 12345
    assert out.at[0, "matched_via"] == "minted"
    assert out.at[0, "position_group"] == "Goalkeeper"


def test_minting_is_deterministic_across_calls():
    tr = _translated([{"playerId": 777, "player_name": "New Player",
                       "birth_date": pd.Timestamp("2000-01-01"), "position": "LEFT_WINGER",
                       "minutes": 1000.0, "goals_p90": 0.1}])
    a = attach_identity(tr, _ours()).at[0, "player_id"]
    b = attach_identity(tr, _ours()).at[0, "player_id"]
    assert a == b == IMPECT_ID_OFFSET + 777        # same input -> same id, always


def test_build_spine_returns_identity_and_metrics_keyed_by_our_id():
    tr = _translated([{"playerId": 12345, "player_name": "Jack Butland",
                       "birth_date": pd.Timestamp("1993-03-10"), "position": "GOALKEEPER",
                       "minutes": 3000.0, "rankable": True, "team_name": "Rangers",
                       "competition_id": 901, "season_id": 318, "goals_p90": 0.0}])
    spine, metrics = build_spine(tr, _ours())
    assert list(spine.columns[:4]) == ["player_id", "competition_id", "season_id", "player_name"]
    assert spine.at[0, "player_id"] == IMPECT_ID_OFFSET + 12345
    assert "goals_p90" in metrics.columns and "player_id" in metrics.columns


def test_new_players_lists_only_minted_ids_with_birthdate():
    tr = _translated([
        {"playerId": 12345, "player_name": "Jack Butland", "birth_date": pd.Timestamp("1993-03-10"),
         "position": "GOALKEEPER", "minutes": 3000.0, "rankable": True, "team_name": "Rangers",
         "competition_id": 901, "season_id": 318, "goals_p90": 0.0},
        {"playerId": 999, "player_name": "Adama Sidibeh", "birth_date": pd.Timestamp("1998-06-25"),
         "position": "CENTER_FORWARD", "minutes": 2000.0, "rankable": True, "team_name": "St Mirren",
         "competition_id": 901, "season_id": 318, "goals_p90": 0.4},
    ])
    spine, _ = build_spine(tr, _ours())
    minted = new_players(spine, tr, ours_ids={500})
    # Butland is minted (new); Sidibeh reused id 500, so is NOT a new player.
    assert list(minted["player_id"]) == [IMPECT_ID_OFFSET + 12345]
    assert pd.notna(minted.iloc[0]["birth_date"])
