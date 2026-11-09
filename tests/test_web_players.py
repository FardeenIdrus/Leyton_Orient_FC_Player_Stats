"""Players page API (src/lofc/web/api/players.py). Pure parts run anywhere; the parity tests
need the real database and compare the API's rows with what Streamlit's pool gives for the
same filters."""

import re

import pandas as pd
import pytest
from sqlalchemy import create_engine

from lofc.config import settings
from web_fakes import FakeStore, login, make


def _client(role="head_of_recruitment"):
    s = FakeStore()
    s.add(username="u", full_name="Ann Scout", role=role, password="correct-horse-1")
    c, *_ = make(s)
    login(c, "u", "correct-horse-1")
    return c


def _need_db():
    try:
        create_engine(settings.database_url).connect().close()
    except Exception:
        pytest.skip("no database")


# ---- access ----------------------------------------------------------------------------------

@pytest.mark.parametrize("path", ["/api/players", "/api/players/options", "/api/players/metrics",
                                  "/api/players/search?q=a", "/api/players.csv",
                                  "/api/players/wage"])
def test_every_endpoint_needs_a_session(path):
    c, *_ = make()
    assert c.get(path).status_code == 401


def test_page_needs_a_session_and_has_every_control():
    c, *_ = make()
    assert c.get("/players").status_code == 303
    html = _client().get("/players").text
    for label in ("Search a player", "Season", "Position", "Leagues", "Rank as", "More filters",
                  "Metric filters", "Minimum minutes", "Maximum age", "Preferred foot",
                  "Contract expiry", "Loan status", "Playing style", "Strong only",
                  "Show affordability (modelled)", "Transfer budget (€m)", "Wage budget (× club ceiling)",
                  "Reset metric filters", "Rank on scout-verified rating",
                  "Signed-off assessments only", "Only signable players",
                  "Download this list (CSV)", "About this list", "Not ranked", "✕ Clear"):
        assert label in html, label
    assert re.search(r'<script type="module" src="/static/v/[0-9a-f]+/js/players.js">', html)
    assert not re.search(r"<script(?![^>]*\bsrc=)", html) and not re.search(r"\son[a-z]+=", html)


# ---- query parsing (no database) -------------------------------------------------------------

@pytest.fixture
def parsed(monkeypatch):
    from lofc.core import players_pool as pp
    from lofc.dashboard import loaders as L
    from lofc.web.api import players as api
    monkeypatch.setattr(L, "available_seasons", lambda: [319, 318, 317])
    monkeypatch.setattr(L, "league_names", lambda: ["Championship", "League One", "League Two"])
    monkeypatch.setattr(pp, "minutes_bounds", lambda: {"min": 450, "max": 4000, "step": 10, "default": 450})
    from starlette.datastructures import QueryParams
    return lambda qs: api.Query(QueryParams(qs))


def test_defaults_open_on_the_live_season_centre_forward(parsed):
    q = parsed("")
    f = q.filters()
    assert (f.season_id, f.position, f.archetype, f.min_minutes, f.max_age) == (
        319, "Centre Forward", "All Metrics", 450, 40)
    assert f.leagues == () and f.budget_eur == float("inf") and f.wage_multiplier == 1.0


def test_junk_and_out_of_range_values_fall_back_to_defaults(parsed):
    q = parsed("season=1&position=Striker&rank_as=Nope&min_minutes=-5&max_age=3&foot=Both"
               "&contract=x&loan=y&style=z&budget=abc&leagues=Atlantis")
    f = q.filters()
    assert (f.season_id, f.position, f.min_minutes, f.max_age, f.foot) == (319, "Centre Forward", 450, 18, "Any")
    assert f.leagues == () and f.style == "All styles"


def test_rank_as_only_for_positions_that_have_it_and_style_must_fit_the_position(parsed):
    assert parsed("position=Centre%20Back&rank_as=Attacking").archetype == "All Metrics"
    assert parsed("position=Full%20Back&rank_as=Attacking").archetype == "Attacking"
    assert parsed("position=Centre%20Forward&style=Dribbler").style == "All styles"
    assert parsed("position=Winger&style=1v1&strong_only=1").strong_only is True
    assert parsed("strong_only=1").strong_only is False       # no style chosen -> nothing to be strong in


