"""Physical page: the squad card's "Performance" view (owner 2026-11-13, mock-up tab 1).

Our current squad's RATED players (All Metrics scorecard with an Overall, peer floor applied),
grouped GK, CB, FB, Midfield, W, CF, best Overall first; each with his strongest and weakest
three of his position's Performance metrics, by the card's scorecard percentiles (the card's
own Strengths / Watch-outs rule). Pure core tests + the API over faked sources; real-database
parity with the card is in test_physical_performance_view_parity.py."""
import io

import openpyxl
import pandas as pd
import pytest

from lofc.core import physical_page as core
from lofc.model import scorecard

CB = scorecard._resolved_performance("Centre Back")
GK = scorecard._resolved_performance("Goalkeeper")


def _frames():
    squad = pd.DataFrame({
        "player_id": [1, 2, 3, 4, 5, 6, 7, 8],
        "player_name": ["Keeper", "Back Low", "Back High", "Holder", "Loanee", "Thin Man",
                        "No Row", "Playmaker"],
        "position_group": ["Goalkeeper", "Centre Back", "Centre Back", "Defensive Mid",
                           "Centre Back", "Winger", "Winger", "Attacking Mid"]})
    rows = pd.DataFrame({
        "player_id": [1, 2, 3, 4, 5, 6, 8],
        "competition_id": [4, 4, 4, 4, 5, 903, 4],
        "position_group": ["Goalkeeper", "Centre Back", "Centre Back", "Defensive Mid",
                           "Centre Back", "Winger", "Attacking Mid"],
        "minutes": [3000.0, 900.0, 2000.0, 1200.0, 1500.0, 800.0, 700.0],
        "objective_composite": [3.1, 2.4, 3.6, 2.9, 3.3, None, 3.05],
        "performance_band": [3.1, 2.5, 3.9, 3.0, 3.2, None, 3.1],
        "physical_band": [None, 2.2, 3.2, 2.7, 3.4, None, 3.0],
        "thin": [False, False, False, False, False, True, False],
        "peer_count": [30.0, 40.0, 40.0, 30.0, 30.0, 6.0, 30.0]}).set_index("player_id")
    keys = ["player_id", "competition_id", "season_id", "position_group"]
    recs = []
    # Back High: distinct percentiles; turnovers high (= few turnovers, already inverted)
    hi = {m: 50.0 for m in CB}
    hi.update(blocks_p90=98.4, turnovers_p90=91.0, aerial_win_pct=87.0,
              deep_progressions_p90=2.0, pass_value_p90=6.4, ball_wins_p90=17.0)
    recs.append(dict(zip(keys, [3, 4, 319, "Centre Back"]), **hi))
    # Back Low: every metric 40 except one tie at the top and a tie at the bottom
    lo = {m: 40.0 for m in CB}
    lo.update(ball_wins_p90=80.0, aerial_win_pct=80.0, ground_duel_win_pct=10.0,
              counterpressures_p90=10.0)
    recs.append(dict(zip(keys, [2, 4, 319, "Centre Back"]), **lo))
    recs.append(dict(zip(keys, [5, 5, 319, "Centre Back"]), **{m: 60.0 for m in CB}))
    g = {m: None for m in GK}
    g.update(gk_gsaa_p90=52.0, gk_shot_stopping_pct=51.6)          # only two with a figure
    recs.append(dict(zip(keys, [1, 4, 319, "Goalkeeper"]), **g))
    recs.append(dict(zip(keys, [4, 4, 319, "Defensive Mid"]),
                     **{m: 55.0 for m in scorecard._resolved_performance("Defensive Mid")}))
    recs.append(dict(zip(keys, [8, 4, 319, "Attacking Mid"]),
                     **{m: 45.0 for m in scorecard._resolved_performance("Attacking Mid")}))
    pcts = pd.DataFrame(recs)
    return squad, rows, pcts


NAMES = {4: "League One", 5: "League Two", 903: "Premier League 2"}


def _href(p, c, s):
    return f"/player/{p}/{c}/{s}"


def _view():
    squad, rows, pcts = _frames()
    return core.performance_rows(squad, rows, pcts, 319, NAMES, _href, season_name="2026/27")


