"""The season-by-season table carries each season's SCORE, not just its output.

It showed club, league, minutes, goals and assists -- everything except the one number the
rest of the platform ranks on. A recruiter comparing two seasons had the raw output but not
the rating, and had to change the sidebar season and re-open the player to see it.

NO TREND VERDICT IS COMPUTED, deliberately. Measured on the live data: of 2,184 players with
a composite in both complete seasons, the mean absolute season-on-season change is 0.49 for
players who stayed in the SAME league -- against a population SD of 0.58. A ~0.85 SD swing is
the normal amount of movement, so an "improved / declined" flag would fire on nearly everyone
and carry almost no information. With only two complete seasons there is no curve to draw
either. The numbers are shown beside the league each was earned in; the reader judges.
"""

import pandas as pd

from lofc.dashboard.tabs.players import attach_season_scores

SCORES = pd.DataFrame([
    {"player_id": 1, "competition_id": 4, "season_id": 318, "objective_composite": 3.42},
    {"player_id": 1, "competition_id": 903, "season_id": 318, "objective_composite": 4.00},
    {"player_id": 1, "competition_id": 4, "season_id": 317, "objective_composite": 2.90},
])


def _rows(records):
    return pd.DataFrame(records)


def test_each_season_row_gets_its_own_score():
    rows = _rows([
        {"player_id": 1, "competition_id": 4, "season_id": 318},
        {"player_id": 1, "competition_id": 4, "season_id": 317},
    ])
    out = attach_season_scores(rows, SCORES)
    assert list(out["Score"]) == [3.42, 2.90]


def test_the_score_matches_the_league_the_row_is_for():
    """A loanee holds two rows in one season -- 3.42 in League Two, 4.00 in PL2. Matching on
    player and season alone would put the same number on both, losing the level step."""
    rows = _rows([
        {"player_id": 1, "competition_id": 4, "season_id": 318},
        {"player_id": 1, "competition_id": 903, "season_id": 318},
    ])
    out = attach_season_scores(rows, SCORES)
    assert list(out["Score"]) == [3.42, 4.00]


def test_a_season_with_no_score_reads_as_blank_not_zero():
    """Under 450 minutes means no composite exists. Zero would be a claim; blank is the fact."""
    rows = _rows([{"player_id": 1, "competition_id": 4, "season_id": 319}])
    out = attach_season_scores(rows, SCORES)
    assert pd.isna(out["Score"].iloc[0])


def test_no_trend_or_delta_column_is_produced():
    """Pinned: a season-on-season verdict is not computed, for the reason in the docstring."""
    rows = _rows([
        {"player_id": 1, "competition_id": 4, "season_id": 318},
        {"player_id": 1, "competition_id": 4, "season_id": 317},
    ])
    out = attach_season_scores(rows, SCORES)
    assert not {"Change", "Trend", "Delta", "Direction"} & set(out.columns)


def test_an_empty_frame_is_handled():
    out = attach_season_scores(pd.DataFrame(columns=["player_id", "competition_id", "season_id"]),
                               SCORES)
    assert "Score" in out.columns and out.empty


def test_the_caller_frame_is_not_mutated():
    rows = _rows([{"player_id": 1, "competition_id": 4, "season_id": 318}])
    attach_season_scores(rows, SCORES)
    assert "Score" not in rows.columns
