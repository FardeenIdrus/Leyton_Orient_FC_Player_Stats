"""Player identity matching, independent of whether Transfermarkt priced the player."""

import pandas as pd

from lofc.model.valuation import _norm
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


# --------------------------------------------------------------------------
# F2 -- one Transfermarkt row must not be claimed by two of our players.
#
# This was cosmetic while tm_player_id was only a profile link. store/injuries.py
# now inner-joins the injury history on it, so a duplicate copies one player's whole
# injury record onto a second player and the availability figure -- a medical
# judgement -- follows it. There is no way to tell which of the two is right, so
# neither is written.
# --------------------------------------------------------------------------

def test_two_players_resolving_to_one_squad_row_are_both_dropped(tmp_path, capsys):
    squad = load_efl_identity(_csv(tmp_path))
    ours = pd.DataFrame([
        {"player_id": 900, "player_name": "Nicke Kabamba",
         "birth_date": "1993-05-05", "competition_id": 65},
        {"player_id": 901, "player_name": "Nicke Kabamba",
         "birth_date": "1993-05-05", "competition_id": 65},
    ])
    matched = match_identity(ours, squad)
    assert matched.empty
    assert list(matched.columns) == ["player_id", "tm_player_id", "birth_date", "foot",
                                     "contract_until", "height_cm"]
    printed = capsys.readouterr().out
    assert "222" in printed                      # the ambiguous Transfermarkt id
    assert matched.attrs["dropped_ambiguous"] == 2


def test_an_ambiguous_id_does_not_take_the_unambiguous_ones_with_it(tmp_path):
    squad = load_efl_identity(_csv(tmp_path))
    ours = pd.DataFrame([
        {"player_id": 900, "player_name": "Nicke Kabamba",
         "birth_date": "1993-05-05", "competition_id": 65},
        {"player_id": 901, "player_name": "Nicke Kabamba",
         "birth_date": "1993-05-05", "competition_id": 65},
        {"player_id": 902, "player_name": "Sam Morsy",
         "birth_date": "1991-09-10", "competition_id": 3},
    ])
    matched = match_identity(ours, squad)
    assert list(matched["player_id"]) == [902]
    assert int(matched.loc[0, "tm_player_id"]) == 111
    assert matched.attrs["dropped_ambiguous"] == 2


def test_a_clean_match_reports_nothing_dropped(tmp_path):
    squad = load_efl_identity(_csv(tmp_path))
    ours = pd.DataFrame([
        {"player_id": 900, "player_name": "Nicke Kabamba",
         "birth_date": "1993-05-05", "competition_id": 65},
    ])
    matched = match_identity(ours, squad)
    assert len(matched) == 1
    assert matched.attrs["dropped_ambiguous"] == 0


# --- already-linked players: match on the Transfermarkt id we already hold -------------
# match_identity linked ONLY on name + birth date within one league. A player whose
# tm_player_id we already stored, but whose name spelling differs from the squad page or
# who changed league mid-season, failed that re-match and so never received the contract
# date sitting in the scrape. Measured on the live data: 128 already-linked players had a
# scraped contract and a NULL contract_until, and ALL 128 failed the name+DOB re-match.
#
# An id we already hold is a STRONGER link than name+DOB, so it is tried first.

def _squad_row(tm_id=555, name="Alan Smith", dob="1998-05-14", comp=4,
               contract="2028-06-30", foot="right", height=182):
    import pandas as pd
    return pd.DataFrame([{
        "tm_player_id": tm_id, "player_name": name, "nname": _norm(name),
        "birth_date": pd.Timestamp(dob), "competition_id": comp,
        "contract_until": contract, "foot": foot, "height_cm": height}])


def _ours_row(player_id=1, name="Alan Smith", dob="1998-05-14", comp=4, tm_id=None):
    import pandas as pd
    row = {"player_id": player_id, "player_name": name,
           "birth_date": pd.Timestamp(dob), "competition_id": comp}
    if tm_id is not None:
        row["tm_player_id"] = tm_id
    return pd.DataFrame([row])


def test_a_known_tm_id_matches_even_when_the_name_differs():
    """The squad page spells him differently. We already know his Transfermarkt id, so
    the contract must still land."""
    out = match_identity(_ours_row(name="Alan J. Smith", tm_id=555), _squad_row())
    assert len(out) == 1
    assert out.iloc[0]["contract_until"] == "2028-06-30"


def test_a_known_tm_id_matches_across_a_league_change():
    """He moved League One -> Championship mid-season, so the league-scoped name+DOB
    match cannot find him. The id still can."""
    out = match_identity(_ours_row(comp=3, tm_id=555), _squad_row(comp=4))
    assert len(out) == 1
    assert out.iloc[0]["tm_player_id"] == 555


def test_name_and_dob_still_match_a_player_with_no_stored_id():
    """The existing path must keep working for players we have never linked."""
    out = match_identity(_ours_row(tm_id=None), _squad_row())
    assert len(out) == 1
    assert out.iloc[0]["tm_player_id"] == 555


def test_a_stored_id_absent_from_the_scrape_falls_back_to_name_and_dob():
    out = match_identity(_ours_row(tm_id=999), _squad_row(tm_id=555))
    assert len(out) == 1
    assert out.iloc[0]["tm_player_id"] == 555


def test_two_players_claiming_one_id_are_still_dropped():
    """The ambiguity guard protects the injury join and must survive this change."""
    import pandas as pd
    ours = pd.concat([_ours_row(player_id=1, tm_id=555),
                      _ours_row(player_id=2, name="Alan Smyth", tm_id=555)])
    assert match_identity(ours, _squad_row()).empty
