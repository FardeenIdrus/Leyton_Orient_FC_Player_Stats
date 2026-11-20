"""The Players pool lives in lofc.core.players_pool so Streamlit and the web front end rank the
same list. `legacy_pool` below is a frozen copy of what `dashboard/app.py::main()` computed
inline BEFORE the lift (steps in the same order, same loaders); the lifted function must give
the identical frames for several filter combinations on the real database."""

import pandas as pd
import pytest
from sqlalchemy import create_engine

from lofc.config import settings


def _need_db():
    try:
        create_engine(settings.database_url).connect().close()
    except Exception:
        pytest.skip("no database")


def legacy_pool(season_id, position, archetype="All Metrics", min_minutes=450, max_age=40,
                chosen_leagues=(), contract_horizon="Any", loan_choice="Any", foot_choice="Any",
                style_choice="All styles", strong_only=False, budget_eur=float("inf"),
                wage_multiplier=1.0):
    """Verbatim copy of the pre-lift inline code (app.py::main, lines ~273-362)."""
    from lofc.constrain.filters import apply_gates
    from lofc.dashboard.loaders import (
        load_candidates, load_current_clubs, load_loan_status, load_scorecards,
        load_scorecards_archetype, load_style_labels)
    from lofc.dashboard.search import build_search_index
    from lofc.dashboard.seasons import contract_mask, loan_mask
    from lofc.model import club_framework as cf
    from lofc.model import styles as styles_mod
    from lofc.model.scorecard import MIN_PEERS_FOR_RANKING, peer_pool_sizes, with_peer_counts

    chosen_leagues = list(chosen_leagues)
    candidates = load_candidates(wage_multiplier, season_id)
    search_index = build_search_index(candidates)
    age_ok = (candidates["age"] <= max_age) | candidates["age"].isna()
    candidates = candidates[age_ok]
    if chosen_leagues:
        candidates = candidates[candidates["league"].isin(chosen_leagues)]
    contract_unknown = 0
    mask = contract_mask(candidates["contract_until"], contract_horizon)
    if mask is not None:
        in_position = candidates["position_group"] == position
        contract_unknown = int((candidates["contract_until"].isna() & in_position).sum())
        candidates = candidates[mask]
    if foot_choice != "Any":
        candidates = candidates[candidates["foot"].isin([foot_choice.lower(), "both"])]
    pool = apply_gates(candidates[(candidates["position_group"] == position) &
                                  (candidates["minutes"] >= min_minutes)], budget_eur)
    keys3 = ["player_id", "competition_id", "season_id"]
    sc_cols = keys3 + ["objective_composite", "full_composite", "objective_weight_covered",
                       "performance_band", "physical_band", "financial_band", "resale_band",
                       "psychological_band", "medical_band", "veto", "below_min_composite"]
    all_round = load_scorecards(season_id)[keys3 + ["objective_composite"]].rename(
        columns={"objective_composite": "allround_composite"})
    ranking = (load_scorecards(season_id) if archetype == cf.DEFAULT_ARCHETYPE
               else load_scorecards_archetype(position, archetype, season_id))
    pool = pool.merge(ranking[sc_cols], on=keys3, how="left").merge(all_round, on=keys3, how="left")
    _loans = load_loan_status()
    pool = pool.merge(_loans, on="player_id", how="left")
    pool["on_loan"] = pool["on_loan"].fillna(False)
    _loan_filter = loan_mask(pool["on_loan"], pool["loan_ends"], loan_choice)
    if _loan_filter is not None:
        pool = pool[_loan_filter]
    pool["qualifies"] = pool["affordable_fee"] & pool["affordable_wage"]
    pool_sizes = peer_pool_sizes(ranking)
    pool = with_peer_counts(pool, pool_sizes)
    _style = load_style_labels(season_id)
    if not _style.empty:
        _style_cols = keys3 + ["style_label", "tier", "strong_styles", "leans_styles"] + \
            [c for c in _style.columns if c.startswith("fit.")]
        pool = pool.merge(_style[_style_cols], on=keys3, how="left")
        if style_choice != "All styles":
            pool = pool[[styles_mod.has_style(r, style_choice, strong_only)
                         for r in pool.to_dict("records")]]
    _current = load_current_clubs()
    if not _current.empty:
        pool = pool.merge(_current, on="player_id", how="left")
    thin = pool["peer_count"].isna() | (pool["peer_count"] < MIN_PEERS_FOR_RANKING)
    withheld = pool.loc[thin, ["player_name", "team_name", "league"]].copy()
    pool = pool[~thin]
    pool = pool.sort_values("objective_composite", ascending=False, na_position="last").reset_index(drop=True)
    return dict(pool=pool, withheld=withheld, contract_unknown=contract_unknown,
                candidates=candidates, search_index=search_index, ranking=ranking)


