"""Central Mid is scored on the club's BOX TO BOX profile, not a copy of Defensive Mid.

THE PROBLEM. `Impect Data - Positional Metrics.xlsx` describes THREE midfielder types on its
MF tab -- Defensive, Box to Box, Attacking -- but its Input tab (the one carrying actual metric
names) has only TWO midfield rows: "Centre Midfield" and "Attacking Midfield". So one of the
three roles has no metric list, and the platform gave Defensive Mid and Central Mid the same
17 metrics. 667 players in 25/26 were scored on one profile written for one role.

WHICH ROW IS WHICH, resolved 2026-09-13 by the owner with delegated authority from the club.
The label and the contents of the "Centre Midfield" row disagree: the name suggests the
box-to-box role (the 6/8/10 convention), but the row contains `Aerial Win%` and `PAdj Tackles
& Interceptions` and contains NO Shots, Dribbles, box touches or crosses -- and the MF tab
says those four are exactly what separates Box to Box from Defensive. Contents were taken as
the better evidence of intent: "Centre Midfield" is the DEFENSIVE midfielder's list.

So Defensive Mid keeps it unchanged, and Central Mid becomes the missing Box to Box list:
the same metrics plus the four capabilities the MF tab gives Box to Box and withholds from
Defensive. Every added metric already appears in the club's OWN Attacking Midfield row --
nothing is invented and nothing new is sourced.

AERIAL DUELS were KEPT, deliberately. The MF tab lists "Defend aerial duels" for Defensive and
Attacking but not for Box to Box. That single omission was judged weak evidence of intent
against the same tab's "defend in a low block" and "win 2nd balls", which both involve
contesting aerial balls. Recorded here because it is the one genuine judgement call in the
change, and the one to revisit first if the club ever reads it differently.
"""

from lofc.model.club_framework import PERFORMANCE_METRICS

BOX_TO_BOX_ADDITIONS = {
    "shots_p90",                # MF tab: "Shots"
    "dribbles_p90",             # MF tab: "Dribbles attempted / success"
    "dribble_success_pct",      # MF tab: "Ability to break lines through dribbling"
    "touches_in_box_p90",       # MF tab: "Availability in the box"
    "successful_box_cross_pct",  # MF tab: "Crosses & crossing types - low / high"
}


def test_central_mid_is_no_longer_a_copy_of_defensive_mid():
    """The defect: two distinct position groups scored on one identical list."""
    assert set(PERFORMANCE_METRICS["Central Mid"]) != set(PERFORMANCE_METRICS["Defensive Mid"])


def test_central_mid_adds_exactly_the_box_to_box_capabilities():
    central = set(PERFORMANCE_METRICS["Central Mid"])
    defensive = set(PERFORMANCE_METRICS["Defensive Mid"])
    assert central - defensive == BOX_TO_BOX_ADDITIONS


def test_central_mid_drops_nothing_from_the_defensive_list():
    """Box to Box does everything the defensive midfielder does, plus more -- the MF tab
    gives him the whole defensive set (low block, 1v1, intercepting, second balls)."""
    assert not set(PERFORMANCE_METRICS["Defensive Mid"]) - set(PERFORMANCE_METRICS["Central Mid"])


def test_aerial_duels_are_kept_for_central_mid():
    """The one judgement call, pinned so it cannot be changed silently."""
    assert "aerial_win_pct" in PERFORMANCE_METRICS["Central Mid"]


def test_every_added_metric_comes_from_the_clubs_own_attacking_midfield_row():
    """Nothing invented: each addition is a metric the club already chose for a midfielder."""
    assert BOX_TO_BOX_ADDITIONS <= set(PERFORMANCE_METRICS["Attacking Mid"])


def test_defensive_mid_is_unchanged_at_17_metrics():
    assert len(PERFORMANCE_METRICS["Defensive Mid"]) == 17


def test_central_mid_has_22_metrics():
    assert len(PERFORMANCE_METRICS["Central Mid"]) == 22
