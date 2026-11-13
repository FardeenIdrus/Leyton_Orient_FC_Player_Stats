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


def _xy(vals):
    """[(name, x, y, age)] -> rows with values only (the "High on both" rule needs no percentile)."""
    return _players([(n, x, None, y, None, age) for n, x, y, age in vals])


# A..L: x median 6.5, y median 5.5; above both: K, B, C, A, D (L is high on x only, J on neither)
_HOB = [("A", 10.0, 10.0, 25), ("B", 9.0, 12.0, 25), ("C", 12.0, 9.0, 25), ("D", 8.0, 8.0, 25),
        ("E", 1.0, 1.0, 25), ("F", 2.0, 2.0, 25), ("G", 3.0, 3.0, 25), ("H", 4.0, 4.0, 25),
        ("I", 5.0, 5.0, 25), ("J", 6.0, 6.0, 25), ("K", 7.0, 20.0, 20), ("L", 20.0, 1.0, 25)]


def test_scatter_summary_median_of_the_plotted_pool():
    rows = _xy(_HOB + [("M", 5.0, None, 25)])
    s = pp.scatter_summary(rows, "a", "b", "")
    assert s["idx"] == list(range(12))                        # M has no y: not plotted
    assert s["median"]["x"] == 6.5 and s["median"]["y"] == 5.5
    assert s["median"]["x_t"] == "6.5" and s["median"]["y_t"] == "5.5"


def test_high_on_both_ranked_by_value_over_median():
    """Owner 2026-11-13: above BOTH medians, best first by x/median_x + y/median_y."""
    rows = _xy(_HOB)
    s = pp.scatter_summary(rows, "a", "b", "")
    # K 7/6.5+20/5.5=4.71, B 3.57, C 3.48, A 3.36, D 2.69
    assert [rows[i]["name"] for i in s["top"]] == ["K", "B", "C", "A", "D"]
    assert s["top_marked"] == pp.TOP_MARKED == 5


def test_high_on_both_lists_at_most_eight_ties_by_name():
    rows = _xy([(f"P{i:02d}", float(i), float(i), 25) for i in range(1, 21)]
               + [("Z", 20.0, 20.0, 25), ("AA", 20.0, 20.0, 25)])
    s = pp.scatter_summary(rows, "a", "b", "")
    names = [rows[i]["name"] for i in s["top"]]
    assert len(names) == pp.TOP_SHOWN == 8
    assert names[:3] == ["AA", "P20", "Z"] and names[3:] == ["P19", "P18", "P17", "P16", "P15"]


def test_high_on_both_follows_the_age_band():
    rows = _xy(_HOB + [(f"Y{i}", float(i), float(i), 20) for i in range(1, 10)])
    u21 = pp.scatter_summary(rows, "a", "b", "u21")
    assert [rows[i]["name"] for i in u21["idx"]] == ["K"] + [f"Y{i}" for i in range(1, 10)]
    assert u21["median"]["x"] == 5.5 and u21["median"]["y"] == 5.5
    assert [rows[i]["name"] for i in u21["top"]] == ["K", "Y9", "Y8", "Y7", "Y6"]


def test_high_on_both_withheld_below_the_peer_floor():
    """Fewer plotted players than MIN_PEERS_FOR_RANKING: medians drawn, nobody ranked."""
    rows = _xy(_HOB[:9])
    s = pp.scatter_summary(rows, "a", "b", "")
    assert len(s["idx"]) == 9 and s["median"]["x"] is not None and s["top"] == []
    assert s["top_note"] == "Not rated: only 9 comparable players (needs 10)"
    assert pp.scatter_summary(_xy(_HOB), "a", "b", "")["top_note"] is None


def test_high_on_both_says_when_nobody_is_above_both():
    rows = _xy([(f"P{i}", float(i), float(12 - i), 25) for i in range(12)])
    s = pp.scatter_summary(rows, "a", "b", "")
    assert s["top"] == [] and s["top_note"] == "Nobody better on both."


def test_high_on_both_needs_positive_medians():
    rows = _xy([(f"P{i}", 0.0 if i < 8 else 1.0, float(i), 25) for i in range(12)])
    s = pp.scatter_summary(rows, "a", "b", "")
    assert s["median"]["x"] == 0.0 and s["top"] == []


# --- lower-is-better axes (owner 2026-11-13): top right always means better on both ----------
def test_lower_is_better_metrics_are_the_timing_tests():
    from lofc.model import club_framework as cf
    lower = {m["key"] for m in pp.metric_list() if m["lower"]}
    assert lower == {k for k in pp.KEYS if k in cf.LOWER_IS_BETTER}
    assert {"time_to_sprint", "time_to_hsr", "agility_505_90", "agility_505_180"} <= lower
    assert "top5_psv99_kmh" not in lower and "sprint_count_p90" not in lower


