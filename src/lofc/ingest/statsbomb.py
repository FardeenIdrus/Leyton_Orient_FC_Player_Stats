"""StatsBomb data access via statsbombpy.

Open data by default (no credentials). If the config supplies API credentials and
open-data mode is off, the same calls hit the paid StatsBomb API instead. This is
the only module that talks to statsbombpy, so the open-data vs API choice lives in
one place.

All getters return plain Python lists/dicts (fmt="dict") so the orchestrator can
write them straight to disk as raw JSON. Events use flatten_attrs=False to keep
StatsBomb's original nested structure.
"""

from __future__ import annotations

import warnings

from statsbombpy import sb

from lofc.config import settings

# statsbombpy warns on every call when no credentials are set. That is expected in
# open-data mode, so silence just that one message to keep the pull logs readable.
warnings.filterwarnings("ignore", message="credentials were not supplied")


def _creds() -> dict | None:
    """Credentials dict for the paid API, or None to use open data."""
    if settings.statsbomb_authenticated:
        return {"user": settings.sb_username, "passwd": settings.sb_password}
    return None


def _call(func, *args, **kwargs):
    """Call a statsbombpy function, passing credentials only in API mode."""
    creds = _creds()
    if creds is not None:
        kwargs["creds"] = creds
    return func(*args, **kwargs)


def data_source() -> str:
    """Human-readable label for which source the next call will hit."""
    if settings.statsbomb_authenticated:
        return "StatsBomb API (authenticated)"
    return "StatsBomb open data"


def get_competitions() -> list[dict]:
    """All competitions/seasons available to the current source."""
    data = _call(sb.competitions, fmt="dict")
    return list(data.values())


def get_matches(competition_id: int, season_id: int) -> list[dict]:
    """Every match in one competition season."""
    data = _call(sb.matches, competition_id, season_id, fmt="dict")
    return list(data.values())


def get_events(match_id: int) -> list[dict]:
    """Raw, nested event records for one match."""
    data = _call(sb.events, match_id, fmt="dict", flatten_attrs=False)
    return list(data.values())


def get_lineups(match_id: int) -> dict:
    """Lineups for one match, keyed by team id."""
    return _call(sb.lineups, match_id, fmt="dict")
