"""Load the club-provided SkillCorner tracking export into Postgres.

The xlsx in data/reference/skillcorner/ holds physical (tracking) data for League
One: team-level sheets cover all 24 clubs, player-level sheets cover Leyton
Orient's own squad only. We load the two season sheets into
skillcorner_team_season and skillcorner_player_season, and match LOFC players to
our players table by birth date + name so physical data joins onto scores.

Scope note (also in docs/methodology.md): player-level tracking exists for our
squad only, so it informs the club's own physical identity and league
benchmarking. It can never score recruitment targets.

Run with:  python -m lofc.ingest.skillcorner
"""

from __future__ import annotations

import difflib
from pathlib import Path

import openpyxl
import pandas as pd

from lofc.config import settings
from lofc.model.valuation import DOB_NAME_CUTOFF, _norm
from lofc.store.load import _records, _upsert, get_engine
from lofc.store.models import SkillCornerPlayerSeason, SkillCornerTeamSeason

# Sheet header -> metric column, shared by the team and player season sheets.
METRIC_MAP = {
    "Minutes": "avg_minutes",
    "Distance P90": "distance_p90",
    "M/min P90": "m_per_min_p90",
    "Running Distance P90": "running_distance_p90",
    "HSR Distance P90": "hsr_distance_p90",
    "HSR Count P90": "hsr_count_p90",
    "Sprint Distance P90": "sprint_distance_p90",
    "Sprint Count P90": "sprint_count_p90",
    "HI Distance P90": "hi_distance_p90",
    "HI Count P90": "hi_count_p90",
    "PSV-99": "psv99_kmh",
    "TOP 5 PSV-99": "top5_psv99_kmh",
    "Medium Acceleration Count P90": "medium_accel_count_p90",
    "High Acceleration Count P90": "high_accel_count_p90",
    "Medium Deceleration Count P90": "medium_decel_count_p90",
    "High Deceleration Count P90": "high_decel_count_p90",
    "Explosive Acceleration to HSR Count P90": "explosive_accel_to_hsr_p90",
    "Explosive Acceleration to Sprint Count P90": "explosive_accel_to_sprint_p90",
    "Change of Direction Count P90": "cod_count_p90",
}
MEASURED = "Count Performances (Physical Check passed)"


def source_file() -> Path | None:
    """The newest SkillCorner export on disk, or None."""
    folder = Path(settings.reference_data_dir) / "skillcorner"
    files = sorted(folder.glob("*.xlsx"))
    return files[-1] if files else None


def _cell(value):
    """SkillCorner writes literal 'null' strings for missing numbers."""
    return None if value in (None, "null", "") else value


def read_sheet(path: Path, sheet: str) -> list[dict]:
    """One dict per row, keyed by the sheet's header names."""
    book = openpyxl.load_workbook(path, read_only=True)
    rows = list(book[sheet].iter_rows(values_only=True))
    header = list(rows[0])
    return [dict(zip(header, (_cell(v) for v in row))) for row in rows[1:]]


def team_season_records(path: Path) -> list[dict]:
    records = []
    for row in read_sheet(path, "Team x Season (avg P90)"):
        rec = {
            "sc_team_id": int(row["Team ID"]),
            "team_name": str(row["Team"]),
            "season_label": str(row["Season"]),
            "matches_measured": int(row[MEASURED] or 0),
        }
        rec.update({col: row.get(src) for src, col in METRIC_MAP.items()})
        records.append(rec)
    return records


def player_season_records(path: Path) -> list[dict]:
    records = []
    for row in read_sheet(path, "Player x Season (avg P90)"):
        birth = row.get("Birthdate")
        rec = {
            "sc_player_id": int(row["Player ID"]),
            "player_name": str(row["Player"]),
            # ISO string, not a date object: rows pass through a JSON round-trip on
            # the way to the upsert, which would turn dates into epoch integers.
            "birth_date": birth.date().isoformat() if hasattr(birth, "date") else None,
            "season_label": str(row["Season"]),
            "matches_measured": int(row[MEASURED] or 0),
        }
        rec.update({col: row.get(src) for src, col in METRIC_MAP.items()})
        records.append(rec)
    return records


def match_player_ids(records: list[dict], engine) -> int:
    """Fill player_id on each record via birth date + name against our players table."""
    players = pd.read_sql("SELECT player_id, player_name, birth_date FROM players "
                          "WHERE birth_date IS NOT NULL", engine)
    # ISO strings on both sides of the lookup (records carry ISO, see above).
    players["birth_date"] = pd.to_datetime(players["birth_date"]).dt.date.astype(str)
    players["nname"] = players["player_name"].map(_norm)
    by_dob = {dob: grp for dob, grp in players.groupby("birth_date")}

    matched = 0
    for rec in records:
        rec["player_id"] = None
        candidates = by_dob.get(rec["birth_date"])
        if candidates is None:
            continue
        ours = " ".join(sorted(_norm(rec["player_name"]).split()))
        best_score, best_id = 0.0, None
        for cand in candidates.itertuples():
            score = difflib.SequenceMatcher(
                None, ours, " ".join(sorted(cand.nname.split()))).ratio()
            if score > best_score:
                best_score, best_id = score, int(cand.player_id)
        if best_id is not None and best_score >= DOB_NAME_CUTOFF:
            rec["player_id"] = best_id
            matched += 1
    return matched


def main() -> None:
    path = source_file()
    if path is None:
        print("no SkillCorner export found in data/reference/skillcorner/, skipping")
        return
    print(f"SkillCorner source: {path.name}")

    engine = get_engine()
    teams = team_season_records(path)
    players = player_season_records(path)
    matched = match_player_ids(players, engine)

    # The export is the source of truth: clear then insert, like other reference data.
    with engine.begin() as conn:
        conn.execute(SkillCornerTeamSeason.__table__.delete())
        conn.execute(SkillCornerPlayerSeason.__table__.delete())
    n_teams = _upsert(engine, SkillCornerTeamSeason.__table__, _records(pd.DataFrame(teams)),
                      ["sc_team_id", "season_label"])
    n_players = _upsert(engine, SkillCornerPlayerSeason.__table__, _records(pd.DataFrame(players)),
                        ["sc_player_id", "season_label"])

    unmatched = [r["player_name"] for r in players if r["player_id"] is None]
    print(f"skillcorner_team_season: {n_teams} clubs")
    print(f"skillcorner_player_season: {n_players} LOFC players, {matched} matched to StatsBomb ids")
    if unmatched:
        print(f"unmatched ({len(unmatched)}): {', '.join(unmatched)}")


if __name__ == "__main__":
    main()
