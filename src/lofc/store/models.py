"""SQLAlchemy ORM models. Source of truth for the database schema.

Phase 3 defines the four tables we can populate now: players, player_season_metrics,
wage_framework, identity_profiles. The downstream tables (valuations, archetypes,
shortlists) are added in their own phases, when their columns are known.

The per-90 metric columns mirror the processed table from Phase 2 one-to-one.
"""

from __future__ import annotations

import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# The per-90 rate columns, in the same order Phase 2 produces them.
PER90_COLUMNS = [
    "goals_p90", "np_goals_p90", "xg_p90", "np_xg_p90", "shots_p90",
    "assists_p90", "xa_p90", "key_passes_p90",
    "passes_p90", "passes_completed_p90", "progressive_passes_p90",
    "passes_into_final_third_p90", "passes_into_box_p90",
    "dribbles_p90", "dribbles_completed_p90", "carries_p90", "progressive_carries_p90",
    "pressures_p90", "tackles_p90", "interceptions_p90", "blocks_p90",
    "clearances_p90", "ball_recoveries_p90", "gk_saves_p90",
]

# Season totals kept on the row for readability.
TOTAL_COLUMNS = ["goals", "np_goals", "assists", "shots", "xg", "np_xg", "xa"]


class Base(DeclarativeBase):
    pass


