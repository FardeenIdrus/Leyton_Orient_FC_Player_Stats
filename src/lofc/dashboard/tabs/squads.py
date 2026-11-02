"""Squad view: who is at each club right now, on what contract, and on loan from whom.

The January window's page. It exists because the ranking cannot answer January's question.
A composite needs 450 minutes; two months into 2026/27 the average player has 69-119, so
NOBODY is rankable and a season filter set to 26/27 returned an empty screen. The 450 rule
is right -- a per-90 rate on 70 minutes is noise -- but "nothing to show" is the wrong
answer to "who is at this club and can I sign him".

So this page answers a different question from the ranking, using facts that ARE current:

  who is in the squad now      current-season appearances
  is he gettable               contract expiry, and how long is left
  is he even available         on loan from whom, until when
  how good is he               LAST season's composite, labelled as such

Nothing here is scored. The rating column is carried across from the last complete season
and says so, because inventing a 26/27 composite from 70 minutes would be worse than
showing none.
"""

from __future__ import annotations

import datetime

import pandas as pd
import streamlit as st

from lofc.dashboard.formatting import dash_blanks
from lofc.dashboard.loaders import competition_name_by_id, get_engine
from lofc.dashboard.search import fold
from lofc.dashboard.seasons import contract_data_date, loan_data_date
from lofc.dashboard.session import go_to_player
from lofc.dashboard.sidebar_filters import SidebarFilters, apply_sidebar_filters
from lofc.model.scorecard import peer_pool_sizes, pool_is_thin
from lofc.store import squads as store_squads


@st.cache_data(ttl=300)
def squad_frame(season_id: int, rating_season_id: int) -> pd.DataFrame:
    """Every player at every club this season, with contract, loan and last season's rating."""
    return pd.read_sql(
        """
        WITH rated AS (
            -- ONE rating row per player. 116 players hold two scorecards for the last
            -- season because they appeared in two leagues (a loanee playing U21 and
            -- senior football), and a plain join on player_id duplicated every one of
            -- them in the squad table -- Yusuf Akhamrich appeared twice under Leyton
            -- Orient. The kept row is the league he played MOST minutes in, which is the
            -- most representative single number; the other is carried alongside as
            -- `alt_rating` rather than discarded, because the gap between them is real
            -- information (3.42 in League Two against 4.00 in PL2 answers "does it hold
            -- up a level up?").
            SELECT s.player_id, s.objective_composite, s.competition_id, m.minutes,
                   ROW_NUMBER() OVER (PARTITION BY s.player_id
                                      ORDER BY m.minutes DESC NULLS LAST,
                                               s.competition_id) AS rn,
                   COUNT(*)   OVER (PARTITION BY s.player_id) AS n_leagues
            FROM player_scorecards s
            JOIN player_metrics_neutral m
              ON m.player_id = s.player_id AND m.competition_id = s.competition_id
             AND m.season_id = s.season_id
            WHERE s.season_id = %(prev)s AND s.archetype = 'All Metrics'
              AND s.objective_composite IS NOT NULL
        ),
        best AS (SELECT * FROM rated WHERE rn = 1),
        second AS (SELECT player_id, objective_composite AS alt_rating,
                          competition_id AS alt_competition_id
                   FROM rated WHERE rn = 2)
        SELECT n.competition_id, n.team_name, n.player_id, n.player_name,
               n.position_group, n.minutes,
               p.contract_until, p.foot, p.height_cm, p.nationality, p.birth_date,
               l.parent_club, l.loan_ends,
               b.objective_composite AS last_season_rating,
               b.competition_id      AS rating_competition_id,
               sc.alt_rating, sc.alt_competition_id
        FROM player_metrics_neutral n
        JOIN players p ON p.player_id = n.player_id
        LEFT JOIN player_loans l ON l.player_id = n.player_id AND l.season_id = %(cur)s
        LEFT JOIN best   b  ON b.player_id  = n.player_id
        LEFT JOIN second sc ON sc.player_id = n.player_id
        WHERE n.season_id = %(cur)s
        ORDER BY n.team_name, n.minutes DESC
        """,
        get_engine(), params={"cur": season_id, "prev": rating_season_id})