def test_all_leagues_selected_means_no_league_filter(parsed):
    assert parsed("leagues=Championship&leagues=League%20One&leagues=League%20Two").leagues == ()
    assert parsed("leagues=League%20Two").leagues == ("League Two",)


def test_metric_filter_params_are_collected(parsed):
    q = parsed("pct_xa_p90=70&raw_top5_psv99_kmh=31.5&pct_bad=zz")
    assert q.pct == {"xa_p90": 70.0} and q.raw == {"top5_psv99_kmh": 31.5}


def test_money_off_ignores_budget_and_wage(parsed):
    f = parsed("budget=2&wage=9000").filters()
    assert f.budget_eur == float("inf") and f.wage_multiplier == 1.0


# ---- pure core pieces -------------------------------------------------------------------------

def test_wage_slider_and_pounds_convert_like_the_streamlit_control():
    from lofc.core import players_pool as pp
    assert pp.wage_pounds_from_slider(2.0, 6000.0) == 12000
    assert pp.wage_slider_from_pounds(6000, 6000.0) == 1.0
    assert pp.wage_slider_from_pounds(1, 6000.0) == 0.5            # clamped to 0.5
    assert pp.wage_slider_from_pounds(10 ** 6, 6000.0) == 25.0     # clamped to 25
    assert pp.wage_slider_from_pounds(11500, 6000.0) == 2.0        # snapped to the 0.5 step


def _table():
    return pd.DataFrame({
        "#": [1, 2, 3, 4], "Player": ["b", "A", "c", "d"], "age": [30.0, None, 20.0, 25.0],
        "Age": ["30.0", "—", "20.0", "25.0"], "minutes": [900, 1000, 800, 700],
        "Mins": [900, 1000, 800, 700], "Composite": [4.0, 3.0, None, 2.0],
        "Style": [["x"], [], ["a", "b"], None]})


def test_sort_uses_values_not_text_blanks_last_ranking_numbers_kept():
    from lofc.core import players_pool as pp
    t = pp._sorted(_table(), "Age", False)
    assert list(t["#"]) == [3, 4, 1, 2]                 # 20, 25, 30, then the blank
    t = pp._sorted(_table(), "Age", True)
    assert list(t["#"]) == [1, 4, 3, 2]                 # blank still last
    t = pp._sorted(_table(), "Player", False)
    assert list(t["Player"]) == ["A", "b", "c", "d"]    # case-insensitive
    t = pp._sorted(_table(), "Composite", True)
    assert list(t["#"]) == [1, 2, 4, 3]


def test_cells_never_leak_nan_or_none():
    from lofc.core import players_pool as pp
    for v in (float("nan"), None, pd.NA, pd.NaT):
        assert pp._clean(v) is None
    assert pp._clean(["a", "b"]) == ["a", "b"] and pp._clean(3) == 3


def test_csv_filename_matches_streamlit():
    from lofc.core import players_pool as pp
    assert pp.csv_filename("Centre Forward") == "lofc_players_centre_forward.csv"


def test_hidden_text_matches_streamlit_notice():
    from lofc.core import players_pool as pp
    from lofc.dashboard.tabs.players import hidden_notice
    assert hidden_notice(5) == "#### " + pp.hidden_text(5)
    assert pp.hidden_text(0) is None


