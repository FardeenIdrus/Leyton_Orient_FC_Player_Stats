"""`lofc.core.squad_lists`: the rebuilt Squads & loans page (owner-approved 2026-11-16).

League (every Impect league) -> Club -> squad = players with minutes for THAT club this season
(per-club minutes: a mover is at both clubs, with his minutes at each) united with the
Transfermarkt-registered players who have none. Contract and loan are joined by PLAYER. No
database here: every function takes frames."""
import datetime as dt
import pathlib

import pandas as pd
import pytest

from lofc.core import squad_lists as Q

TODAY = dt.date(2026, 11, 16)
SEP7 = pd.Timestamp("2026-09-07 10:34")
DASH = "—"
LEAGUES = {4: "League One", 5: "League Two", 901: "Scottish Premiership"}
CURRIE = 72298


def _frame(cols, rows):
    return pd.DataFrame([dict(zip(cols, r)) for r in rows], columns=cols)


def _src(**over):
    minutes = _frame(Q.MINUTES_COLUMNS, [
        # player_id, competition_id, team_name, minutes, position_group
        (1, 4, "Leyton Orient", 600.0, "Centre Forward"),     # a mover: Orient, then Oxford
        (1, 4, "Oxford United", 300.0, "Centre Forward"),
        (3, 4, "Leyton Orient", 450.0, "Winger"),             # not on Transfermarkt's list
        (5, 4, "FC Reading", 200.4, "Centre Back"),           # Orient's loanee at Reading
        (6, 4, "FC Reading", 900.0, "Goalkeeper"),            # TM "Reading FC" (crosswalk)
        (7, 901, "Celtic Glasgow", 800.0, "Centre Forward"),  # a club with no TM data
        (8, 4, "Leyton Orient", 950.0, "Centre Forward"),     # rated in another league only
    ])
    tm = _frame(Q.TM_COLUMNS, [
        # competition_id, club_name, tm_player_id, player_name, date_of_birth, contract_until,
        # tm_position, scraped_at, player_id
        (4, "Leyton Orient", 101, "One Mover", pd.Timestamp("2000-01-01"),
         pd.Timestamp("2027-06-30"), "Centre-Forward", SEP7, 1),
        (4, "Leyton Orient", 102, "Two Registered", pd.Timestamp("2004-03-01"),
         pd.Timestamp("2027-01-31"), "Centre-Back", SEP7, 2),
        (4, "Leyton Orient", 109, "Nine Unlinked", pd.Timestamp("2006-05-01"), pd.NaT,
         "Goalkeeper", SEP7, None),
        (4, "Leyton Orient", 108, "Eight Forward", pd.Timestamp("1999-01-01"),
         pd.Timestamp("2028-06-30"), "Centre-Forward", SEP7, 8),
        (4, "Oxford United", 101, "One Mover", pd.Timestamp("2000-01-01"),
         pd.Timestamp("2027-06-30"), "Centre-Forward", SEP7, 1),
        (4, "Reading FC", 106, "Six Keeper", pd.Timestamp("1995-01-01"),
         pd.Timestamp("2026-12-31"), "Goalkeeper", SEP7, 6),
    ])
    players = _frame(Q.PLAYER_COLUMNS, [
        (1, "One Mover", pd.Timestamp("2000-01-01"), pd.Timestamp("2027-06-30"), 101),
        (2, "Two Registered", pd.Timestamp("2004-03-01"), pd.Timestamp("2027-01-31"), 102),
        (3, "Three Unlisted", pd.Timestamp("2003-06-01"), pd.NaT, None),
        (4, "Four Loanee", pd.Timestamp("2005-02-01"), pd.NaT, 104),
        (5, "Five Out", pd.Timestamp("2006-01-01"), pd.Timestamp("2028-06-30"), 105),
        (6, "Six Keeper", pd.Timestamp("1995-01-01"), pd.Timestamp("2026-12-31"), 106),
        (7, "Seven Celtic", pd.Timestamp("1998-01-01"), pd.NaT, None),
        (8, "Eight Forward", pd.Timestamp("1999-01-01"), pd.Timestamp("2028-06-30"), 108),
        (CURRIE, "Jack Currie", pd.Timestamp("2001-01-01"), pd.NaT, 851972),
    ])
    loans = _frame(Q.LOAN_COLUMNS, [
        # player_id, tm_player_id, player_name, club_name, parent_club, loan_ends
        (4, 104, "Four Loanee", "Leyton Orient", "Coventry City", pd.Timestamp("2027-05-31")),
        (5, 105, "Five Out", "Reading FC", "Leyton Orient", pd.Timestamp("2027-05-31")),
    ])
    current = _frame(["player_id", "club_name"], [(1, "Oxford United"), (3, "Leyton Orient"),
                                                  (CURRIE, "Oxford United")])
    cards = _frame(Q.CARD_COLUMNS, [
        # player_id, competition_id, season_id, position_group, objective_composite, peer_pool, size
        (1, 4, 319, "Centre Forward", 3.40, "position", 14),
        (3, 4, 319, "Winger", 3.10, "position", 6),            # thin pool: withheld
        (5, 4, 319, "Centre Back", 2.90, "midfield", 22),        # tagged
        (6, 4, 319, "Goalkeeper", 3.80, "position", 12),
        (7, 901, 319, "Centre Forward", 4.20, "position", 11),
        (8, 5, 319, "Centre Forward", 4.50, "position", 12),     # League Two, not his row's league
    ])
    src = Q.Sources(season_id=319, minutes=minutes, tm=tm, players=players, loans=loans,
                    current=current, cards=cards, crosswalk={"Reading FC": "FC Reading"},
                    league_names=LEAGUES)
    for k, v in over.items():
        setattr(src, k, v)
    return src