@st.cache_data(ttl=300)
def loans_frame(season_id: int, rating_season_id: int) -> pd.DataFrame:
    """EVERY loan, whether or not the player has appeared in league data yet.

    Sourced from player_loans rather than from the squad frame. The squad frame is built
    from player_metrics_neutral, which only holds players who have PLAYED -- so 135 of the
    290 linked loanees were missing from it (injured, not yet selected, or not yet in an
    Impect file). "Who is on loan at this club" has to mean all of them, not only the ones
    who have had a game.

    Player details are LEFT joined: a loan we cannot yet match to one of our players is
    still a true fact about the club, and is listed with blank details rather than hidden.

    Detail is attached in pandas rather than in one SQL statement so the loan's identity can
    be RESOLVED first. 108 of 411 loan rows carry no `player_id`, and joining detail on that
    column left all of them blank -- including the 77 for whom the platform holds a full
    record under an id the loan row simply never carried.
    """
    loans = pd.read_sql(
        "SELECT competition_id, club_name AS team_name, player_id, tm_player_id, "
        "       player_name, parent_club, loan_ends "
        "FROM player_loans WHERE season_id = %(cur)s "
        "ORDER BY club_name, loan_ends NULLS LAST, player_name",
        get_engine(), params={"cur": season_id})
    if loans.empty:
        return loans
    # Fill the missing internal ids from the Transfermarkt id, dropping any claimed by two
    # of our players. Row count is unchanged -- see resolve_loan_player_ids.
    loans = resolve_loan_player_ids(
        loans,
        pd.read_sql("SELECT player_id, tm_player_id FROM players "
                    "WHERE tm_player_id IS NOT NULL", get_engine()))

    bio = pd.read_sql(
        "SELECT player_id, contract_until, foot, nationality, birth_date, height_cm "
        "FROM players", get_engine())
    # ONE appearance row per player, the league he played MOST minutes in. The previous
    # query additionally required the appearance's competition to match the LOAN's, so a
    # loanee whose minutes sat in another competition showed no position at all; this
    # matches what `registered_squad_frame` does, so the two tables cannot disagree.
    now = pd.read_sql(
        "SELECT DISTINCT ON (player_id) player_id, position_group, minutes "
        "FROM player_metrics_neutral WHERE season_id = %(s)s "
        "ORDER BY player_id, minutes DESC NULLS LAST",
        get_engine(), params={"s": season_id})
    last = pd.read_sql(
        "SELECT DISTINCT ON (player_id) player_id, position_group AS last_position "
        "FROM player_metrics_neutral WHERE season_id = %(s)s "
        "ORDER BY player_id, minutes DESC NULLS LAST",
        get_engine(), params={"s": rating_season_id})
    # Last season's rating, and the SECOND reading where he played in two leagues. `alt_*`
    # was once hardcoded NULL here, so a loanee -- exactly the cohort most likely to have a
    # second reading -- showed a blank while the platform held the number. Yusuf Akhamrich
    # read 3.42 with nothing beside it, when 4.00 in PL2 was known.
    rated = pd.read_sql(
        """SELECT player_id, objective_composite, competition_id, rn FROM (
             SELECT s.player_id, s.objective_composite, s.competition_id,
                    ROW_NUMBER() OVER (PARTITION BY s.player_id
                                       ORDER BY m.minutes DESC NULLS LAST) rn
             FROM player_scorecards s
             JOIN player_metrics_neutral m ON m.player_id = s.player_id
              AND m.competition_id = s.competition_id AND m.season_id = s.season_id
             WHERE s.season_id = %(s)s AND s.archetype = 'All Metrics'
               AND s.objective_composite IS NOT NULL) x WHERE rn <= 2""",
        get_engine(), params={"s": rating_season_id})

    out = loans.merge(bio, on="player_id", how="left")
    out = out.merge(now, on="player_id", how="left")
    out = out.merge(last, on="player_id", how="left")
    out = out.merge(rated[rated.rn == 1][["player_id", "objective_composite",
                                          "competition_id"]]
                    .rename(columns={"objective_composite": "last_season_rating",
                                     "competition_id": "rating_competition_id"}),
                    on="player_id", how="left")
    out = out.merge(rated[rated.rn == 2][["player_id", "objective_composite",
                                          "competition_id"]]
                    .rename(columns={"objective_composite": "alt_rating",
                                     "competition_id": "alt_competition_id"}),
                    on="player_id", how="left")
    # Last known position, marked -- same three tiers as the squad view, so the Position
    # filter behaves identically whichever table the reader is looking at.
    return with_last_season_position(out)


@st.cache_data(ttl=300)
def player_rated_rows(player_id: int) -> pd.DataFrame:
    """Every league-season this player has a rating in, with his minutes -- the input to
    `best_profile_target`. Small (a handful of rows per player) and cached."""
    return pd.read_sql(
        "SELECT s.competition_id, s.season_id, m.minutes, s.objective_composite "
        "FROM player_scorecards s "
        "JOIN player_metrics_neutral m ON m.player_id = s.player_id "
        " AND m.competition_id = s.competition_id AND m.season_id = s.season_id "
        "WHERE s.player_id = %(p)s AND s.archetype = 'All Metrics'",
        get_engine(), params={"p": int(player_id)})


@st.cache_data(ttl=300)
def _season_scorecards(season_id: int) -> pd.DataFrame:
    """The live season's All-Metrics scorecards, for the "This season" column and its
    peer-pool gate. 300s, matching the other loaders on this page."""
    return pd.read_sql(
        "SELECT player_id, competition_id, season_id, position_group, objective_composite "
        "FROM player_scorecards WHERE season_id = %(s)s AND archetype = 'All Metrics' "
        "AND objective_composite IS NOT NULL",
        get_engine(), params={"s": season_id})


@st.cache_data(ttl=300)
def scraped_squads() -> pd.DataFrame:
    """The REGISTERED squad at every club, from the Transfermarkt scrape.

    The page used to be built from `player_metrics_neutral`, which holds only players who
    have APPEARED. Five matches into 2026/27 that showed 16 of Leyton Orient's 33 players:
    Aaron Connolly, Alex Gilbert and 16 others were in the squad, their contracts scraped
    the same morning, and invisible.

    Impect cannot supply a squad list -- it knows a player only once he plays. Transfermarkt
    publishes the registered squad, which is what "who is at this club" means.

    Reads `transfermarkt_squads`, NOT the scrape CSV. The CSV is the scraper's handoff to the
    pipeline stages that run beside it on the same disk; the dashboard is a separate process
    and may be a separate host, where that file does not exist. While this read the file, the
    page silently fell back to appearance data -- 2,966 players instead of 3,783 -- anywhere
    the scrape had not been run. Same shape as `player_injuries`: scrape -> loader -> table ->
    dashboard reads the table.
    """
    frame = store_squads.load_frame(get_engine())
    if frame.empty:
        return pd.DataFrame()
    keep = ["competition_id", "club_name", "player_name", "tm_player_id",
            "date_of_birth", "contract_until", "height_cm", "foot", "position"]
    d = frame[[c for c in keep if c in frame.columns]].copy()
    d = d.rename(columns={"position": "tm_position"})
    d["contract_until"] = pd.to_datetime(d["contract_until"], errors="coerce")
    d["date_of_birth"] = pd.to_datetime(d["date_of_birth"], errors="coerce")
    return d


