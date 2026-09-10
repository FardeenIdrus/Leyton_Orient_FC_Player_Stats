"""Decision 9 made visible: one scout dimension is not a partial assessment.

The badges are per dimension, so a player with only Psychological signed off shows a green
"Signed off" badge and still scores nothing. Observed live: of four assessed players two had
a single dimension, and neither scout could tell why the rating never appeared. These tests
pin the helper that lets the interface say so.
"""

from lofc.model.scout_scores import MEDICAL, PSYCHOLOGICAL, missing_dimensions


def test_both_dimensions_scoring_leaves_nothing_missing():
    assert missing_dimensions({PSYCHOLOGICAL: "signed_off", MEDICAL: "signed_off"}) == []


def test_a_submitted_pair_also_scores():
    """Sign-off is not required to score -- Decision 16. Only agreement is."""
    assert missing_dimensions({PSYCHOLOGICAL: "submitted", MEDICAL: "submitted"}) == []


def test_the_absent_dimension_is_named():
    """Jaze Kabia's exact case: Psychological signed off, Medical Risk never entered."""
    assert missing_dimensions({PSYCHOLOGICAL: "signed_off"}) == [MEDICAL]


def test_a_draft_does_not_count_as_present():
    assert missing_dimensions({PSYCHOLOGICAL: "signed_off",
                               MEDICAL: "draft"}) == [MEDICAL]


def test_a_rejected_dimension_does_not_count_as_present():
    """Fletcher Holman's case: the only assessment on the player was declined."""
    assert missing_dimensions({PSYCHOLOGICAL: "rejected"}) == [PSYCHOLOGICAL, MEDICAL]


def test_an_unresolved_conflict_does_not_count_as_present():
    """Decision 17: disagreeing unsigned assessments score nothing, so the dimension is
    still outstanding even though rows exist."""
    assert missing_dimensions({PSYCHOLOGICAL: "conflict",
                               MEDICAL: "signed_off"}) == [PSYCHOLOGICAL]


def test_nothing_assessed_names_both():
    assert missing_dimensions({}) == [PSYCHOLOGICAL, MEDICAL]
