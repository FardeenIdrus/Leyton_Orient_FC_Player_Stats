"""`core/card.py` -- the player card's pure builders (TASKS 2.36). No database, no Streamlit
runtime: contract / loan chips, minutes split, rating wording, advisory, money, output tiles,
assessment wording, JSON hygiene."""
import datetime

import numpy as np
import pandas as pd

from lofc.core import card as C

TODAY = datetime.date(2026, 11, 8)


# --- clean(): blanks are null, never nan / None text ---------------------------------------
def test_clean_makes_everything_json_safe():
    out = C.clean({"a": np.int64(3), "b": np.float64("nan"), "c": float("inf"), "d": pd.NaT,
                   "e": pd.Timestamp("2026-06-30"), "f": (1, np.bool_(True)), "g": pd.NA,
                   "h": {1: np.float32(1.5)}})
    assert out == {"a": 3, "b": None, "c": None, "d": None, "e": "2026-06-30",
                   "f": [1, True], "g": None, "h": {"1": 1.5}}
    assert type(out["a"]) is int and type(out["h"]["1"]) is float


# --- header ---------------------------------------------------------------------------------
def test_register_cells_text_and_blanks():
    row = pd.Series({"age": 24.43, "foot": "right", "height_cm": 167.0, "nationality": None,
                     "minutes": 3066.7})
    assert C.register_cells(row) == [("Age", "24.4"), ("Foot", "Right"), ("Height", "167 cm"),
                                     ("Nationality", None), ("Minutes", "3,067")]
    assert [v for _, v in C.register_cells(pd.Series({}))] == [None] * 5


def test_contract_chip_wording_matches_the_streamlit_card():
    parts = lambda c: "".join(t for t, _ in c["parts"])
    assert parts(C.contract_chip(None, TODAY)) == "Contract not recorded"
    assert parts(C.contract_chip(pd.NaT, TODAY)) == "Contract not recorded"
    c = C.contract_chip(pd.Timestamp("2028-06-30"), TODAY)
    assert parts(c) == "Contract to Jun 2028 · 1y 7m left" and not c["expiring"]
    assert ("Jun 2028", True) in c["parts"]
    c = C.contract_chip(pd.Timestamp("2027-06-30"), TODAY)
    assert parts(c) == "Contract to Jun 2027 · 7m left" and c["expiring"]       # under 12 months
    assert parts(C.contract_chip(pd.Timestamp("2028-11-30"), TODAY)) == "Contract to Nov 2028 · 2y left"
    c = C.contract_chip(pd.Timestamp("2026-06-30"), TODAY)
    assert parts(c) == "Contract expired (Jun 2026)" and c["expiring"]


def test_loan_chip():
    assert C.loan_chip(None) is None
    loan = pd.Series({"parent_club": "Southampton FC", "loan_ends": pd.Timestamp("2027-06-30")})
    assert "".join(t for t, _ in C.loan_chip(loan)["parts"]) == \
        "On loan from Southampton FC · until Jun 2027"
    assert "".join(t for t, _ in C.loan_chip(pd.Series({"parent_club": None, "loan_ends": None}))["parts"]) == "On loan"


def _shares(rows):
    return pd.DataFrame(rows, columns=["position_group", "minutes", "share", "goals", "assists"])


def test_minutes_split_only_with_two_positions_and_marks_the_scored_one():
    assert C.minutes_split(None, "Winger") is None
    assert C.minutes_split(_shares([("Winger", 900, 1.0, 3, 1)]), "Winger") is None
    m = C.minutes_split(_shares([("Winger", 600, .6, 2, 0), ("Centre Forward", 400, .4, 0, 0)]), "Winger")
    assert [(s["position"], round(s["share_pct"]), s["assigned"]) for s in m["segments"]] == [
        ("Winger", 60, True), ("Centre Forward", 40, False)]
    assert m["segments"][0]["colour"] == "#C8102E" and m["segments"][1]["colour"] == "#6E747C"
    assert m["goals_line"] is None                       # his goals are in his biggest position


def test_minutes_split_goals_line_when_goals_come_from_elsewhere():
    m = C.minutes_split(_shares([("Winger", 600, .6, 0, 0), ("Centre Forward", 400, .4, 4, 0)]), "Winger")
    assert m["goals_line"] == "Goals: 4 as centre forward"