@pytest.fixture
def rows():
    return Q.build_rows(_src(), today=TODAY)


def _page(rows, **kw):
    kw.setdefault("league", "League One")
    kw.setdefault("club", "Leyton Orient")
    return Q.build_page(rows, **kw)


def _by_player(view):
    return view.frame.set_index("player")


# --- who is listed ---------------------------------------------------------------------
def test_a_mover_is_at_both_clubs_with_his_minutes_at_each(rows):
    orient = _by_player(_page(rows))
    oxford = _by_player(_page(rows, club="Oxford United"))
    assert orient.loc["One Mover", "minutes"] == 600 and oxford.loc["One Mover", "minutes"] == 300
    assert "Now at Oxford United" in orient.loc["One Mover", "marks"]
    assert oxford.loc["One Mover", "marks"] == []


def test_the_squad_is_impect_minutes_plus_transfermarkt_players_without_minutes(rows):
    v = _by_player(_page(rows))
    assert set(v.index) == {"One Mover", "Two Registered", "Nine Unlinked", "Three Unlisted",
                            "Eight Forward"}
    assert v.loc["Two Registered", "minutes"] == 0
    assert v.loc["Two Registered", "marks"] == ["TM only, no minutes"]
    assert v.loc["Nine Unlinked", "marks"] == ["TM only, no minutes"]       # no player link
    # with minutes here but not on the club's Transfermarkt list; the date is the list's
    assert v.loc["Three Unlisted", "marks"] == ["Not on TM list (7 Sep)"]
    # the default order: most minutes first, then the registered players by name
    assert list(v.index) == ["Eight Forward", "One Mover", "Three Unlisted", "Nine Unlinked",
                             "Two Registered"]


def test_a_transfermarkt_name_reaches_its_impect_club_through_the_list(rows):
    v = _by_player(_page(rows, club="FC Reading"))
    assert v.loc["Six Keeper", "minutes"] == 900 and v.loc["Six Keeper", "marks"] == []
    assert v.loc["Six Keeper", "contract_until"] == pd.Timestamp("2026-12-31")