@st.cache_data(ttl=300)
def registered_squad_frame(season_id: int, rating_season_id: int) -> pd.DataFrame:
    """Every REGISTERED squad member, with appearances joined on where they exist.

    Base is the scrape, not the appearance table, so a signing shows up with his contract
    the day he is registered. Position and Minutes stay blank until he plays -- and where
    he has not, his LAST KNOWN position is carried across so the column reads as a fact
    about the player rather than a gap.
    """
    squads = scraped_squads()
    if squads.empty:
        return squad_frame(season_id, rating_season_id)

    ours = pd.read_sql(
        "SELECT player_id, tm_player_id, nationality, birth_date, contract_until, "
        "       foot, height_cm FROM players WHERE tm_player_id IS NOT NULL",
        get_engine())
    # A Transfermarkt id claimed by more than one of our players would FAN THE JOIN OUT,
    # listing that squad member twice. 15 such pairs exist (the unresolved identity-split
    # defect). Dropped rather than picked, exactly as identity.drop_ambiguous_matches
    # does: guessing which of two records is the real player would attach one man's rating
    # and injury history to another. He still appears, from the scrape's own bio; he just
    # carries no link.
    ours = ours.drop_duplicates("tm_player_id", keep=False)
    # The full roster, for the name+date-of-birth route below (players with no
    # tm_player_id are absent from `ours`, which is keyed on it).
    ours_all = pd.read_sql(
        "SELECT player_id, player_name, birth_date FROM players "
        "WHERE birth_date IS NOT NULL", get_engine())
    # ONE appearance row per player: a player who has turned out in two leagues this
    # season (a loanee playing U21 and senior football) has two, and joining both would
    # list him twice under the same club.
    now = pd.read_sql(
        "SELECT DISTINCT ON (player_id) player_id, competition_id, team_name, "
        "       position_group, minutes FROM player_metrics_neutral "
        "WHERE season_id = %(s)s ORDER BY player_id, minutes DESC NULLS LAST",
        get_engine(), params={"s": season_id})
    last = pd.read_sql(
        "SELECT DISTINCT ON (player_id) player_id, position_group AS last_position "
        "FROM player_metrics_neutral WHERE season_id = %(s)s "
        "ORDER BY player_id, minutes DESC NULLS LAST",
        get_engine(), params={"s": rating_season_id})
    rated = pd.read_sql(
        """SELECT player_id, objective_composite, competition_id, rn FROM (
             SELECT s.player_id, s.objective_composite, s.competition_id,
                    ROW_NUMBER() OVER (PARTITION BY s.player_id
                                       ORDER BY m.minutes DESC NULLS LAST) rn
             FROM player_scorecards s
             JOIN player_metrics_neutral m ON m.player_id = s.player_id
              AND m.competition_id = s.competition_id AND m.season_id = s.season_id
             WHERE s.season_id = %(s)s AND s.archetype = 'All Metrics'
               AND s.objective_composite IS NOT NULL) x WHERE rn <= 2""",
        get_engine(), params={"s": rating_season_id})
    # BOTH keys, and NO `player_id IS NOT NULL` filter. That filter discarded 108 of 411
    # loans at source -- every one held under a Transfermarkt id alone, which is the key
    # this frame is built on. `attach_loans` prefers player_id and falls back to
    # tm_player_id, so a loan reaches the squad member under either.
    loans = pd.read_sql(
        "SELECT player_id, tm_player_id, parent_club, loan_ends "
        "FROM player_loans WHERE season_id = %(s)s",
        get_engine(), params={"s": season_id})

    # --- LINK FIRST, then attach bio ---------------------------------------------
    # Order matters: bio is keyed on OUR player_id, so it must be merged AFTER both link
    # routes have run. Merging it on tm_player_id first left every name-linked player
    # (Oliver Dovin among them) with a player_id but no nationality, age or height, even
    # though the platform held all three.
    link = squads[["tm_player_id", "player_name", "date_of_birth"]].copy()
    link = link.merge(ours[["tm_player_id", "player_id"]], on="tm_player_id", how="left")

    # Route 2: name + date of birth for rows with no id link. 717 of 3,783 squad rows have
    # none, and 301 of those ARE players we hold. A key claimed by more than one of our
    # players is DROPPED rather than guessed -- identity.drop_ambiguous_matches' rule, for
    # the same reason: a wrong link attaches one man's record to another.
    unlinked = link["player_id"].isna()
    if unlinked.any():
        keyed = ours_all.copy()
        keyed["_k"] = (keyed["player_name"].str.lower().str.strip() + "|"
                       + keyed["birth_date"].astype(str))
        keyed = keyed.drop_duplicates("_k", keep=False)[["_k", "player_id"]]
        gap = link.loc[unlinked].copy()
        gap["_k"] = (gap["player_name"].str.lower().str.strip() + "|"
                     + gap["date_of_birth"].dt.date.astype(str))
        found = gap.merge(keyed, on="_k", how="left", suffixes=("", "_byname"))
        link.loc[unlinked, "player_id"] = found["player_id_byname"].to_numpy()

    out = squads.copy()
    out["player_id"] = link["player_id"].to_numpy()

    bio = pd.read_sql(
        "SELECT player_id, nationality, birth_date, contract_until, foot, height_cm "
        "FROM players", get_engine())
    out = out.merge(bio, on="player_id", how="left", suffixes=("_tm", ""))
    # The scrape's own bio fills anything the platform does not hold.
    for col in ("contract_until", "foot", "height_cm"):
        out[col] = out[col].combine_first(out[f"{col}_tm"])
    out["birth_date"] = out["birth_date"].combine_first(out["date_of_birth"])

    out = out.merge(now[["player_id", "position_group", "minutes"]], on="player_id",
                    how="left")
    out = out.merge(last, on="player_id", how="left")
    out = out.merge(rated[rated.rn == 1][["player_id", "objective_composite",
                                          "competition_id"]]
                    .rename(columns={"objective_composite": "last_season_rating",
                                     "competition_id": "rating_competition_id"}),
                    on="player_id", how="left")
    out = out.merge(rated[rated.rn == 2][["player_id", "objective_composite",
                                          "competition_id"]]
                    .rename(columns={"objective_composite": "alt_rating",
                                     "competition_id": "alt_competition_id"}),
                    on="player_id", how="left")
    out = attach_loans(out, loans)
    out["team_name"] = out["club_name"]
    # Last known position, marked, where he has not featured yet this season; failing
    # that, the position Transfermarkt registers him under, marked as such (P18).
    out = with_last_season_position(out)
    out = with_registered_position(out)
    return out


