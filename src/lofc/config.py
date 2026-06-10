"""Application configuration.

All credentials and parameters load from environment variables / a local ``.env``
file via pydantic-settings, so nothing sensitive lives in code. Import the shared
``settings`` instance, or construct ``Settings()`` directly (e.g. in tests).
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import BaseModel, Field
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

    # --- Paths --------------------------------------------------------------
    raw_data_dir: str = Field(default="data/raw")
    reference_data_dir: str = Field(default="data/reference")

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


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance for app-wide reuse."""
    return Settings()


settings = get_settings()
