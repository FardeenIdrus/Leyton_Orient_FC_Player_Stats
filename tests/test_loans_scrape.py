"""Parsing Transfermarkt's per-club loan page.

Reads by COLUMN NAME, never by position: reading positionally is what destroyed 1,381
contract dates on 11 Aug 2026, and this page's column order differs from the squad page's.
"""

import datetime

from lofc.ingest.transfermarkt_loans import (club_id_from_url, parse_loan_end, parse_loans,
                                             loans_url)

# Mirrors the real page: 6 headers but NINE cells per row (the player is a nested
# construct), and the parent club is a crest link carrying a title, with no text.
_PAGE = """
<table class="items"><thead><tr>
  <th>Player</th><th>Age</th><th>Nat.</th><th>On loan from</th>
  <th>Loan ends</th><th>MV end of loan</th></tr></thead>
<tbody>
  <tr><td><a href="/x/profil/spieler/812345">Harry Howell</a> Attacking Midfield</td>
      <td></td><td><a href="/x/profil/spieler/812345">Harry Howell</a></td>
      <td>Attacking Midfield</td><td>19</td>
      <td><img alt="England" title="England"/></td>
      <td><a href="/x/startseite/verein/39336" title="Leicester City"><img alt="Leicester City"/></a></td>
      <td>31/05/2027</td><td>&euro;8.00m</td></tr>
  <tr><td><a href="/y/profil/spieler/990001">Sam Doe</a> Left-Back</td>
      <td></td><td><a href="/y/profil/spieler/990001">Sam Doe</a></td>
      <td>Left-Back</td><td>21</td>
      <td><img alt="Scotland" title="Scotland"/></td>
      <td><a href="/z/startseite/verein/124" title="Rangers FC"><img alt="Rangers FC"/></a></td>
      <td>30.06.2027</td><td>-</td></tr>
</tbody></table>
"""


def test_each_loan_row_is_read():
    rows = parse_loans(_PAGE, "Leyton Orient", 4, 319)
    assert len(rows) == 2
    assert {r["player_name"] for r in rows} == {"Harry Howell", "Sam Doe"}


def test_the_parent_club_is_captured():
    """Without it the row says a player is on loan but not from whom, which is the one
    fact a recruiter needs before approaching anyone."""
    rows = parse_loans(_PAGE, "Leyton Orient", 4, 319)
    assert rows[0]["parent_club"] == "Leicester City"
    assert rows[1]["parent_club"] == "Rangers FC"


def test_the_loan_end_date_is_parsed_in_both_formats():
    """It separates a player going back in the summer from one available in January."""
    rows = parse_loans(_PAGE, "Leyton Orient", 4, 319)
    assert rows[0]["loan_ends"] == datetime.date(2027, 5, 31)   # 31/05/2027
    assert rows[1]["loan_ends"] == datetime.date(2027, 6, 30)   # 30.06.2027


def test_the_transfermarkt_id_is_captured_for_linking():
    rows = parse_loans(_PAGE, "Leyton Orient", 4, 319)
    assert rows[0]["tm_player_id"] == 812345


def test_club_and_season_are_stamped_on_every_row():
    rows = parse_loans(_PAGE, "Leyton Orient", 4, 319)
    assert all(r["club_name"] == "Leyton Orient" for r in rows)
    assert all(r["competition_id"] == 4 and r["season_id"] == 319 for r in rows)


def test_a_table_without_the_loan_column_returns_nothing():
    """A squad page, or a changed layout, must yield NOTHING rather than be read
    positionally. This is the 11 Aug failure mode."""
    squad = _PAGE.replace("On loan from", "Signed from")
    assert parse_loans(squad, "Leyton Orient", 4, 319) == []


def test_the_players_position_is_never_mistaken_for_the_parent_club():
    """The first version mapped header position to cell position. The header row has 6
    columns and each body row has 9, so every player's POSITION was stored as his parent
    club -- 392 rows of it."""
    rows = parse_loans(_PAGE, "Leyton Orient", 4, 319)
    assert all(r["parent_club"] not in ("Attacking Midfield", "Left-Back") for r in rows)


def test_a_page_with_no_table_returns_nothing():
    assert parse_loans("<html><body>no squad</body></html>", "X", 4, 319) == []


def test_a_club_with_no_loans_returns_an_empty_list():
    empty = _PAGE.split("<tbody>")[0] + "<tbody></tbody></table>"
    assert parse_loans(empty, "X", 4, 319) == []


def test_an_unparseable_date_is_none_not_a_guess():
    assert parse_loan_end("end of season") is None
    assert parse_loan_end("") is None


def test_the_club_id_is_taken_from_the_squad_url():
    url = "https://www.transfermarkt.com/leicester-city/kader/verein/1003/saison_id/2026"
    assert club_id_from_url(url) == "1003"
    assert club_id_from_url("https://example.com/nothing") is None


