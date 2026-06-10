"""Roll up per-match numbers into one row per player per competition season.

For each player: sum minutes and every counting metric across all their matches,
convert counts to per-90, pick the position group they played most, and flag whether
they have enough minutes to be ranked fairly. Output is one tidy table per league,
ready for Phase 3 to load into Postgres.
"""

from __future__ import annotations

from collections import defaultdict

import pandas as pd

from lofc.aggregate.events import POSITION_GROUPS, extract_match
from lofc.config import Competition
from lofc.ingest import landing

# Below this many minutes a player's per-90 numbers are too noisy to rank.
RANKABLE_MINUTES = 450

# Counting metrics that get summed then divided to a per-90 rate.
COUNTING_METRICS = [
    "goals", "np_goals", "xg", "np_xg", "shots",
    "assists", "xa", "key_passes",
    "passes", "passes_completed", "progressive_passes",
    "passes_into_final_third", "passes_into_box",
    "dribbles", "dribbles_completed", "carries", "progressive_carries",
    "pressures", "tackles", "interceptions", "blocks", "clearances", "ball_recoveries",
    "gk_saves",
]

# Season totals kept on the row as-is (handy for reading and spot-checks).
TOTAL_COLUMNS = ["goals", "np_goals", "assists", "shots", "xg", "np_xg", "xa"]


def _new_accumulator(name: str) -> dict:
    return {
        "player_name": name,
        "birth_date": None,
        "seconds": 0.0,
        "matches": 0,
        "position_seconds": defaultdict(float),
        "team_seconds": defaultdict(float),
        "metrics": defaultdict(float),
        "gk_conceded": 0,
    }


def _main_goalkeeper_per_team(players: dict) -> dict[int, int]:
    """The player_id that kept goal longest for each team in one match."""
    best: dict[int, tuple[int, float]] = {}
    for pid, info in players.items():
        gk_seconds = info["position_seconds"].get(1, 0.0)
        if gk_seconds <= 0:
            continue
        current = best.get(info["team_id"])
        if current is None or gk_seconds > current[1]:
            best[info["team_id"]] = (pid, gk_seconds)
    return {team_id: pid for team_id, (pid, _) in best.items()}


def aggregate_competition(comp: Competition, log=print) -> pd.DataFrame:
    """Build the player-season table for one competition season."""
    cid, sid = comp.competition_id, comp.season_id
    matches = landing.read_json(landing.matches_path(cid, sid))
    comp_name = matches[0]["competition"]["competition_name"]
    season_name = matches[0]["season"]["season_name"]

    acc: dict[int, dict] = {}
    total = len(matches)
    for i, match in enumerate(sorted(matches, key=lambda m: m["match_id"]), start=1):
        mid = match["match_id"]
        events = landing.read_json(landing.events_path(cid, sid, mid))
        lineups = landing.read_json(landing.lineups_path(cid, sid, mid))
        # Real feeds occasionally serve an empty payload for one fixture; one bad
        # match must not kill a 4,000-match run. Skip it loudly and move on.
        if not events:
            log(f"  [{comp.label}] WARNING: match {mid} has no events, skipping")
            continue
        data = extract_match(events, lineups)

        for pid, info in data["players"].items():
            a = acc.setdefault(pid, _new_accumulator(info["player_name"]))
            a["birth_date"] = a["birth_date"] or info.get("birth_date")
            a["seconds"] += info["seconds"]
            a["matches"] += 1
            a["team_seconds"][info["team_name"]] += info["seconds"]
            for pos_id, sec in info["position_seconds"].items():
                a["position_seconds"][pos_id] += sec
            for key, value in info["metrics"].items():
                a["metrics"][key] += value

        # Attribute each team's conceded goals to its main goalkeeper that match.
        gk_of = _main_goalkeeper_per_team(data["players"])
        for team_id, conceded in data["team_goals_against"].items():
            if team_id in gk_of:
                acc[gk_of[team_id]]["gk_conceded"] += conceded

        if i % 50 == 0 or i == total:
            log(f"  [{comp.label}] {i}/{total} matches, {len(acc)} players so far")

    return _build_table(acc, cid, comp_name, sid, season_name)


def _build_table(acc, cid, comp_name, sid, season_name) -> pd.DataFrame:
    rows = []
    for pid, a in acc.items():
        minutes = a["seconds"] / 60.0
        if minutes <= 0:
            continue
        dominant_position = max(a["position_seconds"], key=a["position_seconds"].get)
        team = max(a["team_seconds"], key=a["team_seconds"].get)
        metrics = a["metrics"]

        row = {
            "competition_id": cid,
            "competition_name": comp_name,
            "season_id": sid,
            "season_name": season_name,
            "player_id": pid,
            "player_name": a["player_name"],
            "birth_date": a["birth_date"],
            "team_name": team,
            "position_group": POSITION_GROUPS.get(dominant_position, "Unknown"),
            "dominant_position_id": dominant_position,
            "minutes": round(minutes, 1),
            "matches_played": a["matches"],
            "rankable": minutes >= RANKABLE_MINUTES,
        }
        for col in TOTAL_COLUMNS:
            row[col] = round(metrics.get(col, 0.0), 2)
        for metric in COUNTING_METRICS:
            row[f"{metric}_p90"] = round(metrics.get(metric, 0.0) / minutes * 90.0, 3)

        passes = metrics.get("passes", 0.0)
        dribbles = metrics.get("dribbles", 0.0)
        saves, conceded = metrics.get("gk_saves", 0.0), a["gk_conceded"]
        row["pass_completion_pct"] = round(metrics.get("passes_completed", 0.0) / passes, 3) if passes else None
        row["dribble_success_pct"] = round(metrics.get("dribbles_completed", 0.0) / dribbles, 3) if dribbles else None
        row["goals_conceded"] = conceded
        row["save_pct"] = round(saves / (saves + conceded), 3) if (saves + conceded) > 0 else None
        rows.append(row)

    table = pd.DataFrame(rows).sort_values(["position_group", "minutes"], ascending=[True, False])
    return table.reset_index(drop=True)
