"""`core/squad.py` -- "Against our <position>s" on the player card (TASKS 2.32).

Pure functions only (no Streamlit runtime, no Postgres): who counts as "ours", the ordering and
"Nth of M", the two gap lists, the singular/plural wording, the Orient-player exclusion, the
unrated rows and the median the card's radar draws.
"""
import pandas as pd

from lofc.core import squad as sf
from lofc.core.squad import SfPlayer


def _p(name, overall=None, minutes=None, pct=None, **kw):
    return SfPlayer(name=name, overall=overall, minutes=minutes, pct=pct or {}, **kw)


# --- who is "ours" ---------------------------------------------------------------------
def test_orient_matched_by_name_or_by_impect_squad_id():
    assert sf.is_orient_club("Leyton Orient", None)
    assert sf.is_orient_club("leyton orient fc", None)       # spelling drift
    assert sf.is_orient_club(None, 966)                      # name missing, id known
    assert not sf.is_orient_club("FC Lorient", 49)           # contains "orient" but is not us
    assert not sf.is_orient_club(None, None)
    assert not sf.is_orient_club(float("nan"), None)


def test_position_is_the_most_minutes_row_of_the_most_recent_season():
    neutral = pd.DataFrame({
        "player_id": [1, 1, 1, 2, 2],
        "player_name": ["A", "A", "A", "B", "B"],
        "season_id": [318, 319, 319, 318, 318],
        "position_group": ["Winger", "Centre Forward", "Winger", "Winger", "Centre Forward"],
        "minutes": [3000, 100, 900, 200, 50],
    })
    got = sf.current_positions(neutral)
    assert got.set_index("player_id")["position_group"].to_dict() == {1: "Winger", 2: "Winger"}
    # A is a winger because that is where he played most in 2026/27 (900 > 100), not because
    # of 2025/26; B has only 2025/26.
    neutral.loc[neutral.position_group == "Centre Forward", "minutes"] = [1000, 10]
    got = sf.current_positions(neutral).set_index("player_id")["position_group"].to_dict()
    assert got == {1: "Centre Forward", 2: "Winger"}


def test_ours_are_the_orient_rows_at_the_position_only():
    squad = pd.DataFrame({"player_id": [1, 2, 3], "player_name": ["A", "B", "C"],
                          "position_group": ["Winger", "Centre Forward", "Winger"]})
    assert sf.ours_at(squad, "Winger")["player_id"].tolist() == [1, 3]
    assert sf.ours_at(squad, "Goalkeeper").empty
    assert sf.ours_at(squad, "Winger", exclude_player_id=3)["player_id"].tolist() == [1]


# --- wording ----------------------------------------------------------------------------
def test_plural_and_title():
    assert sf.plural("Centre Forward") == "Centre Forwards"
    assert sf.plural("Goalkeeper") == "Goalkeepers"
    assert sf.title("Centre Forward", target_is_ours=False) == "Against our Centre Forwards"
    assert sf.title("Centre Forward", target_is_ours=True) == "Against our other Centre Forwards"
    assert sf.subtitle("Centre Forward") == (
        "Leyton Orient's current centre forwards · each rated in his own league")


def test_ordinal():
    assert [sf.ordinal(n) for n in (1, 2, 3, 4, 11, 12, 13, 21, 22)] == [
        "1st", "2nd", "3rd", "4th", "11th", "12th", "13th", "21st", "22nd"]


def test_gap_note_singular_and_plural():
    assert sf.gap_note(1, "Centre Forward") == (
        "Gap in percentile points vs our only rated centre forward on that metric.")
    assert sf.gap_note(5, "Centre Forward") == (
        "Gap in percentile points vs the best of our 5 centre forwards on that metric.")


def test_better_than_heading_singular_when_one_rated():
    assert sf.better_heading(4, "Centre Forward") == "Better than all our Centre Forwards"
    assert sf.better_heading(1, "Centre Forward") == "Better than our only rated centre forward"


# --- ordering / "Nth of M" ----------------------------------------------------------------
def test_summary_second_of_six_with_best_named():
    target = _p("Drinan", 4.17)
    ours = [_p("Kabia", 4.18, league="League Two"), _p("Connolly", 3.16), _p("Oyekunle", 2.63),
            _p("Scarlett", 2.49), _p("Balde", 3.61), _p("Unrated")]
    s = sf.summary(target, ours)
    assert (s["rank"], s["of"]) == (2, 6)
    assert s["n_ours"] == 6 and s["n_unrated"] == 1
    assert s["best"].name == "Kabia"
    assert s["rank_text"] == "2nd of 6"


