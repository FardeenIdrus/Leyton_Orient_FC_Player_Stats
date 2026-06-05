"""Phase 0 smoke test: configuration loads and exposes the locked defaults."""

from lofc.config import DEFAULT_COMPETITIONS, Settings


def test_settings_load_with_defaults():
    settings = Settings()
    assert settings.database_url.startswith("postgresql")
    # Open-data mode is the default; no credentials required.
    assert settings.use_open_data is True
    assert settings.statsbomb_authenticated is False


def test_target_competitions_are_the_2015_16_trio():
    settings = Settings()
    ids = {(c.competition_id, c.season_id) for c in settings.competitions}
    assert ids == {(2, 27), (11, 27), (12, 27)}
    assert len(DEFAULT_COMPETITIONS) == 3
