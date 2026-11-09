"""`lofc.core.squads`: the Squads & loans page logic, shared by Streamlit and the web page.
No database: every function here takes frames."""
import datetime as dt
import inspect

import pandas as pd
import pytest

from lofc.dashboard.sidebar_filters import SidebarFilters

TODAY = dt.date(2026, 11, 9)
DASH = "—"


def _prepared(**over):
    """A tiny prepared squad frame (as `prepare` returns), three clubs in two leagues."""
    rows = [
        dict(Club="Leyton Orient", Player="Ann Ab", Position="Winger", League="League One",
             Age=22.4, Minutes=905.6, **{"This season": 3.1, "Last season": 3.42, "Also rated": 4.0},
             player_id=1, competition_id=4, contract_until=pd.Timestamp("2027-06-30"),
             parent_club=None, loan_ends=None, Foot="left", Nationality="England",
             rating_competition_id=4, alt_competition_id=901),
        dict(Club="Leyton Orient", Player="Bob Cé", Position="Centre Back (last season)",
             League="League One", Age=30.0, Minutes=None,
             **{"This season": None, "Last season": 2.5, "Also rated": None},
             player_id=2, competition_id=4, contract_until=pd.Timestamp("2028-06-30"),
             parent_club="Everton FC U21", loan_ends=pd.Timestamp("2027-05-31"), Foot="right",
             Nationality="Wales", rating_competition_id=4, alt_competition_id=None),
        dict(Club="Crewe Alexandra", Player="Cy Dee", Position=None, League="League Two",
             Age=None, Minutes=12.5, **{"This season": None, "Last season": None, "Also rated": None},
             player_id=None, competition_id=5, contract_until=None, parent_club=None,
             loan_ends=None, Foot=None, Nationality=None, rating_competition_id=None,
             alt_competition_id=None),
    ]
    f = pd.DataFrame(rows)
    f["Months left"] = f["contract_until"].map(lambda d: None if pd.isna(d) else
                                               (d.year - 2026) * 12 + d.month - 11)
    f["On loan from"] = f["parent_club"]
    f["Contract to"] = pd.to_datetime(f["contract_until"]).dt.date
    f["Loan ends"] = pd.to_datetime(f["loan_ends"]).dt.date
    f["Rated in"] = f["rating_competition_id"].map({4: "League One"})
    f["Also in"] = f["alt_competition_id"].map({901: "Premier League 2"})
    for k, v in over.items():
        f[k] = v
    return f


def test_streamlit_page_uses_the_core_functions():
    """Moved, not copied: the Streamlit tab re-exports core's objects, and its render draws
    through `build_view`."""
    from lofc.core import squads as S
    from lofc.dashboard.tabs import squads as T
    for name in ("prepare", "this_season_score", "attach_loans", "resolve_loan_player_ids",
                 "loan_view", "filter_by_position", "filter_by_name", "sidebar_view",
                 "summary_counts", "squad_display", "for_export", "best_profile_target",
                 "transfermarkt_asof", "squad_source_warning", "months_left", "position_options",
                 "with_last_season_position", "with_registered_position", "ensure_display_columns",
                 "no_record_message", "no_rating_message"):
        assert getattr(T, name) is getattr(S, name), name
    assert T.DISPLAY_COLUMNS is S.DISPLAY_COLUMNS
    src = inspect.getsource(T.render)
    assert "build_view(" in src and "league_options(" in src and "club_options(" in src


def test_page_seasons_is_latest_and_the_one_before():
    from lofc.core.squads import page_seasons
    assert page_seasons([317, 319, 318], 1) == (319, 318)
    assert page_seasons([318], 1) == (318, 318)
    assert page_seasons([], 5) == (5, 5)


def test_options_follow_the_filters_in_order():
    from lofc.core.squads import build_view, club_options, league_options
    f = _prepared()
    assert league_options(f) == ["All", "League One", "League Two"]
    assert club_options(f) == ["All", "Crewe Alexandra", "Leyton Orient"]
    v = build_view(f, SidebarFilters(), league="League One")
    assert v.club_options == ["All", "Leyton Orient"]
    assert v.position_options == ["All", "Centre Back", "Winger"]
    assert v.view["Player"].tolist() == ["Ann Ab", "Bob Cé"]