def _cases():
    return [
        dict(season_id=318, position="Centre Forward"),
        dict(season_id=318, position="Winger", archetype="Direct & 1v1 Specialist"),
        dict(season_id=317, position="Full Back", loan_choice="On loan now",
             chosen_leagues=("League Two", "League One")),
        dict(season_id=318, position="Centre Back", budget_eur=5_000_000.0, wage_multiplier=2.0),
        dict(season_id=319, position="Defensive Mid", contract_horizon="Out of contract summer 2027",
             foot_choice="Left"),
        dict(season_id=318, position="Attacking Mid", style_choice="Dribbler", strong_only=False),
        dict(season_id=318, position="Goalkeeper", min_minutes=900, max_age=28),
        dict(season_id=318, position="Full Back", archetype="Attacking",
             contract_horizon="Contract already expired (free agents)", loan_choice="Not on loan"),
    ]


@pytest.mark.parametrize("case", _cases(), ids=lambda c: f"{c['season_id']}-{c['position']}")
def test_lifted_pool_equals_the_old_inline_result(case):
    _need_db()
    from lofc.core import players_pool as pp
    from lofc.dashboard import loaders
    if case["season_id"] not in loaders.available_seasons():
        pytest.skip("season not loaded")
    old = legacy_pool(**case)
    f = pp.PoolFilters(
        season_id=case["season_id"], position=case["position"],
        archetype=case.get("archetype", "All Metrics"),
        min_minutes=case.get("min_minutes", 450), max_age=case.get("max_age", 40),
        leagues=tuple(case.get("chosen_leagues", ())),
        contract_horizon=case.get("contract_horizon", "Any"), loan=case.get("loan_choice", "Any"),
        foot=case.get("foot_choice", "Any"), style=case.get("style_choice", "All styles"),
        strong_only=case.get("strong_only", False),
        budget_eur=case.get("budget_eur", float("inf")),
        wage_multiplier=case.get("wage_multiplier", 1.0))
    new = pp.build_pool(f)
    # peer_pool (2026-11-16, the midfield-fallback tag) is the one column the lifted pool adds
    pd.testing.assert_frame_equal(new.pool.drop(columns=["peer_pool"], errors="ignore"),
                                  old["pool"])
    pd.testing.assert_frame_equal(new.withheld, old["withheld"])
    pd.testing.assert_frame_equal(new.candidates, old["candidates"])
    pd.testing.assert_frame_equal(new.search_index, old["search_index"])
    assert new.contract_unknown == old["contract_unknown"]
    assert len(new.pool) > 0 or case["position"] in ("Goalkeeper",) or case["season_id"] == 319 \
        or case.get("contract_horizon", "Any") != "Any" or case.get("loan_choice", "Any") != "Any"


def test_streamlit_main_calls_the_lifted_function():
    """app.py must not carry its own copy of the pool steps any more."""
    from pathlib import Path
    src = (Path(__file__).parents[1] / "src/lofc/dashboard/app.py").read_text()
    assert "build_pool(" in src
    assert "apply_gates(" not in src and "with_peer_counts(" not in src


# --- owner 2026-11-13: the Report's empty search box lists every player of the season A-Z ------
def test_season_players_every_player_a_to_z_with_the_search_key(monkeypatch):
    import pandas as pd
    from lofc.core import players_pool as pp
    from lofc.dashboard.search import build_search_index, filter_labels, fold
    cands = pd.DataFrame({
        "player_id": [3, 1, 2, 4, 5], "competition_id": [5, 4, 4, 9, 4], "season_id": 318,
        "player_name": ["Zak Young", "Nathaniel Méndez-Laing", "Aaron Ball", "Ole Ørsted", "AJ Bridge"],
        "team_name": ["Club Z", "Club M", None, "Club O", "Club B"],
        "position_group": ["Winger", "Winger", "Centre Back", "Full Back", "Winger"],
        "league": ["League Two", "League One", "League One", None, "League One"]})
    idx = build_search_index(cands)
    monkeypatch.setattr(pp, "_search_index_for", lambda version, season: idx)
    monkeypatch.setattr(pp.L, "data_version", lambda **k: "v")
    rows = pp.season_players(318)
    # A-Z as a reader sorts: case and accents ignored ("Aaron" before "AJ")
    assert [r[2] for r in rows] == ["Aaron Ball", "AJ Bridge", "Nathaniel Méndez-Laing", "Ole Ørsted", "Zak Young"]
    assert rows[0][:6] == [2, 4, "Aaron Ball", "Centre Back", "Unknown club", "League One"]
    assert rows[3][5] is None                                     # no league: shown as "—"
    # the key is the server's own fold of the search label: same matches as /api/players/search
    for q in ("mendez", "Méndez", "orsted", "club z", "winger", "league one"):
        want = {l.split(" — ")[0] for l in filter_labels(idx["label"].tolist(), q)}
        got = {r[2] for r in rows if fold(q) in r[6]}
        assert {w.split(" (")[0] for w in want} == got, q


