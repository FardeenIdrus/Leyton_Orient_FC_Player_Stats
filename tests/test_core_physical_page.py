"""core.physical_page: the web Physical page's pure logic (TASKS 2.1e). No database."""
import math

import pandas as pd
import pytest

from lofc.core import physical_page as pp
from lofc.model.scorecard import MIN_PEERS_FOR_RANKING


# --- metrics and wording -------------------------------------------------------------------
def test_metrics_are_the_cards_physical_rows_with_the_cards_labels():
    from lofc.dashboard import detail_section as ds
    keys = [m["key"] for m in pp.metric_list()]
    assert keys == [m for m, _ in ds.PHASE_METRICS] + [m for m, _, _ in ds.SPEED_METRICS]
    labels = {m["key"]: m["label"] for m in pp.metric_list()}
    assert labels["top5_psv99_kmh"] == "Top speed (km/h)"
    assert labels["sprint_count_p90"] == "Sprints"


def test_rated_metrics_are_the_seven_scored_ones_and_definitions_are_the_glossarys():
    from lofc.dashboard.glossary_data import PHYSICAL
    from lofc.model import club_framework as cf
    assert set(pp.RATED) == set(cf.PHYSICAL_METRICS["Winger"]) and len(pp.RATED) == 7
    for m in pp.metric_list():
        assert m["definition"] == PHYSICAL[m["key"]][1]
        assert m["rated"] == (m["key"] in pp.RATED)


def test_positions_leave_out_goalkeepers():
    assert "Goalkeeper" not in pp.positions()
    assert pp.positions()[0] == "Centre Back" and "Centre Forward" in pp.positions()


def test_no_data_text():
    assert pp.no_data_text("2024/25") == "No physical data for 2024/25."


@pytest.mark.parametrize("v,text", [(10184.34, "10184.3"), (None, "—"), (float("nan"), "—"),
                                    (29.55, f"{29.55:.1f}")])
def test_value_text_is_the_cards_format(v, text):
    assert pp.value_text(v) == text


@pytest.mark.parametrize("p,out", [(86.3, 86), (None, None), (float("nan"), None), (12.5, 12)])
def test_pct_is_rounded_as_the_card_rounds(p, out):
    assert pp.pct_value(p) == out


# --- fixtures ---------------------------------------------------------------------------------
def _cands(n=12, comp=4, pos="Winger"):
    return pd.DataFrame({
        "player_id": range(1, n + 1), "competition_id": comp, "season_id": 319,
        "position_group": pos, "player_name": [f"P{i:02d}" for i in range(1, n + 1)],
        "team_name": "Club", "minutes": [900.5] * n, "age": [24.04] * n})


def _values(cands, metric="sprint_count_p90", missing=()):
    v = cands[["player_id", "competition_id"]].copy()
    for m in pp.KEYS:
        v[m] = float("nan")
    v[metric] = [float("nan") if p in missing else float(p) for p in cands["player_id"]]
    v["top5_psv99_kmh"] = [30.0 + p / 10 for p in cands["player_id"]]
    return v


def _pcts(cands, values):
    """Mid-rank percentiles as metric_percentiles computes them (within the pool)."""
    p = cands[["player_id", "competition_id", "season_id", "position_group"]].copy()
    for m in pp.KEYS:
        col = values[m]
        p[m] = ((col.rank() - 0.5) / col.count() * 100.0).values
    return p


# --- pool + leaders ---------------------------------------------------------------------------
def test_pool_counts_are_the_percentile_divisor():
    c = _cands(12)
    v = _values(c, missing=(3,))
    counts = pp.pool_counts(_pcts(c, v))
    assert pp.count_for(counts, 4, "Winger", "sprint_count_p90") == 11
    assert pp.count_for(counts, 4, "Winger", "top5_psv99_kmh") == 12
    assert pp.count_for(counts, 5, "Winger", "top5_psv99_kmh") == 0


def test_leaders_order_by_percentile_with_ranks_and_values():
    c = _cands(12)
    v = _values(c)
    pool = pp.pool_frame(c, v, _pcts(c, v), 4, "Winger")
    out = pp.leaders(pool, "sprint_count_p90")
    assert out["n"] == 12 and out["thin"] is None
    names = [pool.iloc[i]["player_name"] for i, _r in out["order"]]
    assert names[0] == "P12" and names[-1] == "P01"
    assert [r for _i, r in out["order"]][:3] == [1, 2, 3]


