"""The web "Club vs League One" page: shell, login, and the API's shape on fake frames.
Real-database parity: tests/test_web_club_vs_league_parity.py."""
import types

import pandas as pd
import pytest

from lofc.core import club_vs_league as cv
from lofc.web.api import club_vs_league as api
from web_fakes import FakeStore, login, make

CUR, PREV = 319, 318
CLUBS = ["Leyton Orient"] + [f"Club {c}" for c in "ABCDEFGH"]


def _frames():
    cards, neutral, pid = [], [], 100
    for season in (CUR, PREV):
        for k, club in enumerate(CLUBS):
            for pos in ("Winger", "Centre Back", "Central Mid"):
                pid += 1
                ovr = 2.5 + k * 0.15
                cards.append((pid, 4, season, pos, ovr, ovr, 3.0))
                neutral.append((pid, 4, season, 900.0, club, f"<{club}> {pos} {season}", 10.0 + k))
    cards.append((900, 5, CUR, "Winger", 4.9, 4.0, 4.0))
    neutral.append((900, 5, CUR, 1200.0, "League Two side", "L2 star", 9.0))
    c = pd.DataFrame(cards, columns=["player_id", "competition_id", "season_id", "position_group",
                                     "objective_composite", "performance_band", "physical_band"])
    n = pd.DataFrame(neutral, columns=["player_id", "competition_id", "season_id", "minutes",
                                       "team_name", "player_name", "sprint_count_p90"])
    return c, n


def _src(cards, neutral):
    ours = neutral[(neutral.team_name == "Leyton Orient") & (neutral.season_id == CUR)]
    squad = ours.rename(columns={})[["player_id", "player_name"]].assign(
        position_group=list(cards.set_index("player_id").loc[list(ours.player_id), "position_group"]))
    keys = ["player_id", "competition_id", "season_id"]
    pcts = cards[keys + ["position_group"]].assign(sprint_count_p90=50.0)
    src = types.SimpleNamespace(
        seasons=lambda: (CUR, PREV), season_name=lambda s: {CUR: "2026/27", PREV: "2025/26"}[s],
        cards=lambda: cards, neutral=lambda: neutral, squad=lambda: squad,
        pcts=lambda s: pcts[pcts.season_id == s],
        candidates=lambda s: cards[cards.season_id == s][keys].assign(age=24.0, contract_until=pd.NaT),
        league_names=lambda: {3: "Championship", 4: "League One", 5: "League Two"},
        metrics=lambda pos: ["sprint_count_p90"], physical=["sprint_count_p90"],
        label=lambda m: {"sprint_count_p90": "Sprints"}.get(m, m),
        watched=lambda: {(900, 5, CUR)})
    return src


@pytest.fixture
def fake(monkeypatch):
    src = _src(*_frames())
    monkeypatch.setattr(api, "_sources", lambda: src)
    api.clear()
    yield src
    api.clear()


def _client():
    s = FakeStore()
    s.add(username="u", full_name="Ann Scout", role="scout", password="correct-horse-1")
    c, *_ = make(s)
    login(c, "u", "correct-horse-1")
    return c


def test_page_shell_and_nav_entry(fake):
    r = _client().get("/club-vs-league")
    assert r.status_code == 200 and "/js/club_vs_league.js" in r.text
    assert "Where we fall short of a top-6 League One side this season, and who could close the gap." in r.text
    assert 'href="/club-vs-league"' in r.text and "Club vs League One" in r.text


def test_how_it_is_worked_out_explains_the_big_picture_ranks(fake):
    """Owner 2026-11-10: the fold-out says how Big picture ranks are built; the ⓘ no longer
    says "physical" only, since the table holds performance measures too."""
    html = _client().get("/club-vs-league").text
    how = html.split('id="cv-how"')[1].split("</details>")[0]
    assert ("<b>Big picture</b>: each club's average of its players' figures, weighted by "
            "minutes, then ranked 1–24. Ratings rows use rated players (450+ minutes); "
            "measure rows use every player, per 90.") in how
    assert how.index("<b>Top 6</b>") < how.index("<b>Big picture</b>") < how.index("<b>Our level</b>")
    assert ("Our rank among League One clubs on the minutes-weighted average of our players' "
            "ratings and per-90 figures.") in html
    assert "per-90 physical figures" not in html


