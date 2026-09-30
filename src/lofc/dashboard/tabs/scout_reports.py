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
import html as _html

import pandas as pd
import streamlit as st

from lofc.dashboard import theme
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

DISPLAY_COLUMNS = ["Watched", "Player", "Club", "Fixture", "Position", "Scout", "Seen",
                   "Grade", "Verdict", "Rating", MODEL_VIEW]


# --- pure logic ---------------------------------------------------------------------------

def filter_reports(frame: pd.DataFrame, scout: str | None = None,
                   verdict: str | None = None, grade: str | None = None,
                   club: str | None = None, observation: str | None = None,
                   position: str | None = None, search: str | None = None,
                   in_our_data: str | None = None) -> pd.DataFrame:
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
    if search and "player_name" in out.columns:
        # Substring, case-insensitive: a recruiter looking for "bangura" should not have
        # to reproduce "Ra'ess Bangura-Williams" -- including its typo, which the live
        # sheet actually carries.
        out = out[out["player_name"].str.contains(search.strip(), case=False, na=False,
                                                  regex=False)]
    if in_our_data == "In our data":
        out = out[out["player_id"].notna()]
    elif in_our_data == "Not in our data":
        out = out[out["player_id"].isna()]
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


# --- the report card ----------------------------------------------------------------------

VERDICT_TONES = {"Sign": "positive", "Don't sign": "negative"}
# Sign green, Monitor amber, Don't sign red. The rejection red is DEEPER than Leyton
# Orient's #C8102E, which is used across the platform for emphasis and for the club itself
# -- a rejection has to read as a judgement, not as branding.
TONE_COLOURS = {
    "positive": ("#1B7A4B", "#E6F2EB"),
    "negative": ("#A8201A", "#FBEAE9"),
    "neutral": ("#8A6410", "#FBF2DF"),
}

# Decisiveness, not frequency: the two verdicts where a scout COMMITTED sit at the ends,
# the two non-commitments between them. Ordering by count would make a player's summary
# reshuffle itself every time a report arrived, and would read as ranking the verdicts.
VERDICT_ORDER = ("Sign", "Monitor Priority", "Monitor", "Don't sign")


def verdict_tone(verdict) -> str:
    """positive / negative / neutral for one verdict.

    Anything unrecognised is neutral rather than an error: the form's dropdown can gain an
    option at any time without telling us, and a new verdict must not break the page.
    """
    if verdict is None or (isinstance(verdict, float) and pd.isna(verdict)):
        return "neutral"
    return VERDICT_TONES.get(str(verdict).strip(), "neutral")


def verdict_counts(verdicts) -> list[tuple[str, int]]:
    """What the scouts concluded about one player, counted, most decisive first.

    The profile previously printed the DISTINCT verdicts -- so three Signs against one
    Don't sign read exactly like one against one, and the split was invisible. Counting is
    not picking a winner; it is showing the reader the evidence.

    An unrecognised verdict is kept and placed last. The form's dropdown can gain an option
    without telling us, and dropping it would make a report vanish from its own player's
    summary.
    """
    if verdicts is None:
        return []
    counts: dict[str, int] = {}
    for v in verdicts:
        if v is None or (isinstance(v, float) and pd.isna(v)):
            continue
        text = str(v).strip()
        if text:
            counts[text] = counts.get(text, 0) + 1
    known = [(v, counts[v]) for v in VERDICT_ORDER if v in counts]
    other = [(v, n) for v, n in counts.items() if v not in VERDICT_ORDER]
    return known + other


def fixture_label(home, away, when) -> str:
    """"Gillingham v Millwall · 21 Jul 2026" -- the match, not a bare date.

    The first version showed only a date under a column headed "Fixture", which is what
    prompted "what does the fixture column represent?". A fixture is two teams and a day.
    """
    parts = []
    if pd.notna(home) and pd.notna(away) and str(home).strip() and str(away).strip():
        parts.append(f"{home} v {away}")
    stamp = pd.to_datetime(when, errors="coerce")
    if pd.notna(stamp):
        parts.append(stamp.strftime("%d %b %Y"))
    return " · ".join(parts)


