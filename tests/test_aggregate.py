"""Tests for the aggregation logic, using small handmade fixtures (no real files)."""

from lofc.aggregate import events as ev


# Boundary events: half 1 runs 0:00-48:00, half 2 runs 45:00-94:00 (clock resets).
BOUND_EVENTS = [
    {"type": {"name": "Half Start"}, "period": 1, "minute": 0, "second": 0},
    {"type": {"name": "Half End"}, "period": 1, "minute": 48, "second": 0},
    {"type": {"name": "Half Start"}, "period": 2, "minute": 45, "second": 0},
    {"type": {"name": "Half End"}, "period": 2, "minute": 94, "second": 0},
]


def _player(pid, name, positions):
    return {"player_id": pid, "player_name": name, "positions": positions}


def test_parse_clock():
    assert ev.parse_clock("00:00") == 0
    assert ev.parse_clock("79:08") == 79 * 60 + 8
    assert ev.parse_clock("1:30:00") == 90 * 60


def test_period_bounds_handles_clock_reset():
    bounds = ev.period_bounds(BOUND_EVENTS)
    assert bounds == {1: (0, 2880), 2: (2700, 5640)}


def test_minutes_are_period_aware():
    bounds = ev.period_bounds(BOUND_EVENTS)
    offsets = ev._cumulative_offsets(bounds)
    lineups = {
        10: {
            "team_id": 10,
            "team_name": "Test FC",
            "lineup": [
                # Played the whole match (still on at the final whistle).
                _player(1, "Ever Present", [
                    {"position_id": 4, "position": "Center Back", "from": "00:00", "to": None,
                     "from_period": 1, "to_period": 2, "start_reason": "Starting XI", "end_reason": "Final Whistle"},
                ]),
                # Started, subbed off at 79:08 in the second half.
                _player(2, "Subbed Off", [
                    {"position_id": 14, "position": "Center Midfield", "from": "00:00", "to": "79:08",
                     "from_period": 1, "to_period": 2, "start_reason": "Starting XI", "end_reason": "Substitution - Off"},
                ]),
                # Unused substitute (no position spells).
                _player(3, "Unused Sub", []),
            ],
        }
    }
    minutes = ev.player_minutes(lineups, bounds, offsets)

    # Full match = length of both halves = 48 + 49 = 97 minutes.
    assert round(minutes[1]["seconds"] / 60) == 97
    # Subbed at 79:08: first-half stoppage means it is 82, not a naive 79.
    assert round(minutes[2]["seconds"] / 60) == 82
    # Unused sub never appears.
    assert 3 not in minutes


def test_position_groups():
    assert ev.POSITION_GROUPS[1] == "Goalkeeper"
    assert ev.POSITION_GROUPS[4] == "Centre Back"
    assert ev.POSITION_GROUPS[2] == "Full Back"
    assert ev.POSITION_GROUPS[10] == "Defensive Mid"
    assert ev.POSITION_GROUPS[14] == "Central Mid"
    assert ev.POSITION_GROUPS[17] == "Winger"
    assert ev.POSITION_GROUPS[19] == "Attacking Mid"
    assert ev.POSITION_GROUPS[23] == "Centre Forward"


def _evt(eid, etype, pid, extra=None):
    e = {"id": eid, "type": {"name": etype}, "player": {"id": pid, "name": f"P{pid}"}, "team": {"id": 1}}
    if extra:
        e.update(extra)
    return e


def test_match_metrics_and_xa():
    events = [
        # Player 1: a progressive completed pass into the final third.
        _evt("p1", "Pass", 1, {"location": [60, 40], "pass": {"end_location": [90, 40]}}),
        # Player 1: a completed pass that set up a shot (key pass), inside final third.
        _evt("p2", "Pass", 1, {"location": [100, 40], "pass": {"end_location": [110, 40], "shot_assist": True}}),
        # Player 2: a non-penalty goal.
        _evt("s1", "Shot", 2, {"shot": {"statsbomb_xg": 0.5, "outcome": {"name": "Goal"}, "type": {"name": "Open Play"}}}),
        # Player 2: a penalty goal.
        _evt("s2", "Shot", 2, {"shot": {"statsbomb_xg": 0.76, "outcome": {"name": "Goal"}, "type": {"name": "Penalty"}}}),
        # Player 3: a saved shot that came from player 1's key pass (p2) -> xA to player 1.
        _evt("s3", "Shot", 3, {"shot": {"statsbomb_xg": 0.3, "outcome": {"name": "Saved"}, "type": {"name": "Open Play"}, "key_pass_id": "p2"}}),
    ]
    m = ev.match_metrics(events)

    assert m[1]["passes"] == 2
    assert m[1]["passes_completed"] == 2
    assert m[1]["progressive_passes"] == 1          # only p1 moves >= 15m forward
    assert m[1]["passes_into_final_third"] == 1     # only p1 crosses x=80
    assert m[1]["key_passes"] == 1
    assert round(m[1]["xa"], 2) == 0.30             # xG of the shot it created

    assert m[2]["shots"] == 2
    assert m[2]["goals"] == 2
    assert m[2]["np_goals"] == 1                    # penalty excluded
    assert round(m[2]["xg"], 2) == 1.26
    assert round(m[2]["np_xg"], 2) == 0.50

    assert m[3]["shots"] == 1
    assert m[3].get("goals", 0) == 0
