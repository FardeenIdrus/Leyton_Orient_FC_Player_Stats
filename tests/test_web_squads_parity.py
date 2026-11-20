"""The rebuilt Squads & loans page against the REAL database (skipped without one).

What the page shows for Leyton Orient and for a club in a league with no Transfermarkt data is
checked, cell by cell where it matters, against the tables it is built from: per-club minutes
(`impect_squad_minutes`, or `player_metrics_neutral` for a league-season the table does not hold
yet), the Transfermarkt squad list, `player_loans`, `player_scorecards` and
`player_current_club`. The Mac database is a copy of the server's; counts differ from live.
"""
import pandas as pd
import pytest
from sqlalchemy import create_engine

from lofc.config import settings
from web_fakes import FakeStore, login, make

DASH = "—"
CURRIE = 72298


@pytest.fixture(scope="module")
def env():
    try:
        engine = create_engine(settings.database_url)
        engine.connect().close()
        cur = int(pd.read_sql("SELECT MAX(season_id) s FROM player_metrics_neutral",
                              engine)["s"][0])
    except Exception:
        pytest.skip("no database")
    s = FakeStore()
    s.add(username="u", full_name="Ann Scout", role="scout", password="correct-horse-1")
    c, *_ = make(s)
    login(c, "u", "correct-horse-1")
    from lofc.web.api import squads as api
    api._answers.clear()
    return c, engine, cur


def _get(c, **params):
    p = c.get("/api/squads", params=params).json()
    keys = [x["key"] for x in p["columns"]]
    rows = [dict(zip(keys, r)) for r in p["rows"]]
    return p, rows


def _minutes(engine, cur, club):
    """The page's minutes source for one club: the per-club table where its league's per-club
    minutes add up to the combined table's (within a minute, for 98% of players), else the
    combined table."""
    per = pd.read_sql("SELECT player_id, competition_id, minutes FROM impect_squad_minutes "
                      "WHERE season_id = %(s)s AND team_name = %(c)s", engine,
                      params={"s": cur, "c": club})
    if len(per):
        off = pd.read_sql(
            "WITH s AS (SELECT player_id, SUM(minutes) m FROM impect_squad_minutes "
            "           WHERE season_id = %(s)s AND competition_id = %(l)s GROUP BY 1) "
            "SELECT AVG(CASE WHEN s.m IS NULL OR ABS(s.m - n.minutes) > 1 THEN 1.0 ELSE 0 END) x "
            "FROM player_metrics_neutral n LEFT JOIN s USING (player_id) "
            "WHERE n.season_id = %(s)s AND n.competition_id = %(l)s", engine,
            params={"s": cur, "l": int(per["competition_id"].iloc[0])})["x"][0]
        if off <= 0.02:
            return per
    return pd.read_sql("SELECT player_id, competition_id, minutes FROM player_metrics_neutral "
                       "WHERE season_id = %(s)s AND team_name = %(c)s", engine,
                       params={"s": cur, "c": club})


def _half_up(x):
    return f"{int(float(x) + 0.5):,}"


def test_orient_squad_is_minutes_plus_registered_players(env):
    c, engine, cur = env
    p, rows = _get(c)                                  # opens on Leyton Orient
    assert p["state"]["club"] == "Leyton Orient"
    mins = _minutes(engine, cur, "Leyton Orient")
    tm = pd.read_sql("SELECT tm_player_id FROM transfermarkt_squads "
                     "WHERE club_name = 'Leyton Orient'", engine)
    marks = [r["Player"]["marks"] for r in rows]
    tm_only = sum("TM only, no minutes" in m for m in marks)
    unlisted = sum(any(x.startswith("Not on TM list") for x in m) for m in marks)
    # the squad = every player with minutes here + every registered player without
    assert len(rows) == len(mins) + tm_only
    assert tm_only + len(mins) - unlisted == len(tm)
    with_minutes = [r["Minutes"] for r, m in zip(rows, marks) if "TM only, no minutes" not in m]
    assert sorted(with_minutes) == sorted(_half_up(m) for m in mins["minutes"])
    assert p["tiles"][0] == {"label": "Players", "value": f"{len(rows):,}"}


