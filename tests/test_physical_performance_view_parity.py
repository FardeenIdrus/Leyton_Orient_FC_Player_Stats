"""The squad card's Performance view shows the player card's Strengths / Watch-outs, on the REAL
database (skipped without one). Read-only."""
import pytest
from sqlalchemy import create_engine

from lofc.config import settings

SUFFIX = " (fewer is better)"


@pytest.fixture(scope="module")
def engine():
    try:
        e = create_engine(settings.database_url)
        e.connect().close()
    except Exception:
        pytest.skip("no database")
    return e


@pytest.fixture(scope="module")
def view(engine):
    from lofc.web.api import physical
    return physical.page_json("319")["perf"]


def test_every_rated_squad_player_once(view):
    from lofc.core import squad
    rows = squad.rated_rows(319)
    ours = squad.squad()
    listed = [r["name"] for g in view["groups"] for r in g["rows"]]
    rated = [str(n) for p, n in zip(ours["player_id"], ours["player_name"])
             if int(p) in rows.index and rows.loc[int(p), "objective_composite"] == rows.loc[int(p), "objective_composite"]]
    assert sorted(listed) == sorted(rated)
    assert view["unrated"] == len(ours) - len(rated)


def test_strongest_weakest_are_the_cards(engine, view):
    """One rule (card.split_strong_weak, owner 2026-11-13): the view's Strongest 3 / Weakest 3
    are the card's Strengths / Watch-outs, and never share a metric."""
    from lofc.core import card
    rows = [r for g in view["groups"] for r in g["rows"]]
    assert len(rows) >= 2
    checked = 0
    for r in rows[:6]:
        p, c, s = (int(x) for x in r["href"].split("/")[2:5])
        d = card.build_card(engine, p, c, s)
        sw = d["rating"]["strengths"]
        assert r["overall"] == pytest.approx(d["rating"]["overall"]["value"])
        strong = [(x["label"].removesuffix(SUFFIX), x["pct"]) for x in r["strong"]]
        weak = [(x["label"].removesuffix(SUFFIX), x["pct"]) for x in r["weak"]]
        assert not {m for m, _ in strong} & {m for m, _ in weak}
        assert (strong, weak) == ([(x["metric"], x["pct"]) for x in sw["strengths"]],
                                  [(x["metric"], x["pct"]) for x in sw["watch_outs"]])
        checked += 1
    assert checked >= 2


def test_baxter_card_no_metric_in_both(engine, view):
    """Seen 2026-11-13 on his card: "Goals saved above average 52" in Strengths AND Watch-outs
    (five figures). The card now splits them, as the Performance view does."""
    from lofc.core import card
    d = card.build_card(engine, 9300, 4, 319)
    sw = d["rating"]["strengths"]
    if sw is None:
        pytest.skip("Baxter has no strengths in this database")
    strong = [x["metric"] for x in sw["strengths"]]
    weak = [x["metric"] for x in sw["watch_outs"]]
    assert not set(strong) & set(weak), (strong, weak)
    assert min(x["pct"] for x in sw["strengths"]) >= max(x["pct"] for x in sw["watch_outs"])
    row = next((r for g in view["groups"] for r in g["rows"] if r["href"] == "/player/9300/4/319"), None)
    if row is not None:
        assert [x["label"].removesuffix(SUFFIX) for x in row["strong"]] == strong
        assert [x["label"].removesuffix(SUFFIX) for x in row["weak"]] == weak


def test_baxter_no_metric_in_both(view):
    """Seen 2026-11-13: goalkeeper Nathan Baxter had "Goals saved above average 52" in both."""
    gk = next((g for g in view["groups"] if g["group"] == "Goalkeeper"), None)
    if gk is None:
        pytest.skip("no rated goalkeeper")
    for r in gk["rows"]:
        assert not {x["label"] for x in r["strong"]} & {x["label"] for x in r["weak"]}, r["name"]


def test_unrated_line_names_the_season(view):
    if view["unrated"]:
        assert view["unrated_t"].endswith("not rated in 2026/27 (under 450 minutes or too few peers)")
