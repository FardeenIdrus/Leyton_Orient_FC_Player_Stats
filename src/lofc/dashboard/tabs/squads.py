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

from lofc.dashboard.loaders import competition_name_by_id, get_engine
from lofc.dashboard.session import go_to_player
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
    """
    return pd.read_sql(
        """
        WITH rated AS (
            SELECT s.player_id, s.objective_composite, s.competition_id,
                   ROW_NUMBER() OVER (PARTITION BY s.player_id
                                      ORDER BY m.minutes DESC NULLS LAST) AS rn
            FROM player_scorecards s
            JOIN player_metrics_neutral m
              ON m.player_id = s.player_id AND m.competition_id = s.competition_id
             AND m.season_id = s.season_id
            WHERE s.season_id = %(prev)s AND s.archetype = 'All Metrics'
              AND s.objective_composite IS NOT NULL
        )
        SELECT l.competition_id, l.club_name AS team_name, l.player_id, l.player_name,
               l.parent_club, l.loan_ends,
               n.position_group, n.minutes,
               p.contract_until, p.foot, p.nationality, p.birth_date, p.height_cm,
               b.objective_composite  AS last_season_rating,
               b.competition_id       AS rating_competition_id,
               sc.objective_composite AS alt_rating,
               sc.competition_id      AS alt_competition_id
        FROM player_loans l
        LEFT JOIN players p ON p.player_id = l.player_id
        LEFT JOIN player_metrics_neutral n
               ON n.player_id = l.player_id AND n.season_id = %(cur)s
              AND n.competition_id = l.competition_id
        LEFT JOIN rated b  ON b.player_id  = l.player_id AND b.rn = 1
        -- The SECOND reading, same as the squad view. This was hardcoded NULL, so a
        -- loanee -- exactly the cohort most likely to have played in two leagues -- showed
        -- a blank "Also rated" while the platform held the number. Yusuf Akhamrich read
        -- 3.42 with nothing beside it, when 4.00 in PL2 was known.
        LEFT JOIN rated sc ON sc.player_id = l.player_id AND sc.rn = 2
        WHERE l.season_id = %(cur)s
        ORDER BY l.club_name, l.loan_ends NULLS LAST, l.player_name
        """,
        get_engine(), params={"cur": season_id, "prev": rating_season_id})


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
            "date_of_birth", "contract_until", "height_cm", "foot"]
    d = frame[[c for c in keep if c in frame.columns]].copy()
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
    # Likewise one loan row per player.
    loans = pd.read_sql(
        "SELECT DISTINCT ON (player_id) player_id, parent_club, loan_ends "
        "FROM player_loans WHERE season_id = %(s)s AND player_id IS NOT NULL "
        "ORDER BY player_id, loan_ends DESC NULLS LAST",
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
    out = out.merge(loans, on="player_id", how="left")
    out["team_name"] = out["club_name"]
    # Last known position, marked, where he has not featured yet this season.
    out["position_group"] = out["position_group"].fillna(
        out["last_position"].map(lambda v: f"{v} (last season)" if pd.notna(v) else None))
    return out


def months_left(when, today: datetime.date | None = None) -> float | None:
    """Whole months from today to a contract expiry. Negative means already expired."""
    if when is None or pd.isna(when):
        return None
    today = today or datetime.date.today()
    end = pd.Timestamp(when).date()
    return (end.year - today.year) * 12 + (end.month - today.month)


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
    return out.rename(columns={
        "team_name": "Club", "player_name": "Player", "position_group": "Position",
        "minutes": "Minutes", "foot": "Foot", "nationality": "Nationality",
        "last_season_rating": "Last season"})


DISPLAY_COLUMNS = ["Club", "Player", "Position", "Age", "Minutes", "Last season",
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


def render(season_id: int, rating_season_id: int, season_label: str,
           rating_label: str) -> None:
    st.subheader("Squads, contracts and loans")
    st.caption(f"Every registered squad member, {season_label}. Click a row to open the "
               f"player. Ratings are {rating_label} — this season is not scored yet.")

    frame = prepare(registered_squad_frame(season_id, rating_season_id))
    # Before anything else on the page: is this the real squad list, or the appearance-based
    # fallback? `scraped_squads()` is @st.cache_data, so this second call is free.
    warning = squad_source_warning(len(scraped_squads()), len(frame))
    if warning:
        st.error(warning)
    if frame.empty:
        st.info("No squad data for this season yet.")
        return

    names = competition_name_by_id()
    c1, c2, c3 = st.columns([2, 2, 3])
    league = c1.selectbox("League", ["All"] + sorted(frame["League"].unique()))
    view = frame if league == "All" else frame[frame["League"] == league]
    club = c2.selectbox("Club", ["All"] + sorted(view["Club"].dropna().unique()))
    if club != "All":
        view = view[view["Club"] == club]
    show = c3.radio("Show", ["Everyone", "On loan only", "Contract expiring (under 12 months)"],
                    horizontal=True, label_visibility="visible")

    if show == "On loan only":
        # From player_loans, NOT from the squad frame: 135 of 290 linked loanees have not
        # appeared in league data yet and are absent from the squad frame entirely.
        loans = prepare(loans_frame(season_id, rating_season_id))
        if not loans.empty:
            loans["League"] = loans["competition_id"].map(names).fillna("\u2014")
            if league != "All":
                loans = loans[loans["League"] == league]
            if club != "All":
                loans = loans[loans["Club"] == club]
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

    table = view[DISPLAY_COLUMNS].reset_index(drop=True)
    selection = st.dataframe(
        table, hide_index=True, width="stretch", height=560,
        on_select="rerun", selection_mode="single-row", key="squads_table",
        column_config={
            "Age": st.column_config.NumberColumn("Age", format="%.1f", width="small"),
            "Position": st.column_config.TextColumn(
                "Position", help="Where he has played THIS season. Marked '(last season)' "
                                 "where he has not featured yet."),
            "Minutes": st.column_config.NumberColumn(
                "Minutes", format="%d", width="small",
                help="This season, in our seven leagues only."),
            "Minutes": st.column_config.NumberColumn("Minutes", format="%d", width="small"),
            "Last season": st.column_config.NumberColumn(
                f"{rating_label} rating", format="%.2f", width="small",
                help="The club composite from the last complete season. This season is "
                     "not scored yet."),
            "Also rated": st.column_config.NumberColumn(
                "Also rated", format="%.2f", width="small",
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
            go_to_player(int(picked["player_id"]), int(picked["competition_id"]),
                         int(rating_season_id))

    d1, d2 = st.columns([1, 4])
    d1.download_button(
        "⬇ Download (CSV)", data=for_export(table).to_csv(index=False).encode("utf-8"),
        file_name=f"lofc_squads_{(club if club != 'All' else league).lower().replace(' ', '_')}.csv",
        mime="text/csv", width="stretch",
        help="Exactly the rows and columns shown above, after the filters.")

    st.caption("Blank means unknown, not zero. Loans are read per club, so a player "
               "loaned out beyond our seven leagues will not appear.")