def test_scored_as_notice_only_when_largest_position_is_under_half():
    assert C.scored_as_notice(_shares([("Winger", 900, 1.0, 0, 0)])) is None
    assert C.scored_as_notice(_shares([("Winger", 600, .6, 0, 0), ("Full Back", 400, .4, 0, 0)])) is None
    n = C.scored_as_notice(_shares([("Winger", 450, .45, 0, 0), ("Full Back", 400, .40, 0, 0),
                                    ("Centre Back", 150, .15, 0, 0)]))
    assert n.startswith("Scored as **Winger** — his largest position, but only 45% of his minutes.")


def test_other_league_notes():
    others = pd.DataFrame({"competition_id": [4, 9], "minutes": [1234.4, 500.0],
                           "team_name": ["X FC", "Y FC"], "objective_composite": [3.456, np.nan]})
    got = C.other_league_notes(others, {4: "League One"}.get)
    assert got[0] == ("Also played 1,234 min for X FC in **League One** this season — rated "
                      "**3.46** there. Same player, scored separately because percentiles are "
                      "league-relative.")
    assert "competition 9" in got[1] and "rated" not in got[1]


# --- rating ---------------------------------------------------------------------------------
def test_rank_text():
    assert C.rank_text(None, 40) is None
    assert C.rank_text(3, 92) == "3rd of 92 in this league"
    assert C.rank_text(11, 45) == "11th of 45 in this league"
    assert C.rank_text(22, 45) == "22nd of 45 in this league"


def test_money_block_off_with_value_and_without():
    row = pd.Series({"competition_id": 5, "market_value_eur": 1_500_000.0, "fair_value_eur": np.nan,
                     "estimated_weekly_wage_gbp": 4200.0, "wage_ceiling_gbp": 6500.0})
    assert C.money_block(row, False) is None
    m = C.money_block(row, True)
    assert m["tiles"] == [{"label": "Market value", "value": "€1.5m"},
                          {"label": "Fair value", "value": "n/a"}]
    assert m["captions"] == ["Modelled weekly wage £4,200 vs the wage cap £6,500 for this player — "
                             "modelled estimate, not an actual salary."]
    nl = row.copy()
    nl["competition_id"], nl["fair_value_eur"] = 65, 2_000_000.0
    assert any(c.startswith("⚠️ Fair-value note") for c in C.money_block(nl, True)["captions"])
    none = row.copy()
    none["market_value_eur"] = np.nan
    assert C.money_block(none, True) == {"tiles": [], "captions": [
        "No market-value or wage data for this league (Scottish / PL2 aren't priced) — this is a quality view."]}


def test_veto_reasons_and_advisory_follow_the_affordability_switch():
    row = pd.Series({"veto": True, "performance_band": 3.0, "resale_band": 1.58,
                     "financial_band": 4.0, "below_min_composite": False,
                     "objective_composite": 3.4})
    assert C.advisory_flags(row, True) == ["Resale Potential 1.58 is below the club minimum of 2.00"]
    # modelling off: a flag that trips only on Resale says nothing (not the generic line)
    assert C.advisory_flags(row, False) == []
    generic = pd.Series({"veto": True, "below_min_composite": False})
    assert C.advisory_flags(generic, True) == [
        "below the club minimum (band < 2.0) on a dimension — detail unavailable on this view"]
    assert C.advisory_flags(generic, False) == []


def test_below_minimum_composite_flag_wording():
    row = pd.Series({"veto": False, "below_min_composite": True, "objective_composite": 2.5})
    assert C.advisory_flags(row, False) == ["Composite 2.50 is below the club's 3.00 minimum standard"]
    row["objective_composite"] = np.nan
    assert C.advisory_flags(row, False) == ["composite below the club's 3.00 minimum standard"]


def test_strengths_watchouts_needs_two_and_takes_three_each():
    p = pd.Series({"a": 90.0, "b": 10.0, "c": 50.0, "d": 70.0, "e": 30.0, "f": np.nan})
    got = C.strengths_watchouts(p, list("abcdef"), str.upper)
    assert got["strengths"] == [{"metric": "A", "pct": 90}, {"metric": "D", "pct": 70},
                                {"metric": "C", "pct": 50}]
    assert got["watch_outs"] == [{"metric": "B", "pct": 10}, {"metric": "E", "pct": 30},
                                 {"metric": "C", "pct": 50}]
    assert C.strengths_watchouts(pd.Series({"a": 1.0}), ["a"], str) is None
    assert C.strengths_watchouts(None, ["a"], str) is None


