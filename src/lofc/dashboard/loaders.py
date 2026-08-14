"""Every database read the dashboard performs, cached in one place.

All Streamlit @cache_data loaders live here so the data layer is separate from presentation:
the tabs receive DataFrames and never open a connection themselves. Restart the dashboard
container after a pipeline run to pick up fresh data (the caches are time-limited, not
event-driven).
"""

from __future__ import annotations

import pandas as pd
import streamlit as st
from sqlalchemy import create_engine

from lofc.config import settings
from lofc.constrain.filters import build_candidates
from lofc.dashboard.labels import LABELS
from lofc.dashboard.seasons import SEASON_REF_DATE
from lofc.model import club_framework as cf
from lofc.model import metric_registry as reg
from lofc.model import scorecard as scorecard_mod
from lofc.model.financial_resale import financial_resale_bands

@st.cache_resource
def get_engine():
    return create_engine(settings.database_url)


# --- season selection --------------------------------------------------------------
# The platform holds multiple seasons of Impect data. Scoring/ranking is done WITHIN one
# season at a time (so a player appears once, on that season's form, ranked against that
# season's peers, with that season's physical coverage). The default is the latest season;
# 2024/25 stays fully available (switch the sidebar selector) and powers the trajectory
# chart. SkillCorner physical exists for 2025/26 only.
# Contract-expiry horizons for the free-transfer market, as a table so no date is hard-coded
# in the filter (the previous "out of contract by summer 2026" checkbox silently became a
# description of the PAST once that date passed).
#
# English contracts effectively all end on 30 JUNE (of the 1,381 expiry dates we hold, 1,377
# are June and 4 are May; ZERO are January). So there is no such thing as a player "out of
# contract in January" here: the January window matters because a player whose deal ends in
# summer is then inside his final six months, which is the same set as the summer horizon --
# read it off the "Months left" column (<= 6) rather than a separate filter.

@st.cache_data(ttl=600)
def available_seasons() -> list[int]:
    """Season ids present in the data, latest first (the default is the first)."""
    df = pd.read_sql("SELECT DISTINCT season_id FROM player_metrics_neutral ORDER BY season_id DESC",
                     get_engine())
    return df["season_id"].astype(int).tolist()


@st.cache_data(ttl=600)
def load_candidates(wage_ceiling_multiplier: float, season_id: int | None = None) -> pd.DataFrame:
    engine = get_engine()
    # all_leagues: keep EVERY scored player (EFL + Scottish/PL2). Non-EFL players carry
    # NaN market value/wage, so they can't pass the affordability gates, but they are
    # browsable and rankable by quality/style — the merged Shortlist spans all leagues.
    candidates = build_candidates(engine, wage_ceiling_multiplier, all_leagues=True)
    keys = ["player_id", "competition_id", "season_id"]
    archetypes = pd.read_sql("SELECT player_id, competition_id, season_id, cluster_label "
                             "FROM archetypes", engine)
    # Season goals/assists totals + underlying rates, from the combined table (all leagues).
    totals = pd.read_sql("SELECT player_id, competition_id, season_id, np_goals_p90, "
                         "assists_p90, np_xg_p90, xa_p90 FROM player_metrics_neutral", engine)
    bio = pd.read_sql("SELECT player_id, birth_date, foot, contract_until, height_cm, tm_player_id "
                      "FROM players", engine)
    out = (candidates.merge(archetypes, on=keys, how="left")
           .merge(totals, on=keys, how="left")
           .merge(bio, on="player_id", how="left"))
    out["contract_until"] = pd.to_datetime(out["contract_until"], errors="coerce")
    out["league"] = out["competition_id"].map(_competition_name_by_id()).fillna("—")
    # Age from birth_date (present for ~99% of players in every league) at the season midpoint,
    # so age is not limited to valued EFL players. The valuations age (EFL only) is the fallback
    # for the rare player with no birth date. Implausible results are ignored, not shown.
    out["birth_date"] = pd.to_datetime(out["birth_date"], errors="coerce")
    ref = out["season_id"].map(SEASON_REF_DATE)
    dob_age = ((ref - out["birth_date"]).dt.days / 365.25).round(1)
    dob_age = dob_age.where(dob_age.between(14, 50))          # drop nonsense before using
    out["age"] = dob_age.where(dob_age.notna(), out["age"])
    if season_id is not None:                       # rank within one season only
        out = out[out["season_id"] == season_id].reset_index(drop=True)
    return out


@st.cache_data(ttl=600)
def load_scorecards(season_id: int | None = None) -> pd.DataFrame:
    """The club's 1-5 composite scorecard per player for one season, read from the persisted
    `player_scorecards` table (computed live as a fallback if it has not been built yet).
    Scored WITHIN the season (percentiles and coverage are that season's), so a player appears
    once. Two composites: objective (Performance + Physical) and full (adds the modelled
    Financial + Resale). Nobody is excluded by the advisory veto/gate flags."""
    return _build_scorecard_frame(season_id=season_id)