def months_left(when, today: datetime.date | None = None) -> float | None:
    """Whole months from today to a contract expiry. Negative means already expired."""
    if when is None or pd.isna(when):
        return None
    today = today or datetime.date.today()
    end = pd.Timestamp(when).date()
    return (end.year - today.year) * 12 + (end.month - today.month)


# Position falls back to last season where a player has not featured, marked in the column so
# the reader can tell an observed position from an inferred one. The filter must match on the
# bare position, or "Centre Back" and "Centre Back (last season)" become two separate choices.
_FALLBACK_SUFFIX = " (last season)"
_REGISTERED_SUFFIX = " (registered)"


def _bare_position(value) -> str | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value)
    for suffix in (_FALLBACK_SUFFIX, _REGISTERED_SUFFIX):
        if text.endswith(suffix):
            return text[: -len(suffix)]
    return text


# P18 (owner, 2026-10-22): Transfermarkt's 16 position names -> our 8 groups. Left/Right
# Back and Left/Right Winger merge exactly as club_framework does. The owner's calls: Left /
# Right Midfield -> Winger, Second Striker -> Centre Forward, and the vague "Midfielder" /
# "Defender" are deliberately ABSENT -- naming a group the source did not state is a guess.
TM_POSITION_GROUPS = {
    "Goalkeeper": "Goalkeeper",
    "Centre-Back": "Centre Back",
    "Left-Back": "Full Back", "Right-Back": "Full Back",
    "Defensive Midfield": "Defensive Mid",
    "Central Midfield": "Central Mid",
    "Attacking Midfield": "Attacking Mid",
    "Left Winger": "Winger", "Right Winger": "Winger",
    "Left Midfield": "Winger", "Right Midfield": "Winger",
    "Centre-Forward": "Centre Forward", "Striker": "Centre Forward",
    "Second Striker": "Centre Forward",
}


def registered_position(tm_position) -> str | None:
    """Our position group for a Transfermarkt position, or None when it cannot be said."""
    if tm_position is None or (isinstance(tm_position, float) and pd.isna(tm_position)):
        return None
    return TM_POSITION_GROUPS.get(str(tm_position).strip())


def with_registered_position(frame: pd.DataFrame, column: str = "position_group",
                             source: str = "tm_position") -> pd.DataFrame:
    """`frame` with still-blank positions filled from Transfermarkt, MARKED "(registered)".

    The THIRD tier, after this season and last season (owner rule 1: Impect wins wherever it
    has a position, because it records where a player actually lined up). Reached only by a
    squad member who has played in neither season -- Impect holds no position for him at all:
    its player list has no position field, positions come only from matches (verified against
    the API 2026-10-22). The suffix keeps a registration label visibly different from an
    observed position; `_bare_position` strips it so one filter covers all three tiers.
    """
    out = frame.copy()
    if out.empty or column not in out.columns or source not in out.columns:
        return out
    marked = out[source].map(
        lambda v: f"{g}{_REGISTERED_SUFFIX}" if (g := registered_position(v)) else None)
    out[column] = out[column].where(out[column].notna(), marked)
    return out


def best_profile_target(rows: pd.DataFrame) -> tuple[int, int] | None:
    """(competition_id, season_id) where this player's profile should open, or None.

    The click used to carry THIS season's competition_id with LAST season's season_id -- one
    from each -- so a player who changed league over the summer was looked up in a
    league-season he had barely played in. Phillip Chinedu, at Leyton Orient in 2026/27, was
    looked up in League One 2025/26 where he has 14 minutes and no rating, and no profile
    rendered. It hits most of a 2026/27 squad, since a summer move is the normal case.

    The rule: his most recent season WITH A RATING, and within it the league he played most
    minutes in. That row best represents him, and it is guaranteed to exist because it is
    chosen from the rows he actually has -- the previous version constructed a pair that might
    not correspond to any row at all.

    None when he has no rating anywhere; the caller shows a message rather than opening
    somebody else's profile.
    """
    if rows is None or rows.empty:
        return None
    rated = rows[rows["objective_composite"].notna()]
    if rated.empty:
        return None
    latest = rated[rated["season_id"] == rated["season_id"].max()]
    best = latest.sort_values("minutes", ascending=False).iloc[0]
    return int(best["competition_id"]), int(best["season_id"])


