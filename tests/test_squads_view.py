"""The Squads & loans page: who is at each club now, on what contract, on loan from whom.

It exists because the RANKING cannot answer January's question. A composite needs 450
minutes; two months into a season nobody has them, so the ranked view legitimately has
nothing to show. These tests pin the parts that would mislead a recruiter.
"""

import datetime as dt

import pandas as pd

from lofc.dashboard.tabs.squads import months_left, prepare

TODAY = dt.date(2026, 9, 7)


def _frame(**over):
    base = {"competition_id": 4, "team_name": "Leyton Orient", "player_name": "A Player",
            "position_group": "Winger", "minutes": 320.0,
            "contract_until": dt.date(2027, 6, 30), "foot": "left", "height_cm": 180,
            "nationality": "England", "birth_date": dt.date(2000, 1, 1),
            "parent_club": None, "loan_ends": None, "last_season_rating": 3.4,
            "player_id": 1, "rating_competition_id": 5,
            "alt_rating": None, "alt_competition_id": None,
            "last_position": None}
    base.update(over)
    return pd.DataFrame([base])


def test_months_left_counts_forward():
    assert months_left(dt.date(2027, 6, 30), TODAY) == 9


def test_an_expired_contract_is_negative_not_dropped():
    """A lapsed date is a live question -- usually an extension nobody has published --
    so it must stay visible rather than read as 'no contract'."""
    assert months_left(dt.date(2026, 3, 31), TODAY) == -6


def test_an_unknown_contract_is_none_never_zero():
    """Transfermarkt leaves the field blank for ~22% of squad members. Zero months would
    read as 'expires now', which is a different and alarming claim."""
    assert months_left(None, TODAY) is None
    assert months_left(pd.NaT, TODAY) is None


def test_the_rating_column_is_carried_from_the_previous_season():
    out = prepare(_frame(), TODAY)
    assert out.loc[0, "Last season"] == 3.4


def test_a_player_with_no_previous_season_has_no_rating_rather_than_zero():
    """293 players appear only this season. A zero rating would rank them worst."""
    out = prepare(_frame(last_season_rating=None), TODAY)
    assert pd.isna(out.loc[0, "Last season"])


def test_loan_details_are_surfaced():
    out = prepare(_frame(parent_club="Brighton & Hove Albion",
                         loan_ends=dt.date(2027, 5, 31)), TODAY)
    assert out.loc[0, "On loan from"] == "Brighton & Hove Albion"
    assert out.loc[0, "Loan ends"] == dt.date(2027, 5, 31)


def test_a_player_not_on_loan_has_no_parent_club():
    out = prepare(_frame(), TODAY)
    assert pd.isna(out.loc[0, "On loan from"])


def test_age_is_computed_from_the_birth_date():
    out = prepare(_frame(birth_date=dt.date(2000, 9, 7)), TODAY)
    assert round(float(out.loc[0, "Age"])) == 26


def test_an_empty_squad_returns_empty_rather_than_raising():
    assert prepare(pd.DataFrame()).empty


# --- the second rating: 116 players appeared in two leagues last season ----------------

def test_the_alternate_rating_is_carried_not_discarded():
    """Akhamrich rated 3.42 in League Two and 4.00 in PL2. Showing only the
    higher-minutes figure hides exactly the level-step signal a loan is meant to answer."""
    out = prepare(_frame(last_season_rating=3.42, rating_competition_id=5,
                         alt_rating=4.00, alt_competition_id=903), TODAY)
    assert out.loc[0, "Last season"] == 3.42
    assert out.loc[0, "Also rated"] == 4.00


def test_each_rating_names_the_league_it_was_earned_in():
    """A 3.42 in League Two and a 3.42 in Premier League 2 are not the same claim."""
    out = prepare(_frame(rating_competition_id=5, alt_rating=4.0,
                         alt_competition_id=903), TODAY)
    assert out.loc[0, "Rated in"] == "League Two"
    assert out.loc[0, "Also in"] == "Premier League 2"


def test_a_single_league_player_has_no_alternate():
    out = prepare(_frame(), TODAY)
    assert pd.isna(out.loc[0, "Also rated"])


def test_every_display_column_exists_after_prepare():
    """The table selects DISPLAY_COLUMNS directly; a missing one is a KeyError in the UI."""
    from lofc.dashboard.tabs.squads import DISPLAY_COLUMNS
    out = prepare(_frame(), TODAY)
    assert all(c in out.columns for c in DISPLAY_COLUMNS)


def test_player_id_survives_prepare_so_a_row_click_can_carry_it():
    """The row click carries the ID, never the label."""
    assert "player_id" in prepare(_frame(), TODAY).columns