def _attach_scorecard_meta(sc: pd.DataFrame, neutral: pd.DataFrame) -> pd.DataFrame:
    """Add player_name, team_name and league to a scorecard frame."""
    keys = ["player_id", "competition_id", "season_id"]
    meta = neutral[keys + ["player_name", "team_name"]].drop_duplicates(keys)
    sc = sc.merge(meta, on=keys, how="left")
    sc["league"] = sc["competition_id"].map(_competition_name_by_id()).fillna("—")
    return sc


@st.cache_data(ttl=600)
def _stored_scorecards(season_id: int | None = None) -> pd.DataFrame:
    """The persisted club scorecards (`player_scorecards`, written by model/scorecard_run).
    Empty frame if the table has not been built yet — the caller then computes live."""
    where = f"WHERE season_id = {int(season_id)}" if season_id is not None else ""
    try:
        return pd.read_sql(f"SELECT * FROM player_scorecards {where}", get_engine())
    except Exception:                                # table not migrated yet
        return pd.DataFrame()


def _build_scorecard_frame(archetype_by_position: dict[str, str] | None = None,
                           season_id: int | None = None) -> pd.DataFrame:
    """One scorecard row per player for the requested archetype per position.

    Reads the PERSISTED table (fast: the pipeline already did the maths). Falls back to
    computing live if the table is empty — so the dashboard still works on a database where
    the scorecard stage has not run yet.
    """
    engine = get_engine()
    stored = _stored_scorecards(season_id)
    if not stored.empty:
        # Keep, per position, the row whose archetype is the one asked for (default otherwise).
        # An archetype absent from the stored table silently falls back to the default, so a
        # new lens can never blank the ranking.
        available = set(stored["archetype"].unique())
        by_position = {p: a for p, a in (archetype_by_position or {}).items() if a in available}
        wanted = stored["position_group"].map(
            lambda p: by_position.get(p, cf.DEFAULT_ARCHETYPE))
        sc = stored[stored["archetype"] == wanted].drop(columns=["id", "archetype"],
                                                        errors="ignore")
        meta = pd.read_sql("SELECT player_id, competition_id, season_id, player_name, team_name "
                           "FROM player_metrics_neutral", engine)
        return _attach_scorecard_meta(sc.reset_index(drop=True), meta)

    # Fallback: no persisted scorecards yet -> compute them live, exactly as before.
    neutral = pd.read_sql("SELECT * FROM player_metrics_neutral", engine)
    if season_id is not None:                       # score within one season only
        neutral = neutral[neutral["season_id"] == season_id]
    fr = financial_resale_bands(engine)
    sc = scorecard_mod.build_scorecards(neutral, financial_resale=fr,
                                        archetype_by_position=archetype_by_position)
    return _attach_scorecard_meta(sc, neutral)


@st.cache_data(ttl=600)
def load_scorecards_archetype(position: str, archetype: str, season_id: int | None = None) -> pd.DataFrame:
    """Scorecards with one position's Performance dimension scored on a chosen archetype's
    metric subset (the archetype lens). Only that position's rows differ from the default."""
    return _build_scorecard_frame(archetype_by_position={position: archetype}, season_id=season_id)


@st.cache_data(ttl=600)
def load_scorecard_percentiles(season_id: int | None = None) -> pd.DataFrame:
    """Each player's direction-aware percentile per metric (within season + position + league),
    so a selected player's scorecard can show the metric-by-metric detail behind each dimension."""
    neutral = pd.read_sql("SELECT * FROM player_metrics_neutral", get_engine())
    if season_id is not None:
        neutral = neutral[neutral["season_id"] == season_id]
    return scorecard_mod.metric_percentiles(neutral).reset_index()


@st.cache_data(ttl=600)
def load_percentiles(season_id: int | None = None) -> pd.DataFrame:
    # One season, keyed by player AND league: a mid-season mover (e.g. League Two to National
    # League in January) legitimately has one row per league. Other seasons stay in the DB
    # for the trajectory chart.
    where = (f"season_id = {int(season_id)}" if season_id is not None
             else "season_id = (SELECT MAX(season_id) FROM player_percentiles)")
    return pd.read_sql(
        f"SELECT player_id, competition_id, metric, percentile FROM player_percentiles "
        f"WHERE {where}", get_engine())


@st.cache_data(ttl=600)
def load_metric_values(season_id: int | None = None) -> pd.DataFrame:
    """Raw per-90 (and rate) values for every metric, for the profile's full-stats table,
    for one season. Reads the combined table so it covers ALL leagues (including the
    Impect-spined Scottish/PL2 ones) and matches exactly the values scoring uses."""
    engine = get_engine()
    available = pd.read_sql("SELECT * FROM player_metrics_neutral LIMIT 0", engine).columns
    # Every registry metric (incl. physical + club-framework metrics), so the unified detail's
    # grand table has a per-90/total for each dimension's metrics, not just the LABELS set.
    metric_names = [s.name for s in reg.REGISTRY]
    cols = [c for c in dict.fromkeys(list(LABELS) + metric_names) if c in available]
    where = (f"season_id = {int(season_id)}" if season_id is not None
             else "season_id = (SELECT MAX(season_id) FROM player_metrics_neutral)")
    return pd.read_sql(
        f"SELECT player_id, competition_id, {', '.join(cols)} FROM player_metrics_neutral "
        f"WHERE {where}", engine)


