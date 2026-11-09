"""The Report page as plain data (TASKS 2.36): the helpers lifted out of the Streamlit page and
the web view of one `ReportData`. No database: the report itself is `report.data.build`'s
(tested in test_report_data.py); here only what the page decides is pinned."""
import datetime as dt

import pandas as pd
import pytest

from lofc.core import report_page as rp
from lofc.report import data


def _report(**overrides):
    base = dict(
        player_name="A Player", position="Winger", club="A Club",
        league="League Two", season_label="25/26", age=24.1, foot="right",
        height_cm=182, nationality="England", contract_until="30 Jun 2027",
        minutes=1026.5, goals=2.5, assists=6.0, composite=3.9,
        dimension_bands={"Performance": 4.1, "Physical": 3.6,
                         "Psychological": None, "Medical": None},
        rank=7, peer_count=70,
        percentiles={"turnovers_p90": 30.0, "distance_p90": 55.0},
        physical={"distance_p90": 55.0},
        availability=0.92, availability_status="measured", matches_missed=3,
        injuries=[], narrative=None,
        stamp=data.STAMP_DATA_ONLY, snapshot_date="09 Nov 2026",
        comparison_text=("25/26 · League Two only · compared to 70 League Two "
                         "Wingers over 450 minutes"),
        flags=[])
    base.update(overrides)
    return data.ReportData(**base)


# --- lifted from tabs/report.py ---------------------------------------------------------
def test_safe_filename_matches_the_streamlit_page():
    assert rp.safe_filename("Baran Yıldız", "25/26") == "Baran_Y_ld_z_25_26_report.html"
    assert rp.data_only_filename("A_25_26_report.html") == "A_25_26_data_only_report.html"


def test_preselected_label_needs_player_and_competition_and_honours_the_season():
    idx = pd.DataFrame({"player_id": [1, 1], "competition_id": [4, 5], "season_id": [318, 318],
                        "label": ["A — X · Winger · L1", "A — Y · Winger · L2"]})
    by_label = {lab: i for i, lab in enumerate(idx["label"])}
    assert rp.preselected_label(idx, by_label, {"player_id": "1", "competition_id": "5"}) \
        == "A — Y · Winger · L2"
    assert rp.preselected_label(idx, by_label, {"player_id": "1", "competition_id": "5",
                                                "season_id": "317"}) is None
    assert rp.preselected_label(idx, by_label, {"player_id": "x"}) is None
    assert rp.preselected_label(idx, by_label, {}) is None


def test_psych_band_caption_is_the_mean_of_the_scored_criteria():
    assert rp.psych_band_caption({"a": 3, "b": None, "c": 4}) == "Band: 3.50"
    assert rp.psych_band_caption({"a": None}) == "Band: —"


def test_variants_blank_form_is_the_base_report():
    base = _report()
    shown, html, data_only_html = rp.variants(base, None)
    assert shown is base and "Data only" in data_only_html and html.startswith("<!doctype")


# --- thin pool (owner D1) ---------------------------------------------------------------
def test_thin_pool_note_only_below_the_minimum_with_a_composite():
    assert rp.not_rated_note(_report(peer_count=8)) == \
        "Not rated: only 8 comparable players (needs 10)"
    assert rp.not_rated_note(_report(peer_count=10)) is None
    assert rp.not_rated_note(_report(peer_count=3, composite=None)) is None


def test_thin_pool_view_hides_composite_rank_data_bands_and_their_flags():
    d = _report(peer_count=8, rank=1, composite=4.49,
                dimension_bands={"Performance": 4.1, "Physical": 3.6, "Psychological": 3.2,
                                 "Medical": None},
                flags=["Physical 1.50 is below the club minimum of 2.00",
                       "Psychological 1.80 is below the club minimum of 2.00"])
    v = rp.view(d)
    ver = v["verdict"]
    assert ver["composite"] is None and ver["rank"] is None
    assert ver["not_rated"] == "Not rated: only 8 comparable players (needs 10)"
    bands = {b["name"]: b for b in ver["bands"]}
    assert bands["Performance"]["value"] is None and bands["Performance"]["text"] == "—"
    assert bands["Psychological"]["text"] == "3.20"
    assert ver["flags"] == ["Psychological 1.80 is below the club minimum of 2.00"]
    assert v["technical"]["vs"] == "8 League Two Wingers"
    assert v["physical"]["vs"] == "8 League Two Wingers"


def test_rated_view_shows_composite_and_rank():
    v = rp.view(_report())
    assert v["verdict"]["composite"] == "3.90" and v["verdict"]["value"] == 3.9
    assert v["verdict"]["rank"] == "7th of 70 League Two Wingers"
    assert v["verdict"]["not_rated"] is None
    assert v["technical"]["vs"] == "League Two Wingers"


# --- formatting -------------------------------------------------------------------------
def test_counts_round_half_up_and_blanks_are_dashes():
    v = rp.view(_report(chances_created=None, height_cm=None, foot=None))
    counts = {c["label"]: c["text"] for c in v["technical"]["counts"]}
    assert counts == {"Minutes": "1,027", "Goals": "3", "Assists": "6", "Chances created": "—"}
    bio = {b["label"]: b["text"] for b in v["bio"]}
    assert bio["Height"] == "—" and bio["Foot"] == "—" and bio["Age"] == "24.1"
    assert bio["Contract to"] == "30 Jun 2027"


