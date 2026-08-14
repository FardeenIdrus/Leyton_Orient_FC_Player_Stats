"""Tests for the SkillCorner platform config + matching. No network, no database."""

import pandas as pd
import pytest

from lofc.config import (DEFAULT_SKILLCORNER_TARGETS, Settings,
                         parse_skillcorner_targets)
from lofc.model.skillcorner_check import match_to_ours


def test_default_targets_map_covered_editions_to_our_leagues():
    tracked = [t for t in DEFAULT_SKILLCORNER_TARGETS if t.competition_id is not None]
    # The four EFL leagues plus Scottish Premiership (901) and Premier League 2 (903) carry
    # our competition/season keys, so their physical data joins onto those league players.
    assert {t.competition_id for t in tracked} == {3, 4, 5, 65, 901, 903}
    assert all(t.season_id in {318, 319} for t in tracked)   # 2025/26 + the live 2026/27
    # Editions with no league mapping (e.g. Irish Premier Division) are pulled but not joined.
    untracked = [t for t in DEFAULT_SKILLCORNER_TARGETS if t.competition_id is None]
    assert any("Irish" in t.label for t in untracked)


def test_live_season_covers_every_physically_tracked_league():
    """A league missing from the live season silently loses its Physical dimension."""
    live = [t for t in DEFAULT_SKILLCORNER_TARGETS if t.season_id == 319]
    assert {t.competition_id for t in live} == {3, 4, 5, 65, 901, 903}
    assert len(live) == 6


def test_scottish_championship_is_deliberately_not_a_skillcorner_target():
    """SkillCorner lists the competition but holds ZERO physical data for it (verified 0 rows
    for 2024/25 and 2025/26). Configuring it would emit a 'no data' warning on every weekly
    run forever, which would eventually mask a real failure."""
    assert all(t.competition_id != 902 for t in DEFAULT_SKILLCORNER_TARGETS)


def test_edition_ids_are_unique():
    ids = [t.edition_id for t in DEFAULT_SKILLCORNER_TARGETS]
    assert len(ids) == len(set(ids))


def test_parse_editions_keeps_known_mapping_and_rejects_bad():
    t = parse_skillcorner_targets("1211:League One 2025/26")[0]
    assert t.edition_id == 1211 and t.competition_id == 4 and t.season_id == 318
    assert parse_skillcorner_targets("9999:New League")[0].competition_id is None
    with pytest.raises(ValueError):
        parse_skillcorner_targets("1211")          # no label
    with pytest.raises(ValueError):
        parse_skillcorner_targets("x:League")      # non-integer id


def test_skillcorner_authenticated_needs_both(monkeypatch):
    for var in ("SKILLCORNER_USERNAME", "SKILLCORNER_PASSWORD", "SKILLCORNER_EDITIONS"):
        monkeypatch.delenv(var, raising=False)
    assert Settings(_env_file=None).skillcorner_authenticated is False
    assert Settings(_env_file=None, skillcorner_username="u",
                    skillcorner_password="p").skillcorner_authenticated is True


def _ours():
    return pd.DataFrame([
        {"player_id": 100, "player_name": "Dominic Ballard", "birth_date": "2005-04-01"},
        {"player_id": 200, "player_name": "Someone Else", "birth_date": "1999-09-09"},
    ])


def test_match_ties_by_birthdate_and_name():
    physical = pd.DataFrame([
        {"player_id": 1, "player_name": "Dom Ballard", "player_birthdate": "2005-04-01"},
        {"player_id": 2, "player_name": "Someone Else", "player_birthdate": "1999-09-09"},
    ])
    out = match_to_ours(physical, _ours())
    assert out.at[0, "player_id_ours"] == 100
    assert out.at[1, "player_id_ours"] == 200


def test_match_rejects_same_birthday_different_name():
    physical = pd.DataFrame([
        {"player_id": 3, "player_name": "Totally Different", "player_birthdate": "1999-09-09"},
    ])
    out = match_to_ours(physical, _ours())
    assert pd.isna(out.at[0, "player_id_ours"])


def test_match_rescues_day_month_swapped_birthdate():
    physical = pd.DataFrame([
        {"player_id": 9, "player_name": "Luke Harris", "player_birthdate": "2005-03-04"},
    ])
    ours = pd.DataFrame([{"player_id": 300, "player_name": "Luke Harris",
                          "birth_date": "2005-04-03"}])
    out = match_to_ours(physical, ours)
    assert out.at[0, "player_id_ours"] == 300
