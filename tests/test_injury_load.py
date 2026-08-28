"""The injury CSV -> DB join, the volume guard, and the merge itself.

The frame builder and the guard's ratio test are pure functions -- no database needed.
The merge (F3, near the bottom) does need one, to prove the DELETE/INSERT is actually
scoped to the players in the incoming file; it uses an in-memory sqlite engine, same
as `test_store_injuries.py`.
"""

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
# F1 -- the loader deletes and reinserts only the stored transfermarkt rows of the
# players PRESENT IN THE INCOMING FILE, so a shrunken CSV must not be allowed to reach
# that DELETE. `incoming`/`existing` here are already scoped to the same set of
# visited players (see `merge_transfermarkt_rows`) -- a departing player is outside
# this comparison on both sides, so an ordinary transfer-window shrink never appears
# here at all. This section is a pure function of the two (scoped) row counts, no
# database needed; the scoping itself is exercised below with a real engine.
# --------------------------------------------------------------------------

import pytest

from lofc.store.injuries import MIN_ROW_RATIO, guard_volume, volume_problem


def test_a_normal_refresh_of_the_visited_players_is_not_a_problem():
    # Ordinary re-scrape noise among the SAME visited players is fine.
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


# --------------------------------------------------------------------------
# F3 -- the merge itself. A departing player must keep his rows untouched; a player
# present in the file gets refreshed; a manual row survives regardless of player; and
# the guard fires on a genuinely truncated file for the players it DID cover, but not
# on an ordinary transfer-window shrink (a departed player is simply absent from the
# comparison, not counted as a loss). Real sqlite engine -- this is the DELETE/INSERT
# path, not the pure functions above.
# --------------------------------------------------------------------------

import datetime as dt

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from lofc.store.injuries import COLUMNS, merge_transfermarkt_rows, stored_transfermarkt_rows
from lofc.store.models import Base, Player, PlayerInjury


def injury_columns():
    return COLUMNS


def _seeded_engine(rows):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        seen_players = set()
        for row in rows:
            if row["player_id"] not in seen_players:
                session.add(Player(player_id=row["player_id"], player_name=f"P{row['player_id']}"))
                seen_players.add(row["player_id"])
            session.add(PlayerInjury(**row))
        session.commit()
    return engine


def _injury(player_id, source="transfermarkt", games_missed=1, date_from=dt.date(2024, 9, 1)):
    return dict(player_id=player_id, season_label="24/25", injury_type_raw="Knock",
                injury_category="other", date_from=date_from,
                date_until=date_from + dt.timedelta(days=7),
                days_out=7, games_missed=games_missed, source=source)


def _stored_rows(engine, player_id=None, source=None):
    with Session(engine) as session:
        query = select(PlayerInjury)
        if player_id is not None:
            query = query.where(PlayerInjury.player_id == player_id)
        if source is not None:
            query = query.where(PlayerInjury.source == source)
        return session.execute(query).scalars().all()


def test_a_player_absent_from_the_incoming_file_keeps_his_rows():
    # Simulates the transfer-window case: player 2 has left the leagues and is not in
    # today's scrape at all.
    engine = _seeded_engine([_injury(1), _injury(2), _injury(2, games_missed=3)])
    incoming = pd.DataFrame([_injury(1, games_missed=9)]).reindex(columns=injury_columns())

    touched = merge_transfermarkt_rows(engine, incoming)

    assert touched == 1
    assert len(_stored_rows(engine, player_id=2)) == 2      # untouched, both rows survive
    assert [r.games_missed for r in _stored_rows(engine, player_id=1)] == [9]


def test_a_player_present_in_the_file_is_refreshed():
    # Same number of spells stored as scraped -- a routine refresh, values just updated.
    engine = _seeded_engine([_injury(1, games_missed=1)])
    incoming = pd.DataFrame([_injury(1, games_missed=9)]).reindex(columns=injury_columns())

    merge_transfermarkt_rows(engine, incoming)

    rows = _stored_rows(engine, player_id=1)
    assert [r.games_missed for r in rows] == [9]             # old row gone, new one in


def test_manual_rows_survive_a_transfermarkt_merge():
    engine = _seeded_engine([
        _injury(1, source="manual", games_missed=5),
        _injury(1, source="transfermarkt", games_missed=1),
    ])
    incoming = pd.DataFrame([_injury(1, games_missed=9)]).reindex(columns=injury_columns())

    merge_transfermarkt_rows(engine, incoming)

    manual = _stored_rows(engine, player_id=1, source="manual")
    assert len(manual) == 1 and manual[0].games_missed == 5
    tm = _stored_rows(engine, player_id=1, source="transfermarkt")
    assert [r.games_missed for r in tm] == [9]


def test_the_guard_fires_on_a_genuinely_truncated_file_for_the_visited_players():
    # Player 1 is visited by both loads, but today's file returns far fewer of his rows
    # than are already stored for him -- a truncated CSV or a broken identity join, not
    # squad churn (he is IN the file, just under-represented).
    engine = _seeded_engine([_injury(1, date_from=dt.date(2020 + i, 1, 1)) for i in range(6)])
    incoming = pd.DataFrame([_injury(1)]).reindex(columns=injury_columns())

    with pytest.raises(SystemExit):
        merge_transfermarkt_rows(engine, incoming)

    # Nothing was deleted: the refusal happened before the DELETE.
    assert len(_stored_rows(engine, player_id=1)) == 6


def test_the_guard_does_not_fire_on_an_ordinary_transfer_window_shrink():
    # Hundreds of players leave the leagues and drop out of the file entirely -- that
    # must never look like a shrink to the guard, because it is scoped to the players
    # actually present in the file.
    engine = _seeded_engine([_injury(pid) for pid in range(1, 401)])   # 400 stored players
    incoming = pd.DataFrame([_injury(1, games_missed=9)]).reindex(columns=injury_columns())

    touched = merge_transfermarkt_rows(engine, incoming)   # must not raise

    assert touched == 1
    assert stored_transfermarkt_rows(engine) == 400          # 399 departed players untouched