@st.cache_data(ttl=600)
def load_wage_framework() -> pd.DataFrame:
    return pd.read_sql("SELECT position_group, age_band, weekly_wage_ceiling_gbp FROM wage_framework",
                       get_engine())


# The 8 club Physical metrics with a short label + unit, for the raw cross-league comparison.

@st.cache_data(ttl=600)
def load_sc_teams() -> pd.DataFrame:
    """Team-level SkillCorner physical output: all 24 League One clubs."""
    try:
        teams = pd.read_sql("SELECT * FROM skillcorner_team_season", get_engine())
    except Exception:
        return pd.DataFrame()
    teams["display_name"] = teams["team_name"].str.replace(r"\s+FC$", "", regex=True)
    return teams


@st.cache_data(ttl=600)
def load_sc_players() -> pd.DataFrame:
    """Player-level SkillCorner physical output: LOFC's own squad, with positions."""
    engine = get_engine()
    try:
        players = pd.read_sql("SELECT * FROM skillcorner_player_season", engine)
    except Exception:
        return pd.DataFrame()
    if players.empty:
        return players
    positions = pd.read_sql(
        "SELECT player_id, position_group FROM player_season_metrics "
        "WHERE season_id = (SELECT MAX(season_id) FROM player_season_metrics)", engine)
    # A mid-season mover has one latest-season row per club, so dedupe to one
    # position per player or the join fans the 21-row squad table out with copies.
    positions = positions.drop_duplicates("player_id")
    return players.merge(positions, on="player_id", how="left")


@st.cache_data(ttl=600)
def headline(season_id: int | None = None) -> tuple[int, int]:
    """Top-level counts for the KPI strip: distinct players analysed and leagues covered, for
    ONE season (from the combined table, so all 7 leagues — not the EFL-only spine)."""
    engine = get_engine()
    where = f"WHERE season_id = {int(season_id)}" if season_id is not None else ""
    players = pd.read_sql(
        f"SELECT COUNT(DISTINCT player_id) AS c FROM player_metrics_neutral {where}", engine)["c"][0]
    leagues = pd.read_sql(
        f"SELECT COUNT(DISTINCT competition_id) AS c FROM player_metrics_neutral {where}", engine)["c"][0]
    return int(players), int(leagues)


@st.cache_data(ttl=600)
def load_trajectory() -> pd.DataFrame:
    """Every season row per player, for the profile's season-by-season view.

    The dashboard's scores and prices are pinned to the latest season; earlier
    seasons exist purely to show direction (improving or declining). A mid-season
    mover has one row per league, deliberately: rates are league-relative.
    """
    return pd.read_sql(
        "SELECT player_id, season_id, season_name, competition_name, team_name, "
        "minutes, goals, assists, np_xg_p90, xa_p90, "
        "save_pct, gk_saves_p90, tackles_p90, interceptions_p90, pass_completion_pct "
        "FROM player_season_metrics ORDER BY season_id", get_engine())



@st.cache_data(ttl=600)
def season_label() -> str:
    """The season shown in the KPI strip: the latest one in the data (e.g. '2025/26')."""
    name = pd.read_sql(
        "SELECT season_name FROM player_season_metrics "
        "WHERE season_id = (SELECT MAX(season_id) FROM player_season_metrics) LIMIT 1",
        get_engine())["season_name"]
    return str(name[0]).replace("/20", "/") if len(name) else "—"


@st.cache_data(ttl=600)
def max_minutes() -> int:
    """Data-driven top of the minutes slider (a season's real maximum, not a guess)."""
    value = pd.read_sql(
        "SELECT MAX(minutes) AS m FROM player_season_metrics "
        "WHERE season_id = (SELECT MAX(season_id) FROM player_season_metrics)",
        get_engine())["m"][0]
    return int(value) if pd.notna(value) else 3500


def _competition_name_by_id() -> dict[int, str]:
    """competition_id -> clean league name, across BOTH StatsBomb-spined (EFL) and
    Impect-spined (Scottish/PL2) leagues, so every league in the combined table names."""
    names = {c.competition_id: c.label.rsplit(" ", 1)[0] for c in settings.competitions}
    for t in settings.impect_targets:            # adds the Impect-only leagues (901/902/903)
        names.setdefault(t.competition_id, t.competition_name)
    return names


@st.cache_data(ttl=600)
def league_names() -> list[str]:
    """ALL league names present in the combined table (EFL + Scottish/PL2). The Shortlist
    spans every league; players with no market value simply can't pass the money gates."""
    ids = pd.read_sql("SELECT DISTINCT competition_id FROM player_metrics_neutral",
                      get_engine())["competition_id"]
    name_by_id = _competition_name_by_id()
    return [name_by_id.get(int(i), f"League {int(i)}") for i in sorted(ids)]
