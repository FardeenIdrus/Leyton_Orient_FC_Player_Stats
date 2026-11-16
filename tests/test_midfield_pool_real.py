"""The midfield fallback on the REAL database (skipped without one): Lyall Cameron, the only
rankable Scottish Premiership Central Mid in 2026/27, is rated against every rankable
Scottish Premiership midfielder, tagged so, and his pool is that combined count.

Needs `python -m lofc.model.scorecard_run` to have run on the current code."""
import pandas as pd
import pytest
from sqlalchemy import create_engine, text

from lofc.config import settings
from lofc.model import scorecard

CAMERON, SPL, SEASON = 2000169232, 901, 319


@pytest.fixture(scope="module")
def engine():
    try:
        e = create_engine(settings.database_url)
        e.connect().close()
    except Exception:
        pytest.skip("no database")
    return e


@pytest.fixture(scope="module")
def combined(engine):
    """Rankable Scottish Premiership midfielders in 2026/27, counted straight from the source."""
    n = pd.read_sql(text("SELECT position_group, count(*) AS n FROM player_metrics_neutral "
                         "WHERE competition_id = :c AND season_id = :s AND rankable "
                         "GROUP BY position_group"), engine, params={"c": SPL, "s": SEASON})
    counts = dict(zip(n["position_group"], n["n"]))
    if counts.get("Central Mid", 0) >= scorecard.MIN_PEERS_FOR_RANKING:
        pytest.skip("Scottish Premiership Central Mid pool is no longer thin")
    return int(sum(counts.get(p, 0) for p in scorecard.MIDFIELD_POSITIONS))


def test_cameron_is_stored_as_rated_against_all_midfielders(engine, combined):
    row = pd.read_sql(text("SELECT * FROM player_scorecards WHERE player_id = :p AND "
                           "competition_id = :c AND season_id = :s AND archetype = 'All Metrics'"),
                      engine, params={"p": CAMERON, "c": SPL, "s": SEASON}).iloc[0]
    assert combined >= scorecard.MIN_PEERS_FOR_RANKING
    assert row["peer_pool"] == scorecard.POOL_MIDFIELD
    assert int(row["peer_pool_size"]) == combined
    assert pd.notna(row["objective_composite"])


def test_cameron_card_is_rated_tagged_and_unranked(engine, combined):
    from lofc.core import card
    c = card.build_card(engine, CAMERON, SPL, SEASON)
    r = c["rating"]
    assert r["not_rated"] is None and r["overall"]["value"] is not None
    assert r["pool_tag"] == "Rated against all midfielders"
    assert r["overall"]["rank_text"] is None
    assert r["sub"].startswith("Against Scottish Premiership midfielders")
    assert c["performance"]["sub"] == "Percentile vs Scottish Premiership midfielders · band 1–5"


def test_cameron_report_is_rated_and_tagged(engine, combined):
    from lofc.core import report_page as rp
    from lofc.report import data
    d = data.build(engine, CAMERON, SPL, SEASON)
    assert (d.pool_scope, d.pool_size) == (scorecard.POOL_MIDFIELD, combined)
    v = rp.view(d)
    assert v["verdict"]["not_rated"] is None and v["verdict"]["composite"] is not None
    assert v["verdict"]["pool_tag"] == "Rated against all midfielders"
    assert v["technical"]["vs"] == "Scottish Premiership midfielders"
    # no longer 50.0 on every metric
    assert len({b["value"] for b in v["technical"]["bars"] if b["value"] is not None}) > 1
