"""Squads & loans page API (src/lofc/web/api/squads.py) with fake frames: no database.
The page logic is tests/test_core_squad_lists.py; the real database is
tests/test_web_squads_parity.py."""
import datetime as dt
import io
import json
import re

import pandas as pd
import pytest

from test_core_squad_lists import TODAY, _src
from web_fakes import FakeStore, login, make

DASH = "—"


def _client():
    s = FakeStore()
    s.add(username="u", full_name="Ann Scout", role="scout", password="correct-horse-1")
    c, *_ = make(s)
    login(c, "u", "correct-horse-1")
    return c


@pytest.fixture
def fake(monkeypatch):
    from lofc.core import squad_lists as Q
    from lofc.web.api import squads as api
    rows = Q.build_rows(_src(), today=TODAY)
    data = api.Data(cur=319, cur_name="2026/27", rows=rows, today=TODAY,
                    impect_date=dt.date(2026, 11, 9), contracts_date=dt.date(2026, 9, 7),
                    loans_date=dt.date(2026, 9, 18), targets={2: (4, 318)})
    monkeypatch.setattr(api, "_data", lambda: data)
    api._answers.clear()
    yield data
    api._answers.clear()


@pytest.mark.parametrize("path", ["/api/squads", "/api/squads.csv"])
def test_every_endpoint_needs_a_session(path):
    c, *_ = make()
    assert c.get(path).status_code == 401


def test_page_needs_a_session_and_has_every_control():
    c, *_ = make()
    assert c.get("/squads").status_code == 303
    page = _client().get("/squads").text
    for label in ("Player", "League", "Club", "Position", "View", "Maximum age",
                  "Contract expiring", "Loan status", "Preferred foot", "Download (CSV)"):
        assert label in page, label
    assert re.search(r'<script type="module" src="/static/v/[0-9a-f]+/js/squads.js">', page)
    assert not re.search(r"<script(?![^>]*\bsrc=)", page) and not re.search(r"\son[a-z]+=", page)
    assert 'class="on" aria-current="page">Squads &amp; loans' in page


def test_opens_on_leyton_orient(fake):
    p = _client().get("/api/squads").json()
    assert p["state"]["league"] == "League One" and p["state"]["club"] == "Leyton Orient"
    assert p["title"] == "Squads, contracts and loans"
    assert [c["label"] for c in p["columns"]] == [
        "Player", "Position", "Age", "Minutes", "Rating 2026/27", "Contract to", "Loan"]
    assert p["tiles"] == [{"label": "Players", "value": "5"}, {"label": "Played", "value": "3"},
                          {"label": "Loans in", "value": "1"}, {"label": "Loans out", "value": "1"}]
    assert p["asof"] == [{"t": "Minutes: Impect 9 Nov", "stale": False},
                         {"t": "Contracts: Transfermarkt 7 Sep (70 days)", "stale": True},
                         {"t": "Loans: Transfermarkt 18 Sep (59 days)", "stale": True}]
    assert p["stale"] is True
    names = [r[0]["t"] for r in p["rows"]]
    assert names[:2] == ["Eight Forward", "One Mover"]
    two = names.index("Two Registered")
    assert p["rows"][two][0]["marks"] == ["TM only, no minutes"]
    assert p["links"][two] == "/player/2/4/318"                 # his last rated season
    one = names.index("One Mover")
    assert p["links"][one] == "/player/1/4/319"                 # rated in this league-season
    nine = names.index("Nine Unlinked")
    assert p["links"][nine] is None and "no performance record" in p["messages"][nine]
    assert p["csv"]["name"] == "lofc_squads_leyton_orient.csv"
    for part in (p["rows"], p["tiles"], p["options"]["league"], p["options"]["club"]):
        assert not re.search(r"\b(None|nan|NaN|null|undefined)\b", json.dumps(part)), part


def test_all_leagues_and_a_club_with_no_transfermarkt_data(fake):
    c = _client()
    p = c.get("/api/squads", params={"league": "All", "club": "All"}).json()
    assert p["state"]["league"] == "All" and p["state"]["club"] == "All"
    assert [x["key"] for x in p["columns"]][:2] == ["League", "Club"]
    p = c.get("/api/squads", params={"league": "Scottish Premiership",
                                     "club": "Celtic Glasgow"}).json()
    assert "Contract to" not in [x["key"] for x in p["columns"]]
    assert p["asof"][-1] == {"t": "No Transfermarkt data", "stale": False}


def test_rating_sort_is_refused_across_leagues(fake):
    c = _client()
    p = c.get("/api/squads", params={"league": "All", "club": "All", "sort": "Rating"}).json()
    assert p["state"]["sort"] is None
    assert [x for x in p["columns"] if x["key"] == "Rating"][0]["sortable"] is False
    p = c.get("/api/squads", params={"league": "League One", "club": "All",
                                     "sort": "Rating", "dir": "desc"}).json()
    assert p["state"]["sort"] == "Rating"
    ratings = [r[[x["key"] for x in p["columns"]].index("Rating")] for r in p["rows"]]
    shown = [float(v["t"] if isinstance(v, dict) else v) for v in ratings
             if (v["t"] if isinstance(v, dict) else v) != DASH]
    assert shown == sorted(shown, reverse=True)


def test_views_filters_and_state(fake):
    c = _client()
    p = c.get("/api/squads", params={"league": "League One", "club": "Leyton Orient",
                                     "view": "out"}).json()
    assert p["state"]["view"] == "out" and [r[0]["t"] for r in p["rows"]] == ["Five Out"]
    assert [x["label"] for x in p["columns"]][3] == "Minutes (loan club)"
    assert p["csv"]["name"] == "lofc_squads_leyton_orient_loans_out.csv"
    p = c.get("/api/squads", params={"league": "League One", "club": "Leyton Orient",
                                     "contract": "Under 6 months"}).json()
    assert [r[0]["t"] for r in p["rows"]] == ["Two Registered"]
    assert p["state"]["contract"] == "Under 6 months"


def test_junk_parameters_never_fail(fake):
    c = _client()
    for q in ({"max_age": "abc"}, {"view": "x"}, {"league": "Mars League"}, {"sort": "drop"},
              {"contract": "soon"}, {"loan": "?"}, {"foot": "Middle"}, {"q": "x" * 500}, {"dir": "sideways"}):
        assert c.get("/api/squads", params=q).status_code == 200, q


def test_csv_is_the_table_on_screen(fake):
    r = _client().get("/api/squads.csv", params={"league": "League One", "club": "Leyton Orient"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert 'filename="lofc_squads_leyton_orient.csv"' in r.headers["content-disposition"]
    t = pd.read_csv(io.BytesIO(r.content), dtype=str, keep_default_na=False)
    assert list(t.columns) == ["Player", "Position", "Age", "Minutes", "Rating 2026/27",
                               "Contract to", "Loan", "Note"]
    p = _client().get("/api/squads", params={"league": "League One",
                                             "club": "Leyton Orient"}).json()
    assert t["Player"].tolist() == [r[0]["t"] for r in p["rows"]]
    assert t.loc[t["Player"] == "Three Unlisted", "Note"].item() == "Not on TM list (7 Sep)"


def test_no_market_value_in_the_payload(fake):
    body = _client().get("/api/squads", params={"league": "All", "club": "All"}).text
    assert "market" not in body.lower()


def test_preferred_foot_reaches_the_page_state(fake):
    p = _client().get("/api/squads", params={"league": "League One", "club": "Leyton Orient",
                                             "foot": "Left"}).json()
    assert p["state"]["foot"] == "Left"
    assert p["options"]["foot"] == ["Any", "Left", "Right"]