def test_api_needs_login():
    c, *_ = make(FakeStore())
    assert c.get("/api/club-vs-league").status_code == 401


def test_payload(fake):
    d = _client().get("/api/club-vs-league").json()
    assert d["season"] == "2026/27" and d["prev_season"] == "2025/26"
    assert [t["club"] for t in d["top6"]] == [f"Club {c}" for c in "HGFEDC"]
    assert d["orient"] == {"rank": 9, "of": 9, "text": "9th of 9"}
    groups = [g["group"] for g in d["gaps"]]
    assert set(groups) == set(cv.GROUPS)
    first = d["gaps"][0]
    assert first["gap"] is not None and first["bar"]["players"][0]["club"] == "Club H"
    assert d["selected"] == first["group"]
    rec = d["recommendations"]
    assert rec["group"] == d["selected"] and rec["leagues"][0]["league"] == "League One"
    assert all(r["overall"] > first["level"]["rating"] for r in rec["leagues"][0]["rows"])
    assert [b["measure"] for b in d["big_picture"]][:3] == ["Overall", "Performance", "Physical"]


def test_group_and_filters_follow_the_url(fake):
    d = _client().get("/api/club-vs-league?group=Winger&age=u21").json()
    assert d["selected"] == "Winger" and d["filters"]["age"] == "u21"
    assert all(not l["rows"] for l in d["recommendations"]["leagues"]) or d["recommendations"]["leagues"] == []
    d2 = _client().get("/api/club-vs-league?group=Nonsense&contract=bad").json()
    assert d2["selected"] == d2["gaps"][0]["group"] and d2["filters"]["contract"] == ""


def test_watched_flag_and_card_links(fake):
    d = _client().get("/api/club-vs-league?group=Winger").json()
    l2 = next(l for l in d["recommendations"]["leagues"] if l["league"] == "League Two")
    row = l2["rows"][0]
    assert row["name"] == "L2 star" and row["watched"] is True and row["href"] == "/player/900/5/319"


def test_no_financial_figures_anywhere(fake):
    text = _client().get("/api/club-vs-league").text.lower()
    for word in ("market", "fee", "wage", "value_eur", "budget"):
        assert word not in text


def test_strong_filter_is_off_by_default_and_follows_the_url(fake):
    d = _client().get("/api/club-vs-league?group=Winger").json()
    assert d["filters"]["strong"] is False
    on = _client().get("/api/club-vs-league?group=Winger&strong=1").json()
    assert on["filters"]["strong"] is True
    assert all(sum(v is not None and v >= 70 for v in r["weak"]) >= 2
               for l in on["recommendations"]["leagues"] for r in l["rows"])


def test_weak_metric_columns_follow_the_positions_shortfalls(fake):
    d = _client().get("/api/club-vs-league?group=Winger").json()
    sel = next(g for g in d["gaps"] if g["group"] == "Winger")
    rec = d["recommendations"]
    assert [w["metric"] for w in rec["weak_metrics"]] == [s["metric"] for s in sel["shortfalls"]]
    assert all(len(r["weak"]) == len(rec["weak_metrics"]) for l in rec["leagues"] for r in l["rows"])


def test_top6_level_badge_and_the_pages_wording(fake):
    d = _client().get("/api/club-vs-league").json()
    sel = next(g for g in d["gaps"] if g["group"] == d["selected"])
    for l in d["recommendations"]["leagues"]:
        for r in l["rows"]:
            assert r["top6_level"] == (r["overall"] >= sel["bar"]["median"])
    html = _client().get("/club-vs-league").text
    from markupsafe import escape
    for k in ("Top 6", "Our level", "Top-6 bar", "Gap", "Top-6 level", "Players who could close the gap"):
        assert str(escape(cv.TERMS[k])) in html


def test_the_recommendations_help_is_the_owners_sentence(fake):
    assert cv.TERMS["Players who could close the gap"] == (
        "Players rated above our best at this position, ranked by Overall or Gap closed; the metric "
        "columns show his percentile on each chosen measure.")   # owner 2026-11-13
    html = _client().get("/club-vs-league").text
    assert "Strong where we are weak" not in html


