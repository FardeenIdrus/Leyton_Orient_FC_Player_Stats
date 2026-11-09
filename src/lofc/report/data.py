"""Assemble everything one player report needs into a single frozen object.

The report is read by people who cannot interrogate it -- the manager and the chairman --
so this module is deliberate about three things:

  * A band is present only when somebody actually decided it. Two unsigned assessments that
    disagree (Decision 17) yield no band, not the newer one.
  * Every percentile carries its comparison set. `comparison_text` names the league, the
    season, the position group and the 450-minute threshold, because a percentile without a
    stated peer group means nothing to a reader who cannot ask.
  * An absent measurement stays None all the way to the template. A player with no recorded
    height is not 0cm, and the renderer -- not this module -- decides how to say so.

PERCENTILE SOURCE. Percentiles come from `scorecard.metric_percentiles`, NOT from the
`player_percentiles` table. That table holds only 22 metrics, a legacy set predating the
Impect migration, and is missing duels, turnovers, pass value and counterpressures -- two of
the five Central Mid categories cannot be computed from it. `metric_percentiles` returns all
91 and is the same function the composite uses, so the report's percentiles and the player's
bands come from one computation and cannot disagree.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field, replace

import pandas as pd
from sqlalchemy import select, text

from lofc.model import scout_scores
from lofc.model.medical import (AVAILABILITY_SEASONS, availability_with_evidence,
                                games_missed_in_window)
from lofc.config import settings
from lofc.dashboard.seasons import age_reference_date
from lofc.model.scorecard import metric_percentiles, rank_in_pool
from lofc.store import assessments as store_assess
from lofc.store import injuries as store_injuries
from lofc.store.models import Player, PlayerMetricNeutral, PlayerScorecard, PlayerPositionShare

STAMP_DATA_ONLY = "Data only"
STAMP_PROVISIONAL = "Provisional"
STAMP_FINAL = "Final"

RANKABLE_MINUTES = 450

# League names and season labels come from the league registry (lofc/leagues.py), so a new
# competition or season needs no edit here.
def league_name(competition_id: int) -> str:
    from lofc.leagues import league_name as _name
    return _name(competition_id)


def season_short(season_id: int) -> str:
    from lofc.leagues import is_season_id, season_label
    return season_label(season_id, short=True) if is_season_id(season_id) else str(season_id)

_N = PlayerMetricNeutral.__table__
_S = PlayerScorecard.__table__
_P = Player.__table__
_PS = PlayerPositionShare.__table__


@dataclass(frozen=True)
class Narrative:
    """The scout's own words. Never generated -- see the design spec, section 4."""

    summary: str | None
    why_sign: str | None
    considerations: str | None
    assessor: str | None
    assessor_role: str | None
    approver: str | None
    approved_at: datetime.datetime | None


@dataclass(frozen=True)
class Authored:
    """A report written by a user (a saved report, or the live draft). When present it
    REPLACES the scout assessment's narrative and Psychological / Medical bands on the page,
    and the stamp and footer name the author. The figures never feed any
    rating -- see store/saved_reports.py."""

    author_name: str
    author_role: str | None
    created_at: datetime.datetime
    summary: str | None
    why_sign: str | None
    considerations: str | None
    psych_band: float | None
    medical_band: float | None
    # Answered screening criteria only: criterion text -> "Meets" / "Does not meet".
    screening: dict[str, str] = field(default_factory=dict)


