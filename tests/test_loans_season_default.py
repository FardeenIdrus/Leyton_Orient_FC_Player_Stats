"""The loan scrape must stamp OUR season id, not Transfermarkt's.

`scrape_all` works in Transfermarkt season numbers (2026); the platform works in its own
(319). `load()` stamps ours over theirs, and its comment explains why -- but `--season-id`
defaulted to the TRANSFERMARKT season, so running the scraper with no arguments wrote 411 rows
under season_id 2026 while every reader filtered on 319. Three consecutive runs looked like
silent failures; the data was there under a key nothing queried.

A near-identical defect was fixed on 2026-09-07 (the DELETE cleared 319 while the INSERT wrote
2026). That fix corrected the collision and left this default wrong.
"""

from lofc.config import settings
from lofc.ingest.transfermarkt_loans import resolve_season_id


def test_it_defaults_to_our_live_season_not_transfermarkts():
    assert resolve_season_id(None, tm_season=2026, live_season_id=319) == 319


def test_an_explicit_season_id_still_wins():
    """The override exists for backfilling an older season."""
    assert resolve_season_id(318, tm_season=2026, live_season_id=319) == 318


def test_it_never_silently_returns_the_transfermarkt_season():
    """2026 is a Transfermarkt label; nothing in the platform reads it."""
    assert resolve_season_id(None, tm_season=2026, live_season_id=319) != 2026


def test_with_no_live_season_configured_it_refuses_rather_than_guessing():
    """Out of season, writing under a guessed key is how this bug happened."""
    try:
        resolve_season_id(None, tm_season=2026, live_season_id=None)
    except ValueError:
        return
    raise AssertionError("should refuse rather than fall back to the Transfermarkt season")


def test_the_real_config_resolves_to_the_live_season():
    assert resolve_season_id(None, tm_season=2026,
                             live_season_id=settings.live_season_id) == settings.live_season_id