def position_options(frame: pd.DataFrame) -> list[str]:
    """"All" plus every position present, de-suffixed and sorted."""
    if frame.empty or "Position" not in frame.columns:
        return ["All"]
    bare = {p for p in (_bare_position(v) for v in frame["Position"]) if p}
    return ["All"] + sorted(bare)


def filter_by_position(frame: pd.DataFrame, position: str) -> pd.DataFrame:
    """Rows for one position, or everything when "All".

    Players whose position falls back to last season are INCLUDED: a registered signing who
    has not featured yet still has a known position, and he is exactly who a January search is
    looking for. A player with no known position at all is excluded from a specific filter --
    he cannot be asserted into a position group.
    """
    if position == "All" or frame.empty or "Position" not in frame.columns:
        return frame
    return frame[frame["Position"].map(_bare_position) == position]


def with_last_season_position(frame: pd.DataFrame, column: str = "position_group",
                              fallback: str = "last_position") -> pd.DataFrame:
    """`frame` with `column` filled from `fallback`, MARKED as last season's.

    A registered signing who has not featured yet still has a known position, and he is
    exactly who a January search is for. The suffix is not decoration: an observed position
    and an inferred one are different claims and must not read alike. `_bare_position`
    strips it, so one filter covers both tiers.

    No position either season stays blank. Blank is a fact; a guessed group changes which
    peers a reader assumes he was measured against.
    """
    out = frame.copy()
    if out.empty or column not in out.columns or fallback not in out.columns:
        return out
    marked = out[fallback].map(
        lambda v: f"{v}{_FALLBACK_SUFFIX}" if pd.notna(v) else None)
    out[column] = out[column].where(out[column].notna(), marked)
    return out


LOAN_COLUMNS = ["parent_club", "loan_ends"]


def _loan_lookup(frame: pd.DataFrame, loans: pd.DataFrame, key: str,
                 column: str) -> pd.Series:
    """One loan column, looked up through `key`. Blank where the key is absent or ambiguous.

    A key claimed by more than one loan row is DROPPED, not picked -- attaching one man's
    loan to another is worse than showing no loan. Both keys are unique in `player_loans`
    today; the guard is what keeps that true.
    """
    blank = pd.Series([None] * len(frame), index=frame.index, dtype=object)
    if key not in frame.columns or key not in loans.columns or column not in loans.columns:
        return blank
    src = loans.assign(_k=pd.to_numeric(loans[key], errors="coerce")).dropna(subset=["_k"])
    src = src.drop_duplicates("_k", keep=False)
    if src.empty:
        return blank
    return pd.to_numeric(frame[key], errors="coerce").map(src.set_index("_k")[column])


def attach_loans(squad: pd.DataFrame, loans: pd.DataFrame) -> pd.DataFrame:
    """`squad` plus parent_club and loan_ends, matched on player_id OR tm_player_id.

    The squad frame is built from the Transfermarkt scrape and keyed on `tm_player_id`;
    `player_loans` carries our internal `player_id` only where the scrape could resolve one.
    Joining on `player_id` alone left 108 of 411 loans invisible -- Joel Catesby rendered
    with a blank "On loan from" while Transfermarkt plainly showed Accrington Stanley, on
    loan from Everton FC U21 until 31/05/2027.

    `player_id` is preferred where both sides carry one: it is the key the rest of the
    platform joins on, and it survives a Transfermarkt id being re-issued.

    A LEFT attach, always: the row count is the scrape's, and a join that adds or drops a
    row has invented or hidden a registered squad member.
    """
    out = squad.copy()
    for column in LOAN_COLUMNS:
        out[column] = pd.Series([None] * len(out), index=out.index, dtype=object)
    if out.empty or loans.empty:
        return out
    for column in LOAN_COLUMNS:
        primary = _loan_lookup(out, loans, "player_id", column)
        out[column] = primary.where(
            primary.notna(), _loan_lookup(out, loans, "tm_player_id", column))
    return out


def resolve_loan_player_ids(loans: pd.DataFrame, players: pd.DataFrame) -> pd.DataFrame:
    """`loans` with `player_id` filled from `players.tm_player_id` where the scrape left it blank.

    This is what lets a loanee we DO hold show his bio, position and rating in the Loans
    table: 77 of the 108 unresolved loans are players with a full record under an id the
    loan row simply never carried.

    A `tm_player_id` claimed by more than one of our players is left UNRESOLVED. David
    Kamara holds two identities -- 445315 seeded from StatsBomb, 2000224875 minted from
    Impect -- both claiming Transfermarkt 1076889, so a plain join returns 412 rows for 411
    loans and lists him twice. Picking one would attach that identity's rating, injuries and
    assessments to a loan that may belong to the other. Same rule as
    `identity.drop_ambiguous_matches`.
    """
    out = loans.copy()
    if out.empty or players.empty or "tm_player_id" not in out.columns:
        return out
    ours = players.assign(_k=pd.to_numeric(players["tm_player_id"], errors="coerce"))
    ours = ours.dropna(subset=["_k"]).drop_duplicates("_k", keep=False)
    if ours.empty:
        return out
    found = pd.to_numeric(out["tm_player_id"], errors="coerce").map(
        ours.set_index("_k")["player_id"])
    have = (out["player_id"] if "player_id" in out.columns
            else pd.Series([None] * len(out), index=out.index, dtype=object))
    out["player_id"] = have.where(have.notna(), found)
    return out