def authored_from_inputs(*, author_name: str, author_role: str | None,
                         summary: str | None = None, why_sign: str | None = None,
                         considerations: str | None = None,
                         psych_scores: dict | None = None,
                         medical_band: float | None = None,
                         screening: dict | None = None,
                         now: datetime.datetime | None = None) -> Authored | None:
    """The form's inputs as an Authored override, or None when every field is blank (so an
    untouched form gives exactly today's report).

    The Psychological band is the mean of the criteria actually scored -- not
    assessment_rules.psychological_band, which needs every criterion. Here every field is
    optional. Nothing is stored anywhere; this only shapes what is rendered.
    """
    def clean(t):
        t = (t or "").strip()
        return t or None

    scored = [int(v) for v in (psych_scores or {}).values() if v is not None]
    psych = sum(scored) / len(scored) if scored else None
    answered = {k: v for k, v in (screening or {}).items() if v}
    fields = (clean(summary), clean(why_sign), clean(considerations), psych, medical_band,
              answered or None)
    if all(f is None for f in fields):
        return None
    return Authored(author_name=author_name, author_role=author_role,
                    created_at=now or datetime.datetime.now(),
                    summary=fields[0], why_sign=fields[1], considerations=fields[2],
                    psych_band=psych,
                    medical_band=float(medical_band) if medical_band is not None else None,
                    screening=answered)


# Impect counts four things as an assist; Transfermarkt counts only the first. That is why
# a player can read as 5 here and 0 there -- both are correct under their own definition.
# Verified against Impect's own glossary (data/raw/impect/kpi_definitions.json, KPI 77).
ASSIST_DEFINITION = ("Assists follow Impect: the final pass, plus deflections, fouls won "
                     "that lead to a converted penalty or free kick, and forced own goals. "
                     "Transfermarkt counts only the final pass, so its total reads lower.")

# The club itself, for the squad benchmark. Matched on the neutral table's team_name.
CLUB_TEAM_NAME = "Leyton Orient"


@dataclass(frozen=True)
class ReportData:
    """Everything one report needs. Every optional field is None when absent, never a
    placeholder value -- the renderer decides how to present a gap."""

    player_name: str
    position: str
    club: str | None
    league: str
    season_label: str
    age: float | None
    foot: str | None
    height_cm: int | None
    nationality: str | None
    contract_until: str | None
    minutes: float | None
    goals: float | None
    assists: float | None
    composite: float | None
    dimension_bands: dict[str, float | None]
    rank: int | None
    peer_count: int
    percentiles: dict[str, float]
    physical: dict[str, float]
    availability: float | None
    availability_status: str
    matches_missed: int
    injuries: list[dict]
    narrative: Narrative | None
    stamp: str
    snapshot_date: str
    comparison_text: str
    flags: list[str] = field(default_factory=list)
    # Impect's SHOT_ASSISTS: a pass that led to a shot. Shown beside Assists because
    # Impect's "assists" is a four-part definition (see ASSIST_DEFINITION) and a reader
    # comparing it with Transfermarkt needs a second, unambiguous creativity number.
    chances_created: float | None = None
    # (position group, minutes, share, goals, assists) largest first; goals/assists
    # are None where unknown. Empty when not recorded. These NEVER change a score --
    # metrics stay whole-season across every position the player filled.
    position_shares: list[tuple] = field(default_factory=list)
    # Leyton Orient squad MEDIAN percentile per metric, for the same position group.
    # Percentiles are league-relative, so this is the squad's standing in ITS league
    # against the player's standing in HIS -- benchmark_league names which.
    benchmark: dict[str, float] = field(default_factory=dict)
    benchmark_n: int = 0
    benchmark_league: str | None = None
    # Set only for an authored report; None leaves the report exactly as it always was.
    authored: Authored | None = None
    # The player's playing-style row (model/styles.assign_styles): position_group,
    # style_label, strong_styles, leans_styles and fit.<style>. {} when it cannot be
    # computed. Measured data, not opinion, so a data-only report keeps it.
    style: dict = field(default_factory=dict)


