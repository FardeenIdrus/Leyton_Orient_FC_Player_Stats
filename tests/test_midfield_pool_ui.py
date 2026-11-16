"""What the pages say about the pool a player was rated in (owner 2026-11-16).

  * Rated against all midfielders (the midfield fallback): a short tag, percentiles headed
    "vs <League> midfielders", no rank (his own position is below the floor).
  * Not rated (pool below MIN_PEERS_FOR_RANKING): no percentile or band is shown as if real
    -- "—" -- and one line: "Not rated: only N <Position>s in <League> with 450+ minutes
    (needs 10)." Alone in a pool every percentile is 50.0 and every band 3.00 by construction.
No database."""

from lofc.core import card
from lofc.core import report_page as rp
from lofc.model import scorecard
from lofc.report import data

LINE = ("Not rated: only 1 Central Mids in Scottish Premiership with 450+ minutes "
        "(needs 10).")


def _report(**overrides):
    base = dict(
        player_name="Lyall Cameron", position="Central Mid", club="Dundee United FC",
        league="Scottish Premiership", season_label="26/27", age=23.0, foot="right",
        height_cm=180, nationality="Scotland", contract_until=None,
        minutes=476.0, goals=0.0, assists=0.0, composite=3.0,
        dimension_bands={"Performance": 3.0, "Physical": 3.0,
                         "Psychological": None, "Medical": None},
        rank=1, peer_count=1,
        percentiles={"ball_wins_p90": 50.0, "distance_p90": 50.0},
        physical={"distance_p90": 50.0},
        availability=None, availability_status="unknown", matches_missed=0,
        injuries=[], narrative=None,
        stamp=data.STAMP_DATA_ONLY, snapshot_date="16 Nov 2026", comparison_text="",
        flags=[])
    base.update(overrides)
    return data.ReportData(**base)


# --- the wording ---------------------------------------------------------------------------
def test_the_not_rated_line_names_the_position_league_and_minutes():
    assert card.not_rated_line(1, "Central Mid", "Scottish Premiership") == LINE


def test_the_tag_is_short_and_only_for_the_midfield_pool():
    assert scorecard.MIDFIELD_POOL_TAG == "Rated against all midfielders"
    assert card.pool_tag(scorecard.POOL_MIDFIELD) == "Rated against all midfielders"
    assert card.pool_tag(scorecard.POOL_POSITION) is None
    assert card.pool_tag(None) is None


def test_percentile_headings_name_the_pool():
    assert card.pool_vs("League Two", "Winger", scorecard.POOL_POSITION, None) == \
        "League Two Wingers"
    assert card.pool_vs("League Two", "Winger", scorecard.POOL_POSITION, 8) == \
        "8 League Two Wingers"
    assert card.pool_vs("Scottish Premiership", "Central Mid", scorecard.POOL_MIDFIELD, None) == \
        "Scottish Premiership midfielders"


def test_withheld_tables_keep_the_values_and_blank_percentile_and_band():
    table = {"columns": ["Metric", "Per 90 / rate", "Percentile", "Band"],
             "rows": [["Ball wins", "5.10", 50, 3.0], ["Pressures", "20.00", 50, 3.0]]}
    out = card.withhold_percentiles(table)
    assert out["rows"] == [["Ball wins", "5.10", None, None], ["Pressures", "20.00", None, None]]
    assert table["rows"][0][2] == 50                      # the caller's table is not mutated
    assert card.withhold_percentiles(None) is None


# --- the report page -------------------------------------------------------------------------
def test_an_unrated_report_shows_dashes_not_fifties_and_the_line():
    v = rp.view(_report())
    assert v["verdict"]["not_rated"] == LINE
    assert v["verdict"]["composite"] is None and v["verdict"]["rank"] is None
    bars = v["technical"]["bars"]
    assert bars and all(b["value"] is None and b["text"] == "—" for b in bars)
    assert all(x is None for x in v["physical"]["player"])
    assert v["physical"]["withheld"] is True


def test_the_unrated_line_uses_the_pool_actually_tried():
    v = rp.view(_report(pool_size=4, peer_count=4, position="Winger", league="League Two"))
    assert v["verdict"]["not_rated"] == ("Not rated: only 4 Wingers in League Two with 450+ "
                                         "minutes (needs 10).")


def test_a_midfield_pool_report_is_rated_tagged_and_unranked():
    v = rp.view(_report(pool_scope=scorecard.POOL_MIDFIELD, pool_size=24, rank=None,
                        composite=3.4, percentiles={"ball_wins_p90": 71.0}))
    ver = v["verdict"]
    assert ver["not_rated"] is None and ver["composite"] == "3.40"
    assert ver["pool_tag"] == "Rated against all midfielders"
    assert ver["rank"] is None
    assert v["technical"]["vs"] == "Scottish Premiership midfielders"
    assert any(b["value"] == 71.0 for b in v["technical"]["bars"])
    assert v["physical"]["withheld"] is False


def test_a_normal_report_is_unchanged():
    v = rp.view(_report(position="Winger", league="League Two", rank=7, peer_count=70,
                        composite=3.9, percentiles={"distance_p90": 55.0}))
    assert v["verdict"]["pool_tag"] is None
    assert v["verdict"]["rank"] == "7th of 70 League Two Wingers"
    assert v["technical"]["vs"] == "League Two Wingers"


# --- the Players page row ----------------------------------------------------------------------
def test_a_players_row_carries_the_tag_only_for_the_midfield_pool():
    import pandas as pd
    from lofc.core import players_pool as pp
    table = pd.DataFrame({"player_id": [1, 2, 3], "competition_id": [901] * 3,
                          "season_id": [319] * 3, "Player": ["A", "B", "C"],
                          "Composite": [3.4, 3.1, 2.9],
                          "peer_pool": [scorecard.POOL_MIDFIELD, scorecard.POOL_POSITION, None]})
    lr = pp.ListResult(pool=None, table=table, columns=["Player", "Composite"], keys=None, meta={})
    rows = pp.row_dicts(lr)
    assert [r.get("tag") for r in rows] == ["Rated against all midfielders", None, None]
    assert rows[0]["cells"] == {"Player": "A", "Composite": "3.40"}


def test_the_players_about_line_mentions_the_midfield_pool():
    import inspect
    from lofc.web.api import players
    src = inspect.getsource(players.list_payload)
    assert "in their league and position (midfielders: all midfielders if fewer)" in src


# --- the comparison lines that name the pool -----------------------------------------------------
def test_the_report_comparison_line_names_the_pool_used():
    assert data.comparison_line("26/27", "Scottish Premiership", "Central Mid", 38,
                                scorecard.POOL_MIDFIELD) == \
        "26/27 · Scottish Premiership only · compared to 38 Scottish Premiership midfielders over 450 minutes"
    assert data.comparison_line("25/26", "League Two", "Winger", 70, scorecard.POOL_POSITION) == \
        "25/26 · League Two only · compared to 70 League Two Wingers over 450 minutes"


def test_the_scored_as_notice_names_the_midfield_pool():
    import pandas as pd
    shares = pd.DataFrame([{"position_group": "Central Mid", "minutes": 230, "share": .48},
                           {"position_group": "Attacking Mid", "minutes": 220, "share": .46}])
    assert card.scored_as_notice(shares, scorecard.POOL_MIDFIELD) == (
        "Scored as **Central Mid** — his largest position, but only 48% of his minutes. Every "
        "percentile below compares him with all midfielders in his league.")
    assert card.scored_as_notice(shares).endswith("compares him with players in that position.")