def test_leaders_lower_is_better_uses_the_flipped_percentile():
    c = _cands(12)
    v = _values(c, metric="time_to_sprint")
    p = _pcts(c, v)
    p["time_to_sprint"] = 100.0 - p["time_to_sprint"]          # as metric_percentiles flips it
    pool = pp.pool_frame(c, v, p, 4, "Winger")
    first = pool.iloc[pp.leaders(pool, "time_to_sprint")["order"][0][0]]
    assert first["player_name"] == "P01"                         # the quickest (lowest time)


def test_thin_pool_has_no_ranking_and_says_why():
    n = MIN_PEERS_FOR_RANKING - 1
    c = _cands(n)
    v = _values(c)
    pool = pp.pool_frame(c, v, _pcts(c, v), 4, "Winger")
    out = pp.leaders(pool, "sprint_count_p90")
    assert out["n"] == n
    assert out["thin"] == f"Not rated: only {n} comparable players (needs {MIN_PEERS_FOR_RANKING})"
    assert all(r is None for _i, r in out["order"])
    names = [pool.iloc[i]["player_name"] for i, _r in out["order"]]
    assert names == sorted(names)                               # by name, not by value
    rows = pp.pool_players(pool, {"sprint_count_p90": n}, set(), lambda p, c, s: None)
    assert all(r["p"]["sprint_count_p90"] is None for r in rows)
    assert all(r["t"]["sprint_count_p90"] != "—" for r in rows)  # the values stay


def test_players_without_tracking_data_are_not_in_the_pool():
    c = _cands(12)
    v = _values(c)
    v.loc[v["player_id"] == 5, pp.KEYS] = float("nan")
    pool = pp.pool_frame(c, v, _pcts(c, v), 4, "Winger")
    assert 5 not in set(pool["player_id"])


def test_pool_players_payload():
    c = _cands(12)
    v = _values(c)
    pool = pp.pool_frame(c, v, _pcts(c, v), 4, "Winger")
    counts = {k: 12 for k in pp.KEYS}
    rows = pp.pool_players(pool, counts, {7}, lambda p, cc, s: f"/player/{p}/{cc}/{s}")
    r7 = next(r for r in rows if r["name"] == "P07")
    assert r7["orient"] is True and r7["href"] == "/player/7/4/319"
    assert r7["club"] == "Club" and r7["age"] == "24.0" and r7["mins"] == 900.5 and r7["mins_t"] == "901"
    assert r7["v"]["sprint_count_p90"] == 7.0 and r7["t"]["sprint_count_p90"] == "7.0"
    assert r7["p"]["sprint_count_p90"] == round((7 - 0.5) / 12 * 100)
    assert r7["v"]["distance_p90"] is None and r7["t"]["distance_p90"] == "—"
    assert not any(isinstance(x, float) and math.isnan(x) for x in r7["v"].values() if x is not None)


# --- squad ------------------------------------------------------------------------------------
def _rows(cands, thin=()):
    r = cands.set_index("player_id")[["competition_id", "position_group", "team_name", "minutes"]].copy()
    r["physical_band"] = 3.5
    r["peer_count"] = 30.0
    r["thin"] = [p in thin for p in r.index]
    if thin:
        r.loc[list(thin), "peer_count"] = 6.0
        r.loc[list(thin), "physical_band"] = float("nan")
    return r


def test_squad_rows_value_percentile_and_order():
    c = _cands(12)
    v = _values(c)
    pc = _pcts(c, v)
    sq = pd.DataFrame({"player_id": [2, 11, 99, 50], "player_name": ["B", "K", "No Row", "Keeper"],
                       "position_group": ["Winger", "Winger", "Centre Back", "Goalkeeper"]})
    out = pp.squad_rows(sq, _rows(c), v, pc, pp.pool_counts(pc),
                        {4: "League One"}, lambda p, cc, s: f"/player/{p}/{cc}/{s}")
    assert [r["name"] for r in out] == ["No Row", "B", "K"]          # position order; GK left out
    b = out[1]
    assert b["pos"] == "Winger" and b["league"] == "League One" and b["mins"] == 900.5
    assert b["phys"] == 3.5 and b["note"] is None and b["href"] == "/player/2/4/319"
    cell = b["cells"]["sprint_count_p90"]
    assert cell == {"t": "2.0", "v": 2.0, "p": round((2 - 0.5) / 12 * 100)}
    none = out[0]
    assert none["mins"] is None and none["mins_t"] == "—" and none["href"] is None
    assert all(x["t"] == "—" and x["p"] is None for x in none["cells"].values())


