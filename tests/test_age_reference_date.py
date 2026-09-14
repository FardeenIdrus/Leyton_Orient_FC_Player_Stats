"""A player's age in the LIVE season is his age today, not his age at a future date.

Age is measured at a fixed per-season reference date -- the season midpoint -- so a completed
season's age stays put: Leon Chambers-Parillon WAS 24.2 while producing his 2025/26 numbers,
and that does not change because time passes. Correct for a finished season.

For the season being PLAYED it was wrong. `SEASON_REF_DATE[319]` is 2027-01-01, so on
2026-09-14 every 2026/27 player read as up to a year older than he was: Chambers-Parillon
showed 25.2 against an actual 24.9, and Transfermarkt's 24. Age is a recruitment filter --
a 24-year-old reading as 25.2 crosses thresholds he has not reached.
"""

import datetime

import pandas as pd

from lofc.dashboard.seasons import age_reference_date

TODAY = datetime.date(2026, 9, 14)
LIVE = 319


def test_a_completed_season_uses_its_fixed_midpoint():
    """Frozen: the age he was while producing those numbers."""
    assert age_reference_date(318, live_season_id=LIVE, today=TODAY) == pd.Timestamp("2026-01-01")
    assert age_reference_date(317, live_season_id=LIVE, today=TODAY) == pd.Timestamp("2025-01-01")


def test_the_live_season_uses_today():
    """The season is happening now, so his age is a live fact -- and 2027-01-01 has not
    happened yet."""
    assert age_reference_date(LIVE, live_season_id=LIVE, today=TODAY) == pd.Timestamp(TODAY)


def test_the_live_season_reference_moves_with_the_date():
    later = datetime.date(2026, 12, 1)
    assert age_reference_date(LIVE, live_season_id=LIVE, today=later) == pd.Timestamp(later)


def test_out_of_season_falls_back_to_the_fixed_table():
    """LIVE_SEASON_ID unset (between seasons): every season held is complete."""
    assert age_reference_date(318, live_season_id=None, today=TODAY) == pd.Timestamp("2026-01-01")


def test_an_unknown_season_has_no_reference():
    assert age_reference_date(999, live_season_id=LIVE, today=TODAY) is None


def test_the_real_player_reads_his_real_age():
    """Chambers-Parillon, born 2001-11-05, on 2026-09-14: 24.9, not 25.2."""
    ref = age_reference_date(LIVE, live_season_id=LIVE, today=TODAY)
    age = round((ref - pd.Timestamp("2001-11-05")).days / 365.25, 1)
    assert age == 24.9
