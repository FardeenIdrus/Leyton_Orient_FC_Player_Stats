"""The club's per-position Psychological and Medical criteria, encoded verbatim."""

import pytest

from lofc.model import club_framework as cf
from lofc.model.club_criteria import (
    MEDICAL_CRITERIA,
    POSITION_GROUPS,
    PSYCHOLOGICAL_CRITERIA,
    MedicalCriterion,
)


def test_every_position_group_the_framework_scores_has_criteria():
    # The criteria must cover exactly the positions club_framework weights.
    assert set(POSITION_GROUPS) == set(cf.DIMENSION_WEIGHTS)
    for position in POSITION_GROUPS:
        assert PSYCHOLOGICAL_CRITERIA[position], position
        assert MEDICAL_CRITERIA[position], position


def test_the_merged_positions_have_the_agreed_counts():
    # Full Back = Right Back u Left Back; Winger = Left u Right Winger (Decision 6).
    assert len(PSYCHOLOGICAL_CRITERIA["Full Back"]) == 6
    assert len(MEDICAL_CRITERIA["Full Back"]) == 4
    assert len(PSYCHOLOGICAL_CRITERIA["Winger"]) == 8
    assert len(MEDICAL_CRITERIA["Winger"]) == 5


def test_centre_forward_keeps_its_two_criteria_unpadded():
    # The club really does list only two. Padding would invent criteria.
    assert len(PSYCHOLOGICAL_CRITERIA["Centre Forward"]) == 2


def test_merged_winger_text_is_the_club_wording_not_a_new_sentence():
    winger = PSYCHOLOGICAL_CRITERIA["Winger"]
    assert "High pressing work rate in defensive phase" in winger
    assert "Competitive drive to impact matches consistently" in winger
    # The absorbed left-side phrasings must NOT appear as separate criteria.
    assert not any("difference-maker" in c for c in winger)
    assert not any("tracks back when required" in c for c in winger)


def test_merged_winger_medical_keeps_the_left_winger_hamstring_wording():
    # The count-only tests would still pass if the merge had kept the Right Winger's bare
    # "No hamstring injury in prior 12 months" instead of the Left Winger's wording, which
    # carries the club's sprint-dependent-position rationale. Pin the actual text so a
    # wrong-side merge fails loudly.
    texts = [c.text for c in MEDICAL_CRITERIA["Winger"]]
    assert "No hamstring injury in prior 12 months (sprint-dependent position)" in texts
    assert "No hamstring injury in prior 12 months" not in texts
    # Both screening bullets concern different structures and were kept on purpose --
    # neither should be dropped as a "duplicate" of the other.
    assert "Quadriceps and hip flexor screening clear" in texts
    assert "Hip and groin screening clear for high-COD activities" in texts


def test_merged_full_back_medical_keeps_both_distinct_hamstring_bullets():
    # These two bullets differ in scope (one time-bounded, one broader by injury type), so
    # the brief kept both deliberately. Only the count is otherwise pinned (4), so a future
    # "tidy-up" that collapses these into one wording must fail this test.
    texts = [c.text for c in MEDICAL_CRITERIA["Full Back"]]
    assert "No recurring hamstring injuries within the prior 12 months" in texts
    assert "No recurring hamstring or calf injuries" in texts


def test_no_duplicate_criteria_within_a_position():
    for position in POSITION_GROUPS:
        psych = PSYCHOLOGICAL_CRITERIA[position]
        assert len(psych) == len(set(psych)), position
        texts = [c.text for c in MEDICAL_CRITERIA[position]]
        assert len(texts) == len(set(texts)), position


def test_medical_criteria_are_classified_three_ways():
    kinds = {c.kind for cs in MEDICAL_CRITERIA.values() for c in cs}
    assert kinds <= {"availability", "screening", "protocol"}
    # Every position states an availability requirement.
    for position in POSITION_GROUPS:
        assert any(c.kind == "availability" for c in MEDICAL_CRITERIA[position]), position


def test_the_mri_bullet_is_protocol_not_a_player_attribute():
    # "Permanent signings undergo MRI scan" says nothing about the player (Decision 7).
    mri = [c for cs in MEDICAL_CRITERIA.values() for c in cs if "undergo" in c.text]
    assert mri, "expected at least one protocol criterion"
    assert all(c.kind == "protocol" for c in mri)


def test_a_screening_criterion_is_neither_availability_nor_protocol():
    full_back = {c.text: c.kind for c in MEDICAL_CRITERIA["Full Back"]}
    assert full_back["Minimum 60% availability over prior 2 seasons"] == "availability"
    assert full_back["Permanent signings undergo MRI scan"] == "protocol"
    assert full_back["No recurring hamstring or calf injuries"] == "screening"


def test_criteria_are_immutable_value_objects():
    criterion = MEDICAL_CRITERIA["Winger"][0]
    with pytest.raises(Exception):
        criterion.text = "changed"