def loan_view(loans: pd.DataFrame, league: str = "All", club: str = "All",
              position: str = "All") -> pd.DataFrame:
    """The "On loan only" view: the SAME three filters the squad view applies.

    "On loan only" does not filter the squad frame -- it REPLACES it, because 135 of the
    linked loanees have not appeared in league data yet and are absent from the squad frame
    entirely. League and Club were re-applied to the replacement; Position was not, so
    selecting Centre Forward and then "On loan only" returned every position. Every filter
    the page offers has to survive the swap, which is what this function is for.
    """
    if loans.empty:
        return loans
    view = loans
    if league != "All" and "League" in view.columns:
        view = view[view["League"] == league]
    if club != "All" and "Club" in view.columns:
        view = view[view["Club"] == club]
    return filter_by_position(view, position)


def this_season_score(frame: pd.DataFrame, scores: pd.DataFrame, pool_sizes: dict,
                      season_id: int | None = None) -> pd.DataFrame:
    """`frame` plus a `This season` column: the LIVE season's composite, where it is rankable.

    GATED by the same peer-pool floor the Players page enforces. A live-season composite is a
    percentile within a league-position pool, and early in a season those pools are tiny -- a
    player alone in his pool takes the 100th percentile on every metric by construction and
    scores 4.90, above anything earned across a full season. Showing that here would
    reintroduce on this page exactly what was removed from the ranking.

    Blank therefore means "not yet rankable" -- either under 450 minutes, or too few peers --
    never "missing". Returns a copy.
    """
    out = frame.copy()
    keys = ["player_id", "competition_id", "season_id"]
    # The squad frame is built from the Transfermarkt scrape and carries no season column --
    # the page knows which season it is showing, so it is passed in rather than inferred.
    if "season_id" not in out.columns and season_id is not None:
        out["season_id"] = int(season_id)
    if out.empty or scores.empty or "season_id" not in out.columns:
        out["This season"] = pd.Series(dtype="float64")
        return out
    usable = scores[[not pool_is_thin(pool_sizes.get(
        (int(r.competition_id), int(r.season_id), r.position_group)))
        for r in scores.itertuples()]]
    if usable.empty:
        out["This season"] = pd.Series([float("nan")] * len(out), index=out.index)
        return out
    lookup = (usable[keys + ["objective_composite"]]
              .drop_duplicates(keys).set_index(keys)["objective_composite"])
    out["This season"] = lookup.reindex(pd.MultiIndex.from_frame(out[keys])).to_numpy()
    if "season_id" not in frame.columns:
        out = out.drop(columns=["season_id"])
    return out


def prepare(frame: pd.DataFrame, today: datetime.date | None = None) -> pd.DataFrame:
    """Display columns, in the order a recruiter reads them."""
    if frame.empty:
        return frame
    names = competition_name_by_id()
    out = frame.copy()
    out["Months left"] = out["contract_until"].map(lambda d: months_left(d, today))
    out["On loan from"] = out["parent_club"]
    out["Loan ends"] = pd.to_datetime(out["loan_ends"], errors="coerce").dt.date
    out["Contract to"] = pd.to_datetime(out["contract_until"], errors="coerce").dt.date
    out["Age"] = ((pd.Timestamp(today or datetime.date.today())
                   - pd.to_datetime(out["birth_date"], errors="coerce")).dt.days / 365.25)
    out["League"] = out["competition_id"].map(names).fillna("\u2014")
    # Which league last season's rating came from. Without it the number is unreadable:
    # a 3.42 earned in League Two and one earned in PL2 are not the same claim.
    out["Rated in"] = out["rating_competition_id"].map(names)
    # The SECOND reading, where a player appeared in two leagues last season. 116 players
    # have one. Showing only the higher-minutes figure hides exactly the level-step
    # signal a loan is meant to answer.
    out["Also rated"] = out["alt_rating"]
    out["Also in"] = out["alt_competition_id"].map(names)
    # Declared here so `prepare` produces every DISPLAY_COLUMN (the invariant the display
    # contract tests hold), and FILLED by `this_season_score`, which needs the scorecards and
    # the peer-pool sizes. A page rendered without that call shows blanks, never a KeyError.
    out["This season"] = pd.Series([float("nan")] * len(out), index=out.index)
    return out.rename(columns={
        "team_name": "Club", "player_name": "Player", "position_group": "Position",
        "minutes": "Minutes", "foot": "Foot", "nationality": "Nationality",
        "last_season_rating": "Last season"})


DISPLAY_COLUMNS = ["Club", "Player", "Position", "Age", "Minutes", "This season", "Last season",
                   "Rated in", "Also rated", "Also in", "Contract to", "Months left",
                   "On loan from", "Loan ends", "Foot", "Nationality"]


# How each numeric column is rounded for EXPORT. The on-screen table is formatted by
# column_config, but `to_csv` writes the raw float -- so the file the Head of Recruitment
# opens showed "105.097500" minutes and "26.778919" years while the screen showed 105 and
# 26.8. A file that disagrees with the screen it came from is worse than no file.
EXPORT_ROUNDING = {"Age": 1, "Minutes": 0, "Last season": 2, "Also rated": 2,
                   "Months left": 0}


def for_export(table: pd.DataFrame) -> pd.DataFrame:
    """The table as it should be WRITTEN: same values as the screen, same precision."""
    out = table.copy()
    for column, places in EXPORT_ROUNDING.items():
        if column in out.columns:
            rounded = pd.to_numeric(out[column], errors="coerce").round(places)
            out[column] = rounded.astype("Int64") if places == 0 else rounded
    return out


