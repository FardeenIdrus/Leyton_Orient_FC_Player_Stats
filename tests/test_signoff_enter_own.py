"""A reviewer must be able to enter their own assessment from the queue, always.

The capability was built for Decision 17's conflict case and was reachable ONLY there: the
"Enter my own" expander sat inside `if len(submitted) > 1`, so with a single pending
assessment -- the ordinary case -- a reviewer could sign off or reject and nothing else.
Entering their own view of a player, starting from what a scout had already written, meant
leaving the queue entirely.

Nothing in the pre-fill logic ever needed a conflict: it copies criterion scores from a
chosen assessment, and one assessment is a perfectly good thing to copy from.
"""

import pandas as pd

from lofc.dashboard.tabs.signoff import starting_points


def _group(rows):
    return pd.DataFrame(rows)


def test_blank_is_always_offered_first():
    """A reviewer who disagrees wholesale must not have to start from someone else's work."""
    points = starting_points(_group([{"id": 7, "author_name": "A Scout", "band": 3.0}]))
    assert points[0] == ("Blank", None)


def test_a_single_assessment_can_be_copied_from():
    """The case that was unreachable: one pending assessment, no conflict."""
    points = starting_points(_group([{"id": 7, "author_name": "A Scout", "band": 3.0}]))
    assert len(points) == 2
    assert points[1] == ("A Scout — band 3.00", 7)


def test_every_competing_assessment_is_offered():
    points = starting_points(_group([
        {"id": 7, "author_name": "A Scout", "band": 3.0},
        {"id": 9, "author_name": "B Scout", "band": 4.5},
    ]))
    assert [label for label, _ in points] == [
        "Blank", "A Scout — band 3.00", "B Scout — band 4.50"]


def test_a_band_that_was_never_set_reads_as_a_dash_not_zero():
    points = starting_points(_group([{"id": 7, "author_name": "A Scout", "band": None}]))
    assert points[1] == ("A Scout — band —", 7)


def test_no_assessments_still_offers_blank():
    assert starting_points(pd.DataFrame(columns=["id", "author_name", "band"])) == [
        ("Blank", None)]


def test_ids_are_plain_ints_so_they_can_key_a_widget():
    points = starting_points(_group([{"id": 7, "author_name": "A Scout", "band": 3.0}]))
    assert isinstance(points[1][1], int)
