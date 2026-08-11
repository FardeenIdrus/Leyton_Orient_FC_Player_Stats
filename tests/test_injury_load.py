"""The injury CSV -> DB join. The frame builder is pure; no database needed."""

import pandas as pd

from lofc.store.injuries import injury_frame


def _write_csv(tmp_path, rows):
    path = tmp_path / "injuries.csv"
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


PLAYERS = pd.DataFrame({"player_id": [900, 901], "tm_player_id": [111, 222]})


def test_join_maps_tm_id_to_our_player_id(tmp_path):
    path = _write_csv(tmp_path, [{
        "tm_player_id": 111, "season_label": "25/26", "injury_type_raw": "Hamstring injury",
        "injury_category": "hamstring", "date_from": "2025-08-18", "date_until": "2025-08-26",
        "days_out": 9, "games_missed": 2,
    }])
    frame = injury_frame(path, PLAYERS)
    assert list(frame["player_id"]) == [900]
    assert frame.loc[0, "source"] == "transfermarkt"


def test_unmatched_tm_ids_are_dropped_not_guessed(tmp_path):
    # A Transfermarkt player we hold no metrics for must not invent a player_id.
    path = _write_csv(tmp_path, [{
        "tm_player_id": 555, "season_label": "25/26", "injury_type_raw": "Calf strain",
        "injury_category": "calf", "date_from": "2025-09-01", "date_until": "2025-09-10",
        "days_out": 9, "games_missed": 2,
    }])
    assert injury_frame(path, PLAYERS).empty


def test_frame_columns_match_the_table(tmp_path):
    path = _write_csv(tmp_path, [{
        "tm_player_id": 222, "season_label": "24/25", "injury_type_raw": "Ankle sprain",
        "injury_category": "ankle", "date_from": "2024-11-02", "date_until": "2024-11-20",
        "days_out": 18, "games_missed": 4,
    }])
    frame = injury_frame(path, PLAYERS)
    assert set(frame.columns) == {
        "player_id", "tm_player_id", "season_label", "injury_type_raw", "injury_category",
        "date_from", "date_until", "days_out", "games_missed", "source"}


# --------------------------------------------------------------------------
# F1 -- the loader deletes every stored transfermarkt row before appending, so a
# shrunken CSV must not be allowed to reach the DELETE. No database needed: the
# decision is a pure function of the two row counts.
# --------------------------------------------------------------------------

import pytest

from lofc.store.injuries import MIN_ROW_RATIO, guard_volume, volume_problem


def test_a_normal_refresh_is_not_a_problem():
    # Injury histories only grow, but a few players leaving the leagues is normal.
    assert volume_problem(3900, 3930) is None
    assert volume_problem(4200, 3930) is None
    assert volume_problem(2800, 3930) is None          # exactly 71%
    assert MIN_ROW_RATIO == 0.70


def test_a_collapsed_frame_is_a_problem():
    problem = volume_problem(16, 3930)
    assert problem is not None
    assert "16" in problem and "3930" in problem


def test_an_empty_frame_against_a_populated_table_is_a_problem():
    # THE INCIDENT'S SECOND HALF: 16 smoke-test rows replaced a full table. Zero
    # incoming rows must never be allowed to empty it either.
    assert volume_problem(0, 3930) is not None


def test_an_empty_table_accepts_anything():
    # A first ever load, or a table already emptied: there is nothing to protect.
    assert volume_problem(0, 0) is None
    assert volume_problem(10, 0) is None


def test_guard_volume_refuses_and_says_how_to_override(capsys):
    with pytest.raises(SystemExit) as excinfo:
        guard_volume(16, 3930, allow_shrink=False)
    message = str(excinfo.value) + capsys.readouterr().out
    assert "--allow-shrink" in message
    assert "3930" in message


def test_guard_volume_allows_a_healthy_load():
    assert guard_volume(3900, 3930, allow_shrink=False) is None


def test_allow_shrink_overrides_the_guard(capsys):
    guard_volume(16, 3930, allow_shrink=True)          # must not raise
    assert "--allow-shrink" in capsys.readouterr().out


# --------------------------------------------------------------------------
# F2 (the harm path) -- the join itself must refuse an ambiguous tm_player_id.
#
# match_identity no longer WRITES a duplicate, but four already sit in the players
# table (e.g. 948958 -> both Kyrell and Kyreece Lisbie), and the identity update is
# COALESCE-guarded so re-running never clears them. This inner join is where a shared
# id does its damage: it copies one player's entire injury history onto the other.
# --------------------------------------------------------------------------

def test_a_tm_id_held_by_two_players_injures_neither(tmp_path, capsys):
    twins = pd.DataFrame({"player_id": [150216, 150218], "tm_player_id": [948958, 948958]})
    path = _write_csv(tmp_path, [{
        "tm_player_id": 948958, "season_label": "25/26", "injury_type_raw": "Hamstring injury",
        "injury_category": "hamstring", "date_from": "2025-08-18", "date_until": "2025-08-26",
        "days_out": 9, "games_missed": 2,
    }])
    assert injury_frame(path, twins).empty
    assert "948958" in capsys.readouterr().out


def test_an_ambiguous_id_does_not_block_the_unambiguous_ones(tmp_path):
    players = pd.DataFrame({"player_id": [150216, 150218, 900],
                            "tm_player_id": [948958, 948958, 111]})
    path = _write_csv(tmp_path, [
        {"tm_player_id": 948958, "season_label": "25/26", "injury_type_raw": "Hamstring injury",
         "injury_category": "hamstring", "date_from": "2025-08-18", "date_until": "2025-08-26",
         "days_out": 9, "games_missed": 2},
        {"tm_player_id": 111, "season_label": "25/26", "injury_type_raw": "Calf strain",
         "injury_category": "calf", "date_from": "2025-09-01", "date_until": "2025-09-10",
         "days_out": 9, "games_missed": 2},
    ])
    frame = injury_frame(path, players)
    assert list(frame["player_id"]) == [900]
