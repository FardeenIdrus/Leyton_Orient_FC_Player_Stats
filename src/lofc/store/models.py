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


class PlayerScorecard(Base):
    """The club's 1-5 recruitment composite per player (model/scorecard.py), persisted.

    This is the LIVE ranking model (the old player_scores Quality/Fit is retired), stored so
    the offline shortlist pipeline and the BI layer read the same numbers the dashboard shows.

    Scored WITHIN season + league + position group. One row per player-season PER ARCHETYPE:
    'All Metrics' (the default, full-profile) for everyone, plus a row per club archetype for
    the positions that have them (Full Back, Winger) so the lens is queryable in BI.

    TWO composites, deliberately kept as separate columns:
      * objective_composite -- Performance + Physical only, 100% real Impect + SkillCorner
        data. THIS is the ranking (the shortlist sorts on it).
      * full_composite -- adds the MODELLED Financial Fit + Resale Potential, which rest on the
        modelled wage grid and the valuation regression (a screening prior, NOT decision-grade).
        Anything reading this column directly must treat it as part-modelled.

    veto / below_min_composite mirror the club's "< 2.0 on a dimension" and "< 3.0 composite"
    rules. They are ADVISORY FLAGS ONLY and never exclude a player from the ranking.
    """

    __tablename__ = "player_scorecards"
    __table_args__ = (
        UniqueConstraint("player_id", "competition_id", "season_id", "archetype",
                         name="uq_scorecard_player_competition_season_archetype"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    player_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("players.player_id"), index=True)
    competition_id: Mapped[int] = mapped_column(Integer, index=True)
    season_id: Mapped[int] = mapped_column(Integer, index=True)
    position_group: Mapped[str] = mapped_column(String, index=True)
    # 'All Metrics' = the full-profile default; otherwise a club archetype (Full Back / Winger).
    archetype: Mapped[str] = mapped_column(String, index=True)

    # The 1-5 dimension bands. Financial/Resale are MODELLED and are NULL for players with no
    # market value (Scottish/PL2) -- they simply drop out and the composite renormalises.
    performance_band: Mapped[float | None] = mapped_column(Float, nullable=True)
    physical_band: Mapped[float | None] = mapped_column(Float, nullable=True)
    financial_band: Mapped[float | None] = mapped_column(Float, nullable=True)
    resale_band: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Psychological/Medical are human scout inputs (scout_scores.resolve_bands), NULL until
    # both dimensions of an assessment exist for the player (Decision 9).
    psychological_band: Mapped[float | None] = mapped_column(Float, nullable=True)
    medical_band: Mapped[float | None] = mapped_column(Float, nullable=True)

    objective_composite: Mapped[float | None] = mapped_column(Float, nullable=True)
    objective_weight_covered: Mapped[float | None] = mapped_column(Float, nullable=True)
    full_composite: Mapped[float | None] = mapped_column(Float, nullable=True)
    full_weight_covered: Mapped[float | None] = mapped_column(Float, nullable=True)
    # assessed_composite: Performance + Physical + Psychological + Medical (Decision 15) --
    # deliberately excludes the modelled Financial/Resale dimensions. NULL unless both scout
    # dimensions are present (Decision 9).
    assessed_composite: Mapped[float | None] = mapped_column(Float, nullable=True)
    assessed_weight_covered: Mapped[float | None] = mapped_column(Float, nullable=True)

    veto: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    below_min_composite: Mapped[bool | None] = mapped_column(Boolean, nullable=True)


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

    # THE RANKING KEY: the club's objective 1-5 composite (Performance + Physical, real data),
    # copied from player_scorecards. full_composite adds the MODELLED money dimensions and is
    # carried for reference only -- it never orders the shortlist.
    objective_composite: Mapped[float | None] = mapped_column(Float, nullable=True)
    full_composite: Mapped[float | None] = mapped_column(Float, nullable=True)

    performance_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    # RETIRED: the old invented Style-fit. Kept for historical comparison; ranks nothing.
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


class User(Base):
    """A person who can record or approve an assessment.

    USER DATA: never written or cleared by the pipeline. Passwords are stored only as a
    scrypt hash (see dashboard/auth.py); the plaintext never reaches the database.
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String, unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String)
    role: Mapped[str] = mapped_column(String)          # scout | medical | head_of_recruitment | admin
    password_hash: Mapped[str] = mapped_column(String)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true")
    # Login throttling state (dashboard/auth.py). Stored on the row rather than in process
    # memory so a lockout survives a Streamlit restart.
    failed_logins: Mapped[int] = mapped_column(Integer, server_default="0")
    locked_until: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    # True after an admin sets a password on the user's behalf; the login page then forces a
    # change before anything else is shown, so an admin-chosen password is never a standing one.
    must_change_password: Mapped[bool] = mapped_column(Boolean, server_default="false")
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())


class ScoutAssessment(Base):
    """One person's judgement of one dimension for one player-season.

    Decision 14: a `submitted` assessment SCORES. Sign-off does not gate visibility or
    ranking -- it marks the assessment approved and controls what may be exported as final.
    Nothing here is ever deleted, so disagreement between two assessors stays visible.

    `status` is one of `draft` / `submitted` / `signed_off` / `rejected` -- no CHECK
    constraint enforces this (application-layer rule, like the rest of this table's status
    handling). `rejected` is a fourth, terminal outcome: a Head of Recruitment (or admin)
    declined a `submitted` assessment with a mandatory `rejection_reason`. It is NOT a
    deletion -- the row and its criterion scores stay exactly as entered, attributed to their
    author -- it simply stops scoring (`model.scout_scores` only resolves `submitted` /
    `signed_off` rows) and drops out of the sign-off queue. `approved_by` / `approved_at` are
    reused to record who rejected it and when, since they already mean "the reviewer who
    acted on this row and when", not "who approved this".

    Deliberately NOT unique on (player_id, competition_id, season_id, dimension), unlike its
    player/competition/season-keyed siblings elsewhere in this file (PlayerSeasonMetric,
    PlayerScore, Archetype, ...): several people may assess the same player-season on the
    same dimension, and every one of their rows is kept so disagreement between assessors
    stays visible rather than being overwritten. See test_store.py for the regression test
    that guards against a future unique constraint being added here.
    """

    __tablename__ = "scout_assessments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    player_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("players.player_id"), index=True)
    competition_id: Mapped[int] = mapped_column(Integer, index=True)
    season_id: Mapped[int] = mapped_column(Integer, index=True)
    dimension: Mapped[str] = mapped_column(String, index=True)   # Psychological | Medical Risk
    author_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"))
    band: Mapped[float | None] = mapped_column(Float, nullable=True)
    band_note: Mapped[str | None] = mapped_column(String, nullable=True)
    screening_failed: Mapped[bool] = mapped_column(Boolean, server_default="false")
    notes: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, server_default="draft")
    approved_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now(),
                                                          onupdate=func.now())


class ScoutCriterionScore(Base):
    """One criterion inside an assessment. Psychological criteria carry `score` (1-5);
    medical screening criteria carry `passed`. Exactly one of the two is set -- that is an
    application-layer rule, not a database constraint: there is deliberately no CHECK
    enforcing it, because a later plan may add further kinds this schema has not
    anticipated."""

    __tablename__ = "scout_criterion_scores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    assessment_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("scout_assessments.id", ondelete="CASCADE"), index=True)
    criterion_key: Mapped[str] = mapped_column(String)
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)


class PlayerInjury(Base):
    """One injury spell. Scraped from Transfermarkt, or entered by hand where
    Transfermarkt has no coverage (Scottish/PL2).

    ONE SCHEMA, TWO PROVENANCES: `source` records where the row came from, and the
    availability rule deliberately never inspects it -- a hand-entered Scottish
    player and a scraped League One player are computed identically and are directly
    comparable. Only the display differs.
    """

    __tablename__ = "player_injuries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    player_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("players.player_id"),
                                           index=True)
    tm_player_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    season_label: Mapped[str] = mapped_column(String)          # "25/26"
    injury_type_raw: Mapped[str] = mapped_column(String)       # Transfermarkt's own wording
    injury_category: Mapped[str] = mapped_column(String, index=True)
    date_from: Mapped[datetime.date | None] = mapped_column(Date, nullable=True)
    date_until: Mapped[datetime.date | None] = mapped_column(Date, nullable=True)
    days_out: Mapped[int] = mapped_column(Integer, server_default="0")
    games_missed: Mapped[int] = mapped_column(Integer, server_default="0")
    source: Mapped[str] = mapped_column(String, server_default="transfermarkt")
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())
    entered_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)


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


# ---------------------------------------------------------------------------
# Phase 11: the combined provider-neutral metric table.
# One row per player x league x season carrying ALL registry metrics, each filled
# from its single designated source (Impect / StatsBomb advanced / StatsBomb
# computed / SkillCorner). Columns are GENERATED from the metric registry so the
# schema can never drift from the definitions: adding a metric to the registry
# and autogenerating a migration is the whole change. The live tables above stay
# untouched; scoring is re-pointed at this table in a later, explicit step.
# ---------------------------------------------------------------------------
from lofc.model.metric_registry import REGISTRY as _METRIC_REGISTRY  # noqa: E402


class PlayerMetricNeutral(Base):
    """Combined 87-metric row per player-league-season (Phase 11 neutral layer)."""

    __tablename__ = "player_metrics_neutral"
    __table_args__ = (
        UniqueConstraint("player_id", "competition_id", "season_id",
                         name="uq_neutral_player_comp_season"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    player_id: Mapped[int] = mapped_column(BigInteger, index=True)
    competition_id: Mapped[int] = mapped_column(Integer, index=True)
    season_id: Mapped[int] = mapped_column(Integer, index=True)
    player_name: Mapped[str] = mapped_column(String)
    team_name: Mapped[str] = mapped_column(String)
    position_group: Mapped[str] = mapped_column(String)
    minutes: Mapped[float] = mapped_column(Float)
    rankable: Mapped[bool] = mapped_column(Boolean)


# Attach one nullable Float column per registry metric (nullable because a source
# can be absent for a season, e.g. no physical data before 2025/26).
for _spec in _METRIC_REGISTRY:
    setattr(PlayerMetricNeutral, _spec.name, mapped_column(Float, nullable=True))
del _spec
