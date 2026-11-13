"""The info-bar numbers live in lofc.core.infobar so Streamlit and the new web front end show
the same thing. Streamlit's own names must still resolve to the same results."""

import pytest
from sqlalchemy import create_engine

from lofc.config import settings
from lofc.core import infobar
from lofc.dashboard.tabs import players as players_tab


def test_items_are_the_same_function_streamlit_uses():
    assert players_tab.infobar_count_items is infobar.infobar_count_items
    assert infobar.infobar_count_items(4376, 3229) == [
        "<b>4,376</b> players", "<b>3,229</b> rated (450+ mins)"]


def test_leagues_and_headline_match_the_streamlit_loaders():
    engine = create_engine(settings.database_url)
    try:
        engine.connect().close()
    except Exception:
        pytest.skip("no database")
    from lofc.dashboard import loaders
    latest = loaders.available_seasons()[0]
    assert infobar.headline_counts(engine, latest) == loaders.headline(latest)
    assert infobar.league_count(engine) == len(loaders.league_names())


# --- pull dates (owner R6): "Impect 13 Nov · SkillCorner 13 Nov" ---------------------------
def _runs_engine(rows):
    import datetime as dt
    from sqlalchemy import text
    e = create_engine("sqlite://")
    with e.begin() as c:
        c.execute(text("CREATE TABLE pipeline_runs (id INTEGER PRIMARY KEY, run_id TEXT, "
                       "step TEXT, status TEXT, finished_at TIMESTAMP)"))
        for step, status, when in rows:
            c.execute(text("INSERT INTO pipeline_runs (run_id, step, status, finished_at) "
                           "VALUES ('r', :s, :st, :f)"),
                      {"s": step, "st": status, "f": dt.datetime.fromisoformat(when)})
    return e


def test_pull_dates_are_the_latest_successful_main_pull():
    import datetime as dt
    e = _runs_engine([
        ("Pull Impect", "success", "2026-11-06 04:00"),
        ("Pull Impect", "success", "2026-11-13 04:21"),
        ("Pull Impect", "failed", "2026-11-14 04:00"),               # failed: ignored
        ("Pull Impect player data", "success", "2026-11-15 04:00"),  # not the main pull
        ("Pull SkillCorner", "success", "2026-11-02 04:00"),
        ("Pull SkillCorner", "partial", "2026-11-12 04:00"),         # not a success
        ("Pull SkillCorner physical data (platform)", "success", "2026-11-16 04:00")])
    assert infobar.pull_dates(e) == {"Impect": dt.date(2026, 11, 13),
                                     "SkillCorner": dt.date(2026, 11, 2)}


def test_pull_dates_never_pulled_and_no_table():
    e = _runs_engine([("Pull Impect", "failed", "2026-11-14 04:00")])
    assert infobar.pull_dates(e) == {"Impect": None, "SkillCorner": None}
    assert infobar.pull_dates(create_engine("sqlite://")) == {"Impect": None, "SkillCorner": None}


def test_pull_date_items_text():
    import datetime as dt
    assert infobar.pull_date_items({"Impect": dt.date(2026, 11, 13),
                                    "SkillCorner": dt.date(2026, 11, 2)}) == [
        "Impect <b>13 Nov</b>", "SkillCorner <b>2 Nov</b>"]
    assert infobar.pull_date_items({"Impect": None, "SkillCorner": None}) == [
        "Impect <b>—</b>", "SkillCorner <b>—</b>"]


def test_web_info_bar_appends_the_pull_dates(monkeypatch):
    import datetime as dt
    from lofc.web import app as web_app
    monkeypatch.setattr(infobar, "latest_season_id", lambda e: 319)
    monkeypatch.setattr(infobar, "headline_counts", lambda e, s: (10447, 5559, 25))
    monkeypatch.setattr(infobar, "league_count", lambda e: 25)
    monkeypatch.setattr(infobar, "pull_dates", lambda e: {"Impect": dt.date(2026, 11, 13),
                                                          "SkillCorner": None})
    store = type("S", (), {"engine": lambda self: None})()
    items = web_app.InfoBar(store).items()
    assert " · ".join(items) == ("<b>10,447</b> players · <b>5,559</b> rated (450+ mins) · "
                                 "<b>25</b> leagues · <b>2026/27</b> season · "
                                 "Impect <b>13 Nov</b> · SkillCorner <b>—</b>")
