"""Compare page: season-wide search, same-position comparisons, last-season columns.

Pure pandas / dict logic plus loader SQL stubbed in the style of tests/test_loader_cache.py:
no Streamlit runtime, no database."""

import pandas as pd

from lofc.dashboard import loaders
from lofc.dashboard.search import build_search_index, search_options
from lofc.dashboard.tabs import compare as cmp
from lofc.dashboard.theme import NONE_OPTION


def _cands():
    rows = [
        (1, 2, 319, "Cara Forward", "Club A", "Centre Forward", "League One"),
        (2, 2, 319, "Carl Striker", "Club B", "Centre Forward", "League One"),
        (3, 3, 319, "Fred Back", "Club C", "Full Back", "League Two"),
    ]
    return pd.DataFrame(rows, columns=["player_id", "competition_id", "season_id", "player_name",
                                       "team_name", "position_group", "league"])


def test_search_options_include_every_position():
    labels, _ = search_options(build_search_index(_cands()))
    assert any("Full Back" in lbl for lbl in labels) and any("Centre Forward" in lbl for lbl in labels)


def _setup():
    idx = build_search_index(_cands())
    _, by_label = search_options(idx)
    label = next(lbl for lbl in by_label if lbl.startswith("Fred Back"))
    return idx, by_label, label


def test_pick_of_other_position_switches_sidebar_and_resets_other_slots():
    idx, by_label, label = _setup()
    state = {"sidebar_position": "Centre Forward", "sidebar_leagues": ["League One"],
             "cmp_a": "Cara Forward — Club A", "cmp_b": label,
             "cmp_c": "Cara Forward — Club A"}
    cmp.apply_compare_pick(state, idx, by_label, "Centre Forward", "cmp_b")
    assert state["sidebar_position"] == "Full Back"
    assert "League Two" in state["sidebar_leagues"]
    assert state["cmp_b"] == label                         # the slot picked in is kept
    assert "cmp_a" not in state                            # old-position slot reset to default
    assert state["cmp_c"] == NONE_OPTION


def test_pick_of_same_position_only_fills_the_picked_slot():
    idx, by_label, _ = _setup()
    label = next(lbl for lbl in by_label if lbl.startswith("Carl"))
    state = {"sidebar_position": "Centre Forward", "cmp_a": label, "cmp_b": "Cara Forward — Club A",
             "cmp_c": NONE_OPTION}
    cmp.apply_compare_pick(state, idx, by_label, "Centre Forward", "cmp_a")
    assert state["sidebar_position"] == "Centre Forward"
    assert state["cmp_a"] == label and state["cmp_b"] == "Cara Forward — Club A"
    assert state["cmp_c"] == NONE_OPTION


def test_unknown_pick_is_ignored():
    idx, by_label, _ = _setup()
    state = {"sidebar_position": "Centre Forward", "cmp_a": "nobody"}
    cmp.apply_compare_pick(state, idx, by_label, "Centre Forward", "cmp_a")
    assert state == {"sidebar_position": "Centre Forward", "cmp_a": "nobody"}


def test_leagueless_pick_does_not_add_a_dash_league():
    idx = build_search_index(_cands().assign(league=[None, None, None]))
    _, by_label = search_options(idx)
    label = next(lbl for lbl in by_label if lbl.startswith("Fred"))
    state = {"sidebar_leagues": ["League One"], "cmp_a": label}
    cmp.apply_compare_pick(state, idx, by_label, "Centre Forward", "cmp_a")
    assert state["sidebar_leagues"] == ["League One"]


def test_stale_slot_values_are_dropped_when_not_in_pool():
    labels = ["X — A", "Y — B"]
    state = {"cmp_a": "Gone — Z", "cmp_b": "Y — B", "cmp_c": "Gone — Z"}
    cmp.sanitize_slots(state, labels)
    assert "cmp_a" not in state and state["cmp_b"] == "Y — B" and state["cmp_c"] == NONE_OPTION


def test_comparison_rows_are_one_position():
    pool = pd.DataFrame({"player_name": ["a", "b"], "position_group": ["Full Back", "Full Back"]})
    assert cmp.same_position(pool)
    pool.loc[1, "position_group"] = "Winger"
    assert not cmp.same_position(pool)


def _pool_row(**kw):
    base = {"player_id": 1, "competition_id": 2, "season_id": 319, "player_name": "P",
            "team_name": "T", "age": 24.0, "objective_composite": 3.5, "performance_band": 3.4,
            "physical_band": 4.1, "league": "League One"}
    base.update(kw)
    return pd.Series(base)


def test_compare_row_shows_last_season_to_this_season_with_change():
    prev = pd.DataFrame([{"player_id": 1, "prev_composite": 3.41, "prev_physical": 4.5,
                          "prev_performance": 3.4, "prev_league": "League Two",
                          "prev_position": "Full Back"}])
    row = cmp.compare_row(_pool_row(objective_composite=3.68), prev, show_money=False)
    assert row["Overall"] == "3.41 (League Two) → 3.68 (+0.27)"    # league differs -> shown
    assert row["Performance"] == "3.40 → 3.40 (0.00)"
    assert row["Physical"] == "4.50 → 4.10 (-0.40)"
    assert row["League"] == "League One"
    same = cmp.compare_row(_pool_row(league="League Two", objective_composite=3.68), prev)
    assert same["Overall"] == "3.41 → 3.68 (+0.27)"