class Player(Base):
    """One row per player (identity). Bio facts fill in from line-ups + Transfermarkt."""

    __tablename__ = "players"

    player_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    player_name: Mapped[str] = mapped_column(String)
    nationality: Mapped[str | None] = mapped_column(String, nullable=True)
    birth_date: Mapped[datetime.date | None] = mapped_column(Date, nullable=True)
    # From the Transfermarkt squad pages, attached during the valuation match.
    foot: Mapped[str | None] = mapped_column(String, nullable=True)
    contract_until: Mapped[datetime.date | None] = mapped_column(Date, nullable=True)
    height_cm: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Transfermarkt's own player id, for deep links to the player's TM profile.
    tm_player_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class PlayerSeasonMetric(Base):
    """One row per player per league season (the Phase 2 output, in the database)."""

    __tablename__ = "player_season_metrics"
    __table_args__ = (
        UniqueConstraint("player_id", "competition_id", "season_id", name="uq_player_competition_season"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    player_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("players.player_id"), index=True)

    competition_id: Mapped[int] = mapped_column(Integer, index=True)
    competition_name: Mapped[str] = mapped_column(String)
    season_id: Mapped[int] = mapped_column(Integer)
    season_name: Mapped[str] = mapped_column(String)

    player_name: Mapped[str] = mapped_column(String)
    team_name: Mapped[str] = mapped_column(String)
    position_group: Mapped[str] = mapped_column(String, index=True)
    dominant_position_id: Mapped[int] = mapped_column(Integer)

    minutes: Mapped[float] = mapped_column(Float)
    matches_played: Mapped[int] = mapped_column(Integer)
    rankable: Mapped[bool] = mapped_column(Boolean, index=True)

    # Season totals.
    goals: Mapped[float] = mapped_column(Float)
    np_goals: Mapped[float] = mapped_column(Float)
    assists: Mapped[float] = mapped_column(Float)
    shots: Mapped[float] = mapped_column(Float)
    xg: Mapped[float] = mapped_column(Float)
    np_xg: Mapped[float] = mapped_column(Float)
    xa: Mapped[float] = mapped_column(Float)

    # Per-90 rates.
    goals_p90: Mapped[float] = mapped_column(Float)
    np_goals_p90: Mapped[float] = mapped_column(Float)
    xg_p90: Mapped[float] = mapped_column(Float)
    np_xg_p90: Mapped[float] = mapped_column(Float)
    shots_p90: Mapped[float] = mapped_column(Float)
    assists_p90: Mapped[float] = mapped_column(Float)
    xa_p90: Mapped[float] = mapped_column(Float)
    key_passes_p90: Mapped[float] = mapped_column(Float)
    passes_p90: Mapped[float] = mapped_column(Float)
    passes_completed_p90: Mapped[float] = mapped_column(Float)
    progressive_passes_p90: Mapped[float] = mapped_column(Float)
    passes_into_final_third_p90: Mapped[float] = mapped_column(Float)
    passes_into_box_p90: Mapped[float] = mapped_column(Float)
    dribbles_p90: Mapped[float] = mapped_column(Float)
    dribbles_completed_p90: Mapped[float] = mapped_column(Float)
    carries_p90: Mapped[float] = mapped_column(Float)
    progressive_carries_p90: Mapped[float] = mapped_column(Float)
    pressures_p90: Mapped[float] = mapped_column(Float)
    tackles_p90: Mapped[float] = mapped_column(Float)
    interceptions_p90: Mapped[float] = mapped_column(Float)
    blocks_p90: Mapped[float] = mapped_column(Float)
    clearances_p90: Mapped[float] = mapped_column(Float)
    ball_recoveries_p90: Mapped[float] = mapped_column(Float)
    gk_saves_p90: Mapped[float] = mapped_column(Float)

    # Ratios and goalkeeper extras (nullable where undefined, e.g. no dribbles attempted).
    pass_completion_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    dribble_success_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    goals_conceded: Mapped[int] = mapped_column(Integer)
    save_pct: Mapped[float | None] = mapped_column(Float, nullable=True)


class WageFramework(Base):
    """LOFC affordability: a weekly wage ceiling per position group and age band.

    A constructed, documented stand-in (not an official club document). See the
    notes column and docs/methodology.md for provenance.
    """

    __tablename__ = "wage_framework"
    __table_args__ = (
        UniqueConstraint("position_group", "age_band", name="uq_position_age_band"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    position_group: Mapped[str] = mapped_column(String, index=True)
    age_band: Mapped[str] = mapped_column(String)
    weekly_wage_ceiling_gbp: Mapped[int] = mapped_column(Integer)
    notes: Mapped[str | None] = mapped_column(String, nullable=True)


class IdentityProfile(Base):
    """What LOFC wants from each position: which metric matters, its weight, and a floor.

    A constructed, documented stand-in. weight drives the Phase 4 composite score;
    min_percentile drives the Phase 7 on-profile filter.
    """

    __tablename__ = "identity_profiles"
    __table_args__ = (
        UniqueConstraint("position_group", "metric", name="uq_position_metric"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    position_group: Mapped[str] = mapped_column(String, index=True)
    metric: Mapped[str] = mapped_column(String)
    weight: Mapped[float] = mapped_column(Float)
    min_percentile: Mapped[float | None] = mapped_column(Float, nullable=True)
    notes: Mapped[str | None] = mapped_column(String, nullable=True)


class PlayerPercentile(Base):
    """A player's percentile in one metric, ranked within their position and league.

    Long format (one row per player-metric) so the dashboard can draw percentile bars.
    Only rankable players (450+ minutes) are ranked. Phase 4 output.
    """

    __tablename__ = "player_percentiles"
    __table_args__ = (
        UniqueConstraint("player_id", "competition_id", "season_id", "metric",
                         name="uq_percentile_player_competition_season_metric"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    player_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("players.player_id"), index=True)
    competition_id: Mapped[int] = mapped_column(Integer, index=True)
    season_id: Mapped[int] = mapped_column(Integer)
    position_group: Mapped[str] = mapped_column(String, index=True)
    metric: Mapped[str] = mapped_column(String, index=True)
    percentile: Mapped[float] = mapped_column(Float)


class PlayerScore(Base):
    """Per-player scores within position and league. Phase 4 output.

    performance_score: how good (broad, role-relevant stats, equal weight) - data only.
    fit_score: match to the identity profile (focused, identity-weighted) - configurable.
    Both 0-100, comparable. Ranks are within competition + position group.
    """

    __tablename__ = "player_scores"
    __table_args__ = (
        UniqueConstraint("player_id", "competition_id", "season_id",
                         name="uq_score_player_competition_season"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    player_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("players.player_id"), index=True)
    competition_id: Mapped[int] = mapped_column(Integer, index=True)
    season_id: Mapped[int] = mapped_column(Integer)
    position_group: Mapped[str] = mapped_column(String, index=True)

    performance_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    fit_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    performance_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fit_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)


class Archetype(Base):
    """A player's playing-style cluster within their position. Phase 5 output.

    cluster_id and cluster_label come from k-means on the players' style profiles
    (across all leagues). The grouping is data-driven; the label is auto-generated
    from the cluster's standout metrics. distance_to_centroid shows how typical the
    player is of their cluster (smaller = more typical).
    """

    __tablename__ = "archetypes"
    __table_args__ = (
        UniqueConstraint("player_id", "competition_id", "season_id",
                         name="uq_archetype_player_competition_season"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    player_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("players.player_id"), index=True)
    competition_id: Mapped[int] = mapped_column(Integer, index=True)
    season_id: Mapped[int] = mapped_column(Integer)
    position_group: Mapped[str] = mapped_column(String, index=True)
    cluster_id: Mapped[int] = mapped_column(Integer)
    cluster_label: Mapped[str] = mapped_column(String, index=True)
    distance_to_centroid: Mapped[float] = mapped_column(Float)


class Valuation(Base):
    """Fair value vs actual market value per player. Phase 6 output.

    market_value_eur is the real Transfermarkt 2015/16 value (the model's target).
    fair_value_eur is what the model predicts a player at this performance/age/position
    should be worth. undervaluation_eur = fair - actual (positive = a bargain). Fair
    values are out-of-fold cross-validation predictions, so no player is priced by a
    model that trained on them.
    """

    __tablename__ = "valuations"
    __table_args__ = (
        UniqueConstraint("player_id", "competition_id", "season_id",
                         name="uq_valuation_player_competition_season"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    player_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("players.player_id"), index=True)
    competition_id: Mapped[int] = mapped_column(Integer, index=True)
    season_id: Mapped[int] = mapped_column(Integer)
    position_group: Mapped[str] = mapped_column(String, index=True)

    age: Mapped[float | None] = mapped_column(Float, nullable=True)
    market_value_eur: Mapped[float] = mapped_column(Float)
    fair_value_eur: Mapped[float] = mapped_column(Float)
    undervaluation_eur: Mapped[float] = mapped_column(Float)
    undervaluation_pct: Mapped[float] = mapped_column(Float, index=True)
    model_version: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())


class WageEstimate(Base):
    """Modelled weekly wage by league, position group, age band and performance tier.

    A constructed stand-in (source flagged), anchored per league to published wage
    reporting (Capology / SalarySport averages, club accounts). Never derived from
    market value. Replaced wholesale when real wage data arrives. Drives the Phase 7
    wage gate; the low/high band expresses estimate uncertainty so borderline players
    are flagged for human judgement rather than silently dropped.
    """

    __tablename__ = "wage_estimates"
    __table_args__ = (
        UniqueConstraint("competition_id", "position_group", "age_band", "performance_tier",
                         name="uq_wage_estimate_league_position_age_tier"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    competition_id: Mapped[int] = mapped_column(Integer, index=True)
    position_group: Mapped[str] = mapped_column(String, index=True)
    age_band: Mapped[str] = mapped_column(String)
    performance_tier: Mapped[str] = mapped_column(String)
    estimated_weekly_wage_gbp: Mapped[int] = mapped_column(Integer)
    wage_low_gbp: Mapped[int] = mapped_column(Integer)
    wage_high_gbp: Mapped[int] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String)


class Shortlist(Base):
    """The final ranked shortlist per position. Phase 7 output.

    One row per candidate, with both affordability gates (transfer fee and modelled wage)
    and the on-profile flag, ranked within position. is_near_miss marks rows shown only
    because nothing passed all gates (so the screen is never blank).
    """

    __tablename__ = "shortlists"
    __table_args__ = (
        UniqueConstraint("player_id", "competition_id", "season_id",
                         name="uq_shortlist_player_competition_season"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    player_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("players.player_id"), index=True)
    competition_id: Mapped[int] = mapped_column(Integer, index=True)
    season_id: Mapped[int] = mapped_column(Integer)
    position_group: Mapped[str] = mapped_column(String, index=True)

    rank: Mapped[int] = mapped_column(Integer)
    affordable_fee: Mapped[bool] = mapped_column(Boolean)
    affordable_wage: Mapped[bool] = mapped_column(Boolean)
    on_profile: Mapped[bool] = mapped_column(Boolean)
    is_near_miss: Mapped[bool] = mapped_column(Boolean, index=True)

    performance_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    fit_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    undervaluation_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    market_value_eur: Mapped[float | None] = mapped_column(Float, nullable=True)
    estimated_weekly_wage_gbp: Mapped[int | None] = mapped_column(Integer, nullable=True)
    wage_low_gbp: Mapped[int | None] = mapped_column(Integer, nullable=True)
    wage_high_gbp: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # True when the ceiling falls inside the estimate band: affordable on the low
    # estimate, not on the high one, so worth a human judgement call.
    wage_marginal: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    wage_ceiling_gbp: Mapped[int | None] = mapped_column(Integer, nullable=True)
    transfer_budget_eur: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())


class WatchlistEntry(Base):
    """A player the recruiter is tracking, with a status and a free-text note.

    USER DATA: never written or cleared by the pipeline. Keyed by the same
    (player, league, season) triple as every player row, so watching a specific
    season-row is unambiguous even for mid-season movers.
    """

    __tablename__ = "watchlist"
    __table_args__ = (
        UniqueConstraint("player_id", "competition_id", "season_id",
                         name="uq_watchlist_player_competition_season"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    player_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("players.player_id"), index=True)
    competition_id: Mapped[int] = mapped_column(Integer, index=True)
    season_id: Mapped[int] = mapped_column(Integer)
    note: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, server_default="Watching")
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now(),
                                                          onupdate=func.now())


# The curated SkillCorner physical metrics, shared by the team and player tables.
# Per-90 rates plus peak speed; the raw per-match columns stay in the source file.
SKILLCORNER_METRICS = [
    "distance_p90", "m_per_min_p90", "running_distance_p90",
    "hsr_distance_p90", "hsr_count_p90", "sprint_distance_p90", "sprint_count_p90",
    "hi_distance_p90", "hi_count_p90", "psv99_kmh", "top5_psv99_kmh",
    "medium_accel_count_p90", "high_accel_count_p90",
    "medium_decel_count_p90", "high_decel_count_p90",
    "explosive_accel_to_hsr_p90", "explosive_accel_to_sprint_p90", "cod_count_p90",
]


class SkillCornerTeamSeason(Base):
    """Team-level physical output per season: all 24 League One clubs.

    From the club-provided SkillCorner export (tracking data). This is the only
    granularity available for non-LOFC teams, so it powers league benchmarking,
    never per-candidate physical scores.
    """

    __tablename__ = "skillcorner_team_season"
    __table_args__ = (
        UniqueConstraint("sc_team_id", "season_label", name="uq_sc_team_season"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sc_team_id: Mapped[int] = mapped_column(Integer, index=True)
    team_name: Mapped[str] = mapped_column(String, index=True)
    season_label: Mapped[str] = mapped_column(String)
    matches_measured: Mapped[int] = mapped_column(Integer)
    avg_minutes: Mapped[float | None] = mapped_column(Float, nullable=True)
    distance_p90: Mapped[float | None] = mapped_column(Float, nullable=True)
    m_per_min_p90: Mapped[float | None] = mapped_column(Float, nullable=True)
    running_distance_p90: Mapped[float | None] = mapped_column(Float, nullable=True)
    hsr_distance_p90: Mapped[float | None] = mapped_column(Float, nullable=True)
    hsr_count_p90: Mapped[float | None] = mapped_column(Float, nullable=True)
    sprint_distance_p90: Mapped[float | None] = mapped_column(Float, nullable=True)
    sprint_count_p90: Mapped[float | None] = mapped_column(Float, nullable=True)
    hi_distance_p90: Mapped[float | None] = mapped_column(Float, nullable=True)
    hi_count_p90: Mapped[float | None] = mapped_column(Float, nullable=True)
    psv99_kmh: Mapped[float | None] = mapped_column(Float, nullable=True)
    top5_psv99_kmh: Mapped[float | None] = mapped_column(Float, nullable=True)
    medium_accel_count_p90: Mapped[float | None] = mapped_column(Float, nullable=True)
    high_accel_count_p90: Mapped[float | None] = mapped_column(Float, nullable=True)
    medium_decel_count_p90: Mapped[float | None] = mapped_column(Float, nullable=True)
    high_decel_count_p90: Mapped[float | None] = mapped_column(Float, nullable=True)
    explosive_accel_to_hsr_p90: Mapped[float | None] = mapped_column(Float, nullable=True)
    explosive_accel_to_sprint_p90: Mapped[float | None] = mapped_column(Float, nullable=True)
    cod_count_p90: Mapped[float | None] = mapped_column(Float, nullable=True)


class SkillCornerPlayerSeason(Base):
    """Player-level physical output per season: LOFC's own squad only.

    Matched to our players table by birth date + name where possible, so physical
    data joins onto scores and profiles for our squad. Other clubs' players have
    no tracking data in this export.
    """

    __tablename__ = "skillcorner_player_season"
    __table_args__ = (
        UniqueConstraint("sc_player_id", "season_label", name="uq_sc_player_season"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sc_player_id: Mapped[int] = mapped_column(Integer, index=True)
    player_name: Mapped[str] = mapped_column(String, index=True)
    birth_date: Mapped[datetime.date | None] = mapped_column(Date, nullable=True)
    # Our StatsBomb player_id when the DOB+name match succeeds; null otherwise.
    player_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("players.player_id"),
                                                  nullable=True, index=True)
    season_label: Mapped[str] = mapped_column(String)
    matches_measured: Mapped[int] = mapped_column(Integer)
    avg_minutes: Mapped[float | None] = mapped_column(Float, nullable=True)
    distance_p90: Mapped[float | None] = mapped_column(Float, nullable=True)
    m_per_min_p90: Mapped[float | None] = mapped_column(Float, nullable=True)
    running_distance_p90: Mapped[float | None] = mapped_column(Float, nullable=True)
    hsr_distance_p90: Mapped[float | None] = mapped_column(Float, nullable=True)
    hsr_count_p90: Mapped[float | None] = mapped_column(Float, nullable=True)
    sprint_distance_p90: Mapped[float | None] = mapped_column(Float, nullable=True)
    sprint_count_p90: Mapped[float | None] = mapped_column(Float, nullable=True)
    hi_distance_p90: Mapped[float | None] = mapped_column(Float, nullable=True)
    hi_count_p90: Mapped[float | None] = mapped_column(Float, nullable=True)
    psv99_kmh: Mapped[float | None] = mapped_column(Float, nullable=True)
    top5_psv99_kmh: Mapped[float | None] = mapped_column(Float, nullable=True)
    medium_accel_count_p90: Mapped[float | None] = mapped_column(Float, nullable=True)
    high_accel_count_p90: Mapped[float | None] = mapped_column(Float, nullable=True)
    medium_decel_count_p90: Mapped[float | None] = mapped_column(Float, nullable=True)
    high_decel_count_p90: Mapped[float | None] = mapped_column(Float, nullable=True)
    explosive_accel_to_hsr_p90: Mapped[float | None] = mapped_column(Float, nullable=True)
    explosive_accel_to_sprint_p90: Mapped[float | None] = mapped_column(Float, nullable=True)
    cod_count_p90: Mapped[float | None] = mapped_column(Float, nullable=True)