def test_metric_values_apply_with_todays_semantics(monkeypatch):
    """Percentile active above 0; a Min slider active only off its floor, a Max slider off its
    ceiling; players with no value on an active filter are counted, not silently dropped."""
    from lofc.core import players_pool as pp
    from lofc.dashboard import loaders as L
    pool = pd.DataFrame({"player_id": [1, 2, 3, 4], "competition_id": [9] * 4,
                         "season_id": [318] * 4, "position_group": ["Winger"] * 4})
    raw = pd.DataFrame({"player_id": [1, 2, 3, 4], "competition_id": [9] * 4,
                        "top5_psv99_kmh": [30.0, 32.0, None, 34.0],
                        "time_to_sprint": [4.0, 4.5, 4.2, 5.0]})
    pcts = pd.DataFrame({"player_id": [1, 2, 3, 4], "competition_id": [9] * 4,
                         "season_id": [318] * 4, "position_group": ["Winger"] * 4,
                         "xa_p90": [10.0, 80.0, 90.0, 70.0]})
    monkeypatch.setattr(pp, "_raw", lambda s, p: raw)
    monkeypatch.setattr(L, "load_scorecard_percentiles", lambda s: pcts)
    monkeypatch.setattr(pp.metric_filters, "performance_slider_metrics", lambda p, a: ["xa_p90"])
    # at rest: nothing active
    out, hidden = pp.apply_metric_values(pool, 318, "Winger", "All Metrics", {"xa_p90": 0},
                                         {"top5_psv99_kmh": 30.0, "time_to_sprint": 5.0})
    assert len(out) == 4 and hidden == 0
    out, hidden = pp.apply_metric_values(pool, 318, "Winger", "All Metrics", {"xa_p90": 70}, {})
    assert list(out["player_id"]) == [2, 3, 4] and hidden == 0
    out, hidden = pp.apply_metric_values(pool, 318, "Winger", "All Metrics", {},
                                         {"top5_psv99_kmh": 31.0})
    assert list(out["player_id"]) == [2, 4] and hidden == 1      # player 3 has no top speed
    out, hidden = pp.apply_metric_values(pool, 318, "Winger", "All Metrics", {},
                                         {"time_to_sprint": 4.4})   # Max slider moved off ceiling 5.0
    assert list(out["player_id"]) == [1, 3] and hidden == 0


# ---- real database: parity with what Streamlit shows -----------------------------------------

def _legacy(**kw):
    from test_core_players_pool import legacy_pool
    return legacy_pool(**kw)


def _displayed(pool):
    """The order Streamlit's table shows: `_players` sorts the pool a SECOND time (quicksort is
    not stable, so tied composites can swap places against the first sort)."""
    return pool.sort_values("objective_composite", ascending=False,
                            na_position="last").reset_index(drop=True)


COMBOS = [
    ("season=318&position=Centre%20Forward", dict(season_id=318, position="Centre Forward")),
    ("season=318&position=Winger&rank_as=Direct%20%26%201v1%20Specialist",
     dict(season_id=318, position="Winger", archetype="Direct & 1v1 Specialist")),
    ("season=317&position=Full%20Back&loan=On%20loan%20now",
     dict(season_id=317, position="Full Back", loan_choice="On loan now")),
    ("season=318&position=Centre%20Back&max_age=25&foot=Left",
     dict(season_id=318, position="Centre Back", max_age=25, foot_choice="Left")),
    ("season=318&position=Goalkeeper&min_minutes=1500",
     dict(season_id=318, position="Goalkeeper", min_minutes=1500)),
]


@pytest.mark.parametrize("qs,legacy", COMBOS, ids=[c[1]["position"] + str(c[1]["season_id"]) for c in COMBOS])
def test_api_rows_are_the_streamlit_pool_in_the_same_order(qs, legacy):
    _need_db()
    d = _client().get("/api/players?" + qs).json()
    old = _displayed(_legacy(**legacy)["pool"])
    assert [r["id"][0] for r in d["rows"]] == list(old["player_id"])
    assert d["count_caption"] == f"**{len(old)}** {legacy['position']}s ranked."
    assert [r["cells"]["Player"] for r in d["rows"]] == list(old["player_name"])