def _style_labels(engine, season_id: int) -> pd.DataFrame:
    """Every player's playing-style row for the season, built exactly as the dashboard's
    load_style_labels does (loaders.py) but without Streamlit, which this module must not
    import. Percentiles are over the whole season's pool, so the full frame is needed.
    Empty when the season has no style signals."""
    from lofc.model import styles
    base = pd.read_sql(
        text("SELECT n.player_id, n.competition_id, n.season_id, n.position_group, "
             "n.rankable, n.player_name, n.team_name "
             "FROM player_metrics_neutral n WHERE n.season_id = :s"),
        engine, params={"s": int(season_id)})
    sig = pd.read_sql(text("SELECT player_id, competition_id, signal, value FROM "
                           "player_style_signals WHERE season_id = :s"),
                      engine, params={"s": int(season_id)})
    if base.empty or sig.empty:
        return pd.DataFrame()
    wide = sig.pivot_table(index=["player_id", "competition_id"], columns="signal",
                           values="value").reset_index()
    frame = base.merge(wide, on=["player_id", "competition_id"], how="left")
    if not set(styles.SIGNALS) & set(frame.columns):
        return pd.DataFrame()
    return styles.assign_styles(styles.signal_percentiles(frame))


def _style_row(labels: pd.DataFrame, player_id: int, competition_id: int,
               position: str) -> dict:
    """His row of `_style_labels`, or {}."""
    if labels is None or labels.empty:
        return {}
    mine = labels[(labels.player_id == player_id)
                  & (labels.competition_id == competition_id)
                  & (labels.position_group == position)]
    return mine.iloc[0].to_dict() if not mine.empty else {}


@dataclass(frozen=True)
class SeasonInputs:
    """The season-wide frames one report reads: every player-season's neutral row, the
    percentiles computed from them (`metric_percentiles`, the composite's own function) and
    the style labels. The same for every player in the season, so the web front end builds
    them once and passes them to `build` (TASKS 2.36); Streamlit's plain `build` call builds
    them itself. Callers must not mutate them."""

    season_id: int
    neutral: pd.DataFrame
    percentiles: pd.DataFrame
    style_labels: pd.DataFrame


def season_inputs(engine, season_id: int) -> SeasonInputs:
    neutral = pd.read_sql(select(_N).where(_N.c.season_id == season_id), engine)
    return SeasonInputs(season_id=int(season_id), neutral=neutral,
                        percentiles=metric_percentiles(neutral),
                        style_labels=_style_labels(engine, season_id))


def resolved_bands(engine) -> pd.DataFrame:
    """Every player-season's resolved Psychological / Medical bands (Decision 17)."""
    return scout_scores.resolve_bands(store_assess.load_all(engine))


def _age(birth_date, season_id: int) -> float | None:
    """The player's age, measured at the same reference date the dashboard uses.

    This used to always measure against `pd.Timestamp.now()` (behind a dead `if False`
    branch), so the report and the dashboard disagreed about the same player's age on every
    completed season: the dashboard froze it at the season midpoint, the report let it keep
    rising. Both now call `seasons.age_reference_date` -- fixed midpoint for a finished
    season, today for the one being played.
    """
    if birth_date is None:
        return None
    ref = age_reference_date(int(season_id), settings.live_season_id)
    if ref is None:
        return None
    years = (ref - pd.Timestamp(birth_date)).days / 365.25
    return round(years, 1) if 14 <= years <= 50 else None


def _stamp_and_narrative(assessments: pd.DataFrame) -> tuple[str, Narrative | None]:
    """The stamp comes from the strongest state present, and the narrative from the row
    that carries it. A rejected or draft row contributes neither."""
    if assessments.empty:
        return STAMP_DATA_ONLY, None
    live = assessments[assessments["status"].isin(("submitted", "signed_off"))]
    if live.empty:
        return STAMP_DATA_ONLY, None

    signed = live[live["status"] == "signed_off"]
    source = signed if not signed.empty else live
    # Prefer a row that actually carries prose; a bare band-only assessment still counts
    # for the stamp but has no narrative to show.
    with_prose = source[source["summary"].notna() | source["why_sign"].notna()
                        | source["considerations"].notna()]
    row = (with_prose if not with_prose.empty else source).iloc[0]

    stamp = STAMP_FINAL if not signed.empty else STAMP_PROVISIONAL
    narrative = Narrative(
        summary=row.get("summary"), why_sign=row.get("why_sign"),
        considerations=row.get("considerations"),
        assessor=row.get("author_name"), assessor_role=row.get("author_role"),
        approver=row.get("approver_name"), approved_at=row.get("approved_at"))
    return stamp, narrative


