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
from dataclasses import dataclass, field

import pandas as pd
from sqlalchemy import select

from lofc.model import report_categories as rc
from lofc.model import scout_scores
from lofc.model.medical import (AVAILABILITY_SEASONS, availability_with_evidence,
                                games_missed_in_window)
from lofc.model.scorecard import metric_percentiles
from lofc.store import assessments as store_assess
from lofc.store import injuries as store_injuries
from lofc.store.models import Player, PlayerMetricNeutral, PlayerScorecard, PlayerPositionShare

STAMP_DATA_ONLY = "Data only"
STAMP_PROVISIONAL = "Provisional"
STAMP_FINAL = "Final"

RANKABLE_MINUTES = 450

_SEASON_LABELS: dict[int, str] = {317: "24/25", 318: "25/26", 319: "26/27"}
_LEAGUE_NAMES: dict[int, str] = {
    3: "Championship", 4: "League One", 5: "League Two", 65: "National League",
    901: "Scottish Premiership", 902: "Scottish Championship", 903: "Premier League 2",
}

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
    category_scores: dict[str, float]
    physical: dict[str, float]
    peers: list[tuple[str, float, float]]
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


def _age(birth_date, season_id: int) -> float | None:
    if birth_date is None:
        return None
    ref = pd.Timestamp(f"{2008 + season_id % 1000}-01-01") if False else pd.Timestamp.now()
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


def build(engine, player_id: int, competition_id: int, season_id: int) -> ReportData:
    """Everything one player's report needs.

    Raises ValueError naming the player when the player-season does not exist: an empty
    report is worse than an error, because it reads as a player about whom nothing is known.
    """
    neutral = pd.read_sql(
        select(_N).where(_N.c.season_id == season_id), engine)
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
    pcts_wide = metric_percentiles(neutral)
    key = (player_id, competition_id, season_id, position)
    percentiles: dict[str, float] = {}
    if key in pcts_wide.index:
        percentiles = {k: float(v) for k, v in pcts_wide.loc[key].items()
                       if pd.notna(v)}
    categories = rc.category_scores(percentiles, position) if position in rc.CATEGORIES else {}

    # --- the scorecard ---------------------------------------------------------------
    cards = pd.read_sql(
        select(_S).where(_S.c.player_id == player_id, _S.c.competition_id == competition_id,
                         _S.c.season_id == season_id, _S.c.archetype == "All Metrics"),
        engine)
    card = cards.iloc[0] if not cards.empty else None

    # --- assessments: a band only where somebody decided ------------------------------
    assessments = store_assess.load_for_player(engine, player_id, competition_id, season_id)
    resolved = scout_scores.resolve_bands(store_assess.load_all(engine))
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
    ranked = pd.read_sql(
        select(_S.c.player_id, _S.c.objective_composite)
        .where(_S.c.competition_id == competition_id, _S.c.season_id == season_id,
               _S.c.position_group == position, _S.c.archetype == "All Metrics"), engine)
    ranked = ranked.dropna(subset=["objective_composite"]).sort_values(
        "objective_composite", ascending=False).reset_index(drop=True)
    rank = None
    if player_id in set(ranked.player_id):
        rank = int(ranked.index[ranked.player_id == player_id][0]) + 1

    # --- scatter peers, in category units ---------------------------------------------
    peers: list[tuple[str, float, float]] = []
    if position in rc.SCATTER_AXES and not pcts_wide.empty:
        x_cat, y_cat = rc.SCATTER_AXES[position]
        for pid in peers_frame.player_id:
            pk = (int(pid), competition_id, season_id, position)
            if pk not in pcts_wide.index:
                continue
            p = {k: float(v) for k, v in pcts_wide.loc[pk].items() if pd.notna(v)}
            x = rc.category_score(p, position, x_cat)
            y = rc.category_score(p, position, y_cat)
            if x is None or y is None:
                continue
            name = peers_frame.loc[peers_frame.player_id == pid, "player_name"].iloc[0]
            peers.append((str(name), x, y))

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

    league = _LEAGUE_NAMES.get(competition_id, f"Competition {competition_id}")
    season_label = _SEASON_LABELS.get(season_id, str(season_id))

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
            benchmark_league = _LEAGUE_NAMES.get(int(squad_comps[0]))

    return ReportData(
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
        category_scores=categories,
        # The eight SkillCorner percentiles, from the same computation as everything
        # else on the page. Absent metrics stay absent: the radar breaks its line rather
        # than plotting the origin, which would read as "covered no distance".
        physical={k: percentiles[k] for k in (
            "distance_p90", "meters_per_minute", "hsr_distance_p90", "hsr_count_p90",
            "sprint_distance_p90", "sprint_count_p90", "psv99_kmh", "top5_psv99_kmh")
            if k in percentiles},
        peers=peers,
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