def test_columns_and_cell_formats_are_todays():
    _need_db()
    from lofc.dashboard.tabs.players import players_table_columns
    d = _client().get("/api/players?season=318&position=Winger&rank_as=Direct%20%26%201v1%20Specialist").json()
    keys = [c["key"] for c in d["columns"]]
    assert keys == players_table_columns(lens=True, show_money=False, loan_column=False)
    assert [c["label"] for c in d["columns"]][keys.index("Composite")] == "Composite (Direct & 1v1 Specialist)"
    assert "All-round" in keys
    for r in d["rows"][:300]:
        c = r["cells"]
        assert c["Age"] == "—" or re.fullmatch(r"\d\d\.\d", c["Age"])
        assert c["Composite"] is None or re.fullmatch(r"[1-5]\.\d\d", c["Composite"])
        assert isinstance(c["Mins"], int) and c["Mins"] >= 450
        assert c["Top speed"] == "—" or re.fullmatch(r"\d\d\.\d", c["Top speed"])
        assert isinstance(c["Style"], list)
    bad = {"nan", "NaN", "None", "null", "undefined"}
    for r in d["rows"]:
        assert not [v for v in r["cells"].values() if isinstance(v, str) and v.strip() in bad]


def test_composite_is_the_objective_composite_in_descending_order():
    _need_db()
    d = _client().get("/api/players?season=318&position=Centre%20Back").json()
    vals = [float(r["cells"]["Composite"]) for r in d["rows"] if r["cells"]["Composite"]]
    assert vals == sorted(vals, reverse=True)


def test_money_columns_only_with_money_on_and_caption_counts():
    _need_db()
    c = _client()
    off = c.get("/api/players?season=318&position=Winger").json()
    on = c.get("/api/players?season=318&position=Winger&money=1&budget=5").json()
    keys_on = [x["key"] for x in on["columns"]]
    assert all(k not in [x["key"] for x in off["columns"]] for k in
               ("Market value", "Est. wage", "Below fair value", "Fee in budget", "Wages in budget"))
    assert keys_on[-5:] == ["Market value", "Est. wage", "Below fair value", "Fee in budget", "Wages in budget"]
    m = on["money_count"]
    assert on["count_caption"].startswith(f"**{m['total']}** Wingers · **{m['fee']}** within the transfer budget")
    assert on["money"]["note"].startswith("Affordable = both")
    assert on["signable"] == (m["both"] > 0)
    # signable default = on when any qualify: the list is the qualifying subset
    assert len(on["rows"]) == (m["both"] if m["both"] else m["total"])
    allp = c.get("/api/players?season=318&position=Winger&money=1&budget=5&signable=0").json()
    assert len(allp["rows"]) == m["total"]
    assert all(r["cells"]["Fee in budget"] and r["cells"]["Wages in budget"] for r in on["rows"]) or not m["both"]
    assert off["money"] is None and off["affordable_now"] is None and on["affordable_now"] == m["both"]


def test_money_parity_with_streamlit_gates():
    _need_db()
    old = _legacy(season_id=318, position="Centre Back", budget_eur=5_000_000.0, wage_multiplier=2.0)["pool"]
    ceiling = None
    from lofc.core import players_pool as pp
    ceiling = pp.prime_ceiling("Centre Back")
    d = _client().get(f"/api/players?season=318&position=Centre%20Back&money=1&budget=5&wage={int(2 * ceiling)}"
                      "&signable=0").json()
    m = d["money_count"]
    assert m["total"] == len(old) and m["fee"] == int(old["affordable_fee"].sum())
    assert m["wage"] == int(old["affordable_wage"].sum()) and m["both"] == int(old["qualifies"].sum())


