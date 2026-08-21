"""`dashboard/loaders.py`'s pure pandas helpers -- no Streamlit runtime, no live Postgres.

Covers the season-319 outage: a season with player data but zero rankable players (nobody
has yet reached the 450-minute threshold) makes `model/scorecard.build_scorecards` return a
totally columnless `pd.DataFrame([])`. `_attach_scorecard_meta` must turn that into a
well-formed EMPTY frame carrying the full expected schema, not raise `KeyError: 'player_id'`
on the merge -- the same "empty but well-formed" principle as
`store/injuries.py::load_for_player` and `model/scout_scores.resolve_bands`.
"""

import pandas as pd

from lofc.dashboard.loaders import RAW_SCORECARD_COLUMNS, _attach_scorecard_meta


def _neutral():
    return pd.DataFrame({
        "player_id": [1, 2],
        "competition_id": [5, 5],
        "season_id": [319, 319],
        "player_name": ["Player One", "Player Two"],
        "team_name": ["Club A", "Club B"],
    })


def test_attach_scorecard_meta_on_columnless_empty_frame_does_not_raise():
    """The exact shape `build_scorecards` returns when nobody is rankable: 0 rows, 0 columns."""
    sc = pd.DataFrame([])
    out = _attach_scorecard_meta(sc, _neutral())
    assert out.empty
    assert list(out) == RAW_SCORECARD_COLUMNS + ["player_name", "team_name", "league"]


def test_attach_scorecard_meta_columnless_frame_has_no_rows():
    sc = pd.DataFrame([])
    out = _attach_scorecard_meta(sc, _neutral())
    assert len(out) == 0


def test_attach_scorecard_meta_normal_case_unaffected():
    """A non-empty scorecard frame (the ordinary path) still merges player_name/team_name/
    league exactly as before -- the empty-frame guard must not change this branch."""
    sc = pd.DataFrame({
        "player_id": [1], "competition_id": [5], "season_id": [319],
        "position_group": ["Centre Forward"], "objective_composite": [3.5],
    })
    out = _attach_scorecard_meta(sc, _neutral())
    assert len(out) == 1
    assert out.loc[0, "player_name"] == "Player One"
    assert out.loc[0, "team_name"] == "Club A"


def test_downstream_column_selection_works_on_empty_result():
    """The exact operation that used to raise for app.py's `ranking[sc_cols]` /
    `all_round = ...[keys3 + ["objective_composite"]]` -- selecting expected columns off the
    empty result must not KeyError."""
    sc = pd.DataFrame([])
    out = _attach_scorecard_meta(sc, _neutral())
    keys3 = ["player_id", "competition_id", "season_id"]
    selected = out[keys3 + ["objective_composite", "full_composite"]]
    assert selected.empty


def test_downstream_merge_on_empty_result_works():
    """The exact operation app.py performs next: merging the (now well-formed) empty ranking
    onto a non-empty candidate pool must not raise, and must leave the pool's rows intact
    with NaN scorecard columns rather than dropping them."""
    sc = pd.DataFrame([])
    ranking = _attach_scorecard_meta(sc, _neutral())
    keys3 = ["player_id", "competition_id", "season_id"]
    pool = pd.DataFrame({"player_id": [1, 2], "competition_id": [5, 5], "season_id": [319, 319]})
    merged = pool.merge(ranking[keys3 + ["objective_composite"]], on=keys3, how="left")
    assert len(merged) == 2
    assert merged["objective_composite"].isna().all()
