"""Player identity matching, independent of whether Transfermarkt priced the player."""

import pandas as pd

from lofc.model.identity import load_efl_identity, match_identity

SQUAD_CSV_ROWS = [
    # A Championship player WITH a market value.
    {"league_code": "GB2", "competition_id": 3, "club_name": "Ipswich",
     "tm_player_id": 111, "player_name": "Sam Morsy", "date_of_birth": "1991-09-10",
     "position": "DM", "height_cm": 178, "foot": "right",
     "contract_until": "2027-06-30", "market_value_eur": 2000000},
    # A National League player with NO market value -- the case that is being dropped today.
    {"league_code": "CNAT", "competition_id": 65, "club_name": "Barnet",
     "tm_player_id": 222, "player_name": "Nicke Kabamba", "date_of_birth": "1993-05-05",
     "position": "CF", "height_cm": 188, "foot": "right",
     "contract_until": "2027-06-30", "market_value_eur": ""},
    # No Transfermarkt id -- cannot be used for identity at all.
    {"league_code": "CNAT", "competition_id": 65, "club_name": "Barnet",
     "tm_player_id": "", "player_name": "No Id", "date_of_birth": "1995-01-01",
     "position": "CB", "height_cm": 185, "foot": "left",
     "contract_until": "", "market_value_eur": ""},
]


def _csv(tmp_path):
    path = tmp_path / "efl_values.csv"
    pd.DataFrame(SQUAD_CSV_ROWS).to_csv(path, index=False)
    return path


def test_identity_load_keeps_players_with_no_market_value(tmp_path):
    # This is the whole point of the task: valuation drops these, identity must not.
    squad = load_efl_identity(_csv(tmp_path))
    assert 222 in set(squad["tm_player_id"])


def test_identity_load_drops_rows_with_no_transfermarkt_id(tmp_path):
    squad = load_efl_identity(_csv(tmp_path))
    assert len(squad) == 2
    assert squad["tm_player_id"].notna().all()


def test_match_identity_links_an_unvalued_player(tmp_path):
    squad = load_efl_identity(_csv(tmp_path))
    ours = pd.DataFrame([
        {"player_id": 900, "player_name": "Nicke Kabamba",
         "birth_date": "1993-05-05", "competition_id": 65},
    ])
    matched = match_identity(ours, squad)
    assert list(matched["player_id"]) == [900]
    assert int(matched.loc[0, "tm_player_id"]) == 222
    assert matched.loc[0, "foot"] == "right"


def test_match_identity_requires_the_same_birth_date(tmp_path):
    # Same name, different birth date: a namesake, never the same player.
    squad = load_efl_identity(_csv(tmp_path))
    ours = pd.DataFrame([
        {"player_id": 901, "player_name": "Nicke Kabamba",
         "birth_date": "2001-01-01", "competition_id": 65},
    ])
    assert match_identity(ours, squad).empty


def test_match_identity_is_league_scoped(tmp_path):
    # The right birth date and name, but we hold him in the wrong league.
    squad = load_efl_identity(_csv(tmp_path))
    ours = pd.DataFrame([
        {"player_id": 902, "player_name": "Nicke Kabamba",
         "birth_date": "1993-05-05", "competition_id": 3},
    ])
    assert match_identity(ours, squad).empty


def test_match_identity_skips_players_with_no_birth_date(tmp_path):
    squad = load_efl_identity(_csv(tmp_path))
    ours = pd.DataFrame([
        {"player_id": 903, "player_name": "Nicke Kabamba",
         "birth_date": None, "competition_id": 65},
    ])
    assert match_identity(ours, squad).empty
