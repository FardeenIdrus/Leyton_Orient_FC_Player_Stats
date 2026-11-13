"""`lofc.core.scout_reports_page`: the Scout reports page logic shared by Streamlit and the web
page (no database). The real-database parity is in test_web_scout_watchlist_parity.py."""
import datetime as dt

import pandas as pd
import pytest

from lofc.core import scout_reports_page as sp
from lofc.dashboard.tabs import scout_reports as sr


def _frame(rows):
    cols = ["submission_id", "scout", "observation", "player_name", "club_name", "foot",
            "home_team", "away_team", "fixture_date", "comments", "positions_played",
            "recommended_positions", "grade", "squad_role", "verdict", "player_id",
            "name_from_report", "composite", "composite_live", "rated_in", "birth_date",
            "league_id", "in_rating_season", "in_live_season"]
    base = dict.fromkeys(cols)
    return pd.DataFrame([{**base, **r} for r in rows], columns=cols)


ROWS = [
    dict(submission_id="a", scout="Ann", observation="Live", player_name="Al One", club_name="Gills",
         verdict="Sign", player_id=1, composite=2.5, rated_in=4, league_id=4,
         in_rating_season=True, in_live_season=True, positions_played=["CM"],
         fixture_date=pd.Timestamp("2026-10-01"), home_team="Gills", away_team="Orient"),
    dict(submission_id="b", scout="Bob", observation="Video", player_name="Bo Two", club_name="Mill",
         verdict="Don't sign", player_id=2, composite=3.9, rated_in=903, league_id=903,
         in_rating_season=True, in_live_season=False, positions_played=["RB", "RWB"]),
    dict(submission_id="c", scout="Ann", observation="Live", player_name="Cy Three", club_name="X",
         verdict="Monitor", player_id=None, composite=None),
]
NAMES = {4: "League One", 903: "Scottish Championship"}


def test_rating_seasons_is_the_last_complete_season():
    assert sp.rating_seasons([317, 318, 319]) == (318, 319)
    assert sp.rating_seasons([319]) == (319, 319)


def test_live_label_falls_back_to_the_rating_label():
    assert sp.live_label(318, "2025/26", 319) == "2026/27"
    assert sp.live_label(318, "2025/26", 318) == "2025/26"
    assert sp.live_label(318, "2025/26", None) == "2025/26"


def test_short_label():
    assert sp.short_label("2025/26") == "25/26"
    assert sp.short_label("odd") == "odd"


def test_prepare_is_model_view_plus_league():
    out = sp.prepare(_frame(ROWS), "2025/26", "2026/27", NAMES)
    ref = sr.model_view(_frame(ROWS), season="25/26", live_season="26/27")
    assert list(out[sr.MODEL_VIEW]) == list(ref[sr.MODEL_VIEW])
    assert list(out["league"].fillna("-")) == ["League One", "Scottish Championship", "-"]


def test_counts_and_captions():
    f = sp.prepare(_frame(ROWS), "2025/26", "2026/27", NAMES)
    c = sp.counts(f)
    assert c == {"total": 3, "players": 3, "scouts": 2, "linked": 2, "disagree": 2}
    assert sp.browse_caption(1, c) == "1 of 3 reports · 3 players · 2 scouts · 2 matched to our data"
    assert sp.disagree_caption(2) == "2 reports: Sign but rated under 3.0, or Don't sign but rated 3.5+."
    assert list(sp.disagree_view(f)["submission_id"]) == ["a", "b"]      # rating used, low first


def test_tab_labels():
    assert sp.tab_labels({"total": 1234, "disagree": 5}) == [
        "All reports (1,234)", "Data disagrees (5)", "Scout activity"]


def test_sync_line_and_warning():
    now = dt.datetime(2026, 11, 9, 12, 0)
    line, warn = sp.sync_line(dt.datetime(2026, 11, 9, 11, 0), None, now=now)
    assert (line, warn) == ("Synced 1 hour ago", False)
    line, warn = sp.sync_line(None, None, now=now)
    assert warn and line.startswith("Never synced")
    line, warn = sp.sync_line(dt.datetime(2026, 11, 8, 11, 0), None, now=now)
    assert warn and "not updating" in line
    assert sp.sync_line(now, {"changed": False, "written": 0}, now=now)[0] == "Synced just now · sheet unchanged"
    assert sp.sync_line(now, {"changed": True, "written": 7}, now=now)[0] == "Synced just now · 7 reports updated"


def test_filter_options_are_the_streamlit_lists():
    f = sp.prepare(_frame(ROWS), "2025/26", "2026/27", NAMES)
    o = sp.filter_options(f)
    assert o["League"] == ["All", "League One", "Scottish Championship"]
    assert o["Scout"] == ["All", "Ann", "Bob"]
    assert o["Position"] == ["All", "CM", "RB", "RWB"]
    assert o["Foot"] == ["All", "Left", "Right"]
    assert o["Our data"] == ["All", "In our data", "Not in our data"]
    assert o["Data vs scout"] == sr.DATA_VS_SCOUT_GROUPS