def test_squad_thin_pool_hides_rating_and_percentiles():
    c = _cands(12)
    v = _values(c)
    pc = _pcts(c, v)
    sq = pd.DataFrame({"player_id": [2], "player_name": ["B"], "position_group": ["Winger"]})
    out = pp.squad_rows(sq, _rows(c, thin=(2,)), v, pc, pp.pool_counts(pc), {4: "League One"},
                        lambda *a: None)
    b = out[0]
    assert b["phys"] is None
    assert b["note"] == f"Not rated: only 6 comparable players (needs {MIN_PEERS_FOR_RANKING})"
    assert b["cells"]["sprint_count_p90"]["t"] == "2.0"
    assert all(x["p"] is None for x in b["cells"].values())


def test_squad_metric_with_a_thin_count_has_no_percentile():
    c = _cands(12)
    v = _values(c, missing=tuple(range(1, 5)))                     # 8 players have sprints
    pc = _pcts(c, v)
    sq = pd.DataFrame({"player_id": [9], "player_name": ["I"], "position_group": ["Winger"]})
    out = pp.squad_rows(sq, _rows(c), v, pc, pp.pool_counts(pc), {4: "League One"}, lambda *a: None)
    assert out[0]["cells"]["sprint_count_p90"]["p"] is None
    assert out[0]["cells"]["sprint_count_p90"]["t"] == "9.0"
    assert out[0]["cells"]["top5_psv99_kmh"]["p"] is not None


def test_default_league_is_where_most_of_the_squad_play():
    rows = pd.DataFrame({"competition_id": [4, 4, 5, 4]}, index=[1, 2, 3, 4])
    assert pp.default_league([1, 2, 3], rows, [3, 4, 5]) == 4
    assert pp.default_league([1, 2, 3], rows, [3, 5]) == 5
    assert pp.default_league([1, 2], rows, [3, 65]) == 3            # none of ours: the first
    assert pp.default_league([], rows, []) is None


# --- 2.36 Physical page additions --------------------------------------------------------------
@pytest.mark.parametrize("age,bands", [
    (20.9, {"", "u21", "u23"}), (21.0, {"", "u23"}), (22.99, {"", "u23"}),
    (23.0, {"", "23-29"}), (29.99, {"", "23-29"}), (30.0, {"", "30+"}), (None, {""})])
def test_age_bands(age, bands):
    assert {k for k, _ in pp.AGE_BANDS if pp.in_age_band(age, k)} == bands


def test_age_band_labels():
    assert [label for _, label in pp.AGE_BANDS] == ["All", "Under 21", "Under 23", "23–29", "30+"]


def _cards(n=12, comp=4, pos="Winger", sid=319):
    return pd.DataFrame({"player_id": range(1, n + 1), "competition_id": comp, "season_id": sid,
                         "position_group": pos, "archetype": "All Metrics",
                         "physical_band": [1.0 + i * 0.25 for i in range(n)]})


def test_physical_ranks_use_rank_in_pool_on_the_physical_band():
    from lofc.model.scorecard import rank_in_pool
    cards = _cards(12)
    cards.loc[cards["player_id"] == 12, "physical_band"] = cards["physical_band"].max() - 0.25  # tie with 11
    r = pp.physical_ranks(cards, 4, 319, "Winger")
    for pid in range(1, 13):
        assert r[pid]["rank"] == rank_in_pool(cards, pid, 4, 319, "Winger", column="physical_band")[0]
    assert r[11]["rank"] == r[12]["rank"] == 1 and r[11]["text"] == "1st of 12"
    assert r[1]["text"] == "12th of 12" and r[1]["band"] == 1.0


def test_physical_ranks_thin_pool_is_a_dash():
    n = MIN_PEERS_FOR_RANKING - 1
    r = pp.physical_ranks(_cards(n), 4, 319, "Winger")
    assert all(x["rank"] is None and x["text"] == "—" and x["band"] is None for x in r.values())


def test_physical_ranks_other_league_or_position_not_counted():
    cards = pd.concat([_cards(12), _cards(5, comp=5), _cards(5, pos="Centre Back")])
    r = pp.physical_ranks(cards, 4, 319, "Winger")
    assert len(r) == 12 and r[12]["text"] == "1st of 12"