# --- owner 2026-11-20: one tab per chosen league, each ranked within its league ----------------
# Ratings are percentile bands WITHIN league + season + position, so a list ordered across
# leagues by them is invalid (no league-strength adjustment, deliberately).
def _two_league_result():
    from lofc.core import players_pool as pp
    pool = pd.DataFrame({
        "player_id": [1, 2, 3, 4, 5], "competition_id": [8, 9, 8, 9, 9], "season_id": 318,
        "league": ["League One", "League Two", "League One", "League Two", "League Two"],
        "objective_composite": [4.5, 4.4, 3.9, 3.1, 2.0],
        "qualifies": [True, False, False, True, False],
        "affordable_fee": [True, True, False, True, False],
        "affordable_wage": [True, False, False, True, False]})
    withheld = pd.DataFrame({"player_name": ["X", "Y"], "team_name": ["A", "B"],
                             "league": ["League Two", "Championship"]})
    return pp.PoolResult(pool=pool, withheld=withheld, contract_unknown=5,
                         candidates=pool.iloc[0:0], search_index=pool.iloc[0:0],
                         ranking=pool.iloc[0:0],
                         contract_unknown_by_league={"League One": 2, "League Two": 3})


def test_league_result_keeps_only_that_league_in_ranking_order():
    from lofc.core import players_pool as pp
    res = _two_league_result()
    two = pp.league_result(res, "League Two")
    assert list(two.pool["player_id"]) == [2, 4, 5]
    assert list(two.pool.index) == [0, 1, 2]
    assert list(two.withheld["player_name"]) == ["X"]
    assert two.contract_unknown == 3
    assert pp.league_result(res, "Championship").contract_unknown == 0
    assert pp.league_result(res, "Championship").pool.empty


def test_tab_leagues_follow_the_picker_and_drop_leagues_with_nobody():
    from lofc.core import players_pool as pp
    picker = ["Championship", "League One", "League Two", "Scottish Prem"]
    present = {"League Two", "League One", "Championship"}
    assert pp.tab_leagues(picker, (), present) == ["Championship", "League One", "League Two"]
    assert pp.tab_leagues(picker, ("League Two", "League One"), present) == ["League One", "League Two"]
    # a single chosen league is always its tab, even with nobody in it (today's behaviour)
    assert pp.tab_leagues(picker, ("Scottish Prem",), present) == ["Scottish Prem"]
    assert pp.tab_leagues(picker, (), set()) == picker


def test_default_tab_is_league_one_else_the_first():
    from lofc.core import players_pool as pp
    assert pp.default_tab(["Championship", "League One", "League Two"]) == "League One"
    assert pp.default_tab(["Championship", "League Two"]) == "Championship"
    assert pp.default_tab(["Championship", "League Two"], "League Two") == "League Two"
    assert pp.default_tab(["Championship", "League One"], "Atlantis") == "League One"
    assert pp.default_tab([], "League Two") is None


def test_league_counts_are_per_league_after_filters(monkeypatch):
    from lofc.core import players_pool as pp
    from lofc.core import report_page as rp
    res = _two_league_result()
    monkeypatch.setattr(pp, "apply_metric_values",
                        lambda pool, *a, **k: (pool[pool["player_id"] != 3], 0))
    monkeypatch.setattr(rp, "all_player_verdicts", lambda: {})
    req = pp.ListRequest(filters=pp.PoolFilters(season_id=318, position="Winger"))
    assert pp.league_counts(req, res, ["League One", "League Two"]) == {"League One": 1, "League Two": 3}
    # signable is decided per league: League One's only qualifier keeps it, League Two too
    money = pp.ListRequest(filters=req.filters, show_money=True)
    assert pp.league_counts(money, res, ["League One", "League Two"]) == {"League One": 1, "League Two": 1}


def test_csv_is_one_block_per_league_with_league_and_rank_in_league():
    from lofc.core import players_pool as pp
    def lr(league, names):
        t = pd.DataFrame({"#": list(range(1, len(names) + 1)), "Player": names,
                          "League": [league] * len(names), "Composite": [3.0] * len(names)})
        return pp.ListResult(pool=None, table=t, columns=["#", "Player", "League", "Composite"],
                             keys=None, meta={})
    out = pp.csv_by_league([("League One", lr("League One", ["a", "b"])),
                            ("League Two", lr("League Two", ["c"]))]).decode().splitlines()
    assert out == ["League,Rank in league,Player,Composite",
                   "League One,1,a,3.0", "League One,2,b,3.0", "League Two,1,c,3.0"]
