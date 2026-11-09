"""The web "What goes into each rating" page: the Streamlit page's own table
(`dashboard.rating_reference.rating_ingredients`, built from the scoring code) and its Excel
download, per position. No database needed."""
import io

import pandas as pd
import pytest

from lofc.dashboard import rating_reference as rr
from lofc.model import club_framework as cf
from web_fakes import FakeStore, login, make

DEFS = {"ball_wins_p90": "Ball wins, per 90"}


def _client():
    s = FakeStore()
    s.add(username="u", full_name="Ann Scout", role="scout", password="correct-horse-1")
    c, *_ = make(s)
    login(c, "u", "correct-horse-1")
    return c


@pytest.fixture(autouse=True)
def _defs(monkeypatch):
    monkeypatch.setattr(rr, "_definitions", lambda: DEFS)


def test_page_shell():
    r = _client().get("/rating-reference")
    assert r.status_code == 200 and "/js/rating_reference.js" in r.text and "Currently building" not in r.text


def test_api_needs_login():
    c, *_ = make(FakeStore())
    assert c.get("/api/rating-reference").status_code == 401


def test_default_position_and_list():
    d = _client().get("/api/rating-reference").json()
    assert d["positions"] == list(cf.PERFORMANCE_METRICS)
    assert d["position"] == "Centre Back"
    assert d["weights_line"] == rr.weights_line("Centre Back")


@pytest.mark.parametrize("position", list(cf.PERFORMANCE_METRICS))
def test_rows_are_the_streamlit_table(position):
    d = _client().get(f"/api/rating-reference?position={position}").json()
    t = rr.rating_ingredients(position, DEFS)
    cols = [c for c in t.columns if c != "key"]
    assert d["columns"] == cols
    assert d["rows"] == t[cols].astype(str).values.tolist()
    assert d["archetypes"] == cf.archetypes_for(position)[1:]


def test_unknown_position_falls_back():
    assert _client().get("/api/rating-reference?position=Sweeper").json()["position"] == "Centre Back"


def test_excel_download_is_the_streamlit_workbook():
    r = _client().get("/api/rating-reference.xlsx")
    assert r.status_code == 200
    assert "spreadsheetml" in r.headers["content-type"]
    assert "what goes into each rating.xlsx" in r.headers["content-disposition"]
    book = pd.read_excel(io.BytesIO(r.content), sheet_name=None)
    assert list(book)[0] == "Weights" and set(cf.PERFORMANCE_METRICS) <= set(book)