def _without_author_flags(flags: list[str]) -> list[str]:
    """Drop the Psychological / Medical band flags: an author's own view (or no view at all)
    is not a club rating, so those bands raise no club-minimum flag."""
    return [f for f in flags if not f.startswith(("Psychological ", "Medical "))]


def as_data_only(base: ReportData) -> ReportData:
    """The report with no narrative and no Psychological / Medical value. Pure -- derived
    from an already-built report, so it does no database read."""
    bands = {**base.dimension_bands, "Psychological": None, "Medical": None}
    return replace(base, stamp=STAMP_DATA_ONLY, narrative=None, authored=None,
                   dimension_bands=bands, flags=_without_author_flags(base.flags))


def with_authored(base: ReportData, authored: Authored) -> ReportData:
    """The report with a user's own narrative and Psychological / Medical figures in place of
    the scout assessment's. Pure -- no database read."""
    bands = {**base.dimension_bands, "Psychological": authored.psych_band,
             "Medical": authored.medical_band}
    # No assessor/approver: the stamp already names the author, and the byline reads
    # "Assessed by", which this is not.
    narrative = Narrative(summary=authored.summary, why_sign=authored.why_sign,
                          considerations=authored.considerations, assessor=None,
                          assessor_role=None, approver=None, approved_at=None)
    return replace(base, stamp=f"Report by {authored.author_name} · "
                               f"{authored.created_at:%d %b %Y}",
                   narrative=narrative, authored=authored, dimension_bands=bands,
                   flags=_without_author_flags(base.flags))


