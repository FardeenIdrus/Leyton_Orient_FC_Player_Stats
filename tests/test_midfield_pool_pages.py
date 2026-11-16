"""The not-rated line and the midfield-pool tag on every other page (owner 2026-11-16).

The card and report (test_midfield_pool_ui.py) show a not-rated player's percentiles and bands as
"—" with one line, "Not rated: only N <Position>s in <League> with 450+ minutes (needs 10).", and
tag a player rated against all midfielders "Rated against all midfielders". Compare, Squads &
loans, Watchlist, Scout reports and Physical say the same, from the same helpers
(`card.not_rated_line`, `card.pool_tag`). Physical uses the pool he was rated in (stored
`peer_pool` / `peer_pool_size`), not his own position's count. No database."""
import pandas as pd

from lofc.model.scorecard import MIDFIELD_POOL_TAG, POOL_MIDFIELD, POOL_POSITION

DASH = "—"
TAG = "Rated against all midfielders"


def _line(n, pos, league):
    return f"Not rated: only {n} {pos}s in {league} with 450+ minutes (needs 10)."


def test_the_tag_is_the_models():
    assert MIDFIELD_POOL_TAG == TAG


# --- Compare ---------------------------------------------------------------------------------
def test_compare_not_rated_caption_is_the_cards_line():
    from lofc.core import compare as C
    assert C.not_rated_caption("not_rated", 8, 900, "Winger", "Premier League 2") == \
        _line(8, "Winger", "Premier League 2")
    # no pool known / under 450 minutes: the card's other wording, unchanged
    assert C.not_rated_caption("not_rated", float("nan"), 900, "Winger", "X") == \
        "Not rated: too few peers in his league and position"
    assert C.not_rated_caption("ok", 30, 900, "Winger", "X") is None


def test_compare_vs_text_names_the_midfield_pool():
    from lofc.core import compare as C
    assert C.vs_text("Central Mid", "Scottish Premiership", None, POOL_MIDFIELD) == \
        "Scottish Premiership midfielders"
    assert C.vs_text("Winger", "League Two", None, POOL_POSITION) == "League Two Wingers"
    assert C.vs_text("Winger", "Premier League 2", 8) == "8 Premier League 2 Wingers"


def test_compare_withheld_percentiles_are_dashes_and_off_the_radar():
    from lofc.core import compare as C
    pcts = {"A": pd.Series({"m1": 50.0, "m2": 50.0}), "B": pd.Series({"m1": 71.0, "m2": 20.0})}
    out = C.withhold(pcts, ["A", "B"], {0})
    assert out["A"] is None and out["B"] is pcts["B"]
    assert pcts["A"] is not None                                   # the caller's dict untouched


def test_compare_table_cells_of_a_withheld_player_say_dash():
    from lofc.web.api import compare as api
    rows = [{"metric": "m1", "label": "M1", "tier": None,
             "cells": [{"text": "5.10", "pct": None, "cls": None},
                       {"text": "4.00", "pct": 71.0, "cls": "best"}]}]
    out = api._table(rows, withheld={0})
    assert out[0]["cells"][0] == {"text": "5.10", "pct": None, "pct_text": DASH, "cls": None}
    assert out[0]["cells"][1]["pct_text"] == "P71"
    assert api._table(rows)[0]["cells"][0]["pct_text"] is None      # no value, no withholding


# --- Squads & loans ------------------------------------------------------------------------
def _squad_view():
    return pd.DataFrame({"player_id": [1, 2, 3], "competition_id": [903, 901, 4],
                         "rating_competition_id": [903, 901, 4],
                         "alt_competition_id": [None, None, None]})


def _live_cards():
    """903 Wingers: 8 (thin). 901: one Central Mid in a stored midfield pool of 38. 4: 12 CBs."""
    rows = [(1, 903, "Winger", POOL_POSITION, 8)] + \
        [(100 + i, 903, "Winger", POOL_POSITION, 8) for i in range(7)] + \
        [(2, 901, "Central Mid", POOL_MIDFIELD, 38)] + \
        [(3, 4, "Centre Back", POOL_POSITION, 12)] + \
        [(300 + i, 4, "Centre Back", POOL_POSITION, 12) for i in range(11)]
    return pd.DataFrame([{"player_id": p, "competition_id": c, "season_id": 319,
                          "position_group": g, "objective_composite": 3.1, "peer_pool": s,
                          "peer_pool_size": n} for p, c, g, s, n in rows])


NAMES = {903: "Premier League 2", 901: "Scottish Premiership", 4: "League One"}


def test_squads_pool_notes_name_the_pool_and_tag_the_midfield_pool():
    from lofc.core import squads as S
    empty = _live_cards().iloc[0:0]
    thin, tags = S.pool_notes(_squad_view(), _live_cards(), empty, 319, 318, NAMES)
    assert thin == {(0, "This season"): _line(8, "Winger", "Premier League 2")}
    assert tags == {(1, "This season"): TAG}


