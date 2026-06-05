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
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
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
    """One row per player (identity). Age/nationality fill in from Transfermarkt later."""

    __tablename__ = "players"

    player_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    player_name: Mapped[str] = mapped_column(String)
    nationality: Mapped[str | None] = mapped_column(String, nullable=True)
    birth_date: Mapped[datetime.date | None] = mapped_column(Date, nullable=True)


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