def test_owner_additions_vs_best_top6_filter_and_all_shortfalls(fake):
    d = _client().get("/api/club-vs-league?group=Winger").json()
    sel = next(g for g in d["gaps"] if g["group"] == "Winger")
    assert d["filters"]["top6"] is False and "all_shortfalls" in sel
    for l in d["recommendations"]["leagues"]:
        for r in l["rows"]:
            assert r["vs_best"] == cv.vs_best(r["overall"], sel["level"]["rating"])
    on = _client().get("/api/club-vs-league?group=Winger&top6=1").json()
    assert on["filters"]["top6"] is True
    assert all(r["top6_level"] for l in on["recommendations"]["leagues"] for r in l["rows"])
    assert d["terms"]["vs our best"] == ("His rating minus our best at this position; the gap is "
                                         "closed when this reaches the gap size.")   # the column's ⓘ


def test_weakness_labels_use_the_fewer_is_better_wording(fake, monkeypatch):
    from lofc.model import club_framework as cf
    monkeypatch.setattr(cf, "LOWER_IS_BETTER", {"sprint_count_p90"})
    ours = set(fake.neutral().query("team_name == 'Leyton Orient'")["player_id"])
    base = fake.pcts
    fake.pcts = lambda season: base(season).assign(
        sprint_count_p90=lambda f: f["player_id"].map(lambda p: 10.0 if p in ours else 60.0))
    api.clear()
    d = _client().get("/api/club-vs-league?group=Winger").json()
    sel = next(g for g in d["gaps"] if g["group"] == "Winger")
    labels = [s["label"] for s in sel["shortfalls"]] + [w["label"] for w in d["recommendations"]["weak_metrics"]]
    assert labels and all(l == "Sprints (fewer is better)" for l in labels)
    assert [b for b in d["big_picture"] if b["measure"] == "sprint_count_p90"][0]["label"] == "Sprints"


def test_top6_has_performance_and_physical_and_orients_own_row(fake):
    """Owner 2026-11-10: Top 6 shows Overall, Performance and Physical (the same minutes-weighted
    club average) for the six clubs, then Orient's own row with its rank."""
    d = _client().get("/api/club-vs-league").json()
    cards, neutral = fake.cards(), fake.neutral()
    rated = cv.rated_frame(cards, neutral)
    want = cv.club_ratings(rated, CUR).set_index("team_name")
    for t in d["top6"]:
        w = want.loc[t["club"]]
        assert (t["avg"], t["performance"], t["physical"]) == (
            round(w["overall"], 2), round(w["performance"], 2), round(w["physical"], 2))
    us = d["us"]
    assert us["club"] == "Leyton Orient" and us["rank"] == 9 and us["of"] == 9
    w = want.loc["Leyton Orient"]
    assert (us["avg"], us["performance"], us["physical"], us["players"]) == (
        round(w["overall"], 2), round(w["performance"], 2), round(w["physical"], 2), int(w["n"]))


def test_every_shortfall_carries_one_behind_figure(fake, monkeypatch):
    ours = set(fake.neutral().query("team_name == 'Leyton Orient'")["player_id"])
    base = fake.pcts
    fake.pcts = lambda season: base(season).assign(
        sprint_count_p90=lambda f: f["player_id"].map(lambda p: 40.0 if p in ours else 59.5))
    api.clear()
    d = _client().get("/api/club-vs-league?group=Winger").json()
    sel = next(g for g in d["gaps"] if g["group"] == "Winger")
    assert [(s["ours"], s["top6"], s["short"]) for s in sel["shortfalls"]] == [(40, 60, 20)]
    assert [s["short"] for s in sel["all_shortfalls"]] == [20]
    assert "text" not in sel["shortfalls"][0]          # no ordinal percentiles on this page


def test_recommendations_name_the_default_leagues(fake):
    d = _client().get("/api/club-vs-league?group=Winger").json()
    assert d["recommendations"]["default_leagues"] == [4, 3, 5]


def test_page_shell_has_the_new_layout(fake):
    """Owner 2026-11-10 redesign: Top 6 and Big picture full width (Big picture in two
    columns), the gap map's subtitle, and a Leagues multi-select in place of fixed tabs."""
    html = _client().get("/club-vs-league").text
    assert 'class="row tr2 cv-toprow"' not in html
    assert 'id="cv-big-l"' in html and 'id="cv-big-r"' in html
    assert "Our rank of <span id=\"cv-big-of\"></span> League One clubs · minutes-weighted club figures, per 90 unless %" in html
    assert "Biggest gap first · shortfalls are percentiles (100 = best) · click a row for detail" in html
    assert 'id="cv-leagues"' in html and ">Leagues<" in html
    how = html.split('id="cv-how"')[1].split("</details>")[0]
    assert "Where it comes from" not in how and "Show all" not in how
    assert "/js/club_vs_league_rules.js" not in html          # imported by the page module