def test_underlying_rates_only_for_midfielders_and_attackers():
    """Text rule (2.36): the rates are tiles, the reason one short line."""
    row = pd.Series({"np_xg_p90": 0.213, "xa_p90": 0.158})
    r = C.underlying_rates("attacker", row)
    assert r["tiles"] == [{"label": "npxG/90", "value": "0.21"}, {"label": "xA/90", "value": "0.16"}]
    assert r["line"] == "These rates, steadier than raw goals and assists, drive the scores."
    assert C.underlying_rates("goalkeeper", row) is None
    assert C.underlying_rates("attacker", pd.Series({"np_xg_p90": np.nan, "xa_p90": 0.1})) is None
    # the live (Streamlit) card keeps its sentence
    assert C.underlying_rates_caption("attacker", row).startswith("Underlying rates: 0.21 non-pen xG per 90 · 0.16 xA per 90")
    assert C.underlying_rates_caption("goalkeeper", row) is None


def test_availability_short_lines_keep_every_fact():
    from lofc.model.medical import AvailabilityEvidence, AvailabilityStatus
    w = ("24/25", "25/26")
    measured = AvailabilityEvidence(status=AvailabilityStatus.MEASURED, value=1.0)
    assert C.availability_label(w) == "Available, 24/25 + 25/26"
    assert C.availability_line(measured) is None             # the figure + labels say it all
    unknown = AvailabilityEvidence(value=None, status=AvailabilityStatus.UNKNOWN)
    assert C.availability_line(unknown) == "Not known: no injury record, and his minutes do not confirm it — a data gap, not a clean record."
    unscored = AvailabilityEvidence(status=AvailabilityStatus.MEASURED, value=None)
    assert C.availability_line(unscored) == "Injury record present; availability is not scored for this competition."
    conf = AvailabilityEvidence(status=AvailabilityStatus.CONFIRMED_BY_MINUTES, value=1.0)
    assert C.availability_line(conf) == "Available: no injury record, and his minutes rule out a long absence."
    assert C.coverage_line({"with_record": 0.32, "knowable": 0.58}) == \
        "League injury coverage: 32% of players have a record · availability knowable for about 58%"
    assert C.coverage_line({"with_record": 0.32}) == "League injury coverage: 32% of players have a record"
    assert C.coverage_line(None) == "No injury coverage figure for this league: an empty record says nothing."


def test_has_rating_in_season():
    cards = pd.DataFrame({"player_id": [1, 2], "objective_composite": [3.0, np.nan]})
    assert C.has_rating_in_season(cards, 1) and not C.has_rating_in_season(cards, 2)
    assert not C.has_rating_in_season(None, 1) and not C.has_rating_in_season(cards.iloc[0:0], 1)


# --- season output (pure part needs the retired-column plan: patched) ------------------------
def test_season_output_tiles_attacker_goalkeeper_defender():
    row = pd.Series({"minutes": 1000.5, "goals": 7.0, "assists": np.nan})
    mv = pd.Series({"goals_p90": 0.5, "assists_p90": 0.31})
    mvs = pd.DataFrame({"save_pct": [np.nan], "gk_saves_p90": [np.nan], "tackles_p90": [np.nan],
                        "interceptions_p90": [np.nan]})
    out = C.season_output_tiles("attacker", row, mv, mvs)
    assert out["note"] is None
    assert [(t["slot"], t["label"], t["value"]) for t in out["tiles"]] == [
        (0, "Goals", "7"), (1, "Assists", "3"), (2, "Minutes", "1,001")]
    gk = C.season_output_tiles("goalkeeper", row, mv, mvs)
    assert [t["label"] for t in gk["tiles"]] == ["Minutes"] and "no longer published" in gk["note"]
    df = C.season_output_tiles("defender", row, mv, mvs)
    assert [t["label"] for t in df["tiles"]] == ["Minutes"] and "Tackles / Interceptions" in df["note"]
    # data returns: the tile comes back by itself
    mvs.loc[0, "tackles_p90"] = 2.0
    mv2 = pd.Series({"tackles_p90": 2.0})
    out = C.season_output_tiles("defender", row, mv2, mvs)
    assert [(t["slot"], t["label"], t["value"]) for t in out["tiles"]] == [
        (0, "Tackles", "22"), (2, "Minutes", "1,001")] and out["note"] is None


