"""Configuration tests: defaults, env-driven competition targets, parsing.

Settings() reads the process environment and .env, which in the running
container hold real credentials and real targets. Tests that assert defaults
clear those variables first, so they pass identically on a dev laptop, in the
container, and in CI.
"""

import pytest

from lofc.config import DEFAULT_COMPETITIONS, Settings, parse_competitions

SETTINGS_ENV_VARS = [
    "USE_OPEN_DATA",
    "SB_USERNAME",
    "SB_PASSWORD",
    "SB_COMPETITIONS",
    "DATABASE_URL",
]


@pytest.fixture
def clean_env(monkeypatch):
    """Strip every Settings-related variable from the environment."""
    for var in SETTINGS_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    return monkeypatch


def test_settings_load_with_defaults(clean_env):
    settings = Settings(_env_file=None)
    assert settings.database_url.startswith("postgresql")
    # Open-data mode is the default; no credentials required.
    assert settings.use_open_data is True
    assert settings.statsbomb_authenticated is False


def test_target_competitions_default_to_the_2015_16_trio(clean_env):
    settings = Settings(_env_file=None)
    ids = {(c.competition_id, c.season_id) for c in settings.competitions}
    assert ids == {(2, 27), (11, 27), (12, 27)}
    assert len(DEFAULT_COMPETITIONS) == 3


def test_sb_competitions_env_overrides_the_default_targets(clean_env):
    clean_env.setenv(
        "SB_COMPETITIONS",
        "4:318:League One 2025/26,5:317:League Two 2024/25",
    )
    settings = Settings(_env_file=None)
    comps = settings.competitions
    assert [(c.competition_id, c.season_id) for c in comps] == [(4, 318), (5, 317)]
    assert comps[0].label == "League One 2025/26"


def test_parse_competitions_valid_string():
    comps = parse_competitions(" 4:318:League One 2025/26 , 3:317:Championship 2024/25 ")
    assert len(comps) == 2
    assert comps[0].competition_id == 4
    assert comps[0].season_id == 318
    assert comps[0].label == "League One 2025/26"
    assert comps[1].label == "Championship 2024/25"


@pytest.mark.parametrize(
    "raw",
    [
        "4:318",  # missing label
        "4:318:",  # empty label
        "x:318:League One",  # non-integer competition_id
        "4:y:League One",  # non-integer season_id
        "",  # nothing at all
        " , ",  # only separators
    ],
)
def test_parse_competitions_rejects_malformed_input(raw):
    with pytest.raises(ValueError):
        parse_competitions(raw)
