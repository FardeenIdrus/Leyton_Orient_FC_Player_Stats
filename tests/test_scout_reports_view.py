"""The Scout reports page: filters, the model-vs-scout comparison, and freshness.

WHAT THIS PAGE IS FOR. The platform ranks 3,229 players it has never seen anyone watch;
the scouts have written 437 reports on 350 players. Neither list is useful to the other
at those sizes -- but the OVERLAP is 289 reports on 244 players, and that is a list a
Head of Recruitment can read in an afternoon.

The single most valuable thing on the page is where the two DISAGREE. Measured on the
live data: of the 54 reports saying "Sign", 22 are on players the platform can score --
6 the model also rates highly, and 10 it rates below 3.0. Those ten are the conversation.
Agreement is reassuring and carries almost no information; disagreement is where a
recruiter's judgement is actually needed.

TWO HONESTIES THE COMPARISON MUST KEEP:

  A missing rating is NOT a low rating. 129 reports are on players outside the seven
  leagues the platform holds data for -- non-league and academy players scouts are sent
  to watch deliberately. Scoring them as 0, or hiding them, would both be lies.

  The comparison is ACROSS SEASONS. The composite is 2025/26; the fixtures are 2026/27.
  The label says so, because a number presented without that is a different claim from
  the one the data supports.
"""

import datetime as dt

import pandas as pd

from lofc.dashboard.tabs.scout_reports import (
    MODEL_VIEW,
    filter_reports,
    model_view,
    scout_activity,
    sync_status,
)

REPORTS = pd.DataFrame([
    {"player_name": "Alfie Gilchrist", "club_name": "West Brom U21", "scout": "Steve Foster",
     "verdict": "Sign", "grade": "B", "observation": "Live", "composite": 1.74,
     "positions_played": ["RCB"], "fixture_date": dt.date(2026, 7, 28)},
    {"player_name": "Jayden Wareham", "club_name": "Woking", "scout": "Joe Austin",
     "verdict": "Sign", "grade": "B", "observation": "Live", "composite": 3.80,
     "positions_played": ["CF"], "fixture_date": dt.date(2026, 8, 2)},
    {"player_name": "Alain Kizenga", "club_name": "Bray Wanderers", "scout": "Gareth Mycock",
     "verdict": "Sign", "grade": "B", "observation": "Live", "composite": None,
     "positions_played": ["RB", "RWB"], "fixture_date": dt.date(2026, 8, 13)},
    {"player_name": "Will Wright", "club_name": "Harrogate", "scout": "Gary Finley",
     "verdict": "Don't sign", "grade": "C", "observation": "Video", "composite": 4.10,
     "positions_played": ["CM"], "fixture_date": dt.date(2026, 9, 1)},
    {"player_name": "Sam Proctor", "club_name": "Carlisle", "scout": "Joe Austin",
     "verdict": "Monitor", "grade": "B", "observation": "Video", "composite": 3.05,
     "positions_played": ["LW"], "fixture_date": dt.date(2026, 9, 12)},
])


def _names(frame):
    return list(frame["player_name"])


# --- filters ------------------------------------------------------------------------------

def test_no_filters_returns_everything():
    assert len(filter_reports(REPORTS)) == 5


def test_filtering_by_scout():
    assert _names(filter_reports(REPORTS, scout="Joe Austin")) == [
        "Jayden Wareham", "Sam Proctor"]


def test_filtering_by_verdict():
    assert len(filter_reports(REPORTS, verdict="Sign")) == 3


def test_filtering_by_grade():
    assert _names(filter_reports(REPORTS, grade="C")) == ["Will Wright"]


def test_filtering_by_club():
    assert _names(filter_reports(REPORTS, club="Bray Wanderers")) == ["Alain Kizenga"]


def test_filtering_by_observation_type():
    assert len(filter_reports(REPORTS, observation="Video")) == 2


def test_filtering_by_position_matches_any_of_a_multi_value_report():
    """43 reports carry more than one position. A right back who also played wing back
    must appear under BOTH, or a search for wing backs misses him."""
    assert _names(filter_reports(REPORTS, position="RWB")) == ["Alain Kizenga"]
    assert _names(filter_reports(REPORTS, position="RB")) == ["Alain Kizenga"]


def test_filters_compose():
    out = filter_reports(REPORTS, scout="Joe Austin", verdict="Sign")
    assert _names(out) == ["Jayden Wareham"]


def test_a_filter_matching_nothing_returns_an_empty_frame_not_an_error():
    assert filter_reports(REPORTS, scout="Nobody").empty


def test_the_caller_frame_is_not_mutated():
    filter_reports(REPORTS, scout="Joe Austin")
    assert len(REPORTS) == 5