def test_fold_out_describes_every_shortfall_without_a_cut_off(fake):
    """Owner 2026-11-10: "Every shortfall" lists every metric we're behind on (no 20-point cut-off)."""
    html = _client().get("/club-vs-league").text
    how = html.split('id="cv-how"')[1].split("</details>")[0]
    assert "20+" not in how
    assert "open a row for every metric we're behind on, biggest first." in how


# --- owner 2026-11-13: "Gap closed" and the metric-column picker ---------------------------------
@pytest.fixture
def two_metrics(fake):
    """Winger: ours behind on sprints (40 vs 60), ahead on distance (80 vs 50); candidates vary."""
    ours = set(fake.neutral().query("team_name == 'Leyton Orient'")["player_id"])
    base = fake.pcts
    fake.metrics = lambda pos: ["sprint_count_p90", "distance_p90"]

    def pcts(season):
        f = base(season)
        sprint = f["player_id"].map(lambda p: 40.0 if p in ours else 60.0)
        sprint = sprint.where(f["player_id"] != 900, 50.0)          # L2 star closes half
        return f.assign(sprint_count_p90=sprint,
                        distance_p90=f["player_id"].map(lambda p: 80.0 if p in ours else 50.0))
    fake.pcts = pcts
    fake.label = lambda m: {"sprint_count_p90": "Sprints", "distance_p90": "Distance"}.get(m, m)
    api.clear()
    return fake


def _rows(d):
    return [r for l in d["recommendations"]["leagues"] for r in l["rows"]]


def test_gap_closed_on_every_row(two_metrics):
    d = _client().get("/api/club-vs-league?group=Winger").json()
    rows = _rows(d)
    assert rows and all(r["gap_closed"] is None or (isinstance(r["gap_closed"], int) and 0 <= r["gap_closed"] <= 100)
                        for r in rows)
    l2 = next(r for r in rows if r["name"] == "L2 star")
    assert l2["gap_closed"] == 50                                   # 10 of a 20-point sprint gap
    assert all(r["gap_closed"] == 100 for r in rows if r["name"] != "L2 star")
    gc = d["recommendations"]["gap_closed"]
    assert gc == {"custom": False, "note": None}
    assert [w["metric"] for w in d["recommendations"]["weak_metrics"]] == ["sprint_count_p90"]
    assert d["recommendations"]["metric_options"] == [{"metric": "sprint_count_p90", "label": "Sprints"},
                                                      {"metric": "distance_p90", "label": "Distance"}]


def test_rank_by_gap_closed_follows_the_url(two_metrics):
    d = _client().get("/api/club-vs-league?group=Winger&rank=gap").json()
    assert d["filters"]["rank"] == "gap" and d["recommendations"]["rank"] == "gap"
    for l in d["recommendations"]["leagues"]:
        gc = [r["gap_closed"] for r in l["rows"]]
        assert gc == sorted(gc, reverse=True)
    assert _client().get("/api/club-vs-league?group=Winger&rank=bad").json()["filters"]["rank"] == ""


def test_chosen_columns_follow_the_url_and_set_the_score(two_metrics):
    d = _client().get("/api/club-vs-league?group=Winger&cols=distance_p90,sprint_count_p90").json()
    rec = d["recommendations"]
    assert [w["metric"] for w in rec["weak_metrics"]] == ["distance_p90", "sprint_count_p90"]
    assert d["filters"]["cols"] == ["distance_p90", "sprint_count_p90"] and rec["gap_closed"]["custom"] is True
    assert next(r for r in _rows(d) if r["name"] == "L2 star")["gap_closed"] == 50
    # none of the chosen metrics is a shortfall: percentiles shown, no score, one-line note
    n = _client().get("/api/club-vs-league?group=Winger&cols=distance_p90").json()
    assert all(r["gap_closed"] is None and r["weak"] == [50] for r in _rows(n))
    assert n["recommendations"]["gap_closed"]["note"] == "None of these metrics is a shortfall, so no Gap closed."
    # unknown and repeated metrics dropped; the default when nothing valid is left
    b = _client().get("/api/club-vs-league?group=Winger&cols=nope,distance_p90,distance_p90").json()
    assert b["filters"]["cols"] == ["distance_p90"]
    # choosing exactly our biggest shortfalls is the default (score over every shortfall)
    same = _client().get("/api/club-vs-league?group=Winger&cols=sprint_count_p90").json()
    assert same["filters"]["cols"] == [] and same["recommendations"]["gap_closed"]["custom"] is False
    e = _client().get("/api/club-vs-league?group=Winger&cols=nope").json()
    assert e["filters"]["cols"] == [] and e["recommendations"]["gap_closed"]["custom"] is False


