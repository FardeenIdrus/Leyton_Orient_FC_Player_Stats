"""The availability rule -- the objective input to the club's Medical dimension."""

import pandas as pd
import pytest

from lofc.model.medical import (
    MINUTES_CONFIRM_AVAILABILITY_PER_SEASON,
    AvailabilityEvidence,
    AvailabilityStatus,
    availability,
    availability_with_evidence,
    games_missed_in_window,
    window_labels,
)

CHAMPIONSHIP = 3
SCOTTISH_PREM = 901


def test_a_player_who_missed_nothing_is_fully_available():
    assert availability(0, CHAMPIONSHIP) == 1.0


def test_the_club_minimum_bar():
    # 60% availability is the club's stated minimum: 40% of 92 games = 36.8 missed.
    assert availability(37, CHAMPIONSHIP) == pytest.approx(0.5978, abs=0.001)


def test_availability_is_clamped_at_zero():
    # More games missed than the window holds (long-term injury spanning seasons).
    assert availability(200, CHAMPIONSHIP) == 0.0


def test_half_the_window_missed():
    assert availability(46, CHAMPIONSHIP) == 0.5


def test_league_without_a_scheduled_games_constant_returns_none():
    # Scottish/PL2 have no Transfermarkt coverage; the criterion is unscored, not
    # defaulted -- a guessed availability would be worse than an honest gap.
    assert availability(5, SCOTTISH_PREM) is None


def test_window_labels_covers_the_season_and_the_one_before():
    assert window_labels(318) == ("24/25", "25/26")
    assert window_labels(319) == ("25/26", "26/27")


def test_window_labels_raises_for_an_unmapped_season_id():
    # 320 (2027/28) has not been added to _SEASON_LABELS yet -- silently dropping it
    # would zero out the injury count and read the player as 100% available.
    with pytest.raises(ValueError, match="320"):
        window_labels(320)


def test_window_labels_raises_for_a_fully_unmapped_season_id():
    # 316 predates the mapping entirely, so the window would otherwise be empty --
    # the most dangerous case, since an empty window silently matches no injuries.
    with pytest.raises(ValueError):
        window_labels(316)


def test_games_missed_only_counts_the_window():
    injuries = pd.DataFrame({
        "season_label": ["23/24", "24/25", "25/26"],
        "date_from": ["2023-09-01", "2024-09-01", "2025-09-01"],
        "date_until": ["2023-09-10", "2024-09-10", "2025-09-10"],
        "games_missed": [99, 4, 6],
    })
    # 23/24 is outside a two-season window ending at 2025/26, so its 99 is ignored.
    assert games_missed_in_window(injuries, 318) == 10


def test_games_missed_with_no_injuries():
    empty = pd.DataFrame(columns=["season_label", "date_from", "date_until", "games_missed"])
    assert games_missed_in_window(empty, 318) == 0


def test_games_missed_treats_nan_as_zero():
    injuries = pd.DataFrame({
        "season_label": ["24/25", "25/26"],
        "date_from": ["2024-09-01", "2025-09-01"],
        "date_until": ["2024-09-10", "2025-09-10"],
        "games_missed": [float("nan"), 6],
    })
    assert games_missed_in_window(injuries, 318) == 6


def test_games_missed_with_no_injuries_still_validates_the_season():
    # An empty frame must not bypass validation: whether an unmapped season id
    # raises has to be deterministic, not dependent on whether this particular
    # player happens to have any injury rows.
    empty = pd.DataFrame(columns=["season_label", "games_missed"])
    with pytest.raises(ValueError):
        games_missed_in_window(empty, 320)


def test_games_missed_with_no_injuries_and_a_mapped_season_still_returns_zero():
    # The mapped-season behaviour must be unchanged by the validation reordering.
    empty = pd.DataFrame(columns=["season_label", "games_missed"])
    assert games_missed_in_window(empty, 318) == 0


# --- R9: overlapping injury spells must be merged, not summed --------------


def test_wyke_case_identical_concurrent_diagnoses_counted_once():
    # Real case: Charlie Wyke (tm_player_id 163535) has "Ankle injury" and
    # "Broken leg" both logged 2024-10-26 -> 2026-01-30, 64 matches each. That
    # is one absence recorded twice; summing reads 128 against an actual 64.
    injuries = pd.DataFrame({
        "season_label": ["24/25", "24/25"],
        "injury_type_raw": ["Ankle injury", "Broken leg"],
        "date_from": ["2024-10-26", "2024-10-26"],
        "date_until": ["2026-01-30", "2026-01-30"],
        "games_missed": [64, 64],
    })
    assert games_missed_in_window(injuries, 318) == 64


def test_partial_overlap_is_merged_and_takes_the_max():
    # Spell A: Jan-Mar, 10 matches. Spell B: Feb-Apr, 8 matches. They overlap
    # (not identical), so the merged group's total is the MAX, not the sum --
    # this slightly understates a genuine partial overlap, which is the
    # correct direction to err (see games_missed_in_window's docstring).
    injuries = pd.DataFrame({
        "season_label": ["24/25", "24/25"],
        "date_from": ["2025-01-01", "2025-02-01"],
        "date_until": ["2025-03-01", "2025-04-01"],
        "games_missed": [10, 8],
    })
    assert games_missed_in_window(injuries, 318) == 10