def test_a_club_with_no_transfermarkt_data_marks_nobody_and_hides_its_columns(rows):
    v = _page(rows, league="Scottish Premiership", club="Celtic Glasgow")
    assert _by_player(v).loc["Seven Celtic", "marks"] == []
    assert v.tm_in_scope is False
    keys = [c["key"] for c in v.columns]
    assert "Contract to" not in keys and "Loan" not in keys


def test_jack_currie_reads_now_at_oxford_united_wherever_else_he_is_listed():
    """Impect's currentSquadId says Orient; the committed override (player_current_club)
    says Oxford. A row for him at Orient must say where he is now."""
    src = _src()
    src.minutes = pd.concat([src.minutes, _frame(Q.MINUTES_COLUMNS, [
        (CURRIE, 4, "Leyton Orient", 90.0, "Centre Back"),
        (CURRIE, 4, "Oxford United", 977.0, "Centre Back")])], ignore_index=True)
    rows = Q.build_rows(src, today=TODAY)
    assert "Now at Oxford United" in _by_player(_page(rows)).loc["Jack Currie", "marks"]
    oxford = _by_player(_page(rows, club="Oxford United")).loc["Jack Currie", "marks"]
    assert not any(m.startswith("Now at") for m in oxford)


# --- contract, loans, rating ------------------------------------------------------------
def test_contract_and_loan_are_joined_by_player(rows):
    v = _by_player(_page(rows))
    assert v.loc["One Mover", "contract_until"] == pd.Timestamp("2027-06-30")
    assert pd.isna(v.loc["Three Unlisted", "contract_until"])


def test_loans_in_and_out_views(rows):
    inn = _by_player(_page(rows, view="in"))
    assert list(inn.index) == ["Four Loanee"]
    assert inn.loc["Four Loanee", "loan_text"] == "From Coventry City · until May 2027"
    assert inn.loc["Four Loanee", "minutes"] == 0
    out = _by_player(_page(rows, view="out"))
    assert list(out.index) == ["Five Out"]
    # minutes AT THE LOAN CLUB, from Impect, through the club-name list
    assert out.loc["Five Out", "minutes"] == pytest.approx(200.4)
    assert out.loc["Five Out", "loan_text"] == "To Reading FC · until May 2027"
    # and the loanee's row at Reading says where he is from
    reading = _by_player(_page(rows, club="FC Reading"))
    assert reading.loc["Five Out", "loan_text"] == "From Leyton Orient · until May 2027"


def test_rating_is_his_own_league_only_with_the_pool_rules(rows):
    v = _page(rows)
    cells = {r[0]["t"]: r for r in Q.web_cells(v, today=TODAY)}
    ix = [c["key"] for c in v.columns].index("Rating")
    assert cells["One Mover"][ix] == "3.40"
    assert cells["Eight Forward"][ix] == DASH            # rated in League Two, listed in League One
    assert cells["Three Unlisted"][ix] == {
        "t": DASH, "note": "Not rated: only 6 Wingers in League One with 450+ minutes (needs 10)."}
    out = Q.web_cells(_page(rows, view="out"), today=TODAY)
    assert out[0][ix] == {"t": "2.90", "tag": "Rated against all midfielders"}


def test_the_player_cell_carries_name_and_marks(rows):
    cells = Q.web_cells(_page(rows), today=TODAY)
    two = next(r for r in cells if r[0]["t"] == "Two Registered")
    assert two[0] == {"t": "Two Registered", "marks": ["TM only, no minutes"]}
    minutes = [c["key"] for c in _page(rows).columns].index("Minutes")
    assert two[minutes] == "0"


# --- sorting: never across leagues ------------------------------------------------------
def test_rating_sorts_only_within_one_league(rows):
    one = _page(rows, club="All", sort="Rating", descending=True)
    assert one.sort == "Rating"
    every = _page(rows, league="All", club="All", sort="Rating", descending=True)
    assert every.sort is None
    assert [c for c in every.columns if c["key"] == "Rating"][0]["sortable"] is False
    assert [c for c in one.columns if c["key"] == "Rating"][0]["sortable"] is True