def test_summary_first_of_two_and_no_rated():
    s = sf.summary(_p("Drinan", 4.0), [_p("Kabia", 3.77), _p("Unrated")])
    assert (s["rank"], s["of"]) == (1, 2)
    s = sf.summary(_p("Drinan", 4.0), [_p("Unrated"), _p("Other")])
    assert (s["rank"], s["of"]) == (1, 1) and s["best"] is None


def test_summary_tie_shares_the_better_place():
    s = sf.summary(_p("T", 3.5), [_p("A", 3.5), _p("B", 3.0)])
    assert s["rank"] == 1          # level with A, nobody strictly above him


def test_summary_unrated_target_has_no_rank():
    s = sf.summary(_p("T", None), [_p("A", 3.5)])
    assert s["rank"] is None


def test_among_text_wording():
    assert sf.among_text(6, 1, "Centre Forward") == (
        "among our 6 centre forwards (1 not rated this season)")
    assert sf.among_text(5, 0, "Centre Forward") == "among our 5 centre forwards"
    assert sf.among_text(1, 0, "Centre Forward") == "among our only centre forward"
    assert sf.among_text(2, 2, "Centre Forward") == (
        "among our 2 centre forwards (2 not rated this season)")


def test_table_order_rated_best_first_then_unrated_by_minutes():
    ours = [_p("U1", None, 100), _p("A", 3.0, 900), _p("U2", None, 300), _p("B", 4.0, 800)]
    assert [p.name for p in sf.order_ours(ours)] == ["B", "A", "U2", "U1"]


# --- unrated rows --------------------------------------------------------------------------
def test_unrated_text():
    assert sf.unrated_text(104) == "Not rated: under 450 minutes"
    assert sf.unrated_text(449.9) == "Not rated: under 450 minutes"
    # 450+ minutes and still no rating = his league-position pool is below the floor
    assert sf.unrated_text(450) == "Not rated: too few peers in his league"
    assert sf.unrated_text(1800) == "Not rated: too few peers in his league"
    assert sf.unrated_text(0) == "No minutes this season"
    assert sf.unrated_text(None) == "No minutes this season"


# --- gap lists ------------------------------------------------------------------------------
def test_gap_lists_best_of_ours_and_who():
    metrics = ["a", "b", "c", "d"]
    target = _p("T", 4.0, pct={"a": 65, "b": 90, "c": 12, "d": 50})
    ours = [_p("Jaze Kabia", 4.1, pct={"a": 48, "b": 95, "c": 65, "d": 50}),
            _p("Connolly", 3.0, pct={"a": 30, "b": 20, "c": 10, "d": 40})]
    better, worse, n = sf.gap_lists(target, ours, metrics)
    assert n == 2
    assert [(g.metric, g.gap) for g in better] == [("a", 17)]       # b: 90 vs best 95 -> worse
    assert [(g.metric, g.gap, g.who) for g in worse] == [("c", -53, "Jaze Kabia"), ("b", -5, "Jaze Kabia")]
    assert better[0].his == 65 and better[0].theirs == 48
    assert not any(g.metric == "d" for g in better + worse)         # level = in neither list


def test_gap_lists_caps_five_and_four_and_orders_by_size():
    metrics = [f"m{i}" for i in range(12)]
    target = _p("T", pct={f"m{i}": 90 - i for i in range(12)})
    ours = [_p("O", pct={f"m{i}": 50 for i in range(6)} | {f"m{i}": 99 for i in range(6, 12)})]
    better, worse, _ = sf.gap_lists(target, ours, metrics)
    assert len(better) == 5 and [g.metric for g in better] == ["m0", "m1", "m2", "m3", "m4"]
    assert len(worse) == 4 and worse[0].gap <= worse[1].gap <= worse[2].gap


def test_gap_lists_skip_metrics_with_no_value_for_him_or_for_ours():
    target = _p("T", pct={"a": None, "b": 70, "c": 70})
    ours = [_p("O", pct={"a": 10, "b": None})]
    better, worse, _ = sf.gap_lists(target, ours, ["a", "b", "c"])
    assert better == [] and worse == []