def test_squads_web_cells_carry_the_line_and_the_tag():
    from lofc.core.squads import DISPLAY_COLUMNS, squad_display, web_cells
    from test_core_squads import _prepared
    f = _prepared()
    table = squad_display(f[DISPLAY_COLUMNS].reset_index(drop=True))
    rows = web_cells(f, table, {(0, "Also rated"): _line(6, "Winger", "League Two")},
                     {(0, "Last season"): TAG})
    assert rows[0][DISPLAY_COLUMNS.index("Also rated")] == {
        "t": DASH, "note": _line(6, "Winger", "League Two")}
    assert rows[0][DISPLAY_COLUMNS.index("Last season")] == {"t": "3.42", "tag": TAG}
    assert rows[0][DISPLAY_COLUMNS.index("This season")] == "3.10"


# --- Watchlist ---------------------------------------------------------------------------------
def test_watchlist_pool_notes():
    from lofc.core import watchlist_page as wp
    df = pd.DataFrame({"player_id": [1, 2, 3], "competition_id": [903, 901, 4],
                       "season_id": [319] * 3, "objective_composite": [2.93, 3.09, 3.0]})
    notes = wp.pool_notes(df, lambda sid: _live_cards(), NAMES)
    assert notes["not_rated"].tolist() == [_line(8, "Winger", "Premier League 2"), None, None]
    assert notes["pool_tag"].tolist() == [None, TAG, None]


# --- Scout reports ------------------------------------------------------------------------------
def test_scout_reports_thin_lines_name_the_pool():
    from lofc.core import scout_reports_page as sp
    frame = pd.DataFrame({"player_id": [1, 3, None], "rated_in": [903, 4, None],
                          "composite": [2.93, 3.0, None]})
    cards = _live_cards().assign(season_id=318)
    out = sp.thin_lines(frame, cards, 318, NAMES)
    assert out.iloc[0] == _line(8, "Winger", "Premier League 2")
    assert pd.isna(out.iloc[1]) and pd.isna(out.iloc[2])


def test_scout_reports_tags_follow_each_ratings_pool():
    from lofc.core import scout_reports_page as sp
    row = pd.Series({"pool_scope": POOL_POSITION, "pool_scope_live": POOL_MIDFIELD})
    assert sp.rating_tags(row) == {"This season": TAG}
    assert sp.rating_tags(pd.Series({"pool_scope": None})) == {}


# --- Physical -------------------------------------------------------------------------------------
def test_physical_metric_count_uses_the_midfield_pool():
    from lofc.core import physical_page as pp
    pcts = pd.DataFrame({"player_id": range(12), "competition_id": 901, "season_id": 319,
                         "position_group": ["Central Mid"] + ["Defensive Mid"] * 6
                         + ["Attacking Mid"] * 5, "sprint_count_p90": 50.0})
    counts = pp.pool_counts(pcts)
    assert pp.metric_count(counts, 901, "Central Mid", "sprint_count_p90", POOL_POSITION) == 1
    assert pp.metric_count(counts, 901, "Central Mid", "sprint_count_p90", POOL_MIDFIELD) == 12


def test_physical_ranks_midfield_pool_band_no_rank_tagged():
    from lofc.core import physical_page as pp
    cards = pd.DataFrame({"player_id": [2], "competition_id": [901], "season_id": [319],
                          "position_group": ["Central Mid"], "physical_band": [3.4],
                          "peer_pool": [POOL_MIDFIELD], "peer_pool_size": [38]})
    r = pp.physical_ranks(cards, 901, 319, "Central Mid")[2]
    assert r["band"] == 3.4 and r["rank"] is None and r["text"] == DASH and r["tag"] == TAG


def test_physical_ranks_thin_pool_says_the_line():
    from lofc.core import physical_page as pp
    from test_core_physical_page import _cands, _cards, _pcts, _values
    c = _cands(8)
    v = _values(c)
    pool = pp.pool_frame(c, v, _pcts(c, v), 4, "Winger")
    out = pp.rating_leaders(pool, pp.physical_ranks(_cards(8), 4, 319, "Winger"), "Winger",
                            "League Two")
    assert out["thin"] == _line(8, "Winger", "League Two")
    lead = pp.leaders(pool, "sprint_count_p90", "Winger", "League Two")
    assert lead["thin"] == _line(8, "Winger", "League Two")