def test_a_choice_not_on_offer_falls_back_to_all():
    """A stale shared URL still opens: a club of another league, an unknown position."""
    from lofc.core.squads import build_view
    v = build_view(_prepared(), SidebarFilters(), league="League Two", club="Leyton Orient",
                   position="Goalkeeper", show="nonsense")
    assert (v.league, v.club, v.position, v.show) == ("League Two", "All", "All", "Everyone")
    assert v.view["Player"].tolist() == ["Cy Dee"]


def test_position_keeps_last_season_fallbacks_and_name_search_folds_accents():
    from lofc.core.squads import build_view
    v = build_view(_prepared(), SidebarFilters(), position="Centre Back")
    assert v.view["Player"].tolist() == ["Bob Cé"]
    assert build_view(_prepared(), SidebarFilters(), query="bob ce").view["Player"].tolist() == ["Bob Cé"]


def test_expiring_includes_already_expired_and_counts_follow_the_view():
    from lofc.core.squads import SHOW_EXPIRING, build_view
    f = _prepared(**{"Months left": [7, -2, None]})
    v = build_view(f, SidebarFilters(), show=SHOW_EXPIRING)
    assert v.view["Player"].tolist() == ["Ann Ab", "Bob Cé"]
    assert v.counts == {"players": 2, "on_loan": 1, "contract_known": 2, "expiring": 2}


def test_on_loan_only_replaces_the_view_and_reapplies_every_filter():
    from lofc.core.squads import SHOW_LOANS, build_view
    loans = _prepared().iloc[[1, 1]].reset_index(drop=True)
    loans.loc[1, "Club"] = "Crewe Alexandra"
    loans.loc[1, "League"] = "League Two"
    calls = []
    v = build_view(_prepared(), SidebarFilters(), league="League One", show=SHOW_LOANS,
                   loans=lambda: calls.append(1) or loans)
    assert calls == [1]
    assert v.view["Club"].tolist() == ["Leyton Orient"]
    # not asked for unless the loans view is shown
    build_view(_prepared(), SidebarFilters(), loans=lambda: calls.append(1) or loans)
    assert calls == [1]
    # sidebar filters apply to the loans view as well
    v = build_view(_prepared(), SidebarFilters(foot="Left"), show=SHOW_LOANS, loans=lambda: loans)
    assert v.view.empty and v.counts["players"] == 0


def test_build_view_runs_the_loan_and_sidebar_filters():
    """The two bugs the old tests pinned to `render` (Position dropped from the loans view;
    sidebar not applied to it) now live in `build_view`."""
    from lofc.core import squads as S
    src = inspect.getsource(S.build_view)
    assert "loan_view(" in src and "sidebar_view(" in src and "filter_by_name(" in src


def test_sort_is_typed_blanks_last_and_stable():
    from lofc.core.squads import sort_view
    f = _prepared()
    assert sort_view(f, "Minutes", False)["Player"].tolist() == ["Cy Dee", "Ann Ab", "Bob Cé"]
    assert sort_view(f, "Minutes", True)["Player"].tolist() == ["Ann Ab", "Cy Dee", "Bob Cé"]
    assert sort_view(f, "Last season", True)["Player"].tolist() == ["Ann Ab", "Bob Cé", "Cy Dee"]
    assert sort_view(f, "Club", False)["Player"].tolist() == ["Cy Dee", "Ann Ab", "Bob Cé"]
    assert sort_view(f, None, True)["Player"].tolist() == ["Ann Ab", "Bob Cé", "Cy Dee"]
    assert sort_view(f, "nonsense", True)["Player"].tolist() == ["Ann Ab", "Bob Cé", "Cy Dee"]


def test_web_cells_round_minutes_half_up_and_dash_every_blank():
    from lofc.core.squads import DISPLAY_COLUMNS, squad_display, web_cells
    f = _prepared()
    table = squad_display(f[DISPLAY_COLUMNS].reset_index(drop=True))
    rows = web_cells(f.reset_index(drop=True), table, {})
    by = [dict(zip(DISPLAY_COLUMNS, r)) for r in rows]
    assert by[0]["Minutes"] == "906" and by[2]["Minutes"] == "13"     # 12.5 -> 13, half-up
    assert by[1]["Minutes"] == DASH
    assert by[0]["Age"] == "22.4" and by[0]["Last season"] == "3.42" and by[0]["Also rated"] == "4.00"
    assert by[0]["Contract to"] == "Jun 2027" and by[1]["Loan ends"] == "May 2027"
    assert by[0]["Months left"] == "7"
    for r in by[2:]:
        for col in ("Age", "This season", "Contract to", "Months left", "On loan from",
                    "Loan ends", "Foot", "Nationality", "Position"):
            assert r[col] == DASH, col
    for r in rows:
        assert all(isinstance(c, str) for c in r)