def test_season_change_text_and_colour():
    assert cmp.season_change(3.41, 3.68) == "3.41 → 3.68 (+0.27)"
    assert cmp.season_change(3.68, 3.41) == "3.68 → 3.41 (-0.27)"
    assert cmp.season_change(3.0, 3.0) == "3.00 → 3.00 (0.00)"
    assert cmp.season_change(None, 3.2) == "3.20"          # no previous season: this season only
    assert cmp.season_change(float("nan"), None) == "—"
    assert cmp.season_change(3.0, None) == "3.00 → —"
    assert cmp.change_style("3.41 → 3.68 (+0.27)") == cmp.UP_STYLE
    assert cmp.change_style("3.68 → 3.41 (-0.27)") == cmp.DOWN_STYLE
    assert cmp.change_style("3.00 → 3.00 (0.00)") == cmp.NEUTRAL_STYLE
    assert cmp.change_style("3.20") == cmp.NEUTRAL_STYLE and cmp.change_style("—") == cmp.NEUTRAL_STYLE
    assert "green" in cmp.UP_STYLE.lower() or "#" in cmp.UP_STYLE
    assert cmp.UP_STYLE != cmp.DOWN_STYLE


def _rows():
    prev = pd.DataFrame([{"player_id": 1, "prev_composite": 3.41, "prev_physical": 4.5,
                          "prev_performance": 3.4, "prev_league": "League Two"},
                         {"player_id": 2, "prev_composite": 3.90, "prev_physical": 3.0,
                          "prev_performance": 3.9, "prev_league": "League One"}])
    a = _pool_row(player_name="Ann <b>Up</b>", objective_composite=3.68, minutes=1200.0)
    b = _pool_row(player_id=2, player_name="Bob Down", team_name="Other & Co",
                  objective_composite=3.10, minutes=900.0)
    return [cmp.compare_row(a, prev), cmp.compare_row(b, prev)]


def test_comparison_html_has_players_as_columns_and_attributes_as_rows():
    html = cmp.comparison_html(_rows())
    # one header cell per player, escaped
    head = html.split("</thead>")[0]
    assert head.count("<th>") + head.count("<th ") == 3                       # blank corner + 2 players
    assert "Ann &lt;b&gt;Up&lt;/b&gt;" in html and "<b>Up</b>" not in html
    assert "Other &amp; Co" in html
    for label in ("Age", "Minutes", "Overall", "Performance", "Physical"):
        assert f">{label}<" in html
    # this season's value is the prominent figure; last season sits beside it
    assert ">3.68<" in html and "+0.27 vs 3.41 (League Two)" in html
    assert ">3.10<" in html and "-0.80 vs 3.90" in html


def test_comparison_html_colours_rises_green_and_falls_red():
    html = cmp.comparison_html(_rows())
    assert cmp.UP_STYLE in html and cmp.DOWN_STYLE in html


def test_comparison_html_handles_missing_previous_season_and_values():
    rows = [cmp.compare_row(_pool_row(minutes=None), pd.DataFrame())]
    html = cmp.comparison_html(rows)
    assert ">3.50<" in html and " vs " not in html
    assert "<table" in html and "overflow-x" not in html


def test_comparison_html_shows_market_value_row_only_when_given():
    assert "Market" not in cmp.comparison_html(_rows())
    row = cmp.compare_row(_pool_row(market_value_eur=2.5e6), None, show_money=True)
    assert ">Market (€m)<" in cmp.comparison_html([row])


def _pcts(**kw):
    base = {m: 50.0 for m in cmp.cf.PHYSICAL_METRICS["Winger"]}
    base.update(kw)
    return pd.Series(base)


def test_physical_radar_uses_top5_not_average_top_speed():
    axes, traces, missing = cmp.physical_radar_inputs(
        {"A": _pcts(), "B": _pcts(top5_psv99_kmh=80.0)}, "Winger")
    assert "psv99_kmh" not in axes and "top5_psv99_kmh" not in axes   # axes are display labels
    assert "Top speed" in axes and "Average match top speed" not in axes
    assert len(axes) == 6 and missing == []   # 7 rated physical metrics minus psv99
    assert [n for n, _ in traces] == ["A", "B"]
    assert traces[1][1][axes.index("Top speed")] == 80.0


def test_physical_radar_captions_and_excludes_player_without_data():
    nodata = _pcts(**{m: float("nan") for m in cmp.cf.PHYSICAL_METRICS["Winger"]})
    axes, traces, missing = cmp.physical_radar_inputs(
        {"A": _pcts(), "B": nodata, "C": None}, "Winger")
    assert missing == ["B", "C"] and [n for n, _ in traces] == ["A"]
    axes, traces, missing = cmp.physical_radar_inputs({"B": nodata}, "Winger")
    assert traces == [] and missing == ["B"]
    assert cmp.no_physical_caption(["B", "C"]) == "No physical data: B, C"


