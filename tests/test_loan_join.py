"""P17 -- the Squads & loans page joins loans on a key a quarter of them do not have.

`registered_squad_frame` read loans with `WHERE player_id IS NOT NULL` and then merged them
on `player_id`. But the squad frame is built from the Transfermarkt scrape and is keyed on
`tm_player_id`, and 108 of 411 loan rows carry ONLY that key -- the scrape found the loan
before Impect had ever seen the player, or has still never seen him. Those rows were
discarded at source and the "On loan from" / "Loan ends" columns rendered blank.

Joel Catesby is the case: Transfermarkt shows him at Accrington Stanley on loan from Everton
FC U21 until 31/05/2027, we hold exactly that in `player_loans`, and the page showed nothing
-- while his CONTRACT showed, because contract comes from a different join. A row
half-populated from two sources reads as missing data rather than as a broken join, which is
why this survived.

THE DUPLICATION RISK IS REAL, not theoretical. `tm_player_id` is unique in `player_loans`
and in `transfermarkt_squads`, but NOT in `players`: David Kamara holds two identities
(445315 seeded from StatsBomb, 2000224875 minted from Impect) both claiming Transfermarkt id
1076889, so resolving loans through `players` on that key returns 412 rows for 411 loans.
An ambiguous key is DROPPED, never guessed -- attaching one man's loan to another is worse
than showing no loan at all. Same rule as `identity.drop_ambiguous_matches`.

Nothing here touches a score. Display only.
"""

import datetime as dt

import pandas as pd

from lofc.dashboard.tabs.squads import attach_loans, resolve_loan_player_ids

# --- the squad frame: three registered players, only one of whom we have an id for -------

SQUAD = pd.DataFrame([
    # linked the ordinary way -- we hold his Impect identity
    {"player_id": 388235.0, "tm_player_id": 980343, "club_name": "Northampton Town",
     "player_name": "Sam Chambers"},
    # Joel Catesby: we DO hold him (Impect-minted), but his LOAN row carries no player_id
    {"player_id": 2000151869.0, "tm_player_id": 1083709, "club_name": "Accrington Stanley",
     "player_name": "Joel Catesby"},
    # nobody we know at all -- Transfermarkt's row is the only record
    {"player_id": float("nan"), "tm_player_id": 567151, "club_name": "Middlesbrough FC",
     "player_name": "Connor Barron"},
    # not on loan
    {"player_id": 22175.0, "tm_player_id": 633399, "club_name": "Leyton Orient",
     "player_name": "Idris El Mizouni"},
])

LOANS = pd.DataFrame([
    {"player_id": 388235.0, "tm_player_id": 980343, "parent_club": "Leeds United U21",
     "loan_ends": dt.date(2027, 5, 31)},
    {"player_id": float("nan"), "tm_player_id": 1083709, "parent_club": "Everton FC U21",
     "loan_ends": dt.date(2027, 5, 31)},
    {"player_id": float("nan"), "tm_player_id": 567151, "parent_club": "Rangers FC",
     "loan_ends": dt.date(2027, 6, 30)},
])


def _row(frame, name):
    return frame[frame["player_name"] == name].iloc[0]


# --- attach_loans ------------------------------------------------------------------------

def test_a_loan_carrying_our_player_id_still_attaches():
    """Regression: the path that already worked must keep working."""
    out = attach_loans(SQUAD, LOANS)
    assert _row(out, "Sam Chambers")["parent_club"] == "Leeds United U21"


def test_a_loan_with_only_a_transfermarkt_id_attaches():
    """THE DEFECT. Catesby's loan row has no player_id; the squad row is keyed on tm_player_id.

    Real values, straight from the database.
    """
    out = attach_loans(SQUAD, LOANS)
    row = _row(out, "Joel Catesby")
    assert row["parent_club"] == "Everton FC U21"
    assert row["loan_ends"] == dt.date(2027, 5, 31)


def test_a_loanee_we_hold_no_identity_for_still_shows_his_loan():
    """Connor Barron has no player_id at all. He has no score and no profile -- but where
    he is and who owns him are true facts about the club, and they are what the page is for."""
    out = attach_loans(SQUAD, LOANS)
    assert _row(out, "Connor Barron")["parent_club"] == "Rangers FC"


def test_a_player_with_no_loan_stays_blank_never_the_string_none():
    out = attach_loans(SQUAD, LOANS)
    row = _row(out, "Idris El Mizouni")
    assert pd.isna(row["parent_club"])
    assert pd.isna(row["loan_ends"])


def test_the_join_never_changes_the_row_count():
    """The squad frame IS the scrape. A join that adds or drops a row has invented or hidden
    a registered player. 3,783 on the live data; the shape is what matters here."""
    out = attach_loans(SQUAD, LOANS)
    assert len(out) == len(SQUAD)


