"""TASKS 2.36 (owner 2026-11-09, option A): SkillCorner's tracked-match count (`count_match`,
in the raw platform files) is loaded into its own table by the weekly neutral build, from the
same matched rows the physical metrics come from. Display only: never a metric, never scored."""
import pandas as pd
import pytest

from lofc.model import build_neutral as bn


def _matched():
    """What `load_skillcorner` returns: our player_id, the raw count_match, per-90 metrics."""
    return pd.DataFrame({"player_id": [10, 11, 12], "count_match": [23.0, 4.0, None],
                         "count_match_failed": [0.0, 1.0, 0.0],
                         "distance_p90": [9900.0, 10100.0, 9800.0]})


def test_match_counts_from_the_matched_physical_rows():
    out = bn.match_counts(_matched(), 4, 318)
    assert list(out.columns) == ["player_id", "competition_id", "season_id", "matches"]
    assert out.to_dict("records") == [
        {"player_id": 10, "competition_id": 4, "season_id": 318, "matches": 23},
        {"player_id": 11, "competition_id": 4, "season_id": 318, "matches": 4}]
    assert str(out["matches"].dtype).startswith("int")


def test_match_counts_without_physical_data_is_empty():
    out = bn.match_counts(None, 4, 318)
    assert out.empty and list(out.columns) == ["player_id", "competition_id", "season_id", "matches"]
    no_col = bn.match_counts(_matched().drop(columns=["count_match"]), 4, 318)
    assert no_col.empty


def test_the_count_is_never_a_metric():
    """A column on player_metrics_neutral would be ranked as a metric (metric_percentiles ranks
    every non-key column), so the count lives in its own table."""
    from lofc.model import metric_registry as reg
    from lofc.store import models
    assert "matches" not in reg.names_for(reg.SKILLCORNER)
    assert not hasattr(models.PlayerMetricNeutral, "matches")
    t = models.Base.metadata.tables["skillcorner_match_counts"]
    assert {"player_id", "competition_id", "season_id", "matches"} <= set(t.c.keys())
    assert any({c.name for c in u.columns} == {"player_id", "competition_id", "season_id"}
               for u in t.constraints if u.__class__.__name__ == "UniqueConstraint")


def test_the_web_cache_tracks_the_table():
    from lofc.dashboard import loaders as L
    assert "skillcorner_match_counts" in L._WEB_TABLES


def test_weekly_pipeline_runs_the_neutral_build_that_writes_the_counts():
    import inspect
    from lofc import pipeline
    src = inspect.getsource(pipeline)
    assert '"lofc.model.build_neutral", "--write"' in src
    assert "write_match_counts" in inspect.getsource(bn.main)


# --- real database (skipped without one): the stored count is the raw file's ----------------
@pytest.fixture(scope="module")
def engine():
    from sqlalchemy import create_engine
    from lofc.config import settings
    try:
        e = create_engine(settings.database_url)
        e.connect().close()
    except Exception:
        pytest.skip("no database")
    return e


@pytest.mark.parametrize("name,comp,season", [
    ("Theo Archibald", 4, 318), ("Jaze Kabia", 4, 319), ("Dilan Markanday", 5, 318)])
def test_stored_count_equals_the_raw_platform_file(engine, name, comp, season):
    from lofc.config import settings
    from lofc.ingest import skillcorner_api
    target = next(t for t in settings.skillcorner_targets
                  if t.competition_id == comp and t.season_id == season)
    raw = pd.read_parquet(skillcorner_api.physical_path(target.edition_id))
    row = raw[raw["player_name"] == name]
    if row.empty:
        pytest.skip(f"{name} not in the raw file")
    stored = pd.read_sql(
        "SELECT c.matches FROM skillcorner_match_counts c JOIN player_metrics_neutral n "
        "USING (player_id, competition_id, season_id) WHERE n.player_name = %(n)s "
        "AND c.competition_id = %(c)s AND c.season_id = %(s)s", engine,
        params={"n": name, "c": comp, "s": season})
    assert len(stored) == 1 and int(stored["matches"][0]) == int(row["count_match"].iloc[0])