def _esc(value) -> str:
    """Escape one value for markup. Every interpolated field goes through this."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return _html.escape(str(value), quote=True)


def _pill(text: str, tone: str) -> str:
    fg, bg = TONE_COLOURS.get(tone, TONE_COLOURS["neutral"])
    return (f'<span class="lofc-sr-pill" style="color:{fg};background:{bg};">'
            f"{_esc(text)}</span>")


def report_card_html(row: pd.Series) -> str:
    """One scout report as a readable card.

    Replaces `st.text_area(disabled=True)`, which Streamlit renders as grey text on a grey
    field -- a disabled input says "you may not edit this" when the intent is "this is the
    thing worth reading". The scout's prose is the most valuable content on the page and
    was styled as the least.

    EVERY interpolated value is escaped. 437 free-text fields written by six people pass
    through here; raw interpolation would be the injection hole the 2026-08-25 sweep closed
    elsewhere. Newlines become <br> AFTER escaping, so the scout's paragraphing survives
    without the text being trusted.
    """
    tone = verdict_tone(row.get("verdict"))
    accent = TONE_COLOURS[tone][0]
    fixture = fixture_label(row.get("home_team"), row.get("away_team"),
                            row.get("fixture_date"))

    played = row.get("positions_played")
    played = ", ".join(played) if isinstance(played, list) else ""
    wanted = row.get("recommended_positions")
    wanted = ", ".join(wanted) if isinstance(wanted, list) else ""

    meta = " · ".join(_esc(b) for b in [
        row.get("scout"), row.get("observation"),
        f"Grade {row.get('grade')}" if pd.notna(row.get("grade")) else None] if b)

    facts = []
    if fixture:
        facts.append(("Fixture", fixture))
    if played:
        facts.append(("Played", played))
    if wanted:
        facts.append(("Recommended", wanted))
    if pd.notna(row.get("squad_role")):
        facts.append(("Squad role", row.get("squad_role")))
    fact_html = "".join(
        f'<div class="lofc-sr-fact"><span class="lofc-sr-k">{_esc(k)}</span>'
        f'<span class="lofc-sr-v">{_esc(v)}</span></div>' for k, v in facts)

    body = _esc(row.get("comments")).replace("\n", "<br>")
    body_html = (f'<div class="lofc-sr-body">{body}</div>' if body else
                 '<div class="lofc-sr-body lofc-sr-empty">No written report.</div>')

    return f"""
    <div class="lofc-sr-card {tone}" style="border-left-color:{accent};">
      <div class="lofc-sr-head">
        <div class="lofc-sr-name">{_esc(row.get('player_name'))}</div>
        <div class="lofc-sr-club">{_esc(row.get('club_name'))}</div>
      </div>
      <div class="lofc-sr-meta">{meta}{_pill(row.get('verdict') or '—', tone)}</div>
      <div class="lofc-sr-facts">{fact_html}</div>
      {body_html}
    </div>
    """


def verdict_chips_html(verdicts) -> str:
    """The verdict summary for one player: a counted, coloured chip per verdict.

    Replaces `"Scouts did not agree: Sign · Don't sign"`, which listed distinct verdicts and
    therefore hid every split's size.
    """
    chips = verdict_counts(verdicts)
    if not chips:
        return ""
    out = []
    for verdict, count in chips:
        fg, bg = TONE_COLOURS.get(verdict_tone(verdict), TONE_COLOURS["neutral"])
        out.append(
            f'<span class="lofc-vchip" style="color:{fg};background:{bg};'
            f'border-color:{fg}33;"><b>{count}</b>{_esc(verdict)}</span>')
    return f'<div class="lofc-vchips">{"".join(out)}</div>'


def inject_chip_style() -> None:
    """Chip CSS. Colours are stated explicitly, matching `dashboard/theme.py`'s committed
    light chrome -- inheriting whatever the host set is how the grey-on-grey report box
    happened."""
    st.markdown(
        """
        <style>
          .lofc-vchips {
            display:flex; flex-wrap:wrap; gap:.4rem; margin:.1rem 0 .9rem;
          }
          .lofc-vchip {
            display:inline-flex; align-items:baseline; gap:.34rem;
            padding:.18rem .6rem .22rem; border-radius:3px; border:1px solid;
            font-size:.72rem; font-weight:600; letter-spacing:.05em;
            text-transform:uppercase; white-space:nowrap;
          }
          .lofc-vchip b { font-size:.95rem; font-weight:700; letter-spacing:0; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def inject_card_style() -> None:
    """Card CSS. Matches the platform's existing light chrome and Leyton Orient red.

    Colours are stated explicitly rather than inherited: the platform commits to one
    visual world (see `dashboard/theme.py`), and a card that borrowed whatever the host
    happened to set is how the grey-on-grey problem arose in the first place.
    """
    st.markdown(
        f"""
        <style>
          .lofc-sr-card {{
            background: #FFFFFF; border: 1px solid #E8E4E4; border-left-width: 4px;
            border-radius: 4px; padding: 1.05rem 1.25rem 1.15rem; margin: .35rem 0 1rem;
            box-shadow: 0 1px 2px rgba(26,26,26,.04);
          }}
          .lofc-sr-head {{
            display: flex; align-items: baseline; gap: .6rem; flex-wrap: wrap;
            margin-bottom: .15rem;
          }}
          .lofc-sr-name {{
            font-size: 1.18rem; font-weight: 700; color: {theme.DARK}; line-height: 1.2;
          }}
          .lofc-sr-club {{ font-size: .92rem; color: #6b6b6b; }}
          .lofc-sr-meta {{
            display: flex; align-items: center; gap: .55rem; flex-wrap: wrap;
            font-size: .78rem; color: #6b6b6b; letter-spacing: .02em;
            margin-bottom: .85rem;
          }}
          .lofc-sr-pill {{
            display: inline-block; padding: .1rem .55rem; border-radius: 3px;
            font-size: .68rem; font-weight: 700; letter-spacing: .07em;
            text-transform: uppercase;
          }}
          .lofc-sr-facts {{
            display: flex; flex-wrap: wrap; gap: .15rem 2rem;
            padding-bottom: .8rem; margin-bottom: .85rem;
            border-bottom: 1px solid #F0ECEC;
          }}
          .lofc-sr-fact {{ display: flex; flex-direction: column; min-width: 7rem; }}
          .lofc-sr-k {{
            font-size: .64rem; text-transform: uppercase; letter-spacing: .09em;
            color: #9a9a9a; font-weight: 600;
          }}
          .lofc-sr-v {{ font-size: .86rem; color: {theme.DARK}; }}
          /* The scout's own words: the most valuable content on the page, so it gets the
             most readable setting -- full-contrast ink, generous line height, a measure
             that does not run the full 1400px page width. */
          .lofc-sr-body {{
            font-size: .95rem; line-height: 1.62; color: #22201F; max-width: 74ch;
          }}
          .lofc-sr-empty {{ color: #9a9a9a; font-style: italic; }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def scout_consensus(verdicts) -> str | None:
    """What the scouts collectively said about one player, or None if nobody has watched him.

    Asked for directly by the Head of Recruitment: if every scout who watched a player said
    Sign, the Players page should say so.

    "Scouts split" covers BOTH a Sign against a Don't sign and a Sign against a Monitor --
    one scout committed and the others did not, which is not a consensus to sign. That
    disagreement is the signal; averaging it away would hide the one thing worth discussing.

    Blank when there are no reports. 244 of 6,170 players carry one, so blank is the normal
    state and must never read as a judgement.
    """
    if not verdicts:
        return None
    seen = {str(v).strip() for v in verdicts
            if v is not None and not (isinstance(v, float) and pd.isna(v)) and str(v).strip()}
    if not seen:
        return None
    if seen == {"Sign"}:
        return "High priority"
    if "Sign" in seen:
        return "Scouts split"
    if seen == {"Don't sign"}:
        return "Not recommended"
    if "Don't sign" in seen:
        return "Scouts split"
    return "Monitor"


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
               r.name_from_report,
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


@st.cache_data(ttl=60)
def consensus_by_player() -> pd.DataFrame:
    """player_id -> what the scouts collectively said, for the Players page.

    Asked for directly by the Head of Recruitment. Only players with at least one linked
    report appear -- 244 of 6,170 -- so the column is blank for almost everyone, which is
    the honest state: blank means nobody has watched him, never a poor verdict.

    Aggregation only. Nothing here reaches `objective_composite`, which is a percentile
    against league peers -- so the composite reformulation due next week cannot break it,
    and this cannot move the ranking.
    """
    rows = pd.read_sql(
        "SELECT player_id, verdict FROM scout_reports "
        "WHERE player_id IS NOT NULL AND missing_since IS NULL", get_engine())
    if rows.empty:
        return pd.DataFrame(columns=["player_id", "Scouts", "scout_reports"])
    grouped = rows.groupby("player_id")["verdict"]
    out = pd.DataFrame({
        "player_id": grouped.apply(lambda v: v.name).index,
    }).set_index("player_id")
    out["Scouts"] = grouped.apply(lambda v: scout_consensus(list(v)))
    out["scout_reports"] = grouped.size()
    return out.reset_index()


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
    """The display columns, in the order a recruiter reads them.

    "Fixture" names the MATCH. It previously held only a date under that heading, which is
    what prompted "what does the fixture column represent?" -- the label promised a fixture
    and delivered a timestamp.
    """
    out = pd.DataFrame(index=frame.index)
    out["Watched"] = pd.to_datetime(frame["fixture_date"], errors="coerce").dt.date
    # A name read out of the report text is marked, because it is evidence of who was
    # watched rather than a confirmed identity -- the scout could not find him in the
    # form's dropdown and typed the name into his report instead.
    flags = (frame["name_from_report"] if "name_from_report" in frame.columns
             else pd.Series(False, index=frame.index))
    out["Player"] = [f"{n} \u2020" if bool(f) else n
                     for n, f in zip(frame["player_name"], flags.fillna(False))]
    out["Fixture"] = [
        f"{h} v {a}" if pd.notna(h) and pd.notna(a) else ""
        for h, a in zip(frame["home_team"], frame["away_team"])]
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
    left, right = st.columns([5, 1])
    with left:
        (st.warning if "not updating" in status or "Never" in status else st.caption)(
            status)
    with right:
        # The sync runs on its own every 60 seconds. This is for the moment somebody has
        # just filed a report and wants it now -- it clears the cached reads so the next
        # render goes back to Postgres, which the background sync keeps current.
        if st.button("Refresh", key="scout_refresh", width="stretch"):
            reports_frame.clear()
            last_sync.clear()
            consensus_by_player.clear()
            st.rerun()

    frame = model_view(frame)
    names = competition_name_by_id()

    linked = int(frame["player_id"].notna().sum())
    disagree = int((frame[MODEL_VIEW] == "Model disagrees").sum())

    browse, disagreements, scouts = st.tabs(
        [f"All reports ({len(frame):,})", f"Where we disagree ({disagree})",
         "Scout activity"])

    with browse:
        search = st.text_input("Search for a player", placeholder="Start typing a name…",
                               key="scout_search")
        c1, c2, c3, c4, c5, c6, c7 = st.columns(7)
        scout = c1.selectbox("Scout", _options(frame, "scout"))
        verdict = c2.selectbox("Verdict", _options(frame, "verdict"))
        grade = c3.selectbox("Grade", _options(frame, "grade"))
        position = c4.selectbox("Position", _position_options(frame))
        club = c5.selectbox("Club", _options(frame, "club_name"))
        observation = c6.selectbox("Seen", _options(frame, "observation"))
        # 129 reports are on players outside the seven leagues we hold data for. Both
        # halves are worth isolating: "only players I can compare to the model", and
        # "only players the model has never seen", which is the discovery list.
        in_our_data = c7.selectbox("Our data", ["All", "In our data", "Not in our data"])
        view = filter_reports(frame, scout=scout, verdict=verdict, grade=grade,
                              club=club, observation=observation, position=position,
                              search=search, in_our_data=in_our_data)
        st.caption(f"{len(view):,} of {len(frame):,} reports · "
                   f"{frame['player_name'].nunique():,} players · "
                   f"{frame['scout'].nunique()} scouts · {linked:,} matched to our data")
        _report_table(view, names, rating_label, key="scout_all")

    with disagreements:
        # The reason the page exists. Agreement is reassuring and carries almost no
        # information; these are the players where a recruiter's judgement is needed.
        view = frame[frame[MODEL_VIEW] == "Model disagrees"]
        st.caption(f"{len(view)} reports where the scout's verdict and the "
                   f"{rating_label} rating point opposite ways.")
        _report_table(view.sort_values("composite"), names, rating_label,
                      key="scout_disagree")

    with scouts:
        st.dataframe(scout_activity(frame), hide_index=True, width="stretch",
                     height=320, key="scout_activity")


def _report_table(view: pd.DataFrame, names: dict, rating_label: str, key: str) -> None:
    """The reports table, with the full comment shown for whichever row is selected."""
    if view.empty:
        st.info("No reports match these filters.")
        return

    table = _table(view, names).reset_index(drop=True)
    selection = st.dataframe(
        table, hide_index=True, width="stretch", height=680,
        on_select="rerun", selection_mode="single-row", key=key,
        column_config={
            "Rating": st.column_config.NumberColumn(
                f"Rating ({rating_label})", format="%.2f", width="small",
                help="The platform's 1-5 composite from the last complete season. Blank "
                     "means the player is outside the seven leagues we hold data for — "
                     "not that he rated poorly."),
            "Date": st.column_config.DateColumn("Fixture", format="DD MMM YY",
                                                width="small"),
            "Player": st.column_config.TextColumn(
                "Player", help="\u2020 = name read from the report text."),
            MODEL_VIEW: st.column_config.TextColumn(
                MODEL_VIEW, help="Whether the composite points the same way as the "
                                 "scout's verdict. Only 'Sign' and \"Don't sign\" are "
                                 "compared — 'Monitor' is the scout declining to commit."),
        })

    rows = selection.get("selection", {}).get("rows", []) if selection else []
    if rows:
        _report_detail(view.iloc[rows[0]])


def _report_detail(row: pd.Series) -> None:
    """One report in full, as a card, with a way into the player's profile.

    The card replaces `st.text_area(disabled=True)`: Streamlit renders a disabled input as
    grey text on a grey field, which made the scout's own words the least readable thing on
    the page when they are the most valuable.
    """
    inject_card_style()
    st.markdown(report_card_html(row), unsafe_allow_html=True)

    if pd.isna(row.get("player_id")):
        st.caption("This player is not in the platform's data — no rating, percentile or "
                   "peer comparison exists for him. The report above is the whole record.")
        return

    # Which league-season to open him in is NOT obvious, and getting it wrong renders a
    # blank page -- it hit 35% of squad rows before `best_profile_target` existed. Reused
    # rather than reinvented: his most recent season WITH a rating, and within it the
    # league he played the most minutes in.
    from lofc.dashboard.tabs.squads import best_profile_target, player_rated_rows

    target = best_profile_target(player_rated_rows(int(row["player_id"])))
    if not target:
        st.caption("Matched to our data, but he has no rated season yet — nothing to open.")
        return
    if st.button(f"Open {row['player_name']} in Players",
                 key=f"open_{row['submission_id']}", type="primary"):
        go_to_player(int(row["player_id"]), target[0], target[1])