def test_metric_filter_hidden_count_and_rows_match_streamlit_function():
    _need_db()
    from lofc.dashboard import loaders as L
    from lofc.dashboard import metric_filters as mf
    old = _legacy(season_id=318, position="Winger")["pool"]
    pcts = L.load_scorecard_percentiles(318)
    in_pos = pcts.loc[pcts["position_group"] == "Winger", ["player_id", "competition_id"]]
    raw = L.load_metric_values(318).merge(in_pos, on=["player_id", "competition_id"])
    expect, unknown = mf.apply_metric_filters(old, pcts, raw, {"xa_p90": 70.0}, {"top5_psv99_kmh": 31.0}, {})
    expect = _displayed(expect)
    d = _client().get("/api/players?season=318&position=Winger&pct_xa_p90=70&raw_top5_psv99_kmh=31").json()
    assert [r["id"][0] for r in d["rows"]] == list(expect["player_id"])
    assert d["hidden"] == unknown
    assert d["hidden_text"] == (f"{unknown} hidden: no data for an active metric filter." if unknown else None)
    assert d["hidden"] > 0                 # Top speed is missing for many wingers: the notice must show


def test_metric_spec_matches_the_streamlit_sliders():
    _need_db()
    from lofc.dashboard import metric_filters as mf
    spec = _client().get("/api/players/metrics?season=318&position=Winger").json()
    groups = [g["group"] for g in spec["physical"]]
    assert groups == [g for g in mf.PHYSICAL_GROUPS if g in groups]
    labels = {s["metric"]: s["label"] for g in spec["physical"] for s in g["sliders"]}
    for m, l in labels.items():
        kind = "Max" if m in mf.LOWER_IS_BETTER_PHYSICAL else "Min"
        assert l == f"{kind} {mf.PHYSICAL_LABELS[m][0]}"
    for g in spec["physical"]:
        for s in g["sliders"]:
            assert s["rest"] == (s["max"] if s["kind"] == "Max" else s["min"]) and s["min"] < s["max"]
    assert [p["metric"] for p in spec["performance"]] == mf.performance_slider_metrics("Winger", "All Metrics")
    gk = _client().get("/api/players/metrics?season=318&position=Goalkeeper").json()
    assert gk["physical"] == []                      # goalkeepers have no physical sliders


def test_thin_pools_are_withheld_named_and_announced_never_ranked():
    _need_db()
    from lofc.dashboard import loaders as L
    if 319 not in L.available_seasons():
        pytest.skip("no live season")
    d = _client().get("/api/players?season=319&position=Centre%20Forward").json()
    old = _legacy(season_id=319, position="Centre Forward")
    assert len(d["not_ranked"]["rows"]) == len(old["withheld"])
    assert {r["name"] for r in d["not_ranked"]["rows"]} == set(old["withheld"]["player_name"])
    ranked = {r["id"][0] for r in d["rows"]}
    assert not ranked & set(old["withheld"]["player_name"].index)  # sanity
    if len(old["withheld"]):
        assert d["notice"] is not None            # seasons.ranking_notice is surfaced


def test_default_season_is_the_live_one_and_options_are_streamlits():
    _need_db()
    from lofc.dashboard import loaders as L
    from lofc.dashboard import seasons as S
    o = _client().get("/api/players/options").json()
    assert o["default_season"] == max(L.available_seasons())
    assert [s["id"] for s in o["seasons"]] == L.available_seasons()
    assert o["leagues"] == L.league_names()
    assert o["contract"] == list(S.CONTRACT_HORIZONS) and o["loan"] == S.LOAN_FILTERS
    assert o["default_position"] == "Centre Forward" and len(o["positions"]) == 8
    assert o["archetypes"]["Winger"] == ["All Metrics", "Direct & 1v1 Specialist", "Crossing & Creative Threat"]
    assert o["archetypes"]["Goalkeeper"] == ["All Metrics"] and o["styles"]["Goalkeeper"] == []
    assert o["minutes"]["max"] >= 900


def test_assessed_mode_renames_the_column_and_explains_itself():
    _need_db()
    d = _client().get("/api/players?season=318&position=Winger&assessed=1&signed_only=1").json()
    comp = next(c for c in d["columns"] if c["key"] == "Composite")
    assert comp["label"] == "Scout-verified rating" and "assessed ranking" in comp["help"]
    assert d["assessed_caption"]
    ids = [r["id"][0] for r in d["rows"]]
    assert len(ids) == len(set(ids))


