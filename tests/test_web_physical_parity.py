"""The web Physical page shows the player card's physical numbers, on the REAL database (skipped
without one). Read-only.

For each case the page's value text, percentile and minutes for a player are checked against
the card built for the same player, league and season (`core.card.build_card`: its Physical
tables and its Minutes cell), and the percentile against `loaders.load_scorecard_percentiles`
directly. The one intended difference is the honesty rule: where fewer than
MIN_PEERS_FOR_RANKING players in the league and position have a metric, the page shows no
percentile (the card shows it with the pool size in its heading)."""
import pandas as pd
import pytest
from sqlalchemy import create_engine

from lofc.config import settings
from lofc.model.scorecard import MIN_PEERS_FOR_RANKING

# (label, season, league, position, how many players of the pool to check against their card)
POOLS = [("League One CF 2026/27", 319, 4, "Centre Forward", 4),
         ("League Two Winger 2025/26", 318, 5, "Winger", 3),
         ("Championship CB 2025/26", 318, 3, "Centre Back", 2),
         ("thin: Premier League 2 CM 2026/27", 319, 903, "Central Mid", 1)]


@pytest.fixture(scope="module")
def engine():
    try:
        e = create_engine(settings.database_url)
        e.connect().close()
    except Exception:
        pytest.skip("no database")
    return e


@pytest.fixture(scope="module")
def api(engine):
    from lofc.web.api import physical
    return physical


def _card_physical(engine, p, c, s) -> tuple[dict, str]:
    """label -> (value text, percentile) from the card's two physical tables; and its Minutes."""
    from lofc.core import card
    d = card.build_card(engine, p, c, s)
    out = {}
    for part in ("in_rating", "other"):
        t = d["physical"][part]
        for row in (t or {}).get("rows", []):
            out[row[0]] = (row[1], row[4])
    minutes = next(x["value"] for x in d["header"]["register"] if x["label"] == "Minutes")
    return out, minutes


def _checked(engine, page, idxs):
    from lofc.core import physical_page as core
    from lofc.dashboard import loaders as L
    labels = {m["key"]: m["label"] for m in core.metric_list()}
    pool = page["pool"]
    sid = page["filters"]["season"]
    pcts = L.load_scorecard_percentiles(sid)
    n = 0
    for i in idxs:
        r = pool["players"][i]
        p, c, s = (int(x) for x in r["href"].split("/")[2:5])
        card, minutes = _card_physical(engine, p, c, s)
        assert r["mins_t"] == minutes
        prow = pcts[(pcts["player_id"] == p) & (pcts["competition_id"] == c)].iloc[0]
        for k in core.KEYS:
            label = labels[k]
            if r["t"][k] == "—":
                assert label not in card or card[label][0] == "—"
                continue
            assert card[label][0] == r["t"][k], (p, k)
            if r["p"][k] is not None:
                assert r["p"][k] == card[label][1], (p, k)
                assert r["p"][k] == round(float(prow[k])), (p, k)
            else:
                assert pool["leaders"][k]["n"] < MIN_PEERS_FOR_RANKING, (p, k)
            n += 1
    return n


@pytest.mark.parametrize("label,season,league,position,k", POOLS, ids=[p[0] for p in POOLS])
def test_pool_numbers_equal_the_card(engine, api, label, season, league, position, k):
    page = api.page_json(str(season), str(league), position)
    assert page["filters"]["league"] == league and page["filters"]["position"] == position
    pool = page["pool"]
    order = pool["leaders"]["top5_psv99_kmh"]["order"]
    picks = [i for i, _ in order[:k - 1]] + [order[-1][0]] if k > 1 else [order[0][0]]
    assert _checked(engine, page, picks) > 0
    for key, L in pool["leaders"].items():
        if key == "physical_rating":     # ranked on the band, not a percentile (own test below)
            continue
        thin = L["n"] < MIN_PEERS_FOR_RANKING
        assert (L["thin"] is not None) == (thin and L["n"] > 0)
        ranks = [r for _i, r in L["order"]]
        if thin:
            assert all(r is None for r in ranks)
            assert all(pool["players"][i]["p"][key] is None for i, _ in L["order"])
        else:
            pct = [pool["players"][i]["p"][key] for i, _ in L["order"]]
            assert pct == sorted(pct, reverse=True)          # ranked by percentile
            assert ranks[0] == 1 and ranks == sorted(ranks)