def test_gap_lists_ignore_players_without_percentiles():
    target = _p("T", pct={"a": 70})
    ours = [_p("NoPct", None, pct={}), _p("O", pct={"a": 60})]
    better, worse, n = sf.gap_lists(target, ours, ["a"])
    assert n == 1 and len(better) == 1


def test_gap_rounds_half_up():
    better, _, _ = sf.gap_lists(_p("T", pct={"a": 60.5}), [_p("O", pct={"a": 50.0})], ["a"])
    assert better[0].gap == 11         # 10.5 -> 11, not banker's 10


def test_gap_line_text():
    g = sf.Gap("Aerial win %", 17, 65, 48, "Jaze Kabia")
    assert sf.gap_line(g) == ("up", "▲ 17", "Aerial win %", "him 65, our best 48")
    g = sf.Gap("Aerial win %", -53, 12, 65, "Jaze Kabia")
    assert sf.gap_line(g) == ("dn", "▼ 53", "Aerial win %", "him 12, Jaze 65") or \
        sf.gap_line(g)[3] == "him 12, Kabia 65"


# --- median (the card's radar line) ---------------------------------------------------------
def test_median_over_players_with_percentiles_only():
    ours = [_p("A", pct={"a": 10, "b": 40}), _p("B", pct={"a": 30}), _p("C", pct={}),
            _p("D", pct={"a": 90, "b": None})]
    med, n = sf.median_pct(ours, ["a", "b", "z"])
    assert n == 3
    assert med == {"a": 30.0, "b": 40.0}          # z has no value anywhere -> absent, not 0


def test_median_empty():
    assert sf.median_pct([], ["a"]) == ({}, 0)


# --- plain data for the page ---------------------------------------------------------------
def test_table_rows_target_first_with_blanks_as_none_and_unrated_reason():
    t = _p("T <b>", 4.0, 3000, club="Swindon & Co", league="League Two", is_target=True,
           age=28.5, contract="Jun 2030", style="Scorer")
    o = _p("<script>x</script>", None, 104, club="Club", note="On loan from A&B", age=19.8)
    rows = sf.table_rows([t, o])
    # the page escapes (textContent); the data carries the provider's text untouched
    assert [r["name"] for r in rows] == ["T <b>", "<script>x</script>"]
    assert rows[0]["is_target"] and not rows[1]["is_target"]
    assert rows[0]["overall"] == 4.0 and rows[0]["style"] == "Scorer"
    assert rows[1]["overall"] is None and rows[1]["style"] is None
    assert rows[1]["unrated"] == "Not rated: under 450 minutes" and rows[0]["unrated"] is None
    assert rows[1]["note"] == "On loan from A&B"


def test_table_rows_blanks_are_none_never_nan():
    rows = sf.table_rows([_p("T", 4.0, 1000, is_target=True), _p("O", 3.0, 900)])
    for r in rows:
        for k in ("age", "club", "contract", "league_abbr"):
            assert r[k] is None
    assert not any(isinstance(v, float) and v != v for r in rows for v in r.values())


def test_metric_matrix_marks_best_and_handles_missing():
    a = _p("Aaa Target", pct={"m": 50}, is_target=True)
    b = _p("Bbb Kabia", pct={"m": 80, "p": 40})
    mm = sf.metric_matrix([a, b], perf=[("m", "Metric M")], phys=[("p", "Phys P")])
    assert [s["name"] for s in mm["sections"]] == ["Performance", "Physical"]
    perf = mm["sections"][0]["rows"][0]
    assert perf["label"] == "Metric M"
    assert [c["best"] for c in perf["cells"]] == [False, True]
    phys = mm["sections"][1]["rows"][0]["cells"]
    assert phys[0]["pct"] is None and phys[1]["pct"] == 40 and phys[1]["best"]
    assert [p["short"] for p in mm["players"]] == ["Target", "Kabia"]


def test_metric_matrix_leaves_out_a_section_with_no_values():
    a = _p("A B", pct={"m": 50}, is_target=True)
    mm = sf.metric_matrix([a], perf=[("m", "M")], phys=[("p", "P")])
    assert [s["name"] for s in mm["sections"]] == ["Performance"]


