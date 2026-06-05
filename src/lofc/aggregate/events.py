"""Turn one match's raw events and lineups into per-player numbers.

Two jobs:
  1. Minutes played and position time, derived from the lineup position spells.
     The match clock restarts at 45:00 each half, so a spell that crosses halves
     is converted to a single cumulative timeline using each period's real length.
  2. Counting metrics per player from the event stream (goals, xG, passes, etc.).

Pitch is 120 long by 80 wide. StatsBomb records every team as attacking towards
x=120, so "towards goal" always means a larger x.
"""

from __future__ import annotations

from collections import defaultdict

# StatsBomb position_id (1-25) grouped into the 8 groups we rank within.
POSITION_GROUPS: dict[int, str] = {
    1: "Goalkeeper",
    2: "Full Back", 6: "Full Back", 7: "Full Back", 8: "Full Back",
    3: "Centre Back", 4: "Centre Back", 5: "Centre Back",
    9: "Defensive Mid", 10: "Defensive Mid", 11: "Defensive Mid",
    13: "Central Mid", 14: "Central Mid", 15: "Central Mid",
    12: "Winger", 16: "Winger", 17: "Winger", 21: "Winger",
    18: "Attacking Mid", 19: "Attacking Mid", 20: "Attacking Mid",
    22: "Centre Forward", 23: "Centre Forward", 24: "Centre Forward", 25: "Centre Forward",
}

# A pass/carry counts as progressive if it moves the ball at least this many metres
# towards the opponent goal. A single clear threshold, documented as our definition.
PROGRESSIVE_PASS_METRES = 15.0
PROGRESSIVE_CARRY_METRES = 10.0

# Pitch landmarks.
FINAL_THIRD_X = 80.0
BOX_X, BOX_Y_MIN, BOX_Y_MAX = 102.0, 18.0, 62.0


def parse_clock(value: str) -> float:
    """Convert a 'MM:SS' or 'HH:MM:SS' lineup time to seconds."""
    parts = [int(p) for p in value.split(":")]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    return parts[0] * 3600 + parts[1] * 60 + parts[2]


def period_bounds(events: list[dict]) -> dict[int, tuple[float, float]]:
    """First and last clock second seen in each period (ignoring shootouts)."""
    lo: dict[int, float] = {}
    hi: dict[int, float] = {}
    for e in events:
        period = e["period"]
        if period > 4:  # period 5 is a penalty shootout, not playing time
            continue
        t = e["minute"] * 60 + e["second"]
        lo[period] = min(lo.get(period, t), t)
        hi[period] = max(hi.get(period, t), t)
    return {p: (lo[p], hi[p]) for p in lo}


def _cumulative_offsets(bounds: dict[int, tuple[float, float]]) -> dict[int, float]:
    """Seconds of play before each period starts, so halves join into one timeline."""
    offsets: dict[int, float] = {}
    running = 0.0
    for p in sorted(bounds):
        offsets[p] = running
        start, end = bounds[p]
        running += end - start
    return offsets


def _cumulative(period: int, second: float, bounds, offsets) -> float:
    """Position on the single match timeline for a (period, clock-second)."""
    start, _ = bounds[period]
    return offsets[period] + (second - start)


def _spell_seconds(spell: dict, bounds, offsets) -> float:
    """Duration of one position spell, correct across the half-time clock reset."""
    from_p = spell["from_period"]
    start = _cumulative(from_p, parse_clock(spell["from"]), bounds, offsets)

    # "to" is null when the player was still on at the final whistle.
    to_p = spell.get("to_period") or max(bounds)
    if spell.get("to"):
        end = _cumulative(to_p, parse_clock(spell["to"]), bounds, offsets)
    else:
        end = _cumulative(to_p, bounds[to_p][1], bounds, offsets)
    return max(0.0, end - start)


def player_minutes(lineups: dict, bounds, offsets) -> dict:
    """Seconds played and per-position seconds for every player who appeared."""
    out: dict = {}
    for team in lineups.values():
        for p in team["lineup"]:
            pos_seconds: dict[int, float] = defaultdict(float)
            for spell in p.get("positions") or []:
                pos_seconds[spell["position_id"]] += _spell_seconds(spell, bounds, offsets)
            total = sum(pos_seconds.values())
            if total <= 0:
                continue  # unused substitute
            out[p["player_id"]] = {
                "player_name": p.get("player_nickname") or p["player_name"],
                "team_id": team["team_id"],
                "team_name": team["team_name"],
                "seconds": total,
                "position_seconds": dict(pos_seconds),
            }
    return out


def _in_box(x: float, y: float) -> bool:
    return x >= BOX_X and BOX_Y_MIN <= y <= BOX_Y_MAX


