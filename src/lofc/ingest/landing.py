"""Read and write raw StatsBomb payloads under data/raw/.

Idempotent: a file that already exists and is non-empty is not rewritten unless
force=True, so a re-run does no duplicate work and an interrupted run resumes.

Layout:
  data/raw/competitions.json
  data/raw/<competition_id>/<season_id>/matches.json
  data/raw/<competition_id>/<season_id>/events/<match_id>.json
  data/raw/<competition_id>/<season_id>/lineups/<match_id>.json
"""

from __future__ import annotations

import json
from pathlib import Path

from lofc.config import settings


def raw_root() -> Path:
    return Path(settings.raw_data_dir)


def competitions_path() -> Path:
    return raw_root() / "competitions.json"


def season_dir(competition_id: int, season_id: int) -> Path:
    return raw_root() / str(competition_id) / str(season_id)


def matches_path(competition_id: int, season_id: int) -> Path:
    return season_dir(competition_id, season_id) / "matches.json"


def events_path(competition_id: int, season_id: int, match_id: int) -> Path:
    return season_dir(competition_id, season_id) / "events" / f"{match_id}.json"


def lineups_path(competition_id: int, season_id: int, match_id: int) -> Path:
    return season_dir(competition_id, season_id) / "lineups" / f"{match_id}.json"


def exists(path: Path) -> bool:
    """A present, non-empty file counts as already landed."""
    return path.exists() and path.stat().st_size > 0


def write_json(path: Path, data, force: bool = False) -> bool:
    """Write data as JSON. Return True if written, False if skipped.

    Writes to a temporary file then renames, so an interrupted write cannot leave
    a half-written file that the skip check would mistake for complete.
    """
    if exists(path) and not force:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    tmp.replace(path)
    return True


def read_json(path: Path):
    with path.open(encoding="utf-8") as f:
        return json.load(f)