def test_at_most_five_columns(fake):
    ms = [f"m{i}" for i in range(7)]
    fake.metrics = lambda pos: ms
    api.clear()
    d = _client().get("/api/club-vs-league?group=Winger&cols=" + ",".join(ms)).json()
    assert d["filters"]["cols"] == ms[:5] and len(d["recommendations"]["weak_metrics"]) == 5


def test_strong_keeps_the_default_shortfalls_when_columns_change(two_metrics):
    """Chosen columns never change "Strong on 2+": it stays on the position's 3 biggest shortfalls."""
    d = _client().get("/api/club-vs-league?group=Winger&cols=distance_p90&strong=1").json()
    assert _rows(d) == []                       # only one shortfall (sprints): nobody is strong on 2
    assert [w["metric"] for w in d["recommendations"]["weak_metrics"]] == ["distance_p90"]


def test_gap_closed_wording(fake):
    assert cv.TERMS["Gap closed"] == "How much of our player's shortfall vs the top 6 he would make up. 100% = all of it."
    html = _client().get("/club-vs-league").text
    how = html.split('id="cv-how"')[1].split("</details>")[0]
    from markupsafe import escape
    assert ("<b>Gap closed</b>: " + str(escape(cv.TERMS["Gap closed"]))
            + " Each metric counts by its weight in the Overall rating.") in how
    assert 'id="cv-cols"' in html and ">Metric columns<" in html and 'id="cv-rank"' in html


# --- owner 2026-11-13: measure a position against any of our rated players ----------------------
BEST_W, SECOND_W, OUR_CB, BETWEEN = 101, 950, 102, 951


@pytest.fixture
def second(monkeypatch):
    """Wingers: our best (101, 2.5: sprints 40, distance 80) and a second rated winger (950,
    2.0: sprints 20, distance 30); everyone else sprints 60, distance 50 (the L2 star sprints
    50); Club A has a winger at 2.3, above him but below our best."""
    cards, neutral = _frames()
    cards = pd.concat([cards, pd.DataFrame(
        [(SECOND_W, 4, CUR, "Winger", 2.0, 2.0, 3.0), (BETWEEN, 4, CUR, "Winger", 2.3, 2.3, 3.0)],
        columns=cards.columns)], ignore_index=True)
    neutral = pd.concat([neutral, pd.DataFrame(
        [(SECOND_W, 4, CUR, 700.0, "Leyton Orient", "Second Winger", 9.0),
         (BETWEEN, 4, CUR, 800.0, "Club A", "Between Winger", 9.0)], columns=neutral.columns)],
        ignore_index=True)
    src = _src(cards, neutral)
    ours = set(neutral.query("team_name == 'Leyton Orient'")["player_id"])
    base = src.pcts
    src.metrics = lambda pos: ["sprint_count_p90", "distance_p90"]
    src.label = lambda m: {"sprint_count_p90": "Sprints", "distance_p90": "Distance"}.get(m, m)

    def pcts(season):
        f = base(season)
        pid = f["player_id"]
        sprint = pid.map(lambda p: 20.0 if p == SECOND_W else 40.0 if p in ours else 50.0 if p == 900 else 60.0)
        dist = pid.map(lambda p: 30.0 if p == SECOND_W else 80.0 if p in ours else 50.0)
        return f.assign(sprint_count_p90=sprint, distance_p90=dist)
    src.pcts = pcts
    monkeypatch.setattr(api, "_sources", lambda: src)
    api.clear()
    yield src
    api.clear()


def _winger(d):
    return next(g for g in d["gaps"] if g["group"] == "Winger")


