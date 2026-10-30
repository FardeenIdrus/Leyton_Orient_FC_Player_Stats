"""A player's CURRENT club, from Impect (owner, 2026-10-30).

The club on the platform is the club his stats are from: the squad he played most minutes
for in that league and season. Eoin Kenny was rated for Dundalk FC (Ireland 2026, 1,680
minutes) after he had joined Portsmouth (23 minutes, not rated). 111 rated 2026/27 players
had another club that season. Impect's player list carries `currentSquadId` -- his club
now, not the club of the season -- so the platform shows "Dundalk FC · now FC Portsmouth".

Verified 2026-10-30: set for 96% of 2026/27 players, named for 93% of those; agrees with
Transfermarkt's squad for 98% where both are known. A club outside every competition we
can access has no name: then nothing is added rather than a guess. Display only.
"""

import pandas as pd

from lofc import pipeline
from lofc.dashboard.player_header import club_text
from lofc.ingest import impect
from lofc.model import current_club as cc


def _players(*rows):
    return pd.DataFrame(rows, columns=["id", "currentSquadId"])


# --- resolving ------------------------------------------------------------------------

def test_each_linked_player_gets_his_current_club_by_name():
    frames = [(319, _players((161271, 960)), pd.Series({161271: 2_000_161_271}))]
    out = cc.resolve(frames, {960: "FC Portsmouth"})
    assert out.to_dict("records") == [
        {"player_id": 2_000_161_271, "impect_squad_id": 960, "club_name": "FC Portsmouth"}]


def test_a_club_we_cannot_name_is_kept_without_a_name_never_guessed():
    frames = [(319, _players((1, 4637)), pd.Series({1: 10}))]
    assert pd.isna(cc.resolve(frames, {960: "FC Portsmouth"})["club_name"].iloc[0])


def test_no_current_club_and_unlinked_players_are_left_out():
    frames = [(319, _players((1, None), (2, 960)), pd.Series({1: 10}))]   # 2 is not linked
    assert cc.resolve(frames, {960: "FC Portsmouth"}).empty


def test_the_latest_season_wins_when_a_player_appears_twice():
    frames = [(318, _players((1, 100)), pd.Series({1: 10})),
              (319, _players((1, 200)), pd.Series({1: 10}))]
    out = cc.resolve(frames, {100: "Old FC", 200: "New FC"})
    assert out["club_name"].tolist() == ["New FC"]


# --- display --------------------------------------------------------------------------

def test_the_club_label_adds_now_only_when_he_has_moved():
    assert club_text("Dundalk FC", "FC Portsmouth") == "Dundalk FC · now FC Portsmouth"
    assert club_text("FC Portsmouth", "FC Portsmouth") == "FC Portsmouth"
    assert club_text("Dundalk FC", None) == "Dundalk FC"
    assert club_text("Dundalk FC", float("nan")) == "Dundalk FC"


# --- ingest ---------------------------------------------------------------------------

def test_the_player_list_keeps_only_the_id_and_current_club(monkeypatch):
    raw = pd.DataFrame({"id": [1], "commonname": ["A"], "currentSquadId": [960],
                        "birthdate": ["2005-12-30"]})
    monkeypatch.setattr(impect, "_api_frame", lambda path, token, endpoint: raw)
    out = impect.fetch_iteration_players(2114, "t")
    assert list(out.columns) == ["id", "currentSquadId"]


def test_club_names_come_from_every_accessible_season_and_one_failure_is_skipped(monkeypatch):
    def frame(path, token, endpoint):
        if "/7/" in path:
            raise RuntimeError("no access")
        return pd.DataFrame({"id": [960 if "/1/" in path else 289],
                             "name": ["FC Portsmouth" if "/1/" in path else "Swansea City"]})
    monkeypatch.setattr(impect, "_api_frame", frame)
    assert impect.fetch_squad_names([1, 7, 2], "t") == {960: "FC Portsmouth", 289: "Swansea City"}


def test_the_pipeline_records_current_clubs_after_the_style_signals():
    names = [name for name, _ in pipeline.build_steps()]
    current = next(i for i, n in enumerate(names) if n.startswith("Current club"))
    style = next(i for i, n in enumerate(names) if n.startswith("Style signals"))
    assert current == style + 1