def test_pool_is_the_rankable_players_with_tracking_data(engine, api):
    page = api.page_json("319", "4", "Centre Forward")
    n = pd.read_sql("SELECT count(*) AS n FROM player_metrics_neutral WHERE season_id = 319 AND "
                    "competition_id = 4 AND position_group = 'Centre Forward' AND rankable AND "
                    "distance_p90 IS NOT NULL", engine)["n"].iloc[0]
    assert len(page["pool"]["players"]) == n
    assert page["pool"]["leaders"]["distance_p90"]["n"] == n


def test_squad_numbers_equal_the_card(engine, api):
    from lofc.core import physical_page as core
    from lofc.core import squad
    page = api.page_json("319")
    rows = page["squad"]["rows"]
    ours = {int(p) for p in squad.squad()["player_id"]}
    assert rows and all(r["pos"] != "Goalkeeper" for r in rows)
    assert 0 < len(rows) <= len(ours)
    labels = {m["key"]: m["label"] for m in core.metric_list()}
    linked = [r for r in rows if r["href"]][:3]
    assert linked
    for r in linked:
        p, c, s = (int(x) for x in r["href"].split("/")[2:5])
        assert p in ours
        card, minutes = _card_physical(engine, p, c, s)
        assert r["mins_t"] == minutes
        for k, cell in r["cells"].items():
            if cell["t"] != "—":
                assert card[labels[k]][0] == cell["t"]
                if cell["p"] is not None:
                    assert card[labels[k]][1] == cell["p"]


def test_2024_25_has_no_physical_data(api):
    page = api.page_json("317")
    assert page["empty"] == "No physical data for 2024/25."
    assert page["pool"] is None and page["squad"] is None


@pytest.mark.parametrize("label,sid,cid,pos,_n", POOLS, ids=[p[0] for p in POOLS])
def test_physical_rating_rank_is_rank_in_pool_on_stored_scorecards(engine, api, label, sid, cid, pos, _n):
    """TASKS 2.36: "7th of 45" = scorecard.rank_in_pool(column="physical_band") on the stored
    "All Metrics" scorecards of that league, season and position, read here straight from SQL;
    a pool under MIN_PEERS_FOR_RANKING shows "—"."""
    from lofc.dashboard.detail_section import ordinal
    from lofc.model.scorecard import rank_in_pool
    page = api.page_json(sid, cid, pos)
    cards = pd.read_sql("SELECT player_id, competition_id, season_id, position_group, physical_band "
                        "FROM player_scorecards WHERE season_id=%(s)s AND competition_id=%(c)s AND "
                        "position_group=%(p)s AND archetype='All Metrics'", engine,
                        params={"s": sid, "c": cid, "p": pos})
    n = int(cards["physical_band"].notna().sum())
    pids = {r["href"]: r for r in page["pool"]["players"] if r["href"]}
    checked = 0
    for href, r in list(pids.items())[:15]:
        pid = int(href.split("/")[2])
        if pid not in set(cards.loc[cards["physical_band"].notna(), "player_id"]):
            continue
        rank, size = rank_in_pool(cards, pid, cid, sid, pos, column="physical_band")
        want = "—" if size < MIN_PEERS_FOR_RANKING else f"{ordinal(rank)} of {size}"
        assert r["phys_t"] == want, (r["name"], r["phys_t"], want)
        checked += 1
    assert checked or n == 0


@pytest.mark.parametrize("label,sid,cid,pos,_n", POOLS[:3], ids=[p[0] for p in POOLS[:3]])
def test_tracked_matches_are_the_stored_counts(engine, api, label, sid, cid, pos, _n):
    """TASKS 2.36: "Tracked matches" = skillcorner_match_counts (SkillCorner's count_match),
    read here straight from SQL."""
    page = api.page_json(sid, cid, pos)
    stored = pd.read_sql("SELECT player_id, matches FROM skillcorner_match_counts WHERE "
                         "competition_id=%(c)s AND season_id=%(s)s", engine, params={"c": cid, "s": sid})
    want = dict(zip(stored["player_id"].astype(int), stored["matches"].astype(int)))
    checked = 0
    for r in page["pool"]["players"]:
        if not r["href"]:
            continue
        pid = int(r["href"].split("/")[2])
        assert r["matches"] == want.get(pid), (r["name"], r["matches"], want.get(pid))
        checked += r["matches"] is not None
    assert checked > 0