def test_adjacent_non_overlapping_spells_are_both_counted():
    # Spell A ends 2025-01-10; spell B starts 2025-01-12 -- a genuine gap, not
    # an overlap or a shared boundary, so both spells are real absences and
    # must be summed, not merged.
    injuries = pd.DataFrame({
        "season_label": ["24/25", "24/25"],
        "date_from": ["2025-01-01", "2025-01-12"],
        "date_until": ["2025-01-10", "2025-01-20"],
        "games_missed": [5, 3],
    })
    assert games_missed_in_window(injuries, 318) == 8


def test_touching_spells_are_merged():
    # Spell A ends exactly on the day spell B starts -- touching counts as an
    # overlap for merge purposes.
    injuries = pd.DataFrame({
        "season_label": ["24/25", "24/25"],
        "date_from": ["2025-01-01", "2025-01-10"],
        "date_until": ["2025-01-10", "2025-01-20"],
        "games_missed": [5, 3],
    })
    assert games_missed_in_window(injuries, 318) == 5


def test_ongoing_injury_with_null_date_until_does_not_crash():
    # A NULL date_until means the injury is still ongoing. It must not crash
    # and must be treated as extending to the end of the window, not dropped.
    # The ongoing spell sorts LAST here, so this alone does not prove the
    # sentinel actually extends anything -- see the "sorted first" case below
    # for that.
    injuries = pd.DataFrame({
        "season_label": ["25/26", "24/25"],
        "date_from": ["2025-06-01", "2024-11-01"],
        "date_until": [None, "2024-11-15"],
        "games_missed": [10, 3],
    })
    # The two spells don't overlap (Nov 2024 vs June 2025 onward), so both
    # count: 10 + 3 = 13.
    assert games_missed_in_window(injuries, 318) == 13


def test_ongoing_injury_sorted_first_absorbs_a_later_overlapping_spell():
    # The ongoing spell (NULL date_until, from 2024-11-01) sorts FIRST here.
    # It must actually extend forward and absorb the second spell, which
    # starts well within its indefinite span -- proving the sentinel
    # propagates rather than sitting unused. A mutant that does no extension
    # at all (or extends only to date_from) would sum instead of merge here:
    # 10 + 20 = 30, not the correct max(10, 20) = 20.
    injuries = pd.DataFrame({
        "season_label": ["24/25", "25/26"],
        "date_from": ["2024-11-01", "2025-06-01"],
        "date_until": [None, "2025-06-15"],
        "games_missed": [10, 20],
    })
    assert games_missed_in_window(injuries, 318) == 20


def test_merge_takes_the_max_not_the_first_spell():
    # Regression: a merge that kept the FIRST spell's games_missed (instead
    # of the max across the group) would pass every other merge test in this
    # file, since in all of them the larger value happens to belong to the
    # earliest-sorted spell. Here the later spell (starting 2025-01-15) has
    # the larger games_missed, to catch that specifically.
    injuries = pd.DataFrame({
        "season_label": ["24/25", "24/25"],
        "date_from": ["2025-01-01", "2025-01-15"],
        "date_until": ["2025-03-01", "2025-04-01"],
        "games_missed": [3, 12],
    })
    assert games_missed_in_window(injuries, 318) == 12


def test_a_single_spell_is_unchanged():
    injuries = pd.DataFrame({
        "season_label": ["25/26"],
        "date_from": ["2025-09-01"],
        "date_until": ["2025-10-01"],
        "games_missed": [4],
    })
    assert games_missed_in_window(injuries, 318) == 4


# --- R8: "never injured" and "never checked" must be distinguishable -------


def test_has_records_is_measured_and_matches_availability():
    injuries = pd.DataFrame({
        "season_label": ["25/26"],
        "date_from": ["2025-09-01"],
        "date_until": ["2025-10-01"],
        "games_missed": [4],
    })
    result = availability_with_evidence(injuries, 4, CHAMPIONSHIP, minutes_played=1000)
    # Literal expected value (46 scheduled games * 2 seasons = 92), not a call
    # into availability() itself -- asserting against the function under test
    # would still pass if that function were broken.
    assert result == AvailabilityEvidence(AvailabilityStatus.MEASURED, pytest.approx(1 - 4 / 92))


def test_no_records_but_minutes_clear_the_bar_confirms_availability():
    # seasons=1: the caller here only holds one season of minutes, so the bar
    # is not doubled against data that only covers a single season.
    empty = pd.DataFrame(columns=["season_label", "date_from", "date_until", "games_missed"])
    result = availability_with_evidence(
        empty, 0, CHAMPIONSHIP, minutes_played=MINUTES_CONFIRM_AVAILABILITY_PER_SEASON, seasons=1
    )
    assert result == AvailabilityEvidence(AvailabilityStatus.CONFIRMED_BY_MINUTES, 1.0)