def _all(v):
    return {r["name"]: r for g in v["groups"] for r in g["rows"]}


def test_groups_in_order_and_best_overall_first():
    v = _view()
    assert [g["group"] for g in v["groups"]] == ["Goalkeeper", "Centre Back", "Midfield"]
    cb = [r["name"] for r in v["groups"][1]["rows"]]
    assert cb == ["Back High", "Loanee", "Back Low"]
    mf = [r["name"] for r in v["groups"][2]["rows"]]
    assert mf == ["Playmaker", "Holder"]


def test_unrated_are_counted_not_listed():
    v = _view()
    rows = _all(v)
    assert "Thin Man" not in rows and "No Row" not in rows
    assert v["unrated"] == 2
    assert v["unrated_t"] == "2 squad players not rated in 2026/27 (under 450 minutes or too few peers)"


def test_row_fields():
    r = _all(_view())["Back High"]
    assert r["href"] == "/player/3/4/319"
    assert r["mins_t"] == "2,000"
    assert (r["overall"], r["perf"], r["phys"]) == (3.6, 3.9, 3.2)
    assert r["league"] is None and r["pos_tag"] is None   # League One centre back: no tags
    k = _all(_view())["Keeper"]
    assert k["phys"] is None


def test_strongest_and_weakest_three():
    r = _all(_view())["Back High"]
    assert r["strong"] == [{"label": "Blocks", "pct": 98},
                           {"label": "Turnovers (fewer is better)", "pct": 91},
                           {"label": "Aerial win %", "pct": 87}]
    assert r["weak"] == [{"label": "Deep progressions", "pct": 2},
                         {"label": "Pass value (PxT)", "pct": 6},
                         {"label": "Ball wins", "pct": 17}]


def test_ties_keep_the_position_metric_order():
    """Equal percentiles keep the position's metric order (the card's stable sort); a metric
    already in Strongest 3 is never in Weakest 3 (owner 2026-11-13)."""
    r = _all(_view())["Back Low"]
    assert r["strong"] == [{"label": "Ball wins", "pct": 80}, {"label": "Aerial win %", "pct": 80},
                           {"label": "Pressures", "pct": 40}]
    assert r["weak"] == [{"label": "Ground-duel win %", "pct": 10},
                         {"label": "Counterpressures", "pct": 10},
                         {"label": "Defensive-action value (PxT)", "pct": 40}]


def test_same_rule_as_the_card():
    """The card's Strengths / Watch-outs (core.card.strengths_watchouts) on the same row."""
    from lofc.core.card import strengths_watchouts
    from lofc.dashboard.labels import LABELS
    squad, rows, pcts = _frames()
    prow = pcts[pcts["player_id"] == 3].iloc[0]
    card = strengths_watchouts(prow, CB, lambda m: LABELS.get(m, m))
    r = _all(_view())["Back High"]
    assert [x["pct"] for x in r["strong"]] == [x["pct"] for x in card["strengths"]]
    assert [x["pct"] for x in r["weak"]] == [x["pct"] for x in card["watch_outs"]]


def test_goalkeeper_with_two_figures():
    """Two figures (Nathan Baxter, 2026/27): one strongest, one weakest, never the same metric."""
    k = _all(_view())["Keeper"]
    assert k["strong"] == [{"label": "Goals saved above average", "pct": 52}]
    assert k["weak"] == [{"label": "Shot stopping %", "pct": 52}]


@pytest.mark.parametrize("n, n_strong, n_weak", [
    (1, 0, 0), (2, 1, 1), (3, 2, 1), (4, 2, 2), (5, 3, 2), (6, 3, 3), (9, 3, 3)])
def test_strongest_and_weakest_never_overlap(n, n_strong, n_weak):
    """Fewer than six rated metrics: strongest = the top ceil(n/2) (max 3), weakest = the rest
    (max 3), lowest first. Under two: none (the card's rule)."""
    metrics = CB[:n]
    prow = pd.Series({m: 90.0 - 10 * i for i, m in enumerate(metrics)})
    sw = core.strong_weak(prow, metrics, lambda m: m)
    strong, weak = [x["label"] for x in sw["strong"]], [x["label"] for x in sw["weak"]]
    assert (len(strong), len(weak)) == (n_strong, n_weak)
    assert not set(strong) & set(weak)
    assert strong == metrics[:n_strong]
    assert weak == list(reversed(metrics))[:n_weak]