def build(engine, player_id: int, competition_id: int, season_id: int, *,
          authored: Authored | None = None, data_only: bool = False,
          season: SeasonInputs | None = None,
          resolved: pd.DataFrame | None = None) -> ReportData:
    """Everything one player's report needs.

    `authored` swaps in a user's own narrative and Psychological / Medical figures for the
    scout assessment's; `data_only` drops all of them (no narrative, no Psychological or
    Medical value, stamp "Data only"). With neither, the report is built from the scout
    assessments as before.

    `season` (`season_inputs`) and `resolved` (`resolved_bands`) may be passed in when the
    caller already holds them; read here otherwise. Either way the report is the same.

    Raises ValueError naming the player when the player-season does not exist: an empty
    report is worse than an error, because it reads as a player about whom nothing is known.
    """
    if season is None:
        season = season_inputs(engine, season_id)
    elif season.season_id != int(season_id):
        raise ValueError(f"season inputs are for season {season.season_id}, not {season_id}")
    neutral = season.neutral
    mine = neutral[(neutral.player_id == player_id)
                   & (neutral.competition_id == competition_id)]
    if mine.empty:
        raise ValueError(f"no player-season for player {player_id} in competition "
                         f"{competition_id}, season {season_id}")
    row = mine.iloc[0]
    position = str(row["position_group"])

    bio = pd.read_sql(select(_P).where(_P.c.player_id == player_id), engine)
    bio_row = bio.iloc[0] if not bio.empty else None

    # --- percentiles, from the same function the composite uses ---------------------
    pcts_wide = season.percentiles
    key = (player_id, competition_id, season_id, position)
    percentiles: dict[str, float] = {}
    if key in pcts_wide.index:
        percentiles = {k: float(v) for k, v in pcts_wide.loc[key].items()
                       if pd.notna(v)}

    # --- the scorecard ---------------------------------------------------------------
    cards = pd.read_sql(
        select(_S).where(_S.c.player_id == player_id, _S.c.competition_id == competition_id,
                         _S.c.season_id == season_id, _S.c.archetype == "All Metrics"),
        engine)
    card = cards.iloc[0] if not cards.empty else None

    # --- assessments: a band only where somebody decided ------------------------------
    assessments = store_assess.load_for_player(engine, player_id, competition_id, season_id)
    if resolved is None:
        resolved = resolved_bands(engine)
    mine_resolved = resolved[(resolved.player_id == player_id)
                             & (resolved.competition_id == competition_id)
                             & (resolved.season_id == season_id)] if not resolved.empty \
        else pd.DataFrame()

    def _scout_band(prefix: str) -> float | None:
        if mine_resolved.empty:
            return None
        value = mine_resolved.iloc[0].get(f"{prefix}_band")
        status = mine_resolved.iloc[0].get(f"{prefix}_status")
        if status == getattr(scout_scores, "CONFLICT", "conflict"):
            return None
        return float(value) if pd.notna(value) else None

    bands: dict[str, float | None] = {
        "Performance": float(card["performance_band"]) if card is not None
        and pd.notna(card["performance_band"]) else None,
        "Physical": float(card["physical_band"]) if card is not None
        and pd.notna(card["physical_band"]) else None,
        "Psychological": _scout_band("psychological"),
        "Medical": _scout_band("medical"),
    }

    # --- rank within league, season and position, over rankable players only ----------
    peers_frame = neutral[(neutral.competition_id == competition_id)
                          & (neutral.position_group == position)
                          & neutral.rankable.astype(bool)]
    # `rank_in_pool` (model/scorecard.py) does the ranking, so the report and the player
    # profile quote one number from one function and cannot drift apart. It also shares a
    # rank between tied composites rather than ordering them by row position, which the
    # earlier inline version did.
    ranked = pd.read_sql(
        select(_S.c.player_id, _S.c.competition_id, _S.c.season_id, _S.c.position_group,
               _S.c.objective_composite)
        .where(_S.c.competition_id == competition_id, _S.c.season_id == season_id,
               _S.c.position_group == position, _S.c.archetype == "All Metrics"), engine)
    ranked = ranked.dropna(subset=["objective_composite"])
    rank, _peers = rank_in_pool(ranked, player_id, competition_id, season_id, position)

    style = _style_row(season.style_labels, player_id, competition_id, position)

    # --- availability -----------------------------------------------------------------
    spells = store_injuries.load_for_player(engine, player_id)
    minutes = float(row["minutes"]) if pd.notna(row["minutes"]) else None
    missed = games_missed_in_window(spells, season_id) if not spells.empty else 0
    try:
        ev = availability_with_evidence(spells, missed, competition_id, minutes,
                                        seasons=AVAILABILITY_SEASONS, minutes_seasons=1)
        availability, availability_status = ev.value, ev.status.value
    except Exception:
        availability, availability_status = None, "unknown"

    stamp, narrative = _stamp_and_narrative(assessments)

    flags: list[str] = []
    if card is not None:
        for name, band in bands.items():
            if band is not None and band < 2.0:
                flags.append(f"{name} {band:.2f} is below the club minimum of 2.00")
        if pd.notna(card.get("below_min_composite")) and bool(card["below_min_composite"]):
            comp = card["objective_composite"]
            flags.append(f"Composite {comp:.2f} is below the club's 3.00 minimum standard")

    league = league_name(competition_id)
    season_label = season_short(season_id)

    # --- how his minutes actually split across positions ------------------------------
    # The page names ONE position and scores him against that group's peers. For a
    # utility player that label is a minority of his season, so the split is shown rather
    # than implied. Display only -- the assigned group and every score are untouched.
    shares_frame = pd.read_sql(
        select(_PS.c.position_group, _PS.c.minutes, _PS.c.share,
               _PS.c.goals, _PS.c.assists)
        .where(_PS.c.player_id == player_id, _PS.c.competition_id == competition_id,
               _PS.c.season_id == season_id)
        .order_by(_PS.c.share.desc()), engine)
    position_shares = [(str(r.position_group), float(r.minutes), float(r.share),
                        float(r.goals) if pd.notna(r.goals) else None,
                        float(r.assists) if pd.notna(r.assists) else None)
                       for r in shares_frame.itertuples()]

    # --- the Leyton Orient squad benchmark --------------------------------------------
    # "Is he better than what we already have?" is the question the report exists to
    # answer, so the club's own squad median for the same position sits beside him.
    #
    # Percentiles are computed WITHIN a league, so a Leyton Orient median is the squad's
    # standing in League One and the player's is his standing in his own league. Those
    # are different scales whenever the leagues differ; benchmark_league names the club's
    # so the page can say so rather than implying one number.
    squad = neutral[(neutral.team_name == CLUB_TEAM_NAME)
                    & (neutral.position_group == position)
                    & neutral.rankable.astype(bool)]
    squad_keys = [k for k in ((int(r.player_id), int(r.competition_id), season_id, position)
                              for r in squad.itertuples()) if k in pcts_wide.index]
    benchmark: dict[str, float] = {}
    benchmark_league = None
    if squad_keys:
        sub = pcts_wide.loc[squad_keys]
        benchmark = {c: float(sub[c].median()) for c in sub.columns if sub[c].notna().any()}
        squad_comps = squad["competition_id"].unique()
        if len(squad_comps) == 1:
            benchmark_league = league_name(int(squad_comps[0]))

    report = ReportData(
        player_name=str(row["player_name"]),
        position=position,
        club=str(row["team_name"]) if pd.notna(row.get("team_name")) else None,
        league=league,
        season_label=season_label,
        age=_age(bio_row["birth_date"] if bio_row is not None else None, season_id),
        foot=(bio_row["foot"] if bio_row is not None and pd.notna(bio_row["foot"])
              else None),
        height_cm=(int(bio_row["height_cm"]) if bio_row is not None
                   and pd.notna(bio_row["height_cm"]) else None),
        nationality=(bio_row["nationality"] if bio_row is not None
                     and pd.notna(bio_row["nationality"]) else None),
        contract_until=(bio_row["contract_until"].strftime("%d %b %Y")
                        if bio_row is not None and pd.notna(bio_row["contract_until"])
                        else None),
        minutes=minutes,
        goals=float(row["goals_p90"]) * (minutes / 90.0)
        if pd.notna(row.get("goals_p90")) and minutes else None,
        assists=float(row["assists_p90"]) * (minutes / 90.0)
        if pd.notna(row.get("assists_p90")) and minutes else None,
        composite=float(card["objective_composite"]) if card is not None
        and pd.notna(card["objective_composite"]) else None,
        dimension_bands=bands,
        rank=rank,
        peer_count=len(ranked),
        percentiles=percentiles,
        style=style,
        # The eight SkillCorner percentiles, from the same computation as everything
        # else on the page. Absent metrics stay absent: the radar breaks its line rather
        # than plotting the origin, which would read as "covered no distance".
        physical={k: percentiles[k] for k in (
            "distance_p90", "meters_per_minute", "hsr_distance_p90", "hsr_count_p90",
            "sprint_distance_p90", "sprint_count_p90", "psv99_kmh", "top5_psv99_kmh")
            if k in percentiles},
        availability=availability,
        availability_status=availability_status,
        matches_missed=missed,
        injuries=spells.to_dict("records") if not spells.empty else [],
        narrative=narrative,
        stamp=stamp,
        chances_created=float(row["key_passes_p90"]) * (minutes / 90.0)
        if pd.notna(row.get("key_passes_p90")) and minutes else None,
        position_shares=position_shares,
        benchmark=benchmark,
        benchmark_n=len(squad_keys),
        benchmark_league=benchmark_league,
        snapshot_date=datetime.date.today().strftime("%d %b %Y"),
        # The peer COUNT is stated, not just the peer group. A 92nd percentile out of 13
        # players and out of 117 are very different claims, and a reader who cannot query
        # the data has no other way to tell them apart. Central Mid in League One really
        # is 13, because most central midfielders classify as Defensive or Attacking Mid.
        comparison_text=(f"{season_label} · {league} only · compared to "
                         f"{len(ranked)} {league} {position}s "
                         f"over {RANKABLE_MINUTES} minutes"),
        flags=flags,
    )
    if data_only:
        return as_data_only(report)
    return with_authored(report, authored) if authored is not None else report
