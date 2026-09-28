"""Scout reports: what the club's scouts actually watched, beside what the model says.

WHY THIS PAGE EXISTS. The platform ranks 3,229 players nobody at the club has necessarily
seen. The scouts have written 437 reports on 350 players. Neither list helps the other at
those sizes -- but they OVERLAP on 289 reports covering 244 players, and that is a list a
Head of Recruitment can read in an afternoon.

The page leads with DISAGREEMENT, because agreement carries almost no information. Of the
54 reports saying "Sign", 22 are on players the platform can score: 6 the model also rates
highly, 10 it rates below the 3.03 average. Those ten are where a recruiter's judgement is
actually needed, and until now nothing surfaced them.

READ-ONLY, ALL THE WAY DOWN. The reports come from the club's Google Sheet via a
service-account token holding only `spreadsheets.readonly`; a write returns HTTP 403 from
Google. Nothing on this page can alter the scouts' spreadsheet.

NOTHING HERE TOUCHES A SCORE. `objective_composite` is a season-level percentile against
league peers and is unchanged by any of this -- the same wall that already separates scout
assessments from the ranking.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd
import streamlit as st

from lofc.dashboard.loaders import competition_name_by_id, get_engine
from lofc.dashboard.session import go_to_player

# The column the comparison writes. Named once so the page and its tests cannot drift.
MODEL_VIEW = "Model view"

# A verdict only counts as a position the model can be compared against if the scout
# actually committed. "Monitor" and "Monitor Priority" are deliberate non-commitments.
POSITIVE_VERDICTS = ("Sign",)
NEGATIVE_VERDICTS = ("Don't sign",)
# The league-position mean composite is ~3.03 BY CONSTRUCTION (percentiles within a pool),
# so 3.0 is the natural "about average" line and 3.5 a clear positive.
STRONG = 3.5
WEAK = 3.0
# Older than this and the sync is reported as broken rather than merely timestamped --
# register P14, where a failed job served week-old numbers looking entirely normal.
STALE_AFTER = dt.timedelta(hours=6)

DISPLAY_COLUMNS = ["Date", "Player", "Club", "Position", "Scout", "Seen", "Grade",
                   "Verdict", "Rating", MODEL_VIEW]


# --- pure logic ---------------------------------------------------------------------------

def filter_reports(frame: pd.DataFrame, scout: str | None = None,
                   verdict: str | None = None, grade: str | None = None,
                   club: str | None = None, observation: str | None = None,
                   position: str | None = None) -> pd.DataFrame:
    """Reports matching every filter given. "All" and None mean no filter.

    Position matches ANY of a multi-value report: 43 of the 437 carry more than one, and a
    right back who also filled in at wing back has to appear under both or a search for
    wing backs silently misses him.
    """
    out = frame
    for column, value in (("scout", scout), ("verdict", verdict), ("grade", grade),
                          ("club_name", club), ("observation", observation)):
        if value and value != "All" and column in out.columns:
            out = out[out[column] == value]
    if position and position != "All" and "positions_played" in out.columns:
        out = out[out["positions_played"].map(
            lambda v: position in v if isinstance(v, list) else False)]
    return out


def model_view(frame: pd.DataFrame) -> pd.DataFrame:
    """`frame` plus a column saying whether the model and the scout agree.

    Four states, and three of them are deliberately NOT a verdict on the player:

      Model agrees          scout committed, and the composite points the same way
      Model disagrees       scout committed, and the composite points the other way
      Not in our data       no composite. 129 reports are on players outside the seven
                            leagues we hold data for -- academy and non-league players
                            scouts are SENT to watch. Not a low rating; not a gap.
      No verdict to compare "Monitor" is the scout declining to commit. Grading it
                            against the model would invent a position he did not take.

    Disagreement runs both ways: a player the model likes and a scout rejected is as
    worth discussing as the reverse.
    """
    out = frame.copy()
    if out.empty:
        out[MODEL_VIEW] = pd.Series(dtype=object)
        return out

    def one(verdict, composite):
        if composite is None or pd.isna(composite):
            return "Not in our data"
        if verdict in POSITIVE_VERDICTS:
            return "Model agrees" if composite >= STRONG else (
                "Model disagrees" if composite < WEAK else "Model is lukewarm")
        if verdict in NEGATIVE_VERDICTS:
            return "Model disagrees" if composite >= STRONG else (
                "Model agrees" if composite < WEAK else "Model is lukewarm")
        return "No verdict to compare"

    out[MODEL_VIEW] = [one(v, c) for v, c in zip(out["verdict"], out["composite"])]
    return out


def scout_activity(frame: pd.DataFrame) -> pd.DataFrame:
    """Per scout: how many reports, the live/video split, and how many said Sign.

    The live/video split is a real management fact, not decoration -- live viewing costs
    a journey and a ticket, video does not, and the club's own sheet tracks the two
    separately. Ordered by volume, so who is doing the most viewing reads first.
    """
    if frame.empty or "scout" not in frame.columns:
        return pd.DataFrame(columns=["Scout", "Reports", "Live", "Video", "Sign", "Players"])
    rows = []
    for scout, group in frame.groupby("scout"):
        rows.append({
            "Scout": scout,
            "Reports": len(group),
            "Live": int((group["observation"] == "Live").sum()),
            "Video": int((group["observation"] == "Video").sum()),
            "Sign": int(group["verdict"].isin(POSITIVE_VERDICTS).sum()),
            "Players": int(group["player_name"].nunique()),
        })
    return (pd.DataFrame(rows).sort_values("Reports", ascending=False)
            .reset_index(drop=True))


def sync_status(synced_at, now: dt.datetime | None = None) -> str:
    """How fresh the scouting data is, in words a reader does not have to evaluate.

    Register P14 exists because nothing on this platform says when its data was last
    refreshed, and a failed job serves last week's numbers looking entirely normal -- it
    has already happened once. A timestamp alone would repeat that mistake: it asks the
    reader to work out whether 9 hours is fine. Past `STALE_AFTER` this says so outright.
    """
    if synced_at is None or (not isinstance(synced_at, dt.datetime) and pd.isna(synced_at)):
        return "Never synced — the scouting sheet has not been read yet."
    now = now or dt.datetime.now()
    stamp = pd.Timestamp(synced_at).to_pydatetime()
    gap = now - stamp

    if gap < dt.timedelta(minutes=1):
        label = "just now"
    elif gap < dt.timedelta(hours=1):
        minutes = int(gap.total_seconds() // 60)
        label = f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    elif gap < dt.timedelta(days=1):
        hours = int(gap.total_seconds() // 3600)
        label = f"{hours} hour{'s' if hours != 1 else ''} ago"
    else:
        days = gap.days
        label = f"{days} day{'s' if days != 1 else ''} ago"

    if gap > STALE_AFTER:
        return (f"Last synced {label} — the sync is not updating. "
                f"These reports may be out of date.")
    return f"Synced {label}"


# --- reads -------------------------------------------------------------------------------

@st.cache_data(ttl=60)
def reports_frame(rating_season_id: int) -> pd.DataFrame:
    """Every stored report, with the linked player's last complete-season composite.

    The composite is joined LEFT and from the previous complete season: this season is
    not scored until players pass 450 minutes. The column heading says which season it
    is, because a rating shown without that is a different claim from the one the data
    supports.
    """
    return pd.read_sql(
        """
        WITH rated AS (
            SELECT DISTINCT ON (s.player_id) s.player_id, s.objective_composite,
                   s.competition_id
            FROM player_scorecards s
            JOIN player_metrics_neutral m ON m.player_id = s.player_id
             AND m.competition_id = s.competition_id AND m.season_id = s.season_id
            WHERE s.season_id = %(prev)s AND s.archetype = 'All Metrics'
              AND s.objective_composite IS NOT NULL
            ORDER BY s.player_id, m.minutes DESC NULLS LAST
        )
        SELECT r.submission_id, r.scout, r.observation, r.player_name, r.club_name,
               r.foot, r.home_team, r.away_team, r.fixture_date, r.comments,
               r.positions_played, r.recommended_positions, r.grade, r.squad_role,
               r.verdict, r.player_id, r.linkable, r.missing_since,
               b.objective_composite AS composite,
               b.competition_id      AS rated_in
        FROM scout_reports r
        LEFT JOIN rated b ON b.player_id = r.player_id
        WHERE r.missing_since IS NULL
        ORDER BY r.fixture_date DESC NULLS LAST, r.player_name
        """,
        get_engine(), params={"prev": rating_season_id})


@st.cache_data(ttl=60)
def last_sync() -> pd.Series | None:
    """The most recent sync record, or None if the sheet has never been read."""
    frame = pd.read_sql(
        "SELECT digest, synced_at, reports_seen, reports_written, changed "
        "FROM scout_sync ORDER BY id DESC LIMIT 1", get_engine())
    return None if frame.empty else frame.iloc[0]


def reports_for_player(engine, player_id: int) -> pd.DataFrame:
    """Every report on one player, newest first. Used by the player profile."""
    return pd.read_sql(
        "SELECT scout, observation, fixture_date, home_team, away_team, "
        "       positions_played, recommended_positions, grade, squad_role, verdict, "
        "       comments FROM scout_reports "
        "WHERE player_id = %(p)s AND missing_since IS NULL "
        "ORDER BY fixture_date DESC NULLS LAST",
        engine, params={"p": int(player_id)})


# --- presentation --------------------------------------------------------------------------

def _table(frame: pd.DataFrame, names: dict) -> pd.DataFrame:
    """The display columns, in the order a recruiter reads them."""
    out = pd.DataFrame(index=frame.index)
    out["Date"] = pd.to_datetime(frame["fixture_date"], errors="coerce").dt.date
    out["Player"] = frame["player_name"]
    out["Club"] = frame["club_name"]
    out["Position"] = frame["positions_played"].map(
        lambda v: ", ".join(v) if isinstance(v, list) and v else "")
    out["Scout"] = frame["scout"]
    out["Seen"] = frame["observation"]
    out["Grade"] = frame["grade"]
    out["Verdict"] = frame["verdict"]
    out["Rating"] = frame["composite"]
    out[MODEL_VIEW] = frame[MODEL_VIEW]
    return out


def _options(frame: pd.DataFrame, column: str) -> list[str]:
    if frame.empty or column not in frame.columns:
        return ["All"]
    return ["All"] + sorted({str(v) for v in frame[column].dropna() if str(v).strip()})


def _position_options(frame: pd.DataFrame) -> list[str]:
    """Every position code any scout recorded -- their vocabulary, not ours."""
    if frame.empty or "positions_played" not in frame.columns:
        return ["All"]
    codes = {p for v in frame["positions_played"] if isinstance(v, list) for p in v}
    return ["All"] + sorted(codes)


def render(rating_season_id: int, rating_label: str) -> None:
    st.subheader("Scout reports")

    frame = reports_frame(rating_season_id)
    sync = last_sync()

    if frame.empty:
        st.info("No scout reports have been synced yet. Run "
                "`python -m lofc.store.scout_reports`.")
        return

    status = sync_status(sync["synced_at"] if sync is not None else None)
    (st.warning if "not updating" in status or "Never" in status else st.caption)(
        f"{status} · read-only from the club's scouting sheet")

    frame = model_view(frame)
    names = competition_name_by_id()

    linked = int(frame["player_id"].notna().sum())
    disagree = int((frame[MODEL_VIEW] == "Model disagrees").sum())
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Reports", f"{len(frame):,}")
    m2.metric("Players", f"{frame['player_name'].nunique():,}")
    m3.metric("Scouts", f"{frame['scout'].nunique():,}")
    m4.metric("Matched to our data", f"{linked:,}")
    m5.metric("Model disagrees", f"{disagree:,}")

    browse, disagreements, scouts = st.tabs(
        ["All reports", "Where we disagree", "Scout activity"])

    with browse:
        c1, c2, c3, c4, c5, c6 = st.columns(6)
        scout = c1.selectbox("Scout", _options(frame, "scout"))
        verdict = c2.selectbox("Verdict", _options(frame, "verdict"))
        grade = c3.selectbox("Grade", _options(frame, "grade"))
        position = c4.selectbox("Position", _position_options(frame))
        club = c5.selectbox("Club", _options(frame, "club_name"))
        observation = c6.selectbox("Seen", _options(frame, "observation"))
        view = filter_reports(frame, scout=scout, verdict=verdict, grade=grade,
                              club=club, observation=observation, position=position)
        st.caption(f"{len(view):,} of {len(frame):,} reports")
        _report_table(view, names, rating_label, key="scout_all")

    with disagreements:
        # The reason the page exists. Agreement is reassuring and carries almost no
        # information; these are the players where a recruiter's judgement is needed.
        view = frame[frame[MODEL_VIEW] == "Model disagrees"]
        st.markdown(
            f"**{len(view)} reports where the scout committed and the {rating_label} "
            f"rating points the other way.** A scout saw the player; the rating is a "
            f"percentile against his league and position peers. Neither settles it.")
        _report_table(view.sort_values("composite"), names, rating_label,
                      key="scout_disagree")

    with scouts:
        st.dataframe(scout_activity(frame), hide_index=True, width="stretch",
                     key="scout_activity")
        st.caption("Live viewing costs a journey and a ticket; video does not. "
                   "Players counts distinct players, not reports.")


def _report_table(view: pd.DataFrame, names: dict, rating_label: str, key: str) -> None:
    """The reports table, with the full comment shown for whichever row is selected."""
    if view.empty:
        st.info("No reports match these filters.")
        return

    table = _table(view, names).reset_index(drop=True)
    selection = st.dataframe(
        table, hide_index=True, width="stretch", height=430,
        on_select="rerun", selection_mode="single-row", key=key,
        column_config={
            "Rating": st.column_config.NumberColumn(
                f"Rating ({rating_label})", format="%.2f", width="small",
                help="The platform's 1-5 composite from the last complete season. Blank "
                     "means the player is outside the seven leagues we hold data for — "
                     "not that he rated poorly."),
            "Date": st.column_config.DateColumn("Fixture", format="DD MMM YY",
                                                width="small"),
            MODEL_VIEW: st.column_config.TextColumn(
                MODEL_VIEW, help="Whether the composite points the same way as the "
                                 "scout's verdict. Only 'Sign' and \"Don't sign\" are "
                                 "compared — 'Monitor' is the scout declining to commit."),
        })

    rows = selection.get("selection", {}).get("rows", []) if selection else []
    if not rows:
        st.caption("Select a row to read the full report.")
        return
    _report_detail(view.iloc[rows[0]])


def _report_detail(row: pd.Series) -> None:
    """One report in full. The comment is the thing a scout actually wrote; everything
    else on the row is metadata about it."""
    fixture = f"{row['home_team']} v {row['away_team']}" if pd.notna(row["home_team"]) else ""
    date = pd.to_datetime(row["fixture_date"], errors="coerce")
    played = ", ".join(row["positions_played"]) if isinstance(row["positions_played"], list) else ""
    wanted = ", ".join(row["recommended_positions"]) if isinstance(row["recommended_positions"], list) else ""

    st.markdown(f"#### {row['player_name']} — {row['club_name']}")
    bits = [f"**{row['scout']}**", row["observation"],
            date.strftime("%d %b %Y") if pd.notna(date) else None, fixture,
            f"Grade {row['grade']}" if pd.notna(row["grade"]) else None,
            row["verdict"]]
    st.caption(" · ".join(b for b in bits if b))
    if played or wanted:
        st.caption(f"Played {played}" + (f" · recommended {wanted}" if wanted else ""))
    if pd.notna(row["squad_role"]):
        st.caption(f"Squad role: {row['squad_role']}")

    # The scout's own words, rendered as TEXT. st.markdown would let a stray asterisk
    # or bracket in 437 free-text reports change the layout, and would carry an
    # injection risk the platform's 2026-08-25 XSS sweep already closed elsewhere.
    if pd.notna(row["comments"]):
        st.text_area("Report", value=str(row["comments"]), height=180, disabled=True,
                     key=f"comment_{row['submission_id']}", label_visibility="collapsed")

    if pd.notna(row.get("player_id")):
        # Which league-season to open him in is NOT obvious, and getting it wrong renders
        # a blank page -- it hit 35% of squad rows before `best_profile_target` existed.
        # Reused here rather than reinvented: his most recent season WITH a rating, and
        # within it the league he played the most minutes in.
        from lofc.dashboard.tabs.squads import best_profile_target, player_rated_rows

        target = best_profile_target(player_rated_rows(int(row["player_id"])))
        if target and st.button("Open this player's profile",
                                key=f"open_{row['submission_id']}"):
            go_to_player(int(row["player_id"]), target[0], target[1])
        elif not target:
            st.caption("This player is matched to our data but has no rated season yet, "
                       "so there is no profile to open.")
    else:
        st.caption("This player is not in the platform's data — no rating, percentile or "
                   "peer comparison exists for him. The report above is the whole record.")