def match_metrics(events: list[dict]) -> dict:
    """Raw counting metrics per player for one match."""
    m: dict = defaultdict(lambda: defaultdict(float))
    passer_of: dict[str, int] = {}  # pass event id -> player who made it (for xA)

    for e in events:
        player = e.get("player")
        if not player:
            continue  # team-level events (Starting XI, formation changes)
        pid = player["id"]
        etype = e["type"]["name"]
        stat = m[pid]

        if etype == "Pass":
            passer_of[e["id"]] = pid
            pdata = e.get("pass", {})
            stat["passes"] += 1
            if pdata.get("goal_assist"):
                stat["assists"] += 1
            if pdata.get("shot_assist"):
                stat["key_passes"] += 1
            # A completed pass has no outcome recorded under "pass".
            if pdata.get("outcome") is None:
                stat["passes_completed"] += 1
                start, end = e.get("location"), pdata.get("end_location")
                if start and end:
                    sx, ex, ey = start[0], end[0], end[1]
                    if ex - sx >= PROGRESSIVE_PASS_METRES:
                        stat["progressive_passes"] += 1
                    if sx < FINAL_THIRD_X <= ex:
                        stat["passes_into_final_third"] += 1
                    if _in_box(ex, ey) and not _in_box(sx, start[1]):
                        stat["passes_into_box"] += 1

        elif etype == "Shot":
            sd = e.get("shot", {})
            xg = sd.get("statsbomb_xg") or 0.0
            is_penalty = sd.get("type", {}).get("name") == "Penalty"
            is_goal = sd.get("outcome", {}).get("name") == "Goal"
            stat["shots"] += 1
            stat["xg"] += xg
            if is_goal:
                stat["goals"] += 1
            if not is_penalty:
                stat["np_xg"] += xg
                if is_goal:
                    stat["np_goals"] += 1

        elif etype == "Dribble":
            stat["dribbles"] += 1
            if e.get("dribble", {}).get("outcome", {}).get("name") == "Complete":
                stat["dribbles_completed"] += 1

        elif etype == "Carry":
            stat["carries"] += 1
            start, end = e.get("location"), e.get("carry", {}).get("end_location")
            if start and end and end[0] - start[0] >= PROGRESSIVE_CARRY_METRES:
                stat["progressive_carries"] += 1

        elif etype == "Pressure":
            stat["pressures"] += 1
        elif etype == "Interception":
            stat["interceptions"] += 1
        elif etype == "Block":
            stat["blocks"] += 1
        elif etype == "Clearance":
            stat["clearances"] += 1
        elif etype == "Ball Recovery":
            stat["ball_recoveries"] += 1
        elif etype == "Duel":
            if e.get("duel", {}).get("type", {}).get("name") == "Tackle":
                stat["tackles"] += 1
        elif etype == "Goal Keeper":
            # Loose match on "Saved" covers Shot Saved, Penalty Saved, Saved To Post.
            if "Saved" in e.get("goalkeeper", {}).get("type", {}).get("name", ""):
                stat["gk_saves"] += 1

    # xA: give each shot's xG to whoever played the key pass that created it.
    for e in events:
        if e["type"]["name"] != "Shot":
            continue
        key_pass_id = e.get("shot", {}).get("key_pass_id")
        passer = passer_of.get(key_pass_id) if key_pass_id else None
        if passer is not None:
            m[passer]["xa"] += e.get("shot", {}).get("statsbomb_xg") or 0.0

    return {pid: dict(stat) for pid, stat in m.items()}


def team_goals_against(events: list[dict]) -> dict[int, int]:
    """Goals each team conceded in the match (open play, set pieces, own goals)."""
    teams = {e["team"]["id"] for e in events if e.get("team")}
    scored: dict[int, int] = defaultdict(int)
    for e in events:
        etype = e["type"]["name"]
        if etype == "Shot" and e.get("shot", {}).get("outcome", {}).get("name") == "Goal":
            scored[e["team"]["id"]] += 1
        elif etype == "Own Goal For":
            scored[e["team"]["id"]] += 1
    # In a two-team match, a team concedes what the other team scored.
    against: dict[int, int] = {}
    for t in teams:
        against[t] = sum(g for other, g in scored.items() if other != t)
    return against


def extract_match(events: list[dict], lineups: dict) -> dict:
    """Per-player minutes, positions and metrics for one match."""
    bounds = period_bounds(events)
    offsets = _cumulative_offsets(bounds)
    minutes = player_minutes(lineups, bounds, offsets)
    metrics = match_metrics(events)

    players = {}
    for pid, info in minutes.items():
        players[pid] = {**info, "metrics": metrics.get(pid, {})}
    return {"players": players, "team_goals_against": team_goals_against(events)}
