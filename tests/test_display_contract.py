"""Fields the UI renders must actually reach the UI.

Twice in one day a column was complete in the database and blank on screen:

  * `nationality` sat at 97% in `players` while every player card printed "not recorded",
    because loaders.py's bio SELECT never listed it;
  * `alt_rating` was hardcoded NULL in the loans query, so a loanee -- the cohort most
    likely to have a second reading -- showed a blank where the platform held a number.

Both passed every existing test, because the tests checked the DATABASE and the display
layer separately and nothing checked the seam between them. These tests are that seam:
for each field a view renders, assert the frame that view receives actually carries it.
"""

import pandas as pd
import pytest

from lofc.dashboard import player_header as ph
from lofc.dashboard.tabs.squads import DISPLAY_COLUMNS


# Every field player_header.build() reads off its row. Adding a cell to the card without
# adding the column to the loader is exactly the nationality bug.
HEADER_FIELDS = ["player_name", "team_name", "position_group", "league", "age", "foot",
                 "height_cm", "contract_until", "minutes", "nationality"]


def test_the_bio_loader_selects_every_field_the_player_card_renders():
    """A field the card reads but the loader never SELECTs renders as 'not recorded'
    forever, however complete the column is in the database."""
    import inspect
    from lofc.dashboard import loaders
    source = inspect.getsource(loaders.load_candidates)
    # the bio SELECT inside load_candidates
    for column in ("birth_date", "foot", "contract_until", "height_cm", "nationality"):
        assert column in source, (
            f"players.{column} is rendered by the player card but is not selected in "
            f"load_candidates' bio query — it will always read as 'not recorded'")


def test_the_card_renders_every_declared_field_when_present():
    """The opposite direction: a value supplied must actually appear."""
    row = pd.Series({"player_name": "A Player", "team_name": "A Club",
                     "position_group": "Winger", "league": "League One", "age": 24.0,
                     "foot": "left", "height_cm": 183, "nationality": "Morocco",
                     "contract_until": pd.Timestamp("2028-06-30"), "minutes": 1079.0})
    body = ph.build(row).split("</style>")[-1]
    for expected in ("A Player", "A Club", "Winger", "League One", "Left", "183 cm",
                     "Morocco", "Jun 2028", "1,079"):
        assert expected in body, f"{expected!r} was supplied but is not rendered"


def test_the_squad_view_declares_no_column_it_cannot_produce():
    """DISPLAY_COLUMNS is selected directly; a name that prepare() never creates is a
    KeyError in the running app, not a blank cell."""
    from lofc.dashboard.tabs.squads import prepare
    import datetime as dt
    frame = pd.DataFrame([{
        "competition_id": 4, "team_name": "C", "player_id": 1, "player_name": "P",
        "position_group": "Winger", "minutes": 100.0,
        "contract_until": dt.date(2027, 6, 30), "foot": "left", "height_cm": 180,
        "nationality": "England", "birth_date": dt.date(2000, 1, 1),
        "parent_club": None, "loan_ends": None, "last_season_rating": 3.0,
        "rating_competition_id": 4, "alt_rating": None, "alt_competition_id": None}])
    out = prepare(frame)
    missing = [c for c in DISPLAY_COLUMNS if c not in out.columns]
    assert not missing, f"declared but never produced: {missing}"


@pytest.mark.parametrize("column", ["alt_rating", "alt_competition_id",
                                    "last_season_rating", "rating_competition_id"])
def test_both_squad_queries_produce_the_same_rating_columns(column):
    """The loans query hardcoded `NULL AS alt_rating`, so the second reading vanished in
    the one view where loanees appear. Both queries must supply the same shape."""
    import inspect
    from lofc.dashboard.tabs import squads
    squad_sql = inspect.getsource(squads.squad_frame)
    loans_sql = inspect.getsource(squads.loans_frame)
    assert column in squad_sql, f"{column} missing from squad_frame"
    assert column in loans_sql, f"{column} missing from loans_frame"
    assert f"NULL::float           AS {column}" not in loans_sql, (
        f"{column} is hardcoded NULL in loans_frame — it will always render blank")


# --- the peer count: gate and display must not diverge ---------------------------------
#
# A composite is a rank within a league-position pool, and since 2026-09-11 a pool below
# MIN_PEERS_FOR_RANKING is withheld from the ranked list entirely. Gating on a number the
# recruiter cannot see is the same class of failure as the two bugs above, one level up: the
# logic is right, the screen does not say so, and the reader draws a wrong conclusion. The
# player report has stated its peer count since it was built (report/data.py's peer_count);
# the ranked list -- the surface that IS the ranking -- must state it too.

def test_the_pool_carries_a_peer_count_before_any_page_renders_it():
    """`with_peer_counts` must run in main(), against the season's FULL scorecard set."""
    import inspect
    from lofc.dashboard import app
    source = inspect.getsource(app.main)
    assert "with_peer_counts" in source, (
        "the Players pool never gets a peer_count column, so the gate cannot run and the "
        "Peers column would render empty")
    assert "peer_pool_sizes(ranking)" in source, (
        "peer pools must be counted from `ranking` (every scored player that season), not "
        "from the filtered pool — a sidebar filter must not shrink a player's peer group")


def test_the_players_table_renders_the_peer_count_it_gates_on():
    import inspect
    from lofc.dashboard.tabs import players
    source = inspect.getsource(players._players)
    assert '"Peers"' in source, (
        "players are withheld from the ranking when their pool is too small, but the table "
        "never shows the pool size — a recruiter cannot tell a 4.44-of-105 from a 4.90-of-1")
    assert "peer_count" in source, "the Peers column is declared but never sourced"


def test_the_squad_page_announces_the_fallback_instead_of_rendering_it_silently():
    """The fallback is fine; a fallback that looks complete is not. `render` must consult
    `squad_source_warning` — without that call the page degrades with no signal at all."""
    import inspect
    from lofc.dashboard.tabs import squads
    source = inspect.getsource(squads.render)
    assert "squad_source_warning" in source, (
        "Squads & loans falls back to appearance data when the Transfermarkt scrape is "
        "absent (3,783 rows -> 2,966) but never says so — the 2026-09-07 half-squad bug")