def test_web_cells_withhold_a_thin_composite_with_the_note():
    from lofc.core.squads import DISPLAY_COLUMNS, squad_display, web_cells
    f = _prepared()
    table = squad_display(f[DISPLAY_COLUMNS].reset_index(drop=True))
    rows = web_cells(f, table, {(0, "Also rated"): 6})
    cell = rows[0][DISPLAY_COLUMNS.index("Also rated")]
    assert cell == {"t": DASH, "note": "Not rated: only 6 comparable players (needs 10)"}
    assert rows[0][DISPLAY_COLUMNS.index("Last season")] == "3.42"


def test_thin_pools_are_found_per_rating_column():
    """Each composite is looked up in ITS pool: This season = (player, squad league, live
    season), Last season = (player, Rated in league, last season), Also rated = (player,
    Also in league, last season)."""
    from lofc.core.squads import thin_pools
    f = _prepared().reset_index(drop=True)
    live = pd.DataFrame({"player_id": [1] + list(range(100, 112)), "competition_id": [4] * 13,
                         "season_id": [319] * 13,
                         "position_group": ["Winger"] + ["Winger"] * 12,
                         "objective_composite": [3.1] * 13})
    prev = pd.DataFrame({"player_id": [1, 1, 2] + list(range(200, 209)),
                         "competition_id": [4, 901, 4] + [4] * 9, "season_id": [318] * 12,
                         "position_group": ["Winger", "Winger", "Centre Back"] + ["Winger"] * 9,
                         "objective_composite": [1.0] * 12})
    out = thin_pools(f, live, prev, 319, 318)
    # live Winger pool in 4 = 13 (fine); 2025/26 Winger pool in 4 = 10 (fine), in 901 = 1 (thin);
    # Bob's Centre Back pool in 4 = 1 (thin)
    assert out == {(0, "Also rated"): 1, (1, "Last season"): 1}


def test_profile_targets_are_best_profile_target_per_player():
    from lofc.core.squads import best_profile_target, profile_targets
    rows = pd.DataFrame({"player_id": [1, 1, 1, 2, 3], "competition_id": [4, 5, 901, 4, 4],
                         "season_id": [318, 318, 317, 318, 318],
                         "minutes": [900, 1200, 3000, 500, 500],
                         "objective_composite": [3.0, 2.0, 4.0, None, 2.0]})
    out = profile_targets(rows, [1, 2, 3, 4])
    for pid in (1, 2, 3, 4):
        assert out.get(pid) == best_profile_target(rows[rows.player_id == pid]), pid
    assert out[1] == (5, 318) and out.get(2) is None and out.get(4) is None


def test_row_links_and_messages():
    from lofc.core.squads import row_links
    f = _prepared().reset_index(drop=True)
    links, msgs = row_links(f, {1: (4, 318)})
    assert links == ["/player/1/4/318", None, None]
    assert msgs[0] is None
    assert msgs[1] == "Bob Cé: no rating in any season yet (450 minutes needed), so no profile to open."
    assert msgs[2] == "Cy Dee (Crewe Alexandra): no performance record in our data, so no profile to open."


def test_export_filename_is_streamlits():
    from lofc.core.squads import export_filename
    assert export_filename("All", "All") == "lofc_squads_all.csv"
    assert export_filename("League Two", "All") == "lofc_squads_league_two.csv"
    assert export_filename("League One", "Leyton Orient") == "lofc_squads_leyton_orient.csv"


def test_web_texts_are_one_line_each():
    from lofc.core import squads as S
    assert S.incomplete_text(2966) == ("Squad list incomplete: showing the 2,966 players who "
                                       "have appeared this season; unplayed squad members are missing.")
    for t in (S.WEB_FOOTER, S.incomplete_text(1)):
        assert "\n" not in t and len(t) <= 130, t


@pytest.mark.parametrize("show", ["Everyone", "On loan only", "Contract expiring (under 12 months)"])
def test_show_codes_round_trip(show):
    from lofc.core.squads import SHOW_OPTIONS, show_code, show_from_code
    assert show in SHOW_OPTIONS
    assert show_from_code(show_code(show)) == show
    assert show_from_code("junk") == "Everyone"