def test_physical_leaders_midfield_pool_show_percentiles_unranked_tagged():
    from lofc.core import physical_page as pp
    from test_core_physical_page import _cands, _pcts, _values
    c = _cands(3, comp=901, pos="Central Mid")
    v = _values(c)
    pool = pp.pool_frame(c, v, _pcts(c, v), 901, "Central Mid")
    out = pp.leaders(pool, "sprint_count_p90", "Central Mid", "Scottish Premiership",
                     scope=POOL_MIDFIELD, metric_n=38)
    assert out["thin"] is None and out["tag"] == TAG
    assert all(r is None for _i, r in out["order"])                    # no rank
    assert [pool.iloc[i]["player_name"] for i, _ in out["order"]] == ["P03", "P02", "P01"]
    rows = pp.pool_players(pool, {"sprint_count_p90": 38}, set(), lambda *a: None)
    assert all(r["p"]["sprint_count_p90"] is not None for r in rows)


def test_physical_squad_rows_thin_line_and_midfield_pool():
    from lofc.core import physical_page as pp
    from test_core_physical_page import _cands, _pcts, _values
    wing = _cands(12)
    cm = _cands(1, comp=901, pos="Central Mid").assign(player_id=50)
    dm = _cands(11, comp=901, pos="Defensive Mid").assign(player_id=range(60, 71))
    c = pd.concat([wing, cm, dm], ignore_index=True)
    v = _values(c)
    pc = pd.concat([_pcts(wing, v[v.competition_id == 4]),
                    _pcts(pd.concat([cm, dm]), v[v.competition_id == 901])])
    rows = c.set_index("player_id")[["competition_id", "position_group", "team_name",
                                     "minutes"]].copy()
    rows["physical_band"] = 3.5
    rows["peer_count"] = 30.0
    rows["peer_pool"] = POOL_POSITION
    rows["thin"] = False
    rows.loc[2, ["peer_count", "thin", "physical_band"]] = [6.0, True, float("nan")]
    rows.loc[50, ["peer_count", "peer_pool"]] = [12.0, POOL_MIDFIELD]
    sq = pd.DataFrame({"player_id": [2, 50], "player_name": ["B", "Cam"],
                       "position_group": ["Winger", "Central Mid"]})
    out = {r["name"]: r for r in pp.squad_rows(
        sq, rows, v, pc, pp.pool_counts(pc), {4: "League One", 901: "Scottish Premiership"},
        lambda *a: None)}
    assert out["B"]["note"] == _line(6, "Winger", "League One") and out["B"]["tag"] is None
    cam = out["Cam"]
    assert cam["note"] is None and cam["tag"] == TAG and cam["phys"] == 3.5
    assert cam["cells"]["top5_psv99_kmh"]["p"] is not None             # vs all 12 midfielders


def test_physical_performance_view_tags_the_midfield_pool():
    from lofc.core import physical_page as core
    from test_physical_performance_view import _frames, _href, NAMES as PNAMES
    squad, rows, pcts = _frames()
    rows["peer_pool"] = POOL_POSITION
    rows.loc[8, "peer_pool"] = POOL_MIDFIELD
    rows.loc[8, "competition_id"] = 5
    pcts.loc[pcts["player_id"] == 8, "competition_id"] = 5
    v = core.performance_rows(squad, rows, pcts, 319, PNAMES, _href, season_name="2026/27")
    by = {r["name"]: r for g in v["groups"] for r in g["rows"]}
    assert by["Playmaker"]["pool_tag"] == TAG
    assert by["Playmaker"]["league_tip"] == "Percentiles vs League Two midfielders"
    assert by["Holder"]["pool_tag"] is None


def test_physical_lines_count_the_rated_pool_not_the_tracked_players():
    """8 rated Wingers, 7 with tracking for a metric: the line says 8 (the pool he is rated in);
    12 rated with 8 tracked is a coverage gap, not "not rated": the count-only caption."""
    from lofc.core import physical_page as pp
    from test_core_physical_page import _cands, _pcts, _values
    c = _cands(7)
    v = _values(c)
    pool = pp.pool_frame(c, v, _pcts(c, v), 4, "Winger")
    assert pp.leaders(pool, "sprint_count_p90", "Winger", "League Two", pool_n=8)["thin"] == \
        _line(8, "Winger", "League Two")
    assert pp.leaders(pool, "sprint_count_p90", "Winger", "League Two", pool_n=12)["thin"] == \
        "Not rated: only 7 comparable players (needs 10)"
    rows = [{"name": f"P{i}", "v": {"a": float(i), "b": float(i)}, "bands": [""]} for i in range(7)]
    assert pp.scatter_summary(rows, "a", "b", "", position="Winger", league="League Two",
                              pool_n=8)["top_note"] == _line(8, "Winger", "League Two")
    assert pp.scatter_summary(rows, "a", "b", "", position="Central Mid", league="X",
                              pool_n=37)["top_note"] == "Not rated: only 7 comparable players (needs 10)"