# --- trajectory view --------------------------------------------------------------------------
def test_trajectory_view_columns_by_role():
    rows = pd.DataFrame({
        "season_name": ["2025/2026"], "competition_name": ["League Two"], "team_name": ["Chesterfield"],
        "minutes": [3066.7], "Overall": [3.4149], "Performance": [3.8249], "Physical": [np.nan],
        "goals": [8.0], "assists": [np.nan], "np_xg_p90": [0.2149], "xa_p90": [0.1651],
        "save_pct": [0.7], "gk_saves_p90": [3.456], "tackles_p90": [1.234],
        "interceptions_p90": [0.987], "pass_completion_pct": [0.834]})
    v = C.trajectory_view(rows, "attacker")
    assert list(v.columns) == ["Season", "League", "Club", "Minutes", "Overall", "Performance",
                               "Physical", "Goals", "Assists", "npxG/90", "xA/90"]
    r = v.iloc[0]
    assert (r["Season"], r["Minutes"], r["Overall"], r["Goals"], r["Assists"]) == ("2025/26", 3067, 3.41, 8, 0)
    assert pd.isna(r["Physical"]) and r["npxG/90"] == 0.21
    assert list(C.trajectory_view(rows, "goalkeeper").columns)[-2:] == ["Save %", "Saves/90"]
    d = C.trajectory_view(rows, "defender")
    assert list(d.columns)[-3:] == ["Tackles/90", "Interceptions/90", "Pass %"]
    assert d.iloc[0]["Pass %"] == 83


# --- assessment wording ------------------------------------------------------------------------
def test_outstanding_warning_only_when_exactly_one_is_missing():
    assert C.outstanding_warning([]) is None
    assert C.outstanding_warning(["Psychological", "Medical"]) is None
    assert C.outstanding_warning(["Medical"]).startswith("**Medical is still outstanding**")


def test_dimension_caption_conflict_winner_and_single():
    assert C.dimension_caption("signed_off", 1, 1) is None
    assert C.dimension_caption("conflict", 2, 2).startswith("2 assessments disagree.")
    assert C.dimension_caption("signed_off", 3, 2) == (
        "3 assessments exist for this dimension. The signed-off one scores; the others stay on the "
        "record, attributed.")
    assert "The submitted one scores" in C.dimension_caption("submitted", 2, 2)
    assert "None of them currently scores" in C.dimension_caption(None, 2, 0)


def test_flag_lines():
    class E:
        def __init__(self, **kw):
            self.__dict__.update(dict(author_name="Pat", status="submitted", screening_failed=False,
                                      notes=None, rejection_reason=None,
                                      created_at=datetime.datetime(2026, 11, 2)), **kw)
    assert C.flag_lines([E()]) == []
    got = C.flag_lines([E(status="rejected", rejection_reason="too thin", notes="check")])
    assert got == ["**Pat**, 02 Nov 2026 — rejected — too thin; notes: check"]
    assert "rejected (no reason recorded)" in C.flag_lines([E(status="rejected")])[0]
    assert "a screening criterion was not met" in C.flag_lines([E(screening_failed=True)])[0]


def test_report_card_drops_absent_parts_and_keeps_text():
    r = pd.Series({"scout": "Lindon Lynch", "fixture_date": pd.Timestamp("2026-10-10"),
                   "observation": "Live", "grade": "C", "verdict": "Don't sign",
                   "home_team": "A", "away_team": "B", "positions_played": ["RW", "LW"],
                   "squad_role": np.nan, "comments": "He <b>runs</b>"})
    c = C.report_card(r)
    assert c["title"] == [("Lindon Lynch", True), ("10 Oct 2026", False), ("Live", False),
                          ("Grade C", False), ("Don't sign", False)]
    assert c["match"] == "A v B · played RW, LW" and c["squad_role"] is None
    assert c["comments"] == "He <b>runs</b>"             # text, escaped by the page
    bare = pd.Series({"scout": "S", "fixture_date": pd.NaT, "observation": np.nan, "grade": np.nan,
                      "verdict": np.nan, "home_team": np.nan, "away_team": np.nan,
                      "positions_played": None, "squad_role": np.nan, "comments": np.nan})
    c = C.report_card(bare)
    assert c["title"] == [("S", True)] and c["match"] is None and c["comments"] is None


