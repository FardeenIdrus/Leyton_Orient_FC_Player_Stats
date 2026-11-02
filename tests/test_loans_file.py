"""Loans reach the server through a FILE, like squads (TASKS 2.3, 2026-11-02).

Before: the loan scrape (Mac only -- Transfermarkt's WAF blocks the server) wrote straight
into the Mac's database and nowhere else. The documented refresh copies FILES to the server,
and the server had no loader, so a December re-scrape would have updated the Mac and left
the live site on September's loans. Now the scrape also writes
`reference/transfermarkt/loans.csv`, and `lofc.store.loans` loads it on the server -- every
weekly run, like the squads file.
"""

import datetime

import pandas as pd
from sqlalchemy import create_engine, text

from lofc import pipeline
from lofc.ingest import transfermarkt_loans as tl
from lofc.store import loans as store


def _frame(n=3, season_id=319):
    return pd.DataFrame([{"player_name": f"P{i}", "tm_player_id": 1000 + i,
                          "club_name": "Leyton Orient", "parent_club": "Tottenham Hotspur",
                          "competition_id": 4, "season_id": season_id,
                          "loan_ends": datetime.date(2027, 6, 30)} for i in range(n)],
                        columns=tl.COLUMNS)


def _engine():
    eng = create_engine("sqlite://")
    with eng.begin() as c:
        c.execute(text("CREATE TABLE players (player_id INTEGER, tm_player_id INTEGER)"))
        c.execute(text("INSERT INTO players VALUES (77, 1000)"))
        c.execute(text("CREATE TABLE player_loans (id INTEGER PRIMARY KEY, player_id INTEGER, "
                       "tm_player_id INTEGER, player_name TEXT, club_name TEXT, parent_club TEXT, "
                       "competition_id INTEGER, season_id INTEGER, loan_ends DATE, "
                       "scraped_at TIMESTAMP)"))
    return eng


def _count(eng, season_id=319):
    with eng.connect() as c:
        return c.execute(text("SELECT COUNT(*) FROM player_loans WHERE season_id = :s"),
                         {"s": season_id}).scalar()


def test_the_scrape_writes_a_file_with_our_season_and_the_scrape_time(tmp_path):
    path = tmp_path / "loans.csv"
    when = datetime.datetime(2026, 12, 15, 9, 30)
    tl.write_csv(_frame(), 319, when, path)
    back = store.frame_from_csv(path)
    assert len(back) == 3 and set(back["season_id"]) == {319}
    assert back.attrs["scraped_at"] == when
    assert back["loan_ends"].iloc[0] == datetime.date(2027, 6, 30)
    assert not (tmp_path / "loans.csv.tmp").exists()              # written atomically


def test_the_server_loads_the_file_links_players_and_keeps_the_scrape_date(tmp_path):
    path = tmp_path / "loans.csv"
    when = datetime.datetime(2026, 12, 15, 9, 30)
    tl.write_csv(_frame(), 319, when, path)
    eng = _engine()
    assert store.load_file(eng, path) == 3
    with eng.connect() as c:
        linked = c.execute(text("SELECT player_id FROM player_loans WHERE tm_player_id = 1000")).scalar()
        stamp = c.execute(text("SELECT MAX(scraped_at) FROM player_loans")).scalar()
    assert linked == 77
    assert str(stamp).startswith("2026-12-15 09:30")


def test_reloading_the_same_file_every_week_changes_nothing(tmp_path):
    path = tmp_path / "loans.csv"
    tl.write_csv(_frame(), 319, datetime.datetime(2026, 12, 15), path)
    eng = _engine()
    store.load_file(eng, path)
    store.load_file(eng, path)
    assert _count(eng) == 3


def test_a_much_smaller_file_is_refused_and_the_stored_loans_are_kept(tmp_path):
    """A truncated scrape must not empty the table (the squads lesson, 11 Aug 2026)."""
    eng = _engine()
    big, small = tmp_path / "big.csv", tmp_path / "small.csv"
    tl.write_csv(_frame(10), 319, datetime.datetime(2026, 12, 1), big)
    tl.write_csv(_frame(2), 319, datetime.datetime(2026, 12, 15), small)
    store.load_file(eng, big)
    assert store.load_file(eng, small) == 0
    assert _count(eng) == 10
    assert store.load_file(eng, small, allow_shrink=True) == 2


def test_no_file_means_nothing_to_do(tmp_path):
    assert store.load_file(_engine(), tmp_path / "missing.csv") == 0


def test_the_pipeline_loads_loans_after_squads_even_where_it_cannot_scrape(monkeypatch):
    from lofc.config import settings
    monkeypatch.setattr(settings, "skip_transfermarkt_scrape", True, raising=False)
    names = [n for n, _ in pipeline.build_steps()]
    squads = next(i for i, n in enumerate(names) if n.startswith("Squads: load"))
    assert names[squads + 1].startswith("Loans: load")
    assert not any(n.startswith("Pull loan players") for n in names)