def test_an_empty_frame_is_handled():
    assert filter_reports(pd.DataFrame(columns=REPORTS.columns), verdict="Sign").empty


# --- the model comparison ------------------------------------------------------------------

def test_a_sign_the_model_rates_low_is_flagged_as_the_disagreement():
    """THE POINT OF THE PAGE. A scout watched him and said sign; the model puts him below
    the 3.03 average for his league and position."""
    out = model_view(REPORTS)
    assert out.loc[out.player_name == "Alfie Gilchrist", MODEL_VIEW].iloc[0] == \
        "Model disagrees"


def test_a_sign_the_model_also_rates_highly_reads_as_agreement():
    out = model_view(REPORTS)
    assert out.loc[out.player_name == "Jayden Wareham", MODEL_VIEW].iloc[0] == "Model agrees"


def test_a_dont_sign_the_model_rates_highly_is_also_a_disagreement():
    """Disagreement runs both ways. A player the model likes and a scout rejected is
    just as worth discussing as the reverse."""
    out = model_view(REPORTS)
    assert out.loc[out.player_name == "Will Wright", MODEL_VIEW].iloc[0] == "Model disagrees"


def test_a_player_with_no_rating_says_so_and_is_not_scored_as_zero():
    """129 reports are on players outside our leagues. "No rating" is the fact; 0 would
    be a claim, and hiding him would erase the scouting the club actually paid for."""
    out = model_view(REPORTS)
    assert out.loc[out.player_name == "Alain Kizenga", MODEL_VIEW].iloc[0] == "Not in our data"


def test_a_monitor_verdict_is_not_forced_into_agreement_or_disagreement():
    """"Monitor" is the scout declining to commit. Grading it against the model would
    invent a position he did not take."""
    out = model_view(REPORTS)
    assert out.loc[out.player_name == "Sam Proctor", MODEL_VIEW].iloc[0] == "No verdict to compare"


def test_the_row_count_is_unchanged():
    assert len(model_view(REPORTS)) == len(REPORTS)


def test_the_caller_frame_is_not_mutated_by_the_comparison():
    model_view(REPORTS)
    assert MODEL_VIEW not in REPORTS.columns


def test_an_empty_frame_still_gains_the_column():
    """The page selects this column by name; a missing one is a KeyError in the app."""
    out = model_view(pd.DataFrame(columns=REPORTS.columns))
    assert MODEL_VIEW in out.columns


# --- per-scout activity ----------------------------------------------------------------

def test_activity_counts_reports_per_scout():
    out = scout_activity(REPORTS).set_index("Scout")
    assert out.loc["Joe Austin", "Reports"] == 2
    assert out.loc["Steve Foster", "Reports"] == 1


def test_activity_splits_live_from_video():
    """Live viewing costs a trip and a ticket; video does not. The split is a real
    management fact, and the sheet's own "Teams Watched" tab tracks it."""
    out = scout_activity(REPORTS).set_index("Scout")
    assert out.loc["Joe Austin", "Live"] == 1
    assert out.loc["Joe Austin", "Video"] == 1


def test_activity_counts_sign_recommendations():
    out = scout_activity(REPORTS).set_index("Scout")
    assert out.loc["Joe Austin", "Sign"] == 1
    assert out.loc["Gary Finley", "Sign"] == 0


def test_activity_is_ordered_by_volume():
    """Who is doing the most viewing reads first."""
    assert scout_activity(REPORTS)["Scout"].iloc[0] == "Joe Austin"


def test_activity_on_an_empty_frame_is_empty_not_an_error():
    assert scout_activity(pd.DataFrame(columns=REPORTS.columns)).empty


# --- freshness ----------------------------------------------------------------------------

NOW = dt.datetime(2026, 9, 28, 14, 0, 0)


def test_a_sync_seconds_ago_reads_as_just_now():
    assert "just now" in sync_status(NOW - dt.timedelta(seconds=20), NOW).lower()


def test_a_sync_minutes_ago_says_how_many():
    assert "4 minutes ago" in sync_status(NOW - dt.timedelta(minutes=4), NOW)


def test_a_sync_hours_ago_says_how_many():
    assert "3 hours ago" in sync_status(NOW - dt.timedelta(hours=3), NOW)


def test_a_stale_sync_is_called_out_not_merely_reported():
    """Register P14: a failed job serves yesterday's data looking completely normal.
    The platform has been caught by exactly this once already, so an old sync must READ
    as a problem rather than as a timestamp the reader is expected to evaluate."""
    label = sync_status(NOW - dt.timedelta(hours=9), NOW)
    assert "9 hours ago" in label
    assert "not updating" in label.lower() or "stale" in label.lower()


def test_never_synced_says_so_plainly():
    assert "never" in sync_status(None, NOW).lower()