def test_rating_leaders_rank_on_the_physical_band():
    c = _cands(12)
    v = _values(c)
    pool = pp.pool_frame(c, v, _pcts(c, v), 4, "Winger")
    ranks = pp.physical_ranks(_cards(12), 4, 319, "Winger")
    out = pp.rating_leaders(pool, ranks)
    assert out["n"] == 12 and out["thin"] is None
    first = pool.iloc[out["order"][0][0]]
    assert first["player_id"] == 12 and out["order"][0][1] == 1


def test_rating_leaders_thin_pool_listed_unranked_by_name():
    n = MIN_PEERS_FOR_RANKING - 1
    c = _cands(n)
    v = _values(c)
    pool = pp.pool_frame(c, v, _pcts(c, v), 4, "Winger")
    out = pp.rating_leaders(pool, pp.physical_ranks(_cards(n), 4, 319, "Winger"))
    assert out["thin"] and all(r is None for _i, r in out["order"])
    names = [pool.iloc[i]["player_name"] for i, _ in out["order"]]
    assert names == sorted(names) and len(names) == n


def test_pool_players_carry_rating_rank_and_age_bands():
    c = _cands(12)
    c.loc[c["player_id"] == 3, "age"] = 19.5
    v = _values(c)
    pool = pp.pool_frame(c, v, _pcts(c, v), 4, "Winger")
    ranks = pp.physical_ranks(_cards(12), 4, 319, "Winger")
    rows = pp.pool_players(pool, {k: 12 for k in pp.KEYS}, set(), lambda *a: None, ranks)
    r3 = next(r for r in rows if r["name"] == "P03")
    assert r3["phys"] == 1.5 and r3["phys_t"] == "10th of 12"
    assert set(r3["bands"]) == {"", "u21", "u23"}


def _players(vals):
    """[(name, x, px, y, py, age)] -> pool_players-like rows."""
    return [{"name": n, "v": {"a": x, "b": y}, "p": {"a": px, "b": py}, "t": {"a": str(x), "b": str(y)},
             "bands": [k for k, _ in pp.AGE_BANDS if pp.in_age_band(age, k)]}
            for n, x, px, y, py, age in vals]


def test_scatter_summary_median_of_the_plotted_pool_and_top_five():
    rows = _players([("A", 1.0, 10, 5.0, 50, 25), ("B", 2.0, 20, 6.0, 60, 25),
                     ("C", 3.0, 30, 7.0, 70, 25), ("D", 4.0, 40, 8.0, 80, 31),
                     ("E", 5.0, 50, None, None, 25), ("F", 6.0, 90, 9.0, 95, 20),
                     ("G", 7.0, 95, 1.0, 5, 25)])
    s = pp.scatter_summary(rows, "a", "b", "")
    assert s["idx"] == [0, 1, 2, 3, 5, 6]                     # E has no y: not plotted
    assert s["median"]["x"] == 3.5 and s["median"]["y"] == 6.5
    assert s["median"]["x_t"] == "3.5" and s["median"]["y_t"] == "6.5"
    assert [rows[i]["name"] for i in s["top"]] == ["F", "D", "C", "G", "B"]   # px+py, best first; a tie by name
    u23 = pp.scatter_summary(rows, "a", "b", "u23")
    assert u23["idx"] == [5] and u23["median"]["x"] == 6.0 and u23["top"] == [5]


def test_scatter_summary_without_percentiles_labels_nobody():
    rows = _players([(f"P{i}", float(i), None, float(i), None, 25) for i in range(6)])
    s = pp.scatter_summary(rows, "a", "b", "")
    assert s["top"] == [] and s["median"]["x"] == 2.5


def test_pool_and_squad_rows_carry_tracked_matches():
    c = _cands(12)
    v = _values(c)
    pc = _pcts(c, v)
    pool = pp.pool_frame(c, v, pc, 4, "Winger")
    matches = {(3, 4): 23, (4, 4): 5}
    rows = pp.pool_players(pool, {k: 12 for k in pp.KEYS}, set(), lambda *a: None, None, matches)
    by = {r["name"]: r for r in rows}
    assert by["P03"]["matches"] == 23 and by["P04"]["matches"] == 5 and by["P05"]["matches"] is None
    sq = pd.DataFrame({"player_id": [3, 9], "player_name": ["C", "I"], "position_group": ["Winger", "Winger"]})
    out = pp.squad_rows(sq, _rows(c), v, pc, pp.pool_counts(pc), {4: "League One"}, lambda *a: None,
                        None, matches)
    assert {r["name"]: r["matches"] for r in out} == {"C": 23, "I": None}
