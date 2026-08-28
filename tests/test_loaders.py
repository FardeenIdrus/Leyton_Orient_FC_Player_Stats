"""`dashboard/loaders.py`'s pure pandas helpers -- no Streamlit runtime, no live Postgres.

Covers the season-319 outage: a season with player data but zero rankable players (nobody
has yet reached the 450-minute threshold) makes `model/scorecard.build_scorecards` return a
totally columnless `pd.DataFrame([])`. `_attach_scorecard_meta` must turn that into a
well-formed EMPTY frame carrying the full expected schema, not raise `KeyError: 'player_id'`
on the merge -- the same "empty but well-formed" principle as
`store/injuries.py::load_for_player` and `model/scout_scores.resolve_bands`.
"""

import pandas as pd

from lofc.dashboard.loaders import (GOALKEEPER_ONLY_METRICS, RAW_SCORECARD_COLUMNS,
                                    _attach_scorecard_meta, _mask_goalkeeper_only_metrics)


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


# --- _mask_goalkeeper_only_metrics ---------------------------------------------------
# `player_metrics_neutral` carries a real, non-null goalkeeper-metric value for every
# position (Impect's CONCEDED_POSTSHOT_XG / CONCEDED_GOALS columns are populated per
# player-position row as team context, not individual keeper skill), so an outfielder's
# profile "All tracked metrics" table would otherwise show a nonsensical figure like
# "Shot stopping %: -620%" for a centre back. This is the display-layer mask that stops
# that -- scoring is untouched (club_framework.PERFORMANCE_METRICS never lists these for
# an outfield position, so they never fed a percentile there regardless of this table).

def _metric_frame():
    return pd.DataFrame({
        "position_group": ["Centre Back", "Goalkeeper", "Winger"],
        "gk_shot_stopping_pct": [-6.2, -0.5, -4.1],
        "gk_gsaa_p90": [-2.1, -0.8, -1.9],
        "gk_conceded_p90": [2.5, 1.6, 3.0],
        "goals_p90": [0.1, 0.0, 0.4],
    })


def test_mask_goalkeeper_only_metrics_nulls_outfield_rows():
    out = _mask_goalkeeper_only_metrics(_metric_frame())
    outfield = out[out["position_group"] != "Goalkeeper"]
    assert outfield["gk_shot_stopping_pct"].isna().all()
    assert outfield["gk_gsaa_p90"].isna().all()
    assert outfield["gk_conceded_p90"].isna().all()


def test_mask_goalkeeper_only_metrics_keeps_goalkeeper_row_untouched():
    """Including an extreme, small-sample value -- masking is a position check, never a
    clamp on the number itself."""
    out = _mask_goalkeeper_only_metrics(_metric_frame())
    gk = out[out["position_group"] == "Goalkeeper"].iloc[0]
    assert gk["gk_shot_stopping_pct"] == -0.5
    assert gk["gk_gsaa_p90"] == -0.8
    assert gk["gk_conceded_p90"] == 1.6


def test_mask_goalkeeper_only_metrics_leaves_non_gk_metrics_alone():
    out = _mask_goalkeeper_only_metrics(_metric_frame())
    assert out["goals_p90"].tolist() == [0.1, 0.0, 0.4]


def test_mask_goalkeeper_only_metrics_no_position_group_is_a_no_op():
    """A frame without position_group (should never happen from the real loader, but a
    caller passing a stray frame must not KeyError) passes through unchanged."""
    frame = pd.DataFrame({"gk_shot_stopping_pct": [-6.2], "goals_p90": [0.1]})
    out = _mask_goalkeeper_only_metrics(frame)
    assert out["gk_shot_stopping_pct"].tolist() == [-6.2]


def test_mask_goalkeeper_only_metrics_missing_column_is_skipped():
    """A metric in GOALKEEPER_ONLY_METRICS that this frame does not carry is simply
    ignored, not an error -- callers select whatever columns exist in the DB."""
    frame = pd.DataFrame({"position_group": ["Centre Back"], "goals_p90": [0.2]})
    out = _mask_goalkeeper_only_metrics(frame)
    assert list(out.columns) == ["position_group", "goals_p90"]


def test_goalkeeper_only_metrics_are_never_null_becomes_zero():
    """A missing value must never become a zero (project rule): masking always writes
    pd.NA, never 0, regardless of the original value's sign or magnitude."""
    frame = pd.DataFrame({
        "position_group": ["Centre Back"],
        **{m: [0.0] for m in GOALKEEPER_ONLY_METRICS},
    })
    out = _mask_goalkeeper_only_metrics(frame)
    for m in GOALKEEPER_ONLY_METRICS:
        assert pd.isna(out.loc[0, m])