# --- the exported file must match the screen it came from ------------------------------
# column_config formats the on-screen table, but to_csv writes the RAW float. The file the
# Head of Recruitment opened showed "105.097500" minutes and "26.778919" years while the
# screen showed 105 and 26.8.

def test_export_rounds_the_numbers_the_screen_rounds():
    from lofc.dashboard.tabs.squads import for_export
    out = for_export(pd.DataFrame([{"Age": 26.778919, "Minutes": 105.0975,
                                    "Last season": 3.171234, "Also rated": 2.4899,
                                    "Months left": 33.0}]))
    assert out.loc[0, "Age"] == 26.8
    assert out.loc[0, "Minutes"] == 105
    assert out.loc[0, "Last season"] == 3.17
    assert out.loc[0, "Also rated"] == 2.49
    assert out.loc[0, "Months left"] == 33


def test_export_keeps_a_blank_blank_rather_than_writing_zero():
    """A player with no rating must not export as 0.00 — that ranks him worst."""
    from lofc.dashboard.tabs.squads import for_export
    out = for_export(pd.DataFrame([{"Age": None, "Minutes": None, "Last season": None,
                                    "Also rated": None, "Months left": None}]))
    assert out.isna().all().all()


def test_export_preserves_a_negative_months_left():
    """An expired contract is a live question, not a zero."""
    from lofc.dashboard.tabs.squads import for_export
    out = for_export(pd.DataFrame([{"Months left": -6.0}]))
    assert out.loc[0, "Months left"] == -6


def test_export_leaves_text_columns_untouched():
    from lofc.dashboard.tabs.squads import for_export
    out = for_export(pd.DataFrame([{"Club": "Leyton Orient", "Player": "A", "Age": 24.44}]))
    assert out.loc[0, "Club"] == "Leyton Orient" and out.loc[0, "Player"] == "A"


# --- the squad list is the REGISTERED squad, not the appearance list -------------------
# Five matches into 2026/27 the page showed 16 of Leyton Orient's 33 players. The other 17
# were registered, their contracts scraped that morning, and invisible — because the page
# was built from who had PLAYED. Impect cannot supply a squad list; it knows a player only
# once he appears. Transfermarkt publishes the registered squad.

def test_a_player_with_no_appearances_still_appears():
    """A signing must be visible with his contract before he plays."""
    out = prepare(_frame(minutes=None, position_group=None,
                         last_position=None), TODAY)
    assert len(out) == 1
    assert out.loc[0, "Contract to"] is not None


def test_an_unplayed_position_falls_back_to_last_season_and_says_so():
    """Blank read as broken. 'Goalkeeper (last season)' is a fact about the player."""
    import pandas as pd
    row = _frame(minutes=None, position_group=None).iloc[0].to_dict()
    row["position_group"] = "Goalkeeper (last season)"
    out = prepare(pd.DataFrame([row]), TODAY)
    assert "last season" in out.loc[0, "Position"]


def test_join_keys_are_deduped_so_a_player_is_listed_once_per_club():
    """36 players turned out in two leagues this season and 15 Transfermarkt ids are
    claimed by two of our players; either fans the join out and lists a squad member
    twice."""
    import pandas as pd
    from lofc.dashboard.tabs.squads import registered_squad_frame
    import inspect
    src = inspect.getsource(registered_squad_frame)
    assert "DISTINCT ON (player_id)" in src, "appearance join is not deduped"
    assert 'drop_duplicates("tm_player_id", keep=False)' in src, (
        "ambiguous Transfermarkt ids are not dropped from the join")


def test_a_squad_member_with_no_platform_record_does_not_crash_the_click():
    """717 of 3,783 squad rows have no Transfermarkt id link. Calling int() on a NaN
    player_id raised "cannot convert float NaN to integer" and took the whole page down —
    19% of rows were unclickable."""
    import pandas as pd
    from lofc.dashboard.tabs import squads
    import inspect
    src = inspect.getsource(squads.render)
    assert 'pd.isna(picked.get("player_id"))' in src, (
        "the row click does not guard against a squad member we hold no record of")


def test_the_link_runs_before_the_bio_merge():
    """Bio is keyed on OUR player_id, so merging it on tm_player_id first left every
    name-linked player with an id but no nationality, age or height — Oliver Dovin had all
    three in the database and none on screen."""
    import inspect
    from lofc.dashboard.tabs.squads import registered_squad_frame
    src = inspect.getsource(registered_squad_frame)
    assert src.index("LINK FIRST") < src.index('bio = pd.read_sql'), (
        "bio is merged before the name+DOB link resolves player_id")