def test_rating_does_not_sort_a_list_rated_in_two_leagues():
    src = _src()
    src.loans = pd.concat([src.loans, _frame(Q.LOAN_COLUMNS, [
        (7, None, "Seven Celtic", "Celtic FC", "Leyton Orient", pd.Timestamp("2027-05-31"))])],
        ignore_index=True)
    src.crosswalk = {"Reading FC": "FC Reading", "Celtic FC": "Celtic Glasgow"}
    v = _page(Q.build_rows(src, today=TODAY), view="out", sort="Rating")
    assert set(v.frame["player"]) == {"Five Out", "Seven Celtic"} and v.sort is None


def test_other_sorts(rows):
    v = _page(rows, sort="Age", descending=False)
    assert v.frame["player"].iloc[0] == "Nine Unlinked"
    v = _page(rows, sort="Minutes", descending=False)
    assert v.frame["minutes"].tolist() == sorted(v.frame["minutes"].tolist())
    assert _page(rows, sort="drop").sort is None


# --- filters ------------------------------------------------------------------------------
def test_filters(rows):
    names = lambda v: set(v.frame["player"])                          # noqa: E731
    assert names(_page(rows, position="Centre Forward")) == {"One Mover", "Eight Forward"}
    assert names(_page(rows, contract="Under 6 months")) == {"Two Registered"}
    assert names(_page(rows, contract="Under 12 months")) == {"Two Registered", "One Mover"}
    assert names(_page(rows, max_age=21)) == {"Nine Unlinked"}
    assert names(_page(rows, max_age=22)) == {"Nine Unlinked", "Two Registered"}
    assert names(_page(rows, view="squad", club="FC Reading", loan="On loan")) == {"Five Out"}
    assert "Five Out" not in names(_page(rows, club="FC Reading", loan="Not on loan"))
    assert names(_page(rows, q="mover")) == {"One Mover"}


def test_options_and_fallbacks(rows):
    v = _page(rows, league="Mars", club="Nowhere", view="x", position="Striker")
    assert (v.league, v.club, v.view, v.position) == ("All", "All", "squad", "All")
    v = _page(rows, club="All")
    assert v.options["league"] == ["All", "League One", "Scottish Premiership"]
    assert v.options["club"] == ["All", "FC Reading", "Leyton Orient", "Oxford United"]
    assert v.options["contract"] == ["Any", "Under 6 months", "Under 12 months"]
    assert v.options["loan"] == ["Any", "On loan", "Not on loan"]
    keys = [c["key"] for c in v.columns]
    assert keys[0] == "Club" and "League" not in keys
    keys = [c["key"] for c in _page(rows, league="All", club="All").columns]
    assert keys[:2] == ["League", "Club"]


def test_tiles_count_each_view(rows):
    assert _page(rows).tiles == [("Players", 5), ("Played", 3), ("Loans in", 1), ("Loans out", 1)]


# --- the data-date line -----------------------------------------------------------------
def test_the_date_line_names_both_sources_and_marks_stale_transfermarkt():
    sep7, sep18 = dt.date(2026, 9, 7), dt.date(2026, 9, 18)
    assert Q.date_line(dt.date(2026, 11, 9), sep7, sep7, TODAY, True) == [
        {"t": "Minutes: Impect 9 Nov", "stale": False},
        {"t": "Contracts & loans: Transfermarkt 7 Sep (70 days)", "stale": True}]
    assert Q.date_line(dt.date(2026, 11, 9), sep7, sep18, TODAY, True)[1:] == [
        {"t": "Contracts: Transfermarkt 7 Sep (70 days)", "stale": True},
        {"t": "Loans: Transfermarkt 18 Sep (59 days)", "stale": True}]
    assert Q.date_line(dt.date(2026, 11, 9), TODAY - dt.timedelta(days=30), None, TODAY, True)[1] \
        == {"t": "Contracts & loans: Transfermarkt 17 Oct (30 days)", "stale": False}
    assert Q.date_line(None, sep7, sep7, TODAY, False) == [
        {"t": "Minutes: Impect —", "stale": False}, {"t": "No Transfermarkt data", "stale": False}]