# --- orient_median, the card radar's Orient line (data frames patched in) ------------------------
def _patch_data(monkeypatch, pct_rows, squad_rows):
    squad = pd.DataFrame(squad_rows, columns=["player_id", "player_name", "position_group"])
    squad["birth_date"] = pd.NaT
    squad["contract_until"] = pd.NaT
    squad["last_club"] = "Leyton Orient"
    rows = pd.DataFrame({"player_id": [r[0] for r in pct_rows], "competition_id": 4,
                         "position_group": "Winger", "team_name": "Leyton Orient",
                         "minutes": 900.0, "peer_count": 40.0, "objective_composite": 3.0,
                         "performance_band": 3.0, "physical_band": 3.0}).set_index("player_id")
    pf = pd.DataFrame({"player_id": [r[0] for r in pct_rows], "competition_id": 4,
                       "season_id": 319, "position_group": "Winger",
                       "goals_p90": [r[1] for r in pct_rows]})
    monkeypatch.setattr(sf, "squad", lambda: squad)
    monkeypatch.setattr(sf, "season_rows", lambda sid: rows)
    monkeypatch.setattr(sf.L, "load_scorecard_percentiles", lambda sid: pf)
    monkeypatch.setattr(sf.L, "load_loans", lambda sid=None: pd.DataFrame())
    monkeypatch.setattr(sf.L, "competition_name_by_id", lambda: {4: "League One"})


def test_orient_median_is_over_current_players_at_the_position(monkeypatch):
    _patch_data(monkeypatch, [(1, 20.0), (2, 60.0), (3, 90.0)],
                [(1, "A", "Winger"), (2, "B", "Winger"), (3, "C", "Centre Forward")])
    med, n = sf.orient_median("Winger", 319)
    assert n == 2 and med == {"goals_p90": 40.0}        # C is a forward: not counted


def test_orient_median_none_at_that_position(monkeypatch):
    _patch_data(monkeypatch, [(1, 20.0)], [(1, "A", "Winger")])
    assert sf.orient_median("Goalkeeper", 319) == ({}, 0)


# --- follow-ups: position over two seasons, loans matched on Transfermarkt id ----------------
def test_one_short_season_does_not_reclassify_a_player():
    """Connolly: 1,872 CF minutes in 2025/26, 337 W minutes in 2026/27 -> Centre Forward."""
    neutral = pd.DataFrame({
        "player_id": [24835] * 3 + [7] * 2,
        "player_name": ["Aaron Connolly"] * 3 + ["Old Hand"] * 2,
        "season_id": [317, 318, 319, 317, 319],
        "position_group": ["Winger", "Centre Forward", "Winger", "Winger", "Defensive Mid"],
        "minutes": [1056.0, 1872.0, 337.0, 900.0, 40.0],
    })
    got = sf.current_positions(neutral, seasons=[318, 319]).set_index("player_id")["position_group"]
    assert got[24835] == "Centre Forward"        # 2017/18-style older season is ignored
    assert got[7] == "Defensive Mid"             # no data in 318: falls back to latest season


def test_position_sums_both_seasons_before_choosing():
    neutral = pd.DataFrame({
        "player_id": [1, 1, 1], "player_name": ["A"] * 3, "season_id": [318, 319, 319],
        "position_group": ["Winger", "Centre Forward", "Winger"],
        "minutes": [600.0, 700.0, 200.0]})
    got = sf.current_positions(neutral, seasons=[318, 319])
    assert got["position_group"].tolist() == ["Winger"]     # 800 W vs 700 CF


def test_loans_matched_on_tm_id_when_player_id_missing():
    loans = pd.DataFrame({"club_name": ["Leyton Orient", "Leyton Orient", "Elsewhere"],
                          "player_id": [391964.0, None, 5.0],
                          "tm_player_id": [1081149, 527329, 9],
                          "parent_club": ["Southampton FC", "Coventry City", "X"]})
    squad = pd.DataFrame({"player_id": [391964, 42948, 5], "tm_player_id": [1081149, 527329, 9]})
    got = sf.loans_to_orient(loans, squad)
    assert got == {391964: "Southampton FC", 42948: "Coventry City"}   # 5 is on loan elsewhere


def test_an_empty_gap_list_is_empty_so_the_page_writes_the_dash():
    # Owner's rule (TASKS 2.26): blanks read "—", never "None" -- the page does the writing.
    assert sf.gap_items([], lambda m: m) == []


