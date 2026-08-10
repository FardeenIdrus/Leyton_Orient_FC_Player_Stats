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