def test_bars_are_the_documents_bars_with_their_printed_value():
    v = rp.view(_report(benchmark={"turnovers_p90": 60.0}, benchmark_n=2))
    t = next(b for b in v["technical"]["bars"] if b["label"].startswith("Turnovers"))
    assert t["value"] == 70.0 and t["text"] == "70.0" and t["orient"] == 40.0
    assert v["technical"]["orient"] == {"n": 2, "label": "Leyton Orient median (n=2)"}


def test_no_benchmark_means_no_orient_line():
    v = rp.view(_report())
    assert v["technical"]["orient"] is None and v["physical"]["orient"] is None


def test_physical_radar_uses_the_glossary_names_in_the_report_order():
    v = rp.view(_report(physical={"distance_p90": 55.0, "psv99_kmh": 80.0}))
    p = v["physical"]
    assert p["axes"][0] == "Distance" and p["axes"][6] == "Average match top speed"
    assert p["player"][0] == 55.0 and p["player"][1] is None and p["has_data"]
    assert not rp.view(_report(physical={}))["physical"]["has_data"]


def test_availability_figure_and_unknown():
    assert rp.view(_report())["availability"] == {
        "figure": "92%", "note": "3 matches missed through injury, last two seasons."}
    a = rp.view(_report(availability=None))["availability"]
    assert a["figure"] == "Not known" and len(a["note"]) < 80


def test_narrative_absent_present_and_authored():
    assert rp.view(_report())["narrative"]["absent"] == \
        "No scout assessment recorded — this report presents data only."
    n = data.Narrative(summary="One.\n\nTwo.", why_sign="Pace\nWork rate",
                       considerations=None, assessor="Scout One", assessor_role="scout",
                       approver="Head", approved_at=None)
    v = rp.view(_report(narrative=n))["narrative"]
    assert v["summary"] == ["One.", "Two."] and v["why_sign"] == ["Pace", "Work rate"]
    assert v["byline"] == "Assessed by Scout One (scout) · signed off by Head"
    authored = data.authored_from_inputs(author_name="Ann", author_role="scout",
                                         psych_scores={"x": 4}, now=dt.datetime(2026, 11, 9))
    v = rp.view(data.with_authored(_report(), authored))
    assert v["narrative"]["absent"] == "No summary written."
    assert v["authored"] and v["stamp"] == "Report by Ann · 09 Nov 2026"
    assert v["author_note"].startswith("Psychological, Medical and medical checks are Ann's")
    psych = next(b for b in v["verdict"]["bands"] if b["name"] == "Psychological")
    assert psych["author"] and psych["text"] == "4.00"


def test_position_split_and_minority_note():
    d = _report(position_shares=[("Winger", 400.0, 0.45, 1.0, 0.0),
                                 ("Full Back", 300.0, 0.35, 0.0, 0.0),
                                 ("Centre Forward", 100.0, 0.12, 1.0, 0.0),
                                 ("Attacking Mid", 60.0, 0.08, 0.0, 0.0)])
    v = rp.view(d)
    assert v["splits"] == "Winger 45% · Full Back 35% · Centre Forward 12% · +1 more"
    assert v["minority_note"] == "Scored as Winger, his largest position, though under half his minutes."
    assert v["technical"]["whence"] == "1 goal as winger · 1 goal as centre forward"
    assert rp.view(_report())["splits"] is None


def test_style_rows_keep_the_documents_tags():
    from lofc.model import styles as sm
    name = next(iter(next(iter(sm.STYLES[sm.style_group("Winger")].values()))))
    d = _report(style={"style_label": name, "strong_styles": [name], "leans_styles": [],
                       f"fit.{name}": 74.6})
    st = rp.view(d)["style"]
    rows = [r for g in st["groups"] for r in g["rows"]]
    assert [r["name"] for r in rows] == [name]
    r = rows[0]
    assert r["tag"] == "75 · Strong" and r["fit"] == 74.6 and r["level"] == "Strong"
    assert "bar" not in r and st["label"] == name


# --- the form -----------------------------------------------------------------------------
def test_form_spec_lists_the_position_criteria():
    f = rp.form_spec("Winger")
    assert [t["key"] for t in f["text_areas"]] == ["summary", "why_sign", "considerations"]
    assert f["psychological"] and all("text" in c for c in f["psychological"])
    assert all(c["kind"] in ("screening", "availability", "protocol") for c in f["medical"])


def test_authored_from_body_keeps_only_known_criteria_and_valid_values():
    f = rp.form_spec("Winger")
    crit = f["psychological"][0]["text"]
    screen = next((c["text"] for c in f["medical"] if c["kind"] == "screening"), None)
    body = {"summary": " Quick. ", "psych": {crit: 4, "made up": 5, f["psychological"][1]["text"]: 9},
            "medical_band": 3, "screening": {screen: "Meets", "made up": "Meets"} if screen else {}}
    a = rp.authored_from_body("Winger", body, "Ann", "scout", now=dt.datetime(2026, 11, 9))
    assert a.summary == "Quick." and a.psych_band == 4.0 and a.medical_band == 3.0
    if screen:
        assert a.screening == {screen: "Meets"}
    assert rp.authored_from_body("Winger", {}, "Ann", "scout") is None
    assert rp.authored_from_body("Winger", {"medical_band": 7, "summary": "  "}, "Ann", "scout") is None