def test_goalkeeper_has_no_physical_radar():
    axes, traces, missing = cmp.physical_radar_inputs({"A": _pcts()}, "Goalkeeper")
    assert axes == [] and traces == [] and missing == []


def test_compare_row_blank_without_previous_season():
    row = cmp.compare_row(_pool_row(), pd.DataFrame(), show_money=False)
    assert row["Overall"] == "3.50" and row["Performance"] == "3.40" and row["Physical"] == "4.10"
    empty = pd.DataFrame(columns=["player_id", "prev_composite", "prev_physical",
                                  "prev_performance", "prev_league", "prev_position"])
    assert cmp.compare_row(_pool_row(), empty, show_money=False)["Overall"] == "3.50"


# --- load_previous_ratings ------------------------------------------------------------
def test_previous_ratings_keeps_most_minutes_row_and_reads_previous_season(monkeypatch):
    raw = pd.DataFrame({
        "player_id": [1, 1, 2], "competition_id": [2, 3, 2],
        "objective_composite": [3.0, 2.0, 4.0], "physical_band": [3.1, 2.1, None],
        "performance_band": [3.2, 2.2, 4.2],
        "position_group": ["Winger", "Winger", "Full Back"], "minutes": [500, 1500, 900]})
    seen = {}

    def fake_read_sql(sql, con, params=None, **k):
        seen["sql"], seen["params"] = sql, params
        return raw.copy()

    monkeypatch.setattr(loaders.pd, "read_sql", fake_read_sql)
    monkeypatch.setattr(loaders, "get_engine", lambda: None)
    got = loaders.load_previous_ratings.__wrapped__(319)
    assert seen["params"] == {"s": 318}
    assert "'All Metrics'" in seen["sql"] and "player_metrics_neutral" in seen["sql"]
    assert list(got.columns) == ["player_id", "prev_composite", "prev_physical",
                                 "prev_league", "prev_position", "prev_performance"]
    assert "performance_band" in seen["sql"]
    assert len(got) == 2
    p1 = got[got["player_id"] == 1].iloc[0]
    assert p1["prev_composite"] == 2.0 and p1["prev_performance"] == 2.2 and p1["prev_position"] == "Winger"   # 1,500-minute row
    assert 2 not in set(got[got["player_id"] == 3]["player_id"])


def test_previous_ratings_is_version_keyed():
    assert getattr(loaders.load_previous_ratings, "_is_versioned", False)


def test_slot_defaults_never_put_the_same_player_in_a_and_b():
    """Verifier, 2026-11-02: picking the player at index 1 into A left B to default to index 1
    too -- the same player -- and the page said "Pick two different players"."""
    from lofc.dashboard.tabs import compare
    labels = ["P0", "P1", "P2"]
    state = {"cmp_a": "P1"}
    compare.fill_default_slots(state, labels)
    assert state["cmp_a"] == "P1" and state["cmp_b"] == "P0"
    state = {"cmp_b": "P0"}
    compare.fill_default_slots(state, labels)
    assert state["cmp_a"] == "P1" and state["cmp_b"] == "P0"
    state = {}
    compare.fill_default_slots(state, labels)
    assert (state["cmp_a"], state["cmp_b"]) == ("P0", "P1")


def test_defaults_skip_the_picked_player_in_slot_c_too():
    """After an other-position pick into C, A and B default to the top two OTHER players."""
    from lofc.dashboard.tabs import compare
    state = {"cmp_c": "P0"}
    compare.fill_default_slots(state, ["P0", "P1", "P2"])
    assert (state["cmp_a"], state["cmp_b"]) == ("P1", "P2")


def test_slot_labels_for_first_load_come_from_pool_then_the_rest_of_the_position():
    from lofc.dashboard.tabs import compare
    idx = build_search_index(_cands())
    pool = _cands().iloc[[1]]            # filters left one forward in the pool
    got = compare.default_candidates(pool, idx, "Centre Forward")
    assert got[0].startswith("Carl") and got[1].startswith("Cara") and len(got) == 2


def test_compare_has_no_separate_search_box():
    import inspect
    assert not hasattr(cmp, "_search_box")
    assert "cmp_search" not in inspect.getsource(cmp)


def test_row_for_label_prefers_pool_and_falls_back_to_season_wide(monkeypatch):
    idx = build_search_index(_cands())
    _, by_label = search_options(idx)
    carl = next(lbl for lbl in by_label if lbl.startswith("Carl"))
    fred = next(lbl for lbl in by_label if lbl.startswith("Fred"))
    pool = _cands().iloc[[1]].assign(objective_composite=3.3)
    monkeypatch.setattr(cmp, "load_candidates", lambda m, s: _cands())
    monkeypatch.setattr(cmp, "load_scorecards", lambda s: pd.DataFrame())
    assert cmp.row_for_label(carl, idx, by_label, pool)["objective_composite"] == 3.3
    hidden = cmp.row_for_label(fred, idx, by_label, pool)      # filtered out of the pool
    assert hidden["player_name"] == "Fred Back"
