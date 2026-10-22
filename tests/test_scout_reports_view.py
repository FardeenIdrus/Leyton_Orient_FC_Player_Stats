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
import pytest

from lofc.dashboard.tabs.scout_reports import (
    MODEL_VIEW,
    data_vs_scout_group,
    disagrees,
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


def test_searching_matches_part_of_a_name():
    """A recruiter should not have to reproduce "Ra'ess Bangura-Williams" -- including the
    typo the live sheet actually carries -- to find him."""
    assert _names(filter_reports(REPORTS, search="gilchrist")) == ["Alfie Gilchrist"]


def test_the_search_is_case_insensitive():
    assert len(filter_reports(REPORTS, search="ALFIE")) == 1


def test_the_search_treats_its_input_as_text_not_a_pattern():
    """A stray bracket or asterisk in a name search must not raise a regex error."""
    assert filter_reports(REPORTS, search="Gilchrist (").empty


def test_an_empty_search_does_not_filter():
    assert len(filter_reports(REPORTS, search="")) == 5


def test_filtering_to_players_we_hold_data_for():
    """"Only the ones I can compare to the model"."""
    out = filter_reports(REPORTS.assign(player_id=[1, 2, None, 4, 5]),
                         in_our_data="In our data")
    assert "Alain Kizenga" not in _names(out)
    assert len(out) == 4


def test_filtering_to_players_we_do_not_hold():
    """The discovery list: 129 reports on players the model has never seen."""
    out = filter_reports(REPORTS.assign(player_id=[1, 2, None, 4, 5]),
                         in_our_data="Not in our data")
    assert _names(out) == ["Alain Kizenga"]


def test_the_caller_frame_is_not_mutated():
    filter_reports(REPORTS, scout="Joe Austin")
    assert len(REPORTS) == 5


def test_an_empty_frame_is_handled():
    assert filter_reports(pd.DataFrame(columns=REPORTS.columns), verdict="Sign").empty


# --- the model comparison ------------------------------------------------------------------

def test_a_sign_the_model_rates_low_is_flagged_as_the_disagreement():
    """THE POINT OF THE PAGE. A scout watched him and said sign; the model puts him below
    the 3.00 average for his league and position."""
    out = model_view(REPORTS)
    assert out.loc[out.player_name == "Alfie Gilchrist", MODEL_VIEW].iloc[0] == \
        "Data disagrees — rated under 3.0 (25/26)"


def test_a_sign_the_model_also_rates_highly_reads_as_agreement():
    out = model_view(REPORTS)
    assert out.loc[out.player_name == "Jayden Wareham", MODEL_VIEW].iloc[0] == \
        "Data agrees — rated 3.5+ (25/26)"


def test_a_dont_sign_the_model_rates_highly_is_also_a_disagreement():
    """Disagreement runs both ways. A player the model likes and a scout rejected is
    just as worth discussing as the reverse."""
    out = model_view(REPORTS)
    assert out.loc[out.player_name == "Will Wright", MODEL_VIEW].iloc[0] == \
        "Data disagrees — rated 3.5+ (25/26)"


def test_a_player_with_no_rating_says_so_and_is_not_scored_as_zero():
    """129 reports are on players outside our leagues. "No rating" is the fact; 0 would
    be a claim, and hiding him would erase the scouting the club actually paid for."""
    out = model_view(REPORTS)
    assert out.loc[out.player_name == "Alain Kizenga", MODEL_VIEW].iloc[0] == "Not in our data"


def _unrated(**flags):
    """One Sign report with no composite; `flags` say what we hold for him."""
    row = {"player_name": "X", "verdict": "Sign", "composite": None}
    return pd.DataFrame([{**row, **flags}])


def test_a_player_we_hold_but_under_450_minutes_is_not_called_missing():
    """The "Our data" filter tests the LINK; the label used to test the RATING, so a
    linked player under 450 minutes passed "In our data" and read "Not in our data"
    (owner, 2026-10-16: 91 reports on 75 players)."""
    out = model_view(_unrated(player_id=7, in_rating_season=True, in_live_season=True),
                     season="25/26")
    assert out[MODEL_VIEW].iloc[0] == "Under 450 mins (25/26)"


def test_a_player_we_hold_only_this_season_is_new_this_season():
    out = model_view(_unrated(player_id=7, in_rating_season=False, in_live_season=True),
                     season="25/26")
    assert out[MODEL_VIEW].iloc[0] == "New this season"


def test_a_linked_player_with_no_minutes_in_either_season_is_not_rated():
    out = model_view(_unrated(player_id=7, in_rating_season=False, in_live_season=False),
                     season="25/26")
    assert out[MODEL_VIEW].iloc[0] == "Not rated"


def test_an_unlinked_player_is_still_not_in_our_data():
    out = model_view(_unrated(player_id=None, in_rating_season=False, in_live_season=False),
                     season="25/26")
    assert out[MODEL_VIEW].iloc[0] == "Not in our data"


def test_the_label_never_contradicts_the_our_data_filter():
    """Every row "In our data" keeps must carry a label other than "Not in our data", and
    every row "Not in our data" keeps must carry exactly that label."""
    frame = pd.DataFrame([
        {"player_name": "A", "verdict": "Sign", "composite": None, "player_id": 1,
         "in_rating_season": True, "in_live_season": True},
        {"player_name": "B", "verdict": "Sign", "composite": None, "player_id": 2,
         "in_rating_season": False, "in_live_season": True},
        {"player_name": "C", "verdict": "Sign", "composite": None, "player_id": None,
         "in_rating_season": False, "in_live_season": False},
        {"player_name": "D", "verdict": "Sign", "composite": 3.9, "player_id": 4,
         "in_rating_season": True, "in_live_season": True},
    ])
    out = model_view(frame, season="25/26")
    held = filter_reports(out, in_our_data="In our data")
    missing = filter_reports(out, in_our_data="Not in our data")
    assert (held[MODEL_VIEW] != "Not in our data").all()
    assert (missing[MODEL_VIEW] == "Not in our data").all()


# --- two ratings: this season's where it exists, else last season's (owner, 2026-10-16) ---

def _rated(last, this):
    return pd.DataFrame([{"player_name": "X", "verdict": "Sign", "player_id": 1,
                          "composite": last, "composite_live": this,
                          "in_rating_season": True, "in_live_season": True}])


def test_this_seasons_rating_is_used_where_it_exists_and_the_label_says_so():
    out = model_view(_rated(3.8, 2.7), season="25/26", live_season="26/27")
    assert out[MODEL_VIEW].iloc[0] == "Data disagrees — rated under 3.0 (26/27)"


def test_last_seasons_rating_is_the_fallback_and_the_label_says_so():
    out = model_view(_rated(3.8, None), season="25/26", live_season="26/27")
    assert out[MODEL_VIEW].iloc[0] == "Data agrees — rated 3.5+ (25/26)"


def test_a_player_rated_only_this_season_is_compared_on_it():
    out = model_view(_rated(None, 3.9), season="25/26", live_season="26/27")
    assert out[MODEL_VIEW].iloc[0] == "Data agrees — rated 3.5+ (26/27)"


def test_the_rating_used_is_kept_for_sorting():
    out = model_view(_rated(3.8, 2.7), season="25/26", live_season="26/27")
    assert out["rating_used"].iloc[0] == 2.7


def test_disagreement_is_counted_whichever_season_it_came_from():
    labels = pd.Series(["Data disagrees — rated under 3.0 (26/27)",
                        "Data disagrees — rated 3.5+ (25/26)",
                        "Data agrees — rated 3.5+ (26/27)", "Not in our data"])
    assert disagrees(labels).tolist() == [True, True, False, False]


# --- explicit labels and the "Data vs scout" filter (owner, 2026-10-22) -------------------
#
# "Model is lukewarm" was vague and "Model agrees" did not say what the data rated him. Each
# label now names WHO (the data), WHAT (agrees / disagrees) and the RATING BAND it rests on.

def _one(verdict, rating):
    return pd.DataFrame([{"player_name": "X", "verdict": verdict, "player_id": 1,
                          "composite": rating, "in_rating_season": True,
                          "in_live_season": True}])


@pytest.mark.parametrize("verdict,rating,label", [
    ("Sign", 3.80, "Data agrees — rated 3.5+ (25/26)"),
    ("Sign", 3.50, "Data agrees — rated 3.5+ (25/26)"),           # boundary: 3.5 is 3.5+
    ("Sign", 3.49, "Average rating — 3.0 to 3.5 (25/26)"),
    ("Sign", 3.00, "Average rating — 3.0 to 3.5 (25/26)"),        # boundary: 3.0 is average
    ("Sign", 2.99, "Data disagrees — rated under 3.0 (25/26)"),
    ("Don't sign", 2.40, "Data agrees — rated under 3.0 (25/26)"),
    ("Don't sign", 3.20, "Average rating — 3.0 to 3.5 (25/26)"),
    ("Don't sign", 3.90, "Data disagrees — rated 3.5+ (25/26)"),
])
def test_each_label_names_the_data_the_direction_and_the_band(verdict, rating, label):
    assert model_view(_one(verdict, rating), season="25/26")[MODEL_VIEW].iloc[0] == label


def test_the_column_is_called_data_vs_scout():
    assert MODEL_VIEW == "Data vs scout"


@pytest.mark.parametrize("label,group", [
    ("Data agrees — rated 3.5+ (26/27)", "Data agrees"),
    ("Data agrees — rated under 3.0 (25/26)", "Data agrees"),
    ("Data disagrees — rated under 3.0 (26/27)", "Data disagrees"),
    ("Average rating — 3.0 to 3.5 (25/26)", "Average rating"),
    ("No verdict to compare", "No verdict to compare"),
    ("Under 450 mins (25/26)", "No rating"),
    ("New this season", "No rating"),
    ("Not rated", "No rating"),
    ("Not in our data", "No rating"),
])
def test_every_label_falls_in_exactly_one_filter_group(label, group):
    assert data_vs_scout_group(label) == group


def test_the_filter_keeps_only_the_chosen_group():
    frame = model_view(pd.concat([_one("Sign", 3.9), _one("Sign", 2.1), _one("Sign", 3.2),
                                  _one("Monitor", 3.9)], ignore_index=True), season="25/26")
    assert filter_reports(frame, data_vs_scout="Data disagrees")[MODEL_VIEW].tolist() == \
        ["Data disagrees — rated under 3.0 (25/26)"]
    assert len(filter_reports(frame, data_vs_scout="All")) == 4
    assert len(filter_reports(frame, data_vs_scout="Data agrees")) == 1
    assert len(filter_reports(frame, data_vs_scout="Average rating")) == 1


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


def test_the_refresh_button_actually_reads_the_sheet():
    """The first version only cleared Streamlit's cached reads. The page reloaded the same
    stored rows, the "Synced" line never moved, and the button appeared to do nothing --
    because it did nothing. It must call the sync stage, which is the same code path the
    60-second cron uses, so the two cannot drift.
    """
    import inspect

    from lofc.dashboard.tabs import scout_reports
    source = inspect.getsource(scout_reports.render)
    assert "sync_sheet(" in source, (
        "the Refresh button does not call the sync stage — it only clears caches, so the "
        "page would reload the same stored rows")


def test_the_refresh_button_handles_a_failed_read():
    """Google can be unreachable, the credential can be missing, the sheet can be
    unshared. The page must say so rather than show a traceback."""
    import inspect

    from lofc.dashboard.tabs import scout_reports
    source = inspect.getsource(scout_reports.render)
    assert "st.error(" in source and "except Exception" in source


def test_never_synced_says_so_plainly():
    assert "never" in sync_status(None, NOW).lower()