def test_no_records_and_minutes_below_the_bar_is_unknown():
    empty = pd.DataFrame(columns=["season_label", "date_from", "date_until", "games_missed"])
    result = availability_with_evidence(
        empty, 0, CHAMPIONSHIP, minutes_played=MINUTES_CONFIRM_AVAILABILITY_PER_SEASON - 1, seasons=1
    )
    assert result == AvailabilityEvidence(AvailabilityStatus.UNKNOWN, None)


def test_minutes_threshold_scales_with_the_number_of_seasons():
    # Default seasons=2 doubles the bar: one season's worth of minutes must
    # not be enough to confirm a two-season window.
    empty = pd.DataFrame(columns=["season_label", "date_from", "date_until", "games_missed"])
    result = availability_with_evidence(
        empty, 0, CHAMPIONSHIP, minutes_played=MINUTES_CONFIRM_AVAILABILITY_PER_SEASON
    )
    assert result == AvailabilityEvidence(AvailabilityStatus.UNKNOWN, None)


def test_no_records_and_no_minutes_data_is_unknown_not_assumed_clean():
    # A blank record with no minutes to check against must never render as a
    # clean record -- this is the core of R8.
    empty = pd.DataFrame(columns=["season_label", "date_from", "date_until", "games_missed"])
    result = availability_with_evidence(empty, 0, CHAMPIONSHIP, minutes_played=None)
    assert result == AvailabilityEvidence(AvailabilityStatus.UNKNOWN, None)


def test_measured_value_is_unaffected_by_minutes_seasons():
    # Regression: seasons sets the availability denominator; minutes_seasons
    # (independent) sets the minutes bar. A MEASURED player's value must not
    # change depending on how many seasons of minutes the caller happened to
    # hold -- previously the module told callers to pass seasons=1 for a
    # single-season minutes figure, which silently halved the denominator
    # (46 * 2 = 92 -> 46) for every MEASURED player sharing that call: 30
    # games missed read as 0.674 with seasons=2 but 0.348 with seasons=1.
    injuries = pd.DataFrame({
        "season_label": ["25/26"],
        "date_from": ["2025-09-01"],
        "date_until": ["2025-10-01"],
        "games_missed": [30],
    })
    expected = AvailabilityEvidence(AvailabilityStatus.MEASURED, pytest.approx(1 - 30 / 92))
    result_minutes_seasons_1 = availability_with_evidence(
        injuries, 30, CHAMPIONSHIP, minutes_played=1000, seasons=2, minutes_seasons=1
    )
    result_minutes_seasons_2 = availability_with_evidence(
        injuries, 30, CHAMPIONSHIP, minutes_played=1000, seasons=2, minutes_seasons=2
    )
    assert result_minutes_seasons_1 == expected
    assert result_minutes_seasons_2 == expected


def test_minutes_seasons_defaults_to_seasons_when_not_given():
    empty = pd.DataFrame(columns=["season_label", "date_from", "date_until", "games_missed"])
    # seasons=1 and no minutes_seasons override -> bar is 1 * 2000 = 2000.
    result = availability_with_evidence(
        empty, 0, CHAMPIONSHIP, minutes_played=MINUTES_CONFIRM_AVAILABILITY_PER_SEASON, seasons=1
    )
    assert result == AvailabilityEvidence(AvailabilityStatus.CONFIRMED_BY_MINUTES, 1.0)


def test_minutes_seasons_overrides_seasons_for_the_bar_only():
    # seasons=2 (so the bar would default to 4000) but minutes_seasons=1
    # explicitly -> bar is 2000, and a single season of minutes confirms.
    empty = pd.DataFrame(columns=["season_label", "date_from", "date_until", "games_missed"])
    result = availability_with_evidence(
        empty, 0, CHAMPIONSHIP,
        minutes_played=MINUTES_CONFIRM_AVAILABILITY_PER_SEASON,
        seasons=2, minutes_seasons=1,
    )
    assert result == AvailabilityEvidence(AvailabilityStatus.CONFIRMED_BY_MINUTES, 1.0)


def test_pd_na_minutes_played_does_not_raise():
    # pd.NA passes an `is not None` check but raises on boolean evaluation --
    # must use pd.isna() so a pandas-native missing value behaves the same as
    # a plain None.
    empty = pd.DataFrame(columns=["season_label", "date_from", "date_until", "games_missed"])
    result = availability_with_evidence(empty, 0, CHAMPIONSHIP, minutes_played=pd.NA)
    assert result == AvailabilityEvidence(AvailabilityStatus.UNKNOWN, None)


def test_competition_without_scheduled_games_is_still_none_when_measured():
    injuries = pd.DataFrame({
        "season_label": ["25/26"],
        "date_from": ["2025-09-01"],
        "date_until": ["2025-10-01"],
        "games_missed": [4],
    })
    result = availability_with_evidence(injuries, 4, SCOTTISH_PREM, minutes_played=1000)
    assert result == AvailabilityEvidence(AvailabilityStatus.MEASURED, None)