def test_no_player_is_listed_twice_at_the_same_club():
    """A previous version duplicated players via a loose join -- Yusuf Akhamrich appeared
    twice under Leyton Orient."""
    out = attach_loans(SQUAD, LOANS)
    assert not out.duplicated(subset=["club_name", "player_name"]).any()


def test_a_loan_matching_no_squad_member_adds_no_row():
    """A loan at a club outside our seven leagues is correctly absent, not appended."""
    extra = pd.concat([LOANS, pd.DataFrame([
        {"player_id": float("nan"), "tm_player_id": 999999, "parent_club": "Elsewhere FC",
         "loan_ends": dt.date(2027, 6, 30)}])], ignore_index=True)
    out = attach_loans(SQUAD, extra)
    assert len(out) == len(SQUAD)
    assert "Elsewhere FC" not in set(out["parent_club"].dropna())


def test_an_empty_loans_frame_still_produces_the_columns():
    """The page selects these columns by name; a missing one is a KeyError, not a blank."""
    out = attach_loans(SQUAD, pd.DataFrame(
        columns=["player_id", "tm_player_id", "parent_club", "loan_ends"]))
    assert {"parent_club", "loan_ends"} <= set(out.columns)
    assert out["parent_club"].isna().all()


def test_the_caller_frame_is_not_mutated():
    attach_loans(SQUAD, LOANS)
    assert "parent_club" not in SQUAD.columns


# --- resolve_loan_player_ids -------------------------------------------------------------
#
# The other half: the Loans table joins player DETAIL (bio, position, rating) onto each loan
# through our player_id. Filling that id from `players.tm_player_id` is what lets the 77
# loanees we DO hold show their rating there.

PLAYERS = pd.DataFrame([
    {"player_id": 2000151869, "tm_player_id": 1083709.0, "player_name": "Joel Catesby"},
    {"player_id": 388235, "tm_player_id": 980343.0, "player_name": "Sam Chambers"},
    # David Kamara, held TWICE -- one StatsBomb-seeded, one Impect-minted, same TM id.
    {"player_id": 445315, "tm_player_id": 1076889.0, "player_name": "David Kamara"},
    {"player_id": 2000224875, "tm_player_id": 1076889.0, "player_name": "David Kamara"},
])

RAW_LOANS = pd.DataFrame([
    {"player_id": 388235.0, "tm_player_id": 980343, "player_name": "Sam Chambers"},
    {"player_id": float("nan"), "tm_player_id": 1083709, "player_name": "Joel Catesby"},
    {"player_id": float("nan"), "tm_player_id": 1076889, "player_name": "David Kamara"},
    {"player_id": float("nan"), "tm_player_id": 424242, "player_name": "Unknown Player"},
])


def test_a_blank_player_id_is_filled_from_the_transfermarkt_id():
    out = resolve_loan_player_ids(RAW_LOANS, PLAYERS)
    assert _row(out, "Joel Catesby")["player_id"] == 2000151869


def test_an_existing_player_id_is_never_overwritten():
    """The scrape resolved it at write time; that is the stronger claim."""
    out = resolve_loan_player_ids(RAW_LOANS, PLAYERS)
    assert _row(out, "Sam Chambers")["player_id"] == 388235


def test_a_transfermarkt_id_claimed_by_two_of_our_players_stays_unresolved():
    """THE DUPLICATION CASE. David Kamara, tm 1076889 -> 445315 AND 2000224875.

    Picking either would attach one identity's rating, injuries and assessments to a loan
    that may belong to the other. Blank is the honest answer.
    """
    out = resolve_loan_player_ids(RAW_LOANS, PLAYERS)
    assert pd.isna(_row(out, "David Kamara")["player_id"])


def test_resolving_never_changes_the_row_count():
    """412 rows for 411 loans is exactly what the ambiguous key produces if it is joined
    rather than dropped -- David Kamara listed twice in the Loans table."""
    out = resolve_loan_player_ids(RAW_LOANS, PLAYERS)
    assert len(out) == len(RAW_LOANS)


def test_a_loanee_we_hold_no_record_of_is_left_blank_not_dropped():
    out = resolve_loan_player_ids(RAW_LOANS, PLAYERS)
    assert "Unknown Player" in set(out["player_name"])
    assert pd.isna(_row(out, "Unknown Player")["player_id"])


def test_an_empty_players_frame_is_handled():
    out = resolve_loan_player_ids(
        RAW_LOANS, pd.DataFrame(columns=["player_id", "tm_player_id"]))
    assert len(out) == len(RAW_LOANS)


def test_the_caller_loans_frame_is_not_mutated():
    """Catesby's blank id must still be blank on the caller's frame -- the resolution
    belongs to the returned copy. `loans_frame` is @st.cache_data; mutating a cached frame
    in place leaks the change into every later read."""
    resolve_loan_player_ids(RAW_LOANS, PLAYERS)
    assert pd.isna(_row(RAW_LOANS, "Joel Catesby")["player_id"])
    assert _row(RAW_LOANS, "Sam Chambers")["player_id"] == 388235