def test_contract_filter_caption_and_hidden_count():
    _need_db()
    d = _client().get("/api/players?season=318&position=Centre%20Back&contract=Out%20of%20contract%20summer%202027").json()
    assert d["contract_caption"].startswith("Contract filter: **Out of contract summer 2027** —")
    assert "expiring by 2027-06-30" in d["contract_caption"]
    old = _legacy(season_id=318, position="Centre Back", contract_horizon="Out of contract summer 2027")
    assert f"**{old['contract_unknown']} hidden**" in d["contract_caption"]
    assert [r["id"][0] for r in d["rows"]] == list(_displayed(old["pool"])["player_id"])


def test_sorting_orders_by_the_value_and_keeps_ranking_numbers():
    _need_db()
    d = _client().get("/api/players?season=318&position=Centre%20Back&sort=Age&dir=asc").json()
    ages = [None if r["cells"]["Age"] == "—" else float(r["cells"]["Age"]) for r in d["rows"]]
    known = [a for a in ages if a is not None]
    assert known == sorted(known) and ages[:len(known)] == known     # blanks last
    base = _client().get("/api/players?season=318&position=Centre%20Back").json()
    assert sorted(r["cells"]["#"] for r in d["rows"]) == [r["cells"]["#"] for r in base["rows"]]
    assert d["sort"] == {"column": "Age", "descending": False}


def test_csv_is_the_displayed_columns_with_streamlits_filename():
    _need_db()
    c = _client()
    r = c.get("/api/players.csv?season=318&position=Centre%20Back")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert 'filename="lofc_players_centre_back.csv"' in r.headers["content-disposition"]
    d = c.get("/api/players?season=318&position=Centre%20Back").json()
    header = r.text.splitlines()[0].split(",")
    assert header == [x["key"] for x in d["columns"]]
    assert len(r.text.strip().splitlines()) == len(d["rows"]) + 1


def test_search_spans_every_position_and_ignores_accents():
    _need_db()
    r = _client().get("/api/players/search?season=318&q=mendez").json()["results"]
    assert any("Méndez-Laing" in x["name"] for x in r)
    assert len({x["position"] for x in r}) >= 2                      # not limited to one position
    assert all({"label", "player_id", "competition_id", "season_id", "position", "league"} <= set(x) for x in r)
    assert _client().get("/api/players/search?season=318&q=").json() == {"results": []}
    assert _client().get("/api/players/search?season=318&q=zzzz-no-such").json()["results"] == []


def test_wage_endpoint_syncs_slider_and_pounds():
    _need_db()
    from lofc.core import players_pool as pp
    ceil = pp.prime_ceiling("Winger")
    a = _client().get("/api/players/wage?position=Winger&x=2").json()
    assert a["wage"] == int(round(2 * ceil)) and a["wage_x"] == 2.0
    b = _client().get(f"/api/players/wage?position=Winger&gbp={int(ceil)}").json()
    assert b["wage_x"] == 1.0


def test_same_query_is_answered_from_the_cache_except_the_assessed_ranking():
    _need_db()
    c = _client()
    a = c.get("/api/players?season=318&position=Centre%20Back").json()
    b = c.get("/api/players?season=318&position=Centre%20Back").json()
    assert a == b and a["ms"] == b["ms"]                 # second answer is the stored one
    x = c.get("/api/players?season=318&position=Centre%20Back&assessed=1").json()
    y = c.get("/api/players?season=318&position=Centre%20Back&assessed=1").json()
    assert x["rows"] == y["rows"] and x["assessed_caption"]


def test_metric_filters_do_not_change_the_cached_pool_or_other_lists():
    _need_db()
    c = _client()
    base = c.get("/api/players?season=318&position=Winger").json()
    c.get("/api/players?season=318&position=Winger&pct_xa_p90=90")
    again = c.get("/api/players?season=318&position=Winger&sort=Age&dir=asc").json()
    assert sorted(r["id"][0] for r in again["rows"]) == sorted(r["id"][0] for r in base["rows"])