# y = "b" is a time (lower is better). x median 6.5, y median 4.5.
# Better on both = x > 6.5 and y < 4.5: A, B, C, D, K (L: x 20 but y 10, slow).
_REV = [("A", 10.0, 2.0, 25), ("B", 9.0, 1.5, 25), ("C", 12.0, 3.0, 25), ("D", 8.0, 2.5, 25),
        ("E", 1.0, 9.0, 25), ("F", 2.0, 8.0, 25), ("G", 3.0, 7.0, 25), ("H", 4.0, 6.0, 25),
        ("I", 5.0, 5.0, 25), ("J", 6.0, 4.0, 25), ("K", 7.0, 1.0, 25), ("L", 20.0, 10.0, 25)]


def test_better_on_both_with_a_lower_is_better_axis():
    """Score = x / median_x + median_y / y on the reversed axis:
    K 7/6.5 + 4.5/1 = 5.58, B 1.38 + 3.00 = 4.38, A 1.54 + 2.25 = 3.79,
    C 1.85 + 1.50 = 3.35, D 1.23 + 1.80 = 3.03."""
    rows = _xy(_REV)
    s = pp.scatter_summary(rows, "a", "b", "", lower={"b"})
    assert s["median"]["x"] == 6.5 and s["median"]["y"] == 4.5
    assert [rows[i]["name"] for i in s["top"]] == ["K", "B", "A", "C", "D"]
    assert s["rev"] == {"x": False, "y": True}


def test_both_axes_lower_is_better():
    rows = _xy([(n, y, x, a) for n, x, y, a in _REV])      # swap: x is the time now
    s = pp.scatter_summary(rows, "a", "b", "", lower={"a", "b"})
    assert s["rev"] == {"x": True, "y": True}
    # better on both = a < 4.5 and b < 6.5: J (4, 6) only
    assert [rows[i]["name"] for i in s["top"]] == ["J"]


def test_no_reversed_axis_by_default_for_ordinary_metrics():
    s = pp.scatter_summary(_xy(_HOB), "a", "b", "")
    assert s["rev"] == {"x": False, "y": False}


# --- minimum minutes (owner 2026-11-13) ----------------------------------------------------------
def _with_mins(rows, mins):
    for r, m in zip(rows, mins):
        r["mins"] = m
    return rows


def test_min_minutes_slider_values_and_default():
    """Owner 2026-11-13: a slider from 450 in steps of 90; anything else is the default."""
    assert pp.MIN_MINUTES[0] == 450 and pp.MINUTES_STEP == 90
    assert pp.min_minutes(None) == 450 and pp.min_minutes("bad") == 450
    assert pp.min_minutes("900") == 900 and pp.min_minutes("1350") == 1350 and pp.min_minutes("2970") == 2970
    assert pp.min_minutes("1000") == 450 and pp.min_minutes("360") == 450 and pp.min_minutes("-90") == 450


def test_min_minutes_slider_top_is_the_pools_most_minutes_rounded_up_to_90():
    rows = _with_mins(_xy(_HOB), [1000.0] * 11 + [2001.0])
    assert pp.minutes_max(rows, "a", "b", "") == 2070                 # 2001 -> 23 x 90
    rows[11]["v"]["a"] = None                                          # not plotted: not counted
    assert pp.minutes_max(rows, "a", "b", "") == 1080
    assert pp.minutes_max([], "a", "b", "") == 450


def test_min_minutes_narrows_the_plotted_pool():
    rows = _with_mins(_xy(_HOB), [1000.0] * 11 + [500.0])       # L has 500
    s = pp.scatter_summary(rows, "a", "b", "", min_minutes=900)
    assert len(s["idx"]) == 11 and 11 not in s["idx"]
    assert s["median"]["x"] == 6.0                               # A..K: x median 6
    assert pp.scatter_summary(rows, "a", "b", "")["median"]["x"] == 6.5


def test_min_minutes_below_the_peer_floor_ranks_nobody():
    rows = _with_mins(_xy(_HOB), [2000.0] * 9 + [500.0] * 3)
    s = pp.scatter_summary(rows, "a", "b", "", min_minutes=1800)
    assert len(s["idx"]) == 9 and s["top"] == []
    assert s["top_note"] == "Not rated: only 9 comparable players (needs 10)"


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