def test_orient_ratings_are_the_stored_league_one_composites(env):
    c, engine, cur = env
    p, rows = _get(c)
    ids = [int(h.split("/")[2]) if h else None for h in p["links"]]
    cards = pd.read_sql("SELECT player_id, objective_composite FROM player_scorecards "
                        "WHERE season_id = %(s)s AND competition_id = 4 "
                        "AND archetype = 'All Metrics'", engine, params={"s": cur})
    want = dict(zip(cards["player_id"], cards["objective_composite"]))
    checked = 0
    for pid, r in zip(ids, rows):
        v = r[[k for k in r if k == "Rating"][0]]
        text = v["t"] if isinstance(v, dict) else v
        if text != DASH:
            assert pid in want and f"{want[pid]:.2f}" == text, (r["Player"], text)
            checked += 1
    assert checked > 5


def test_orient_contracts_and_loans_come_from_transfermarkt(env):
    c, engine, cur = env
    p, rows = _get(c)
    assert p["asof"][1]["t"].startswith(("Contracts & loans: Transfermarkt", "Contracts: Transfermarkt"))
    loans_out = pd.read_sql("SELECT player_name FROM player_loans WHERE season_id = %(s)s "
                            "AND parent_club = 'Leyton Orient'", engine, params={"s": cur})
    loans_in = pd.read_sql("SELECT player_name FROM player_loans WHERE season_id = %(s)s "
                           "AND club_name = 'Leyton Orient'", engine, params={"s": cur})
    _, out = _get(c, league="League One", club="Leyton Orient", view="out")
    _, inn = _get(c, league="League One", club="Leyton Orient", view="in")
    assert len(out) == len(loans_out) and len(inn) == len(loans_in)
    assert all(r["Loan"].startswith("To ") for r in out)
    assert all(r["Loan"].startswith("From ") for r in inn)
    # Loans out: minutes at the loan club, from Impect, where the loan club is covered
    assert any(r["Minutes"] != "0" for r in out)


def test_a_club_in_a_league_with_no_transfermarkt_data(env):
    c, engine, cur = env
    tm_leagues = set(pd.read_sql("SELECT DISTINCT competition_id FROM transfermarkt_squads",
                                 engine)["competition_id"])
    clubs = pd.read_sql("SELECT competition_id, team_name, COUNT(*) n FROM player_metrics_neutral "
                        "WHERE season_id = %(s)s GROUP BY 1, 2 ORDER BY 2", engine,
                        params={"s": cur})
    other = clubs[~clubs["competition_id"].isin(tm_leagues)]
    if other.empty:
        pytest.skip("every league has Transfermarkt data")
    from lofc.dashboard.loaders import competition_name_by_id
    club = other.iloc[0]
    league = competition_name_by_id()[int(club["competition_id"])]
    p, rows = _get(c, league=league, club=club["team_name"])
    assert p["state"]["club"] == club["team_name"]
    assert "Contract to" not in [x["key"] for x in p["columns"]]
    assert p["asof"][-1]["t"] == "No Transfermarkt data"
    mins = _minutes(engine, cur, club["team_name"])
    assert len(rows) == len(mins)
    assert sorted(r["Minutes"] for r in rows) == sorted(_half_up(m) for m in mins["minutes"])
    assert not any(r["Player"]["marks"] and not r["Player"]["marks"][0].startswith("Now at")
                   for r in rows)


def test_jack_currie_is_at_oxford_and_now_at_oxford(env):
    c, engine, _ = env
    now = pd.read_sql("SELECT club_name FROM player_current_club WHERE player_id = %(p)s",
                      engine, params={"p": CURRIE})
    assert now["club_name"].tolist() == ["Oxford United"]          # the committed override
    p, rows = _get(c, league="League One", club="Oxford United")
    currie = [r for r in rows if r["Player"]["t"] == "Jack Currie"]
    assert currie and not any(m.startswith("Now at") for m in currie[0]["Player"]["marks"])
    _, orient = _get(c, league="League One", club="Leyton Orient")
    for r in orient:                       # if Orient lists him, it says where he is now
        if r["Player"]["t"] == "Jack Currie":
            assert "Now at Oxford United" in r["Player"]["marks"]


def test_no_cross_league_rating_sort(env):
    c, *_ = env
    p, _ = _get(c, league="All", club="All", sort="Rating")
    assert p["state"]["sort"] is None
    p, _ = _get(c, league="League One", club="All", sort="Rating")
    assert p["state"]["sort"] == "Rating"


def test_every_league_is_offered(env):
    c, engine, cur = env
    p, _ = _get(c)
    n = pd.read_sql("SELECT COUNT(DISTINCT competition_id) n FROM player_metrics_neutral "
                    "WHERE season_id = %(s)s", engine, params={"s": cur})["n"][0]
    assert len(p["options"]["league"]) - 1 == n