def squad_source_warning(scrape_rows: int, shown_rows: int) -> str | None:
    """The banner text when this page is running on the fallback, or None when it is not.

    The page is built on the Transfermarkt squad scrape, which is gitignored licensed data
    and therefore absent from a freshly cloned server until the pipeline runs. Without it
    `registered_squad_frame` falls back to `player_metrics_neutral` -- who has APPEARED --
    silently dropping every registered player who has not yet featured. On 2026-09-11 that
    was 3,783 rows down to 2,966, and Leyton Orient 33 down to 21.

    The fallback itself is correct behaviour: a partial page beats a crash. What was wrong
    was that it looked identical to a complete one -- the same defect fixed on 2026-09-07,
    which survived because a half-populated squad list reads as a full one. So the page keeps
    rendering and states plainly that it is incomplete, and says WHICH players are absent,
    because "data missing" tells a recruiter nothing about whether to trust what he sees.
    """
    if scrape_rows:
        return None
    return (f"**Squad list incomplete — this is not the full squad.** Showing the "
            f"**{shown_rows:,}** players who have appeared this season, so every registered "
            f"member who has **not yet played** is missing: new signings, injured and "
            f"unselected players. The Transfermarkt squad scrape (`efl_values.csv`) is not "
            f"present on this server — run the pipeline, or copy `data/reference/"
            f"transfermarkt/` across, to restore the full list.")


def sidebar_view(frame: pd.DataFrame, filters: SidebarFilters) -> pd.DataFrame:
    """A `prepare`d frame narrowed by the sidebar: age, leagues, foot, contract, loan.

    Season, Position and Minimum minutes do not apply here: the page is the current squad,
    has its own Position filter with "All", and lists registered players who have not
    played."""
    if frame.empty:
        return frame
    framed = frame.assign(_on_loan=frame["On loan from"].notna())
    out = apply_sidebar_filters(framed, filters, age="Age", league="League", foot="Foot",
                                contract="contract_until", on_loan="_on_loan",
                                loan_ends="loan_ends")
    return out.drop(columns=["_on_loan"])


# Missing cells must read "—": st.dataframe draws any None/NaN/NaT as a grey "None" (see
# formatting.py). Ratings ("x.xx") and age ("xx.x") sort the same as text; Minutes,
# Months left and the two dates stay typed (as text they would mis-sort) and keep "None".
_DISPLAY_FORMATS = {"Age": "{:.1f}", "This season": "{:.2f}", "Last season": "{:.2f}",
                    "Also rated": "{:.2f}"}


def squad_display(table: pd.DataFrame) -> pd.DataFrame:
    """The table as shown: a copy, row order unchanged so a click still indexes `view`."""
    return dash_blanks(table, _DISPLAY_FORMATS)


def transfermarkt_asof(squads_date: str | None, loans_date: str | None) -> str | None:
    """One line saying how old the Transfermarkt data is. Dates arrive as "07 Sep 2026"
    (the seasons.py helpers) and are shown without the zero pad. None when both unknown."""
    squads_date, loans_date = (d.lstrip("0") if d else None for d in (squads_date, loans_date))
    if squads_date and loans_date and squads_date != loans_date:
        return (f"Transfermarkt data as of {squads_date} (squads & contracts) · "
                f"{loans_date} (loans).")
    if squads_date and loans_date:
        return f"Transfermarkt data as of {squads_date}."
    if squads_date:
        return f"Transfermarkt data as of {squads_date} (squads & contracts)."
    if loans_date:
        return f"Transfermarkt data as of {loans_date} (loans)."
    return None


def filter_by_name(frame: pd.DataFrame, query: str) -> pd.DataFrame:
    """Rows whose Player contains the query, accent-, case- and punctuation-insensitive
    (same folding as the global search). Blank query = no filter."""
    key = fold(query)
    if not key or frame.empty:
        return frame
    return frame[frame["Player"].map(lambda n: key in fold(n))]