def test_other_league_and_midfield_tags():
    rows = _all(_view())
    lo = rows["Loanee"]
    assert lo["league"] == "League Two"
    assert lo["league_tip"] == "Percentiles vs League Two Centre Backs"
    assert lo["href"] == "/player/5/5/319"
    assert rows["Holder"]["pos_tag"] == "Defensive Mid"
    assert rows["Playmaker"]["pos_tag"] == "Attacking Mid"


def test_unrated_line_wording():
    """The line names the season shown (owner 2026-11-13), not "this season"."""
    assert core.unrated_text(0, "2026/27") is None
    assert core.unrated_text(1, "2026/27") == ("1 squad player not rated in 2026/27 "
                                               "(under 450 minutes or too few peers)")
    assert core.unrated_text(15, "2025/26") == ("15 squad players not rated in 2025/26 "
                                                "(under 450 minutes or too few peers)")


# --- the API (faked sources) -------------------------------------------------------------------
@pytest.fixture
def fake(monkeypatch):
    import test_web_physical as twp
    from lofc.web.api import physical as api
    src = twp.install_fake(monkeypatch)
    squad, rows, pcts = _frames()
    src.squad = lambda: squad
    src.rated_rows = lambda s: rows
    src.perf_pcts = lambda s: pcts
    src.league_names = lambda: NAMES
    yield src
    api.clear()


def _client():
    from web_fakes import FakeStore, login, make
    s = FakeStore()
    s.add(username="u", full_name="Ann Scout", role="scout", password="correct-horse-1")
    c, *_ = make(s)
    login(c, "u", "correct-horse-1")
    return c


def test_api_carries_the_performance_view(fake):
    d = _client().get("/api/physical?season=319").json()
    p = d["perf"]
    assert [g["group"] for g in p["groups"]] == ["Goalkeeper", "Centre Back", "Midfield"]
    assert p["unrated"] == 2
    assert p["unrated_t"] == "2 squad players not rated in 2026/27 (under 450 minutes or too few peers)"
    assert p["sub"] == "2026/27 · rated players · percentile vs his league and position"
    r = p["groups"][1]["rows"][0]
    assert r["name"] == "Back High" and r["strong"][0] == {"label": "Blocks", "pct": 98}
    assert "NaN" not in _client().get("/api/physical?season=319").text
    # the Physical view's subtitle is unchanged
    assert d["squad"]["sub"] == "2026/27 · percentile vs his league and position"


def test_page_has_the_switch(fake):
    html = _client().get("/physical").text
    assert 'id="sq-view"' in html and 'id="sq-perf"' in html
    assert 'id="sq-xlsx"' in html


# --- the workbook's Age column (owner 2026-11-13) ---------------------------------------------
def test_workbook_age_always_one_decimal():
    squad = pd.DataFrame({"player_id": [1, 2], "player_name": ["A", "B"],
                          "position_group": ["Winger", "Winger"],
                          "birth_date": pd.to_datetime(["1998-01-01", "2005-01-01"])})
    rows = pd.DataFrame({"player_id": [1], "competition_id": [4], "position_group": ["Winger"],
                         "minutes": [900.0], "objective_composite": [3.0],
                         "performance_band": [3.0], "physical_band": [3.0],
                         "thin": [False]}).set_index("player_id")
    ages = iter([28.0, 21.9])
    out = core.squad_export_rows(squad, rows, lambda *a: (1, 20), lambda *a: None,
                                 age_of=lambda b: next(ages))
    ws = openpyxl.load_workbook(io.BytesIO(core.squad_xlsx(out))).active
    col = [c.value for c in ws[1]].index("Age") + 1
    cells = [ws.cell(row=i, column=col) for i in (2, 3)]
    assert sorted(float(c.value) for c in cells) == [21.9, 28.0]
    assert all(c.number_format == "0.0" and c.data_type == "n" for c in cells)