def test_the_loans_url_targets_the_requested_season():
    assert "saison_id/2026" in loans_url(1003, 2026)
    assert "leihspielerhistorie/verein/1003" in loans_url(1003, 2026)


def test_load_stamps_our_season_id_over_transfermarkts(tmp_path):
    """scrape_all works in Transfermarkt season numbers (2026), the platform in its own
    (319). The first load deleted 319 and inserted 2026, so the delete matched nothing and
    the insert collided with the previous run on uq_player_loan -- the whole transaction
    rolled back and 392 stale rows survived, looking like a successful scrape."""
    import datetime
    import pandas as pd
    from sqlalchemy import create_engine, text
    from lofc.ingest.transfermarkt_loans import load
    from lofc.store.models import Base

    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    frame = pd.DataFrame([{"player_name": "A", "tm_player_id": 1, "club_name": "C",
                           "parent_club": "P", "competition_id": 4,
                           "season_id": 2026,          # Transfermarkt's numbering
                           "loan_ends": datetime.date(2027, 6, 30)}])
    load(eng, frame, season_id=319)                     # ours
    with eng.begin() as c:
        stored = c.execute(text("SELECT season_id FROM player_loans")).scalars().all()
    assert stored == [319]


def test_load_replaces_the_previous_run_rather_than_appending():
    """The page is a CURRENT snapshot: a loan that ended is gone from the source, and
    keeping the old row would tell a recruiter someone is still on loan when he is back."""
    import datetime
    import pandas as pd
    from sqlalchemy import create_engine, text
    from lofc.ingest.transfermarkt_loans import load
    from lofc.store.models import Base

    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    def frame(name, tm):
        return pd.DataFrame([{"player_name": name, "tm_player_id": tm, "club_name": "C",
                              "parent_club": "P", "competition_id": 4, "season_id": 2026,
                              "loan_ends": datetime.date(2027, 6, 30)}])
    load(eng, frame("A", 1), 319)
    load(eng, frame("B", 2), 319)
    with eng.begin() as c:
        names = c.execute(text("SELECT player_name FROM player_loans")).scalars().all()
    assert names == ["B"]


# --- the SQUAD page is the more complete loan source -----------------------------------
# The dedicated loans page omitted Somto Boniface at Leyton Orient — on loan from Ipswich
# Town until 31/05/2027, and marked as such on the squad page. Reading the squad page is
# both more complete and cheaper: it is already fetched for every club to get contracts.

_SQUAD = """
<table class="items"><thead><tr><th>#</th><th>Player</th><th>Height</th>
  <th>Contract</th></tr></thead>
<tbody>
  <tr><td>19</td>
      <td><a href="/x/profil/spieler/922472">Somto Boniface</a>
          <a href="/ipswich/startseite/verein/677"
             title="On loan from Ipswich Town until 31/05/2027"></a></td>
      <td>-</td><td>-</td></tr>
  <tr><td>7</td>
      <td><a href="/y/profil/spieler/111">Owned Player</a></td>
      <td>180</td><td>30/06/2028</td></tr>
  <tr><td>4</td>
      <td><a href="/z/profil/spieler/222">No End Date</a>
          <a href="/c/startseite/verein/1" title="On loan from Celtic"></a></td>
      <td>185</td><td>-</td></tr>
</tbody></table>
"""


def test_a_loan_marked_on_the_squad_page_is_found():
    from lofc.ingest.transfermarkt_loans import parse_squad_loans
    rows = parse_squad_loans(_SQUAD, "Leyton Orient", 4, 319)
    names = {r["player_name"] for r in rows}
    assert "Somto Boniface" in names


def test_the_parent_club_and_end_date_are_read_from_the_title():
    import datetime
    from lofc.ingest.transfermarkt_loans import parse_squad_loans
    row = [r for r in parse_squad_loans(_SQUAD, "Leyton Orient", 4, 319)
           if r["player_name"] == "Somto Boniface"][0]
    assert row["parent_club"] == "Ipswich Town"
    assert row["loan_ends"] == datetime.date(2027, 5, 31)
    assert row["tm_player_id"] == 922472


def test_a_player_who_is_not_on_loan_is_not_listed():
    """Every squad member has a club link somewhere; only the loan phrase counts."""
    from lofc.ingest.transfermarkt_loans import parse_squad_loans
    names = {r["player_name"] for r in parse_squad_loans(_SQUAD, "C", 4, 319)}
    assert "Owned Player" not in names


def test_a_loan_with_no_end_date_is_still_recorded():
    """The parent club alone is actionable; a missing date must not drop the row."""
    from lofc.ingest.transfermarkt_loans import parse_squad_loans
    row = [r for r in parse_squad_loans(_SQUAD, "C", 4, 319)
           if r["player_name"] == "No End Date"][0]
    assert row["parent_club"] == "Celtic" and row["loan_ends"] is None