def test_vs_measures_the_position_against_the_chosen_player(second):
    base = _client().get("/api/club-vs-league?group=Winger").json()
    d = _client().get(f"/api/club-vs-league?group=Winger&vs={SECOND_W}").json()
    w, b = _winger(d), _winger(base)
    assert b["level"]["player_id"] == BEST_W and b["vs"] is None and base["compare"] is None
    assert w["level"]["player_id"] == SECOND_W and w["best"]["player_id"] == BEST_W and w["vs"] == SECOND_W
    assert w["gap"] == pytest.approx(w["bar"]["median"] - 2.0)
    assert w["gap"] > b["gap"]
    # his shortfalls: sprints 20 vs 60 (40), distance 30 vs 50 (20); our best only sprints
    assert [(s["metric"], s["ours"], s["top6"], s["short"]) for s in w["shortfalls"]] == [
        ("sprint_count_p90", 20, 60, 40), ("distance_p90", 30, 50, 20)]
    assert [s["metric"] for s in w["all_shortfalls"]] == ["sprint_count_p90", "distance_p90"]
    assert [s["metric"] for s in b["shortfalls"]] == ["sprint_count_p90"]
    assert d["filters"]["vs"] == SECOND_W and base["filters"]["vs"] is None
    assert d["compare"] == {"player_id": SECOND_W, "name": "Second Winger", "rating": 2.0,
                            "terms": cv.vs_terms("Second Winger")}
    # every other position is unchanged
    assert [g for g in d["gaps"] if g["group"] != "Winger"] == [g for g in base["gaps"] if g["group"] != "Winger"]
    assert [g["group"] for g in d["gaps"]] == [g["group"] for g in base["gaps"]]


def test_vs_lists_players_above_him_with_his_columns_and_gap_closed(second):
    base = _client().get("/api/club-vs-league?group=Winger").json()
    d = _client().get(f"/api/club-vs-league?group=Winger&vs={SECOND_W}").json()
    rec = d["recommendations"]
    rows = _rows(d)
    assert rows and all(r["overall"] > 2.0 for r in rows)
    assert "Between Winger" in [r["name"] for r in rows]                    # 2.3: above him
    assert "Between Winger" not in [r["name"] for r in _rows(base)]         # not above our best
    assert all(r["vs_best"] == cv.vs_best(r["overall"], 2.0) for r in rows)
    assert rec["level"] == 2.0
    assert [w["metric"] for w in rec["weak_metrics"]] == ["sprint_count_p90", "distance_p90"]
    want = cv.gap_closed({"sprint_count_p90": (20.0, 60.0), "distance_p90": (30.0, 50.0)},
                         {"sprint_count_p90": 50.0, "distance_p90": 50.0}, cv.overall_weights("Winger"))
    assert next(r for r in rows if r["name"] == "L2 star")["gap_closed"] == want
    assert next(r for r in _rows(base) if r["name"] == "L2 star")["gap_closed"] == 50
    # "Strong on 2+" uses his biggest shortfalls: sprints 60 and distance 50 -> nobody at 70 on 2
    on = _client().get(f"/api/club-vs-league?group=Winger&vs={SECOND_W}&strong=1").json()
    assert _rows(on) == []
    # chosen columns still work against him
    c = _client().get(f"/api/club-vs-league?group=Winger&vs={SECOND_W}&cols=distance_p90").json()
    assert c["recommendations"]["gap_closed"]["custom"] is True
    assert next(r for r in _rows(c) if r["name"] == "L2 star")["gap_closed"] == 100


def test_invalid_vs_is_ignored(second):
    base = _client().get("/api/club-vs-league?group=Winger").json()
    for bad in (str(BEST_W), str(OUR_CB), "104", "900", "abc", "", "-1"):
        d = _client().get(f"/api/club-vs-league?group=Winger&vs={bad}").json()
        assert d["filters"]["vs"] is None and d["compare"] is None, bad
        assert _winger(d) == _winger(base) and d["recommendations"] == base["recommendations"], bad
    # his id at another position: ignored there
    cb = _client().get(f"/api/club-vs-league?group=Centre%20Back&vs={SECOND_W}").json()
    assert cb["filters"]["vs"] is None and _winger(cb)["vs"] is None


