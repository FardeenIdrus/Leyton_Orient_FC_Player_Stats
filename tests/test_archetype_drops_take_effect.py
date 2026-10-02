"""An archetype must actually change the metrics a player is scored on.

THE DEFECT. `performance_metrics_for_archetype` dropped metrics by the CLUB'S name for
them. But the club's list and the platform's stored list are not the same list: several
club entries resolve, through `CLUB_SUCCESSOR`, to a metric another entry already supplies.
Dropping one of those entries left the other in place, so the measurement survived and the
drop did nothing.

Measured on the live framework before the fix:

    Winger / Crossing & Creative Threat   1 drop configured, 0 took effect
    Full Back / Attacking                 3 drops configured, 2 took effect

The Winger case was the visible one: all 415 wingers scored IDENTICALLY under
"Crossing & Creative Threat" and "All Metrics" -- the archetype was offered, stored and
completely inert. A recruiter could select it and see the full-list rating with nothing to
indicate it had made no difference.

THE FIX drops by the RESOLVED metric. A drop now removes the measurement however many club
entries supply it. This is the instruction each archetype already carried, finally applied;
no archetype's intent is changed, and no metric is added to or removed from any position's
full list, so `objective_composite` -- the ranking -- is untouched.
"""

import pytest

from lofc.model import club_framework as cf
from lofc.model.scorecard import _resolved_performance

ARCHETYPES = [(pos, name)
              for pos, arch in cf.ARCHETYPE_DROPS.items()
              for name in arch]


@pytest.mark.parametrize("position,archetype", ARCHETYPES)
def test_an_archetype_scores_on_fewer_metrics_than_the_full_list(position, archetype):
    """THE GUARD. An archetype whose resolved list equals the full list is inert: it is
    offered in the interface and produces the same number as 'All Metrics'."""
    full = _resolved_performance(position, cf.DEFAULT_ARCHETYPE)
    narrowed = _resolved_performance(position, archetype)
    assert len(narrowed) < len(full), (
        f"{position} / {archetype} scores on the same {len(full)} metrics as the full "
        f"list, so selecting it changes nothing")


@pytest.mark.parametrize("position,archetype", ARCHETYPES)
def test_every_configured_drop_removes_its_metric(position, archetype):
    """Each drop must remove the measurement, not merely one of the club's names for it.

    Full Back / Attacking configured three drops and achieved two: the third,
    `padj_tackles_interceptions_p90`, resolves to `ground_duel_win_pct`, which the club
    also lists in its own right.
    """
    kept = set(_resolved_performance(position, archetype))
    for club_metric in cf.ARCHETYPE_DROPS[position][archetype]:
        resolved = cf.resolve_metric(club_metric)
        if not resolved:
            continue
        assert resolved not in kept, (
            f"{position} / {archetype} is configured to drop {club_metric}, but "
            f"{resolved} is still scored — another club entry supplies the same "
            f"measurement")


@pytest.mark.parametrize("position,archetype", ARCHETYPES)
def test_an_archetype_never_adds_a_metric(position, archetype):
    """An archetype narrows a list. It must never introduce a metric the position does
    not otherwise score."""
    full = set(_resolved_performance(position, cf.DEFAULT_ARCHETYPE))
    assert set(_resolved_performance(position, archetype)) <= full


def test_the_default_archetype_is_the_full_list():
    """'All Metrics' is the ranking's list. If it ever narrowed, the ranking would move."""
    for position in cf.PERFORMANCE_METRICS:
        resolved = _resolved_performance(position, cf.DEFAULT_ARCHETYPE)
        assert len(resolved) == len({cf.resolve_metric(m)
                                     for m in cf.PERFORMANCE_METRICS[position]
                                     if cf.resolve_metric(m)})


def test_an_unknown_archetype_falls_back_to_the_full_list():
    """A stale archetype name in the database must not silently score on nothing."""
    full = _resolved_performance("Winger", cf.DEFAULT_ARCHETYPE)
    assert _resolved_performance("Winger", "No Such Archetype") == full
