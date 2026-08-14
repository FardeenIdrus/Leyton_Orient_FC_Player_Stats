"""Application configuration.

All credentials and parameters load from environment variables / a local ``.env``
file via pydantic-settings, so nothing sensitive lives in code. Import the shared
``settings`` instance, or construct ``Settings()`` directly (e.g. in tests).
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import BaseModel, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Competition(BaseModel):
    """A StatsBomb competition+season target identified by its IDs."""

    competition_id: int
    season_id: int
    label: str


# Default demo competitions: the three complete 2015/16 leagues.
# Data vintage does not affect the pipeline; this is the only set of complete
# men's-club league seasons available on the StatsBomb free tier. Real targets
# (e.g. the EFL leagues on the paid feed) are set via SB_COMPETITIONS instead.
DEFAULT_COMPETITIONS: list[Competition] = [
    Competition(competition_id=2, season_id=27, label="Premier League 2015/16"),
    Competition(competition_id=11, season_id=27, label="La Liga 2015/16"),
    Competition(competition_id=12, season_id=27, label="Serie A 2015/16"),
    
]


class ImpectTarget(BaseModel):
    """An Impect competition iteration (one league season) to ingest.

    sb_competition_id / sb_season_id tie the iteration to the StatsBomb league
    season already in the database (for the EFL, where we can compare the two
    sources player by player). None means we hold no StatsBomb data for that
    league (the Scottish leagues and PL2).

    competition_id / season_id are OUR internal league-season keys, the same
    space every table uses. For an EFL target they default to the StatsBomb ids
    (the two sources describe the same league). For an Impect-only league they are
    minted keys (competition_id in the 900s), and spine_source="impect" tells the
    build to derive player identity/minutes/position from Impect, not StatsBomb.
    """

    iteration_id: int
    label: str
    sb_competition_id: int | None = None
    sb_season_id: int | None = None
    competition_id: int | None = None
    season_id: int | None = None
    spine_source: str = "statsbomb"      # "statsbomb" (EFL) | "impect" (new leagues)

    @model_validator(mode="after")
    def _default_keys_to_statsbomb(self) -> "ImpectTarget":
        # EFL targets: our keys ARE the StatsBomb keys (same league, two providers).
        if self.competition_id is None:
            self.competition_id = self.sb_competition_id
        if self.season_id is None:
            self.season_id = self.sb_season_id
        return self

    @property
    def competition_name(self) -> str:
        """League name (the label without its trailing season), for display."""
        parts = self.label.rsplit(" ", 1)
        return parts[0] if len(parts) == 2 and "/" in parts[1] else self.label


# The live Impect targets: the four EFL leagues mirrored from the StatsBomb era,
# (Scottish Premiership and Championship, PL2),
# each for 2024/25 + 2025/26. Iteration ids verified against the licence's
# iteration catalogue on 2026-07-07.
DEFAULT_IMPECT_TARGETS: list[ImpectTarget] = [
    ImpectTarget(iteration_id=1022, label="Championship 2024/25", sb_competition_id=3, sb_season_id=317),
    ImpectTarget(iteration_id=1410, label="Championship 2025/26", sb_competition_id=3, sb_season_id=318),
    ImpectTarget(iteration_id=1023, label="League One 2024/25", sb_competition_id=4, sb_season_id=317),
    ImpectTarget(iteration_id=1465, label="League One 2025/26", sb_competition_id=4, sb_season_id=318),
    ImpectTarget(iteration_id=1021, label="League Two 2024/25", sb_competition_id=5, sb_season_id=317),
    ImpectTarget(iteration_id=1464, label="League Two 2025/26", sb_competition_id=5, sb_season_id=318),
    ImpectTarget(iteration_id=1062, label="National League 2024/25", sb_competition_id=65, sb_season_id=317),
    ImpectTarget(iteration_id=1511, label="National League 2025/26", sb_competition_id=65, sb_season_id=318),
    # Impect-only leagues: no StatsBomb data, so Impect IS the spine. Minted internal
    # competition_ids (900s, clear of StatsBomb's ids); season_id reuses the EFL era
    # convention (317 = 2024/25, 318 = 2025/26).
    ImpectTarget(iteration_id=1033, label="Scottish Premiership 2024/25",
                 competition_id=901, season_id=317, spine_source="impect"),
    ImpectTarget(iteration_id=1400, label="Scottish Premiership 2025/26",
                 competition_id=901, season_id=318, spine_source="impect"),
    ImpectTarget(iteration_id=1221, label="Scottish Championship 2024/25",
                 competition_id=902, season_id=317, spine_source="impect"),
    ImpectTarget(iteration_id=1474, label="Scottish Championship 2025/26",
                 competition_id=902, season_id=318, spine_source="impect"),
    ImpectTarget(iteration_id=1076, label="Premier League 2 2024/25",
                 competition_id=903, season_id=317, spine_source="impect"),
    ImpectTarget(iteration_id=1529, label="Premier League 2 2025/26",
                 competition_id=903, season_id=318, spine_source="impect"),
    # --- 2026/27 (season_id 319): the LIVE season. -------------------------------------
    # Iteration ids verified against the licence catalogue on 2026-08-04. All are
    # spine_source="impect": there is no StatsBomb 2026/27 (the licence is being retired),
    # so Impect supplies identity for every league now, EFL included.
    # Safe to configure before the season kicks off: the ingest treats "no data yet" as a
    # skip (see LIVE_SEASON_ID in ingest/impect.py) and build_neutral only builds targets
    # whose landed file exists.
    ImpectTarget(iteration_id=2114, label="Championship 2026/27",
                 competition_id=3, season_id=319, spine_source="impect"),
    ImpectTarget(iteration_id=2117, label="League One 2026/27",
                 competition_id=4, season_id=319, spine_source="impect"),
    ImpectTarget(iteration_id=2120, label="League Two 2026/27",
                 competition_id=5, season_id=319, spine_source="impect"),
    ImpectTarget(iteration_id=2125, label="National League 2026/27",
                 competition_id=65, season_id=319, spine_source="impect"),
    ImpectTarget(iteration_id=2156, label="Scottish Premiership 2026/27",
                 competition_id=901, season_id=319, spine_source="impect"),
    ImpectTarget(iteration_id=2157, label="Scottish Championship 2026/27",
                 competition_id=902, season_id=319, spine_source="impect"),
    ImpectTarget(iteration_id=2232, label="Premier League 2 2026/27",
                 competition_id=903, season_id=319, spine_source="impect"),
]

# The season currently BEING PLAYED. Its data grows every matchweek, so the ingest must
# always re-pull it (Impect returns season-to-date aggregates: a landed file is stale the
# moment the next round is played). Finished seasons stay skip-if-exists, because their
# data can no longer change.
#
# UPDATE THIS EACH AUGUST when a new season starts (and the old one becomes final).
# Set to None out of season to make every pull skip-if-exists again.
LIVE_SEASON_ID: int | None = 319          # 2026/27


def parse_impect_targets(raw: str) -> list[ImpectTarget]:
    """Parse the IMPECT_ITERATIONS env value into ImpectTarget entries.

    Format: comma-separated "iteration_id:label" entries, e.g.
    "1465:League One 2025/26,1400:Scottish Premiership 2025/26". Raises
    ValueError on malformed input so a typo fails loudly at startup. An
    env-supplied iteration keeps the default's StatsBomb mapping when its id is
    one of the known defaults; unknown ids carry no mapping.
    """
    known = {t.iteration_id: t for t in DEFAULT_IMPECT_TARGETS}
    targets: list[ImpectTarget] = []
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        parts = chunk.split(":", 1)
        if len(parts) != 2 or not parts[1].strip():
            raise ValueError(
                f"IMPECT_ITERATIONS entry {chunk!r} is not 'iteration_id:label'"
            )
        try:
            iteration_id = int(parts[0])
        except ValueError:
            raise ValueError(
                f"IMPECT_ITERATIONS entry {chunk!r}: iteration_id must be an integer"
            ) from None
        base = known.get(iteration_id)
        targets.append(ImpectTarget(
            iteration_id=iteration_id, label=parts[1].strip(),
            sb_competition_id=base.sb_competition_id if base else None,
            sb_season_id=base.sb_season_id if base else None))
    if not targets:
        raise ValueError("IMPECT_ITERATIONS is set but contains no iterations")
    return targets


class SkillCornerTarget(BaseModel):
    """A SkillCorner competition edition (one league season) of physical data.

    competition_id / season_id tie the edition to our own league-season keys so
    physical data lands on the matching player-season row. None means we do not
    yet hold that league in our database (Scottish/PL2/Irish), so it is pulled
    but only joins players who also appear in a league we track.
    """

    edition_id: int
    label: str
    competition_id: int | None = None
    season_id: int | None = None


# The live SkillCorner targets: the covered leagues for 2025/26 (the season that
# overlaps our event data). SkillCorner physical covers 2025/26 + 2026/27 only
# (no 2024/25); 2026/27 is added once we track that season. Edition ids verified
# against the licence's competition-editions catalogue on 2026-07-10.
DEFAULT_SKILLCORNER_TARGETS: list[SkillCornerTarget] = [
    SkillCornerTarget(edition_id=1216, label="Championship 2025/26", competition_id=3, season_id=318),
    SkillCornerTarget(edition_id=1211, label="League One 2025/26", competition_id=4, season_id=318),
    SkillCornerTarget(edition_id=1214, label="League Two 2025/26", competition_id=5, season_id=318),
    SkillCornerTarget(edition_id=1247, label="National League 2025/26", competition_id=65, season_id=318),
    SkillCornerTarget(edition_id=1259, label="Premier League 2 2025/26",
                      competition_id=903, season_id=318),
    SkillCornerTarget(edition_id=1213, label="Scottish Premiership 2025/26",
                      competition_id=901, season_id=318),
    SkillCornerTarget(edition_id=1081, label="Irish Premier Division 2025"),
    # --- 2026/27 (season_id 319): the LIVE season. ------------------------------------
    # Edition ids verified against the SkillCorner catalogue on 2026-08-10. Like the Impect
    # targets these are safe to configure before kick-off: the live season is always
    # re-pulled and an edition with no data yet is skipped, not treated as an error.
    # NOTE: SkillCorner labels the Scottish Premiership simply "Premiership" (edition 1683).
    # The SCOTTISH CHAMPIONSHIP is deliberately ABSENT: SkillCorner lists the competition and
    # editions for it but holds ZERO physical data (verified 0 rows for 2024/25 and 2025/26
    # against 358 for the Scottish Premiership). Adding it would emit a "no data" warning on
    # every weekly run forever, which would eventually mask a real failure.
    SkillCornerTarget(edition_id=1569, label="Championship 2026/27",
                      competition_id=3, season_id=319),
    SkillCornerTarget(edition_id=1574, label="League One 2026/27",
                      competition_id=4, season_id=319),
    SkillCornerTarget(edition_id=1575, label="League Two 2026/27",
                      competition_id=5, season_id=319),
    SkillCornerTarget(edition_id=1576, label="National League 2026/27",
                      competition_id=65, season_id=319),
    SkillCornerTarget(edition_id=1578, label="Premier League 2 2026/27",
                      competition_id=903, season_id=319),
    SkillCornerTarget(edition_id=1683, label="Scottish Premiership 2026/27",
                      competition_id=901, season_id=319),
]


def parse_skillcorner_targets(raw: str) -> list[SkillCornerTarget]:
    """Parse the SKILLCORNER_EDITIONS env value into SkillCornerTarget entries.

    Format: comma-separated "edition_id:label" entries. Raises ValueError on
    malformed input so a typo fails loudly. A known edition id keeps its
    competition/season mapping; an unknown id carries none.
    """
    known = {t.edition_id: t for t in DEFAULT_SKILLCORNER_TARGETS}
    targets: list[SkillCornerTarget] = []
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        parts = chunk.split(":", 1)
        if len(parts) != 2 or not parts[1].strip():
            raise ValueError(
                f"SKILLCORNER_EDITIONS entry {chunk!r} is not 'edition_id:label'"
            )
        try:
            edition_id = int(parts[0])
        except ValueError:
            raise ValueError(
                f"SKILLCORNER_EDITIONS entry {chunk!r}: edition_id must be an integer"
            ) from None
        base = known.get(edition_id)
        targets.append(SkillCornerTarget(
            edition_id=edition_id, label=parts[1].strip(),
            competition_id=base.competition_id if base else None,
            season_id=base.season_id if base else None))
    if not targets:
        raise ValueError("SKILLCORNER_EDITIONS is set but contains no editions")
    return targets


def parse_competitions(raw: str) -> list[Competition]:
    """Parse the SB_COMPETITIONS env value into Competition targets.

    Format: comma-separated "competition_id:season_id:label" entries, e.g.
    "4:318:League One 2025/26,5:318:League Two 2025/26". The label is free text
    (colons allowed, commas not). Raises ValueError on malformed input so a typo
    fails loudly at startup instead of silently ingesting the wrong league.
    """
    comps: list[Competition] = []
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        parts = chunk.split(":", 2)
        if len(parts) != 3 or not parts[2].strip():
            raise ValueError(
                f"SB_COMPETITIONS entry {chunk!r} is not 'competition_id:season_id:label'"
            )
        try:
            comp_id, season_id = int(parts[0]), int(parts[1])
        except ValueError:
            raise ValueError(
                f"SB_COMPETITIONS entry {chunk!r}: competition_id and season_id must be integers"
            ) from None
        comps.append(Competition(competition_id=comp_id, season_id=season_id, label=parts[2].strip()))
    if not comps:
        raise ValueError("SB_COMPETITIONS is set but contains no competitions")
    return comps


class Settings(BaseSettings):
    """Runtime settings, sourced from the environment / ``.env``."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Database -----------------------------------------------------------
    database_url: str = Field(
        default="postgresql+psycopg2://lofc:lofc@db:5432/lofc",
        description="SQLAlchemy connection URL for the Postgres store.",
    )

    # --- StatsBomb data source ---------------------------------------------
    # Open-data mode (the default) needs no credentials. Setting use_open_data
    # to False with SB_USERNAME/SB_PASSWORD present switches statsbombpy to the
    # authenticated API. This is a config swap, not a code change.
    use_open_data: bool = Field(default=True)
    sb_username: str | None = Field(default=None)
    sb_password: str | None = Field(default=None)

    # Target competitions as "competition_id:season_id:label,..." (see
    # parse_competitions). Unset means the open-data demo trio.
    sb_competitions: str | None = Field(default=None)

    # --- Impect data source ---------------------------------------------------
    # The club's second event-data provider (and the intended future primary).
    # Credentials are the Impect platform login; both must be present for any
    # Impect pull. Target iterations as "iteration_id:label,..." (see
    # parse_impect_targets). Unset means DEFAULT_IMPECT_TARGETS.
    impect_username: str | None = Field(default=None)
    impect_password: str | None = Field(default=None)
    impect_iterations: str | None = Field(default=None)
    # Override the season treated as "currently being played" (always re-pulled). Blank uses
    # LIVE_SEASON_ID above; "none" turns the always-refresh off (every pull skip-if-exists).
    live_season_id_override: str | None = Field(default=None)

    # --- SkillCorner data source (physical/tracking, all players in covered leagues) --
    # The club's SkillCorner platform login. Both required for any pull. Target
    # editions as "edition_id:label,..." (see parse_skillcorner_targets). Unset means
    # DEFAULT_SKILLCORNER_TARGETS.
    skillcorner_username: str | None = Field(default=None)
    skillcorner_password: str | None = Field(default=None)
    skillcorner_editions: str | None = Field(default=None)

    # --- Scoring source (Phase A of the Impect migration) --------------------
    # Which metric table the scorer reads. "neutral" = the provider-neutral
    # player_metrics_neutral (87 metrics, Impect-primary where it supplies a metric);
    # "statsbomb" = the original StatsBomb-only player_season_metrics. Default is the
    # neutral table; the toggle keeps the switch reversible and A/B-testable.
    scoring_source: str = Field(default="neutral")

    # --- Impect-only mode (Phase C: retire StatsBomb) ------------------------
    # When True the EFL is built from the IMPECT identity spine too (not StatsBomb),
    # and scoring maps the StatsBomb-only role/identity metrics to their validated
    # Impect successors (tackles->duels won, interceptions/recoveries->ball wins,
    # progressive passes->packing, etc). The whole platform then runs on Impect +
    # SkillCorner, so StatsBomb can be switched off. Reversible: set False to restore
    # the StatsBomb-spined EFL and the original metric sets.
    impect_only: bool = Field(default=False)

    # --- Paths --------------------------------------------------------------
    raw_data_dir: str = Field(default="data/raw")
    reference_data_dir: str = Field(default="data/reference")

    @property
    def scoring_metrics_table(self) -> str:
        """The DB table the scorer reads, per scoring_source."""
        table = {"neutral": "player_metrics_neutral",
                 "statsbomb": "player_season_metrics"}.get(self.scoring_source)
        if table is None:
            raise ValueError(
                f"SCORING_SOURCE must be 'neutral' or 'statsbomb', got {self.scoring_source!r}")
        return table

    @property
    def competitions(self) -> list[Competition]:
        """Target competitions to ingest.

        SB_COMPETITIONS in the environment overrides the default demo trio.
        """
        if self.sb_competitions:
            return parse_competitions(self.sb_competitions)
        return DEFAULT_COMPETITIONS

    @property
    def statsbomb_authenticated(self) -> bool:
        """True when configured to use the paid StatsBomb API."""
        return not self.use_open_data and bool(self.sb_username and self.sb_password)

    @property
    def impect_targets(self) -> list[ImpectTarget]:
        """Impect iterations to ingest; IMPECT_ITERATIONS overrides the defaults."""
        if self.impect_iterations:
            return parse_impect_targets(self.impect_iterations)
        return DEFAULT_IMPECT_TARGETS

    @property
    def live_season_id(self) -> int | None:
        """The season currently being played, whose data must always be re-pulled (its
        totals grow every matchweek). LIVE_SEASON_ID_OVERRIDE sets it per environment;
        blank/"none" disables the always-refresh behaviour entirely."""
        raw = (self.live_season_id_override or "").strip().lower()
        if raw in {"none", "null", "off"}:
            return None
        if raw:
            return int(raw)
        return LIVE_SEASON_ID

    @property
    def impect_authenticated(self) -> bool:
        """True when Impect credentials are configured."""
        return bool(self.impect_username and self.impect_password)

    @property
    def skillcorner_targets(self) -> list[SkillCornerTarget]:
        """SkillCorner editions to ingest; SKILLCORNER_EDITIONS overrides the defaults."""
        if self.skillcorner_editions:
            return parse_skillcorner_targets(self.skillcorner_editions)
        return DEFAULT_SKILLCORNER_TARGETS

    @property
    def skillcorner_authenticated(self) -> bool:
        """True when SkillCorner credentials are configured."""
        return bool(self.skillcorner_username and self.skillcorner_password)


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance for app-wide reuse."""
    return Settings()


settings = get_settings()