# --- the CSV is the table on screen -----------------------------------------------------
def test_csv_matches_the_screen(rows):
    v = _page(rows)
    t = Q.csv_table(v, today=TODAY)
    assert list(t.columns) == [c["label"] for c in v.columns] + ["Note"]
    two = t[t["Player"] == "Two Registered"].iloc[0]
    assert two["Note"] == "TM only, no minutes" and two["Minutes"] == "0"
    assert two["Contract to"] == "Jan 2027"


def test_no_market_value_anywhere():
    root = pathlib.Path(Q.__file__).resolve().parents[1]
    for path in (root / "core" / "squad_lists.py", root / "web" / "api" / "squads.py",
                 root / "web" / "static" / "js" / "squads.js",
                 root / "web" / "templates" / "squads.html"):
        assert "market_value" not in path.read_text().lower(), path


# --- per-club minutes are used only where they agree with the combined table -------------
def test_per_club_minutes_are_used_where_they_add_up_to_the_league_minutes():
    per = _frame(Q.MINUTES_COLUMNS, [(1, 4, "Leyton Orient", 600.0, "Centre Forward"),
                                     (1, 4, "Oxford United", 300.0, "Centre Forward"),
                                     (2, 5, "Crewe Alexandra", 100.0, "Winger")])
    neutral = _frame(Q.MINUTES_COLUMNS, [(1, 4, "Leyton Orient", 900.0, "Centre Forward"),
                                         (2, 5, "Crewe Alexandra", 950.0, "Winger"),
                                         (9, 901, "Celtic Glasgow", 90.0, "Winger")])
    out = Q.merge_minutes(per, neutral)
    # League One adds up: per club (the mover at both); League Two is older than the combined
    # table (100 v 950): the combined table; Scottish Premiership has no per-club rows yet.
    assert sorted(zip(out["competition_id"], out["team_name"], out["minutes"])) == [
        (4, "Leyton Orient", 600.0), (4, "Oxford United", 300.0),
        (5, "Crewe Alexandra", 950.0), (901, "Celtic Glasgow", 90.0)]
    assert Q.stale_leagues(per, neutral) == [5]


def _footed_rows():
    """Feet: our players table first, then the Transfermarkt list (owner 2026-11-16)."""
    src = _src()
    src.players["foot"] = src.players["player_id"].map({1: "left", 2: "both", 8: "right"})
    src.tm["foot"] = src.tm["tm_player_id"].map({109: "left", 108: "left"})   # 108: ours wins
    return Q.build_rows(src, today=TODAY)


def test_preferred_foot_filter_left_or_right_includes_both_and_drops_unknown():
    rows = _footed_rows()
    names = lambda v: set(v.frame["player"])                          # noqa: E731
    everyone = names(_page(rows))
    assert names(_page(rows, foot="Left")) == {"One Mover", "Two Registered", "Nine Unlinked"}
    assert names(_page(rows, foot="Right")) == {"Two Registered", "Eight Forward"}
    assert names(_page(rows, foot="Any")) == everyone
    v = _page(rows, foot="Middle")                                   # junk -> Any
    assert v.foot == "Any" and names(v) == everyone
    assert _page(rows).options["foot"] == ["Any", "Left", "Right"]
    assert "Foot" not in [c["key"] for c in _page(rows).columns]     # filter only, no column


def test_every_club_of_every_league_is_offered_for_the_club_search(rows):
    """Owner 2026-11-23: the Club box also searches every club in every league; a pick switches
    league and club. The list does not depend on the league chosen."""
    want = [{"club": "Celtic Glasgow", "league": "Scottish Premiership"},
            {"club": "FC Reading", "league": "League One"},
            {"club": "Leyton Orient", "league": "League One"},
            {"club": "Oxford United", "league": "League One"}]
    assert _page(rows).options["all_clubs"] == want
    assert _page(rows, league="Scottish Premiership", club="All").options["all_clubs"] == want