def render(season_id: int, rating_season_id: int, season_label: str,
           rating_label: str, filters: SidebarFilters | None = None) -> None:
    filters = filters or SidebarFilters()
    st.subheader("Squads, contracts and loans")
    st.caption(f"Every registered squad member, {season_label}. Click a row to open the "
               f"player.")

    asof = transfermarkt_asof(contract_data_date(), loan_data_date())
    if asof:
        st.caption(asof)

    frame = prepare(registered_squad_frame(season_id, rating_season_id))
    # This season's rating where it is rankable -- gated by the same peer-pool floor the
    # Players page uses, so a pool-of-one 4.90 cannot appear here after being removed there.
    _live_cards = _season_scorecards(season_id)
    frame = this_season_score(frame, _live_cards, peer_pool_sizes(_live_cards), season_id)
    # Before anything else on the page: is this the real squad list, or the appearance-based
    # fallback? `scraped_squads()` is @st.cache_data, so this second call is free.
    warning = squad_source_warning(len(scraped_squads()), len(frame))
    if warning:
        st.error(warning)
    if frame.empty:
        st.info("No squad data for this season yet.")
        return

    frame = sidebar_view(frame, filters)
    names = competition_name_by_id()
    # Bottom-aligned so every control (and the radio, whose label sits above it) shares a baseline;
    # the radio gets the widest column so its three options do not wrap or squash.
    c1, c2, c3, c4, c5 = st.columns([2, 2, 2, 2.4, 4.6], vertical_alignment="bottom")
    league = c1.selectbox("League", ["All"] + sorted(frame["League"].unique()))
    view = frame if league == "All" else frame[frame["League"] == league]
    club = c2.selectbox("Club", ["All"] + sorted(view["Club"].dropna().unique()))
    if club != "All":
        view = view[view["Club"] == club]
    position = c3.selectbox("Position", position_options(view))
    view = filter_by_position(view, position)
    query = c4.text_input("Player", placeholder="Search a player…")
    view = filter_by_name(view, query)
    show = c5.radio("Show", ["Everyone", "On loan only", "Contract expiring (under 12 months)"],
                    horizontal=True, label_visibility="visible")

    if show == "On loan only":
        # From player_loans, NOT from the squad frame: 135 of 290 linked loanees have not
        # appeared in league data yet and are absent from the squad frame entirely. So this
        # REPLACES the view rather than filtering it -- and every filter the page offers has
        # to be re-applied to the replacement. League and Club were; Position was not, so
        # selecting Centre Forward and then "On loan only" returned every position.
        loans = prepare(loans_frame(season_id, rating_season_id))
        if not loans.empty:
            loans["League"] = loans["competition_id"].map(names).fillna("\u2014")
            loans = sidebar_view(filter_by_name(
                loan_view(loans, league=league, club=club, position=position), query),
                filters)
        view = loans
    elif show.startswith("Contract expiring"):
        # Expired dates are INCLUDED deliberately: a lapsed date is a live question --
        # usually an extension nobody has published -- not a closed one.
        view = view[view["Months left"].notna() & (view["Months left"] < 12)]

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Players", f"{len(view):,}")
    m2.metric("On loan", f"{int(view['On loan from'].notna().sum()):,}")
    m3.metric("Contract known", f"{int(view['Contract to'].notna().sum()):,}")
    expiring = int((view["Months left"].notna() & (view["Months left"] < 12)).sum())
    m4.metric("Expiring < 12 months", f"{expiring:,}")

    table = squad_display(view[DISPLAY_COLUMNS].reset_index(drop=True))
    selection = st.dataframe(
        table, hide_index=True, width="stretch", height=560,
        on_select="rerun", selection_mode="single-row", key="squads_table",
        column_config={
            "Age": st.column_config.TextColumn("Age", width="small"),
            "This season": st.column_config.TextColumn(
                "This season",
                help="This season's rating, where enough of his league-position peers have "
                     "played 450+ minutes for a ranking to mean anything. Blank = not yet "
                     "rankable, not missing."),
            "Position": st.column_config.TextColumn(
                "Position", help="Where he has played THIS season. '(registered)' = "
                                 "Transfermarkt's listed position, where he has not played "
                                 "in either season. Marked '(last season)' "
                                 "where he has not featured yet."),
            "Minutes": st.column_config.NumberColumn(
                "Minutes", format="%d", width="small",
                help="This season, in our seven leagues only."),
            "Last season": st.column_config.TextColumn(
                f"{rating_label} rating", width="small",
                help="The club composite from the last complete season."),
            "Also rated": st.column_config.TextColumn(
                "Also rated", width="small",
                help="A second rating, where the player appeared in two leagues last "
                     "season — the level-step reading."),
            "Contract to": st.column_config.DateColumn(
                "Contract to", format="MMM YYYY",
                help="From Transfermarkt, which publishes no contract for about 22% of "
                     "squad members. A blank means unknown, never 'no contract'."),
            "Loan ends": st.column_config.DateColumn("Loan ends", format="MMM YYYY"),
            "Months left": st.column_config.NumberColumn(
                "Months left", format="%d", width="small",
                help="Months to contract expiry. Negative means the recorded date has "
                     "passed — usually an extension nobody has published yet."),
        })

    # Row click -> that player's profile. The ID is carried, never the label.
    rows = list(selection.selection.rows) if selection and selection.selection else []
    if rows and rows[0] < len(view):
        picked = view.iloc[rows[0]]
        # A squad member we hold no record of has no player_id, and int(NaN) raised
        # "cannot convert float NaN to integer" -- clicking him crashed the whole page.
        # He is in the squad list because Transfermarkt registered him; we cannot open a
        # profile we do not have, so say which and why rather than navigate or crash.
        if pd.isna(picked.get("player_id")):
            st.info(
                f"**{picked['Player']}** is in {picked['Club']}'s squad, but the platform "
                "holds no performance record for him — he has not played in one of our "
                "seven leagues. His contract and loan details above are everything we "
                "have. There is no profile to open.")
        else:
            # Pick a league-season he actually HAS a rating in, rather than pairing this
            # season's league with last season's id -- see best_profile_target.
            target = best_profile_target(player_rated_rows(int(picked["player_id"])))
            if target is None:
                st.info(
                    f"**{picked['Player']}** has no rating in any season yet — he has not "
                    "played 450 minutes in one of our seven leagues. His squad, contract and "
                    "loan details above are everything we hold.")
            else:
                go_to_player(int(picked["player_id"]), target[0], target[1])

    d1, d2 = st.columns([1, 4])
    d1.download_button(
        "⬇ Download (CSV)", data=for_export(table).to_csv(index=False).encode("utf-8"),
        file_name=f"lofc_squads_{(club if club != 'All' else league).lower().replace(' ', '_')}.csv",
        mime="text/csv", width="stretch",
        help="Exactly the rows and columns shown above, after the filters.")

    st.caption("Blank means unknown, not zero. Loans are read per club, so a player "
               "loaned out beyond our seven leagues will not appear.")