def test_text_or_blank_never_lets_nan_through():
    # `x or DASH` keeps NaN (it is truthy); the card header must show the dash instead
    assert C.text_or(float("nan"), C.DASH) == C.DASH
    assert C.text_or(None, "") == "" and C.text_or(pd.NA, "") == ""
    assert C.text_or("", C.DASH) == C.DASH
    assert C.text_or("League Two", "") == "League Two"


def test_csv_disposition_survives_non_latin1_names():
    h = C.csv_disposition("Baran_Yıldız_318_metrics.csv")
    h.encode("latin-1")                                   # a header must be latin-1 safe
    assert 'filename="Baran_Yildiz_318_metrics.csv"' in h
    assert "filename*=UTF-8''Baran_Y%C4%B1ld%C4%B1z_318_metrics.csv" in h
    assert C.csv_disposition("Dilan_Markanday_318_metrics.csv") == (
        'attachment; filename="Dilan_Markanday_318_metrics.csv"; '
        "filename*=UTF-8''Dilan_Markanday_318_metrics.csv")


def test_season_output_totals_round_half_up():
    # owner 2026-11-09: half-up everywhere. 0.25 per 90 over 900 minutes = 2.5 tackles -> "3"
    # (Python's round() gave "2", half to even); goals / assists were already half-up.
    row = pd.Series({"minutes": 900.0, "goals": np.nan, "assists": np.nan})
    mv = pd.Series({"tackles_p90": 0.25, "interceptions_p90": 0.45})   # 4.5 -> "5"
    mvs = pd.DataFrame({"save_pct": [np.nan], "gk_saves_p90": [np.nan], "tackles_p90": [1.0],
                        "interceptions_p90": [1.0]})
    out = C.season_output_tiles("defender", row, mv, mvs)
    vals = {t["label"]: t["value"] for t in out["tiles"]}
    assert vals["Tackles"] == "3" and vals["Interceptions"] == "5"


# --- U15 "vs ours" and U13 weight groups (TASKS 2.36) ---------------------------------------
def test_gap_to_ours_is_whole_points_half_up_both_signs():
    assert C.gap_to_ours(72.0, 54.0) == 18
    assert C.gap_to_ours(40.0, 47.0) == -7
    assert C.gap_to_ours(50.0, 50.0) == 0
    assert C.gap_to_ours(60.5, 50.0) == 11          # +10.5 -> 11
    assert C.gap_to_ours(50.0, 60.5) == -10         # -10.5 -> -10 (half UP)
    assert C.gap_to_ours(50.0, 56.7) == -7
    assert C.gap_to_ours(None, 50.0) is None and C.gap_to_ours(50.0, None) is None
    assert C.gap_to_ours(float("nan"), 50.0) is None and C.gap_to_ours(50.0, np.nan) is None


def test_vs_ours_column_blank_for_thin_pool_and_missing_values():
    prow = pd.Series({"a": 72.0, "b": 40.0, "c": np.nan})
    orient = {"a": 54.0, "b": 47.0, "c": 50.0}
    assert C.vs_ours_column(["a", "b", "c", "d"], prow, orient, thin=None) == [18, -7, None, None]
    assert C.vs_ours_column(["a", "b"], prow, orient, thin=8) == [None, None]
    assert C.vs_ours_column(["a"], None, orient, thin=None) == [None]
    assert C.vs_ours_column(["a"], prow, {}, thin=None) == [None]


def test_vs_ours_help_names_the_median():
    assert C.vs_ours_help("Centre Forward", 4) == ("Gap to our current Centre Forwards' median "
                                                   "(4 players). Percentiles are within each "
                                                   "player's own league.")
    assert C.vs_ours_help("Winger", 1) == ("Gap to our current Wingers' median (1 player). "
                                           "Percentiles are within each player's own league.")
    assert C.vs_ours_help("Winger", 0) is None


def test_weight_tiers_follow_rating_metrics():
    from lofc.dashboard import compare_tables as ct
    from lofc.model import club_framework as cf
    pos, lens = "Winger", cf.DEFAULT_ARCHETYPE
    pairs = ct.rating_metrics(pos, lens)
    metrics = [m for m, _ in pairs]
    assert C.weight_tiers(metrics, pos, lens) == [t for _, t in pairs]
    assert C.weight_tiers(["not_a_metric"], pos, lens) == [None]