def test_apply_filters_reads_the_query_like_the_widgets():
    f = sp.prepare(_frame(ROWS), "2025/26", "2026/27", NAMES)
    assert list(sp.apply_filters(f, {"scout": "Ann"})["submission_id"]) == ["a", "c"]
    assert list(sp.apply_filters(f, {"position": "RWB"})["submission_id"]) == ["b"]
    assert list(sp.apply_filters(f, {"data": "Not in our data"})["submission_id"]) == ["c"]
    # 40 (the widget's top) means no age filter; junk is ignored
    assert len(sp.apply_filters(f, {"max_age": "40"})) == 3
    assert len(sp.apply_filters(f, {"max_age": "abc"})) == 3


def test_parse_max_age():
    assert sp.parse_max_age("24") == 24
    assert sp.parse_max_age("40") is None
    assert sp.parse_max_age("99") is None
    assert sp.parse_max_age("10") is None
    assert sp.parse_max_age(None) is None


def test_report_card_is_what_the_html_card_draws():
    row = _frame(ROWS).iloc[0].copy()
    row["comments"] = "Line one\n<b>bold</b>"
    row["grade"] = "B"
    card = sp.report_card(row)
    assert card["tone"] == "positive" and card["accent"] == "#1B7A4B"
    assert card["meta"] == "Ann · Live · Grade B"
    assert card["verdict"] == "Sign"
    assert ["Fixture", "Gills v Orient · 01 Oct 2026"] in card["facts"]
    assert card["body"] == "Line one\n<b>bold</b>"            # raw: the page escapes it
    assert "&lt;b&gt;bold&lt;/b&gt;" in sr.report_card_html(row)


def test_pool_floor_blanks_a_thin_last_season_rating_and_says_why():
    rows = [dict(ROWS[1]), dict(ROWS[0])]
    rows[0]["composite"] = 3.07                     # thin pool, no live rating
    sizes = pd.Series([8.0, float("nan")])
    out = sp.prepare(_frame(rows), "2025/26", "2026/27", NAMES, thin=sizes)
    assert pd.isna(out.iloc[0]["composite"])
    assert out.iloc[0][sr.MODEL_VIEW] == "Not rated: only 8 comparable players (needs 10)"
    assert sr.data_vs_scout_group(out.iloc[0][sr.MODEL_VIEW]) == "No rating"
    assert out.iloc[1]["composite"] == 2.5


def test_pool_floor_keeps_the_live_rating_comparison():
    row = dict(ROWS[1]); row["composite_live"] = 4.1
    out = sp.prepare(_frame([row]), "2025/26", "2026/27", NAMES, thin=pd.Series([8.0]))
    assert pd.isna(out.iloc[0]["composite"])
    assert out.iloc[0][sr.MODEL_VIEW] == "Data disagrees — rated 3.5+ (26/27)"


def test_thin_sizes_from_the_rating_season_scorecards():
    f = _frame(ROWS)
    sc = pd.DataFrame({"player_id": [1, 2, 9], "competition_id": [4, 903, 903],
                       "season_id": [318] * 3, "position_group": ["CM", "CM", "CM"],
                       "objective_composite": [2.5, 3.9, 3.0]})
    sizes = sp.thin_sizes(f, sc, 318)
    # 1 alone in League One CM (1), 2 with 9 in 903 CM (2); both below the floor; c unlinked
    assert list(sizes.fillna(-1)) == [1.0, 2.0, -1.0]


def test_best_targets_uses_best_profile_target():
    rows = pd.DataFrame({"player_id": [1, 1, 2], "competition_id": [4, 5, 3],
                         "season_id": [318, 318, 317], "minutes": [900, 1200, 500],
                         "objective_composite": [3.0, 3.1, None]})
    assert sp.best_targets(rows) == {1: (5, 318)}


ROLES = ["Core (>70% of Minutes)", "Support (21-69% of Minutes)", "Fringe (<20% of Minutes)",
         "Emerging Talent (Ready in Next 12-18 Months)", "Below the Required Standard for LOFC"]


def test_squad_role_options_come_from_the_data_in_the_sheet_order():
    rows = [dict(ROWS[0], squad_role=ROLES[4]), dict(ROWS[1], squad_role=ROLES[0]),
            dict(ROWS[2], squad_role="A new role")]
    f = sp.prepare(_frame(rows), "2025/26", "2026/27", NAMES)
    assert sp.filter_options(f)["Squad role"] == ["All", ROLES[0], ROLES[4], "A new role"]


def test_squad_role_filter_narrows_and_combines():
    rows = [dict(ROWS[0], squad_role=ROLES[0]), dict(ROWS[1], squad_role=ROLES[1]),
            dict(ROWS[2], squad_role=ROLES[0])]
    f = sp.prepare(_frame(rows), "2025/26", "2026/27", NAMES)
    assert list(sp.apply_filters(f, {"role": ROLES[0]})["submission_id"]) == ["a", "c"]
    assert list(sp.apply_filters(f, {"role": ROLES[0], "scout": "Bob"})["submission_id"]) == []
    assert list(sp.apply_filters(f, {"role": ROLES[0], "data": "In our data"})["submission_id"]) == ["a"]
    assert len(sp.apply_filters(f, {"role": "All"})) == 3
    assert len(sp.apply_filters(f, {"role": ""})) == 3
