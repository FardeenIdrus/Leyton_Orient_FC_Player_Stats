"""Squads & loans page API (src/lofc/web/api/squads.py) with fake frames: no database.
The real-database parity with the Streamlit page is tests/test_web_squads_parity.py."""
import re

import pandas as pd
import pytest

from test_core_squads import _prepared
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
    from lofc.web.api import squads as api
    base = _prepared()
    loans = base.iloc[[1]].reset_index(drop=True)
    data = api.Data(cur=319, prev=318, cur_name="2026/27", prev_name="2025/26", base=base,
                    n_scraped=3, asof="Transfermarkt data as of 7 Sep 2026.",
                    leagues_all=["Championship", "League One", "League Two"])
    monkeypatch.setattr(api, "_data", lambda: data)
    monkeypatch.setattr(api, "_loans", lambda cur, prev: loans)
    monkeypatch.setattr(api, "_thin", lambda view, cur, prev: {(0, "Also rated"): 6}
                        if len(view) and view.iloc[0]["Player"] == "Ann Ab" else {})
    monkeypatch.setattr(api, "_targets", lambda cur, prev: {1: (4, 318)})
    api._answers.clear()
    api._row_cache.clear()
    yield data
    api._answers.clear()
    api._row_cache.clear()


@pytest.mark.parametrize("path", ["/api/squads", "/api/squads.csv"])
def test_every_endpoint_needs_a_session(path):
    c, *_ = make()
    assert c.get(path).status_code == 401


def test_page_needs_a_session_and_has_every_control():
    c, *_ = make()
    assert c.get("/squads").status_code == 303
    page = _client().get("/squads").text
    for label in ("Player", "League", "Club", "Position", "Show", "More filters",
                  "Maximum age", "Leagues", "Preferred foot", "Contract expiry", "Loan status",
                  "Download (CSV)"):
        assert label in page, label
    assert re.search(r'<script type="module" src="/static/v/[0-9a-f]+/js/squads.js">', page)
    assert '/css/squads.css' in page and '/css/players.css' in page
    assert not re.search(r"<script(?![^>]*\bsrc=)", page) and not re.search(r"\son[a-z]+=", page)
    assert 'class="on" aria-current="page">Squads &amp; loans' in page


def test_payload_shape_and_texts(fake):
    p = _client().get("/api/squads").json()
    assert p["title"] == "Squads, contracts and loans"
    assert p["meta"] == "Every registered squad member, 2026/27. Click a row to open the player."
    assert p["asof"] == "Transfermarkt data as of 7 Sep 2026."
    assert p["warning"] is None and p["empty"] is None
    assert [c["label"] for c in p["columns"]] == [
        "Club", "Player", "Position", "Age", "Minutes", "Composite 2026/27", "Composite 2025/26",
        "Rated in", "Also rated", "Also in", "Contract to", "Months left", "On loan from",
        "Loan ends", "Foot", "Nationality"]
    assert p["tiles"] == [{"label": "Players", "value": "3"}, {"label": "On loan", "value": "1"},
                          {"label": "Contract known", "value": "2"},
                          {"label": "Expiring < 12 months", "value": "1"}]
    assert p["links"] == ["/player/1/4/318", None, None]
    assert p["messages"][0] is None and "no rating" in p["messages"][1]
    assert p["rows"][0][8] == {"t": DASH, "note": "Not rated: only 6 comparable players (needs 10)"}
    assert p["options"]["league"] == ["All", "League One", "League Two"]
    assert p["options"]["leagues"] == ["Championship", "League One", "League Two"]
    assert [o["label"] for o in p["options"]["show"]] == [
        "Everyone", "On loan only", "Contract expiring (under 12 months)"]
    assert p["csv"]["name"] == "lofc_squads_all.csv"
    import json
    for part in (p["rows"], p["tiles"], p["options"]["league"], p["options"]["club"]):
        assert not re.search(r"\b(None|nan|NaN|null|undefined)\b", json.dumps(part)), part


def test_filters_and_state_come_back_resolved(fake):
    c = _client()
    p = c.get("/api/squads", params={"league": "League One", "club": "Nowhere FC",
                                     "position": "Winger"}).json()
    assert p["state"]["league"] == "League One" and p["state"]["club"] == "All"
    assert [r[1] for r in p["rows"]] == ["Ann Ab"]
    p = c.get("/api/squads", params={"show": "loan"}).json()
    assert p["state"]["show"] == "loan" and [r[1] for r in p["rows"]] == ["Bob Cé"]
    p = c.get("/api/squads", params={"foot": "Right"}).json()
    assert [r[1] for r in p["rows"]] == ["Bob Cé"]
    p = c.get("/api/squads", params={"q": "ann"}).json()
    assert [r[1] for r in p["rows"]] == ["Ann Ab"]
    p = c.get("/api/squads", params={"max_age": "25"}).json()   # unknown age is kept
    assert [r[1] for r in p["rows"]] == ["Ann Ab", "Cy Dee"]
    p = c.get("/api/squads", params={"sort": "Minutes", "dir": "asc"}).json()
    assert [r[1] for r in p["rows"]] == ["Cy Dee", "Ann Ab", "Bob Cé"]
    assert p["state"]["sort"] == "Minutes" and p["state"]["dir"] == "asc"


def test_junk_parameters_never_fail(fake):
    c = _client()
    for q in ({"max_age": "abc"}, {"show": "x"}, {"leagues": "Mars League"}, {"sort": "drop"},
              {"contract": "soon"}, {"loan": "?"}, {"foot": "both"}, {"q": "x" * 500}):
        assert c.get("/api/squads", params=q).status_code == 200, q


def test_fallback_and_empty_states(fake, monkeypatch):
    from lofc.web.api import squads as api
    monkeypatch.setattr(api, "_data", lambda: fake._replace(n_scraped=0))
    p = _client().get("/api/squads").json()
    assert p["warning"].startswith("Squad list incomplete: showing the 3 players")
    api._answers.clear()
    api._row_cache.clear()
    monkeypatch.setattr(api, "_data", lambda: fake._replace(base=fake.base.iloc[0:0]))
    p = _client().get("/api/squads").json()
    assert p["empty"] == "No squad data for this season yet." and p["rows"] == []


def test_csv_is_the_table_on_screen(fake):
    r = _client().get("/api/squads.csv", params={"league": "League One"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert 'filename="lofc_squads_league_one.csv"' in r.headers["content-disposition"]
    import io
    t = pd.read_csv(io.BytesIO(r.content), dtype=str, keep_default_na=False)
    assert list(t.columns)[:6] == ["Club", "Player", "Position", "Age", "Minutes", "This season"]
    assert t["Player"].tolist() == ["Ann Ab", "Bob Cé"]
    # withheld (thin pool) as on screen; a rounded column's blank is empty in the file, as
    # Streamlit's (for_export reads "—" as no number)
    assert t.loc[0, "Also rated"] == "" and t.loc[0, "Last season"] == "3.42"
    assert t.loc[0, "Minutes"] == "906"