def test_gap_items_carry_the_arrow_label_and_detail():
    g = sf.Gap("m", 17, 65, 48, "Jaze Kabia")
    assert sf.gap_items([g], lambda m: "Aerial") == [
        {"kind": "up", "arrow": "▲ 17", "label": "Aerial", "detail": "him 65, our best 48"}]


# --- reviewer fixes --------------------------------------------------------------------------
def _rows():
    return pd.DataFrame({
        "competition_id": [4, 4, 9], "position_group": ["Winger"] * 3,
        "team_name": ["A", "B", "C"], "minutes": [900.0, 800.0, 700.0],
        "objective_composite": [3.5, 4.9, 3.0], "performance_band": [3.0, 4.8, 2.9],
        "physical_band": [3.1, 4.7, 3.0], "peer_count": [40.0, 1.0, float("nan")],
    }, index=pd.Index([1, 2, 3], name="player_id"))


def test_pool_floor_blanks_ratings_in_a_thin_pool():
    out = sf.apply_pool_floor(_rows())
    assert out.loc[1, "objective_composite"] == 3.5 and not out.loc[1, "thin"]
    for pid in (2, 3):                      # pool of 1, and pool unknown (NaN counts as thin)
        assert out.loc[pid, "thin"]
        assert out.loc[[pid], ["objective_composite", "performance_band", "physical_band"]
                       ].isna().all().all()


def test_thin_pool_player_is_not_ranked_or_named_best():
    thin = _p("Thin", None, 900)
    s = sf.summary(_p("T", 3.0), [thin, _p("Ok", 3.4)])
    assert (s["rank"], s["of"], s["best"].name, s["n_unrated"]) == (2, 2, "Ok", 1)
    assert sf.unrated_text(900) == sf.table_rows([_p("T", 3.0, 500, is_target=True), thin])[1]["unrated"]


def test_lens_overlays_only_the_positions_rows():
    rows = _rows().assign(position_group=["Winger", "Winger", "Centre Back"])
    lens = pd.DataFrame({"player_id": [1], "competition_id": [4], "position_group": ["Winger"],
                         "objective_composite": [2.2], "performance_band": [2.0],
                         "physical_band": [2.4]})
    out = sf.overlay_lens(rows, lens, "Winger")
    assert out.loc[1, "objective_composite"] == 2.2 and out.loc[1, "performance_band"] == 2.0
    assert pd.isna(out.loc[2, "objective_composite"])         # at the position, not in the lens
    assert out.loc[3, "objective_composite"] == 3.0           # other position: untouched


def test_subtitle_names_the_lens_only_when_not_default():
    assert sf.subtitle("Centre Forward", "All Metrics") == sf.subtitle("Centre Forward")
    assert sf.subtitle("Centre Forward", "Target Man").endswith(" \u00b7 Rated as Target Man")


def test_gap_equals_the_displayed_difference():
    better, _, _ = sf.gap_lists(_p("T", pct={"a": 60.4}), [_p("O", pct={"a": 50.6})], ["a"])
    g = better[0]
    assert (g.his, g.theirs, g.gap) == (60, 51, 9)            # not 10 (raw 9.8)


def test_minutes_round_half_up():
    assert sf.table_rows([_p("T", 3.0, 1000.5, is_target=True, club="C")])[0]["minutes"] == 1001
    assert sf.table_rows([_p("T", 3.0, 0.5, is_target=True)])[0]["minutes"] == 1
    assert sf.table_rows([_p("T", 3.0, 0, is_target=True)])[0]["minutes"] is None


def test_orient_median_can_exclude_a_player(monkeypatch):
    _patch_data(monkeypatch, [(1, 20.0), (2, 60.0)],
                [(1, "A", "Winger"), (2, "B", "Winger")])
    assert sf.orient_median("Winger", 319) == ({"goals_p90": 40.0}, 2)
    assert sf.orient_median("Winger", 319, exclude_player_id=2) == ({"goals_p90": 20.0}, 1)


def test_radar_median_label_names_how_many_players():
    # owner-approved 2026-11-09: the key says how many of ours the median is over
    assert sf.median_label("Centre Forward", 1) == "Our current centre forwards' median (1)"
    assert sf.median_label("Winger", 4) == "Our current wingers' median (4)"