def test_fold_out_says_any_of_our_players_can_be_picked(fake):
    how = _client().get("/club-vs-league").text.split('id="cv-how"')[1].split("</details>")[0]
    assert "<li>Pick any of our rated players in a position to measure the gap and the list against him.</li>" in how


# --- owner 2026-11-13: Big picture physical by phase; Gap closed as a live example -------------
def test_big_picture_physical_rows_carry_in_and_out_of_possession(fake):
    n = fake.neutral()
    cur = n[n.season_id == CUR]
    fake.sections = {"sprint_count_p90": "Physical"}
    fake.phase_detail = lambda: pd.DataFrame({
        "player_id": list(cur.player_id) * 2, "competition_id": 4, "season_id": CUR,
        "metric": ["phys_tip.sprint_count_p90"] * len(cur) + ["phys_otip.sprint_count_p90"] * len(cur),
        # in possession: Orient best; out of possession: Orient worst
        "value_p90": [30.0 if t == "Leyton Orient" else 1.0 for t in cur.team_name]
                     + [0.5 if t == "Leyton Orient" else 1.0 for t in cur.team_name]})
    api.clear()
    d = _client().get("/api/club-vs-league").json()
    row = next(b for b in d["big_picture"] if b["measure"] == "sprint_count_p90")
    assert row["now"]["rank"] == 9                                     # all phases: 10 < every other club
    assert row["phases"]["tip"]["now"] == {"rank": 1, "of": 9, "text": "1st of 9"}
    assert row["phases"]["otip"]["now"]["rank"] == 9 and row["phases"]["tip"]["prev"] is None
    assert all("phases" not in b for b in d["big_picture"] if b["kind"] == "rating")


def test_big_picture_without_phase_data_still_works(fake):
    d = _client().get("/api/club-vs-league").json()
    assert all("phases" not in b for b in d["big_picture"])


def test_gap_closed_example_per_league_from_the_pages_figures(two_metrics):
    d = _client().get("/api/club-vs-league?group=Winger").json()
    by = {l["league"]: l for l in d["recommendations"]["leagues"]}
    assert all("top_gap" not in l for l in by.values())               # raw percentiles stay server-side
    l1 = by["League One"]["example"]
    top = max(by["League One"]["rows"], key=lambda r: (r["gap_closed"], r["overall"]))
    w = _winger(d)
    assert l1["candidate"] == {"name": top["name"], "club": top["club"]}
    assert l1["columns"][1] == f"Ours ({w['level']['name'].split()[-1]})"
    assert l1["columns"][4] == f"Target ({top['name'].split()[-1]})"
    # ours sprints 40 vs top 6 60; every League One winger sprints 60 -> the whole gap
    assert l1["rows"] == [{"label": "Sprints", "ours": "40.0", "top6": "60.0", "gap": "20.0", "target": "60.0", "diff": "20.0", "counted": "20.0"}]
    assert l1["more"] is None
    assert l1["total"] == ("Gap closed = total Counted ÷ total Gap = 100%. Measures that count more in "
                           "the Winger rating count more.")
    l2 = by["League Two"]["example"]
    assert l2["rows"][0]["target"] == "50.0" and l2["rows"][0]["counted"] == "10.0" and "= 50%." in l2["total"]


def test_full_list_every_player_above_our_player(two_metrics):
    """Owner 2026-11-13: no top-15 cap -- every rated player above the compared player."""
    d = _client().get("/api/club-vs-league?group=Winger").json()
    for l in d["recommendations"]["leagues"]:
        assert len(l["rows"]) == l["count"]


def test_gap_closed_example_follows_the_compared_player(second):
    d = _client().get(f"/api/club-vs-league?group=Winger&vs={SECOND_W}").json()
    ex = next(l for l in d["recommendations"]["leagues"] if l["league"] == "League One")["example"]
    assert ex["columns"][1] == "Ours (Winger)"                         # "Second Winger"
    assert [r["label"] for r in ex["rows"]] == ["Sprints", "Distance"] and ex["rows"][0]["ours"] == "20.0"


def test_gap_closed_example_none_without_a_shortfall(fake):
    d = _client().get("/api/club-vs-league").json()                   # every percentile 50: no shortfall
    assert all(l["example"] is None for l in d["recommendations"]["leagues"])
    how = _client().get("/club-vs-league").text.split('id="cv-how"')[1].split("</details>")[0]
    assert 'id="cv-how-gc"' in how                                     # the line the page fills in
