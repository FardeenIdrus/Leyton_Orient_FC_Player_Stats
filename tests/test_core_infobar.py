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
