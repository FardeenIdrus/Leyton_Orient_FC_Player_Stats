"""The scoring rules behind an assessment. Pure functions -- no database, no Streamlit.

These are the rules a reviewer must be able to check without running the app: what the
Psychological band is, when an assessment is complete enough to score, and when the
screening flag raises.
"""

import pytest

from lofc.model import assessment_rules as rules
from lofc.model import club_criteria as cc


def _all_psych(position: str, score: int) -> dict[str, int]:
    return {rules.criterion_key(text): score
            for text in cc.PSYCHOLOGICAL_CRITERIA[position]}


def test_psychological_band_is_the_equal_weighted_mean():
    """Decision 8: equal weights, no criterion counts more than another."""
    scores = _all_psych("Centre Back", 4)
    assert rules.psychological_band(scores, "Centre Back") == 4.0


def test_psychological_band_averages_mixed_scores():
    keys = [rules.criterion_key(t) for t in cc.PSYCHOLOGICAL_CRITERIA["Goalkeeper"]]
    scores = dict(zip(keys, [5, 3, 1]))          # Goalkeeper has exactly 3 criteria
    assert rules.psychological_band(scores, "Goalkeeper") == 3.0


def test_psychological_band_is_none_when_a_criterion_is_unscored():
    """Spec section 5: all of the position's criteria must be scored or it stays a draft.
    Averaging over only the answered ones would let a scout raise a band by skipping the
    criteria the player is weak on."""
    scores = _all_psych("Centre Back", 4)
    scores.pop(next(iter(scores)))
    assert rules.psychological_band(scores, "Centre Back") is None


def test_psychological_band_ignores_criteria_that_are_not_the_positions():
    """A stale key left over from a different position must not enter the mean."""
    scores = _all_psych("Goalkeeper", 3)
    scores["not-a-goalkeeper-criterion"] = 5
    assert rules.psychological_band(scores, "Goalkeeper") == 3.0


def test_psychological_band_raises_for_an_unknown_position():
    """Spec section 18: an unknown position group blocks assessment with a clear message --
    never scored against no criteria."""
    with pytest.raises(KeyError):
        rules.psychological_band({}, "Sweeper Keeper")


def test_psychological_status_is_draft_when_incomplete():
    scores = _all_psych("Winger", 3)
    scores.pop(next(iter(scores)))
    assert rules.psychological_status(scores, "Winger") == "draft"


def test_psychological_status_is_submitted_when_complete():
    assert rules.psychological_status(_all_psych("Winger", 3), "Winger") == "submitted"


def test_criterion_key_is_stable_and_slug_like():
    key = rules.criterion_key("Composure under pressure; calm decision-making in own box")
    assert key == rules.criterion_key("Composure under pressure; calm decision-making in own box")
    assert " " not in key


def test_criterion_key_distinguishes_the_two_full_back_hamstring_bullets():
    """Full Back carries two distinct hamstring criteria. If the key collapsed them, one
    would silently overwrite the other's answer."""
    texts = [c.text for c in cc.MEDICAL_CRITERIA["Full Back"] if "hamstring" in c.text]
    assert len(texts) == 2
    assert rules.criterion_key(texts[0]) != rules.criterion_key(texts[1])


def _screening_keys(position: str) -> list[str]:
    return [rules.criterion_key(c.text)
            for c in cc.MEDICAL_CRITERIA[position] if c.kind == "screening"]


def test_screening_failed_is_false_when_all_pass():
    passes = {key: True for key in _screening_keys("Centre Back")}
    assert rules.screening_failed(passes, "Centre Back") is False


def test_screening_failed_is_true_when_any_fails():
    keys = _screening_keys("Centre Back")
    passes = {key: True for key in keys}
    passes[keys[0]] = False
    assert rules.screening_failed(passes, "Centre Back") is True


def test_screening_failed_ignores_protocol_and_availability_criteria():
    """Decision 7: only `screening` criteria are pass/fail. A protocol step ('undergo MRI
    scan') is a club process, not a player attribute, and must never raise the flag."""
    protocol = [rules.criterion_key(c.text)
                for c in cc.MEDICAL_CRITERIA["Goalkeeper"] if c.kind == "protocol"]
    assert protocol
    passes = {key: True for key in _screening_keys("Goalkeeper")}
    passes[protocol[0]] = False
    assert rules.screening_failed(passes, "Goalkeeper") is False


def test_screening_failed_ignores_availability_criteria():
    """Decision 7: `availability` is a computed figure shown as evidence (e.g. 'Minimum 60%
    availability over prior 2 seasons'), not something an assessor marks pass/fail. Only the
    protocol case was covered before -- this pins the other excluded kind on its own, so a
    mutation that folds `availability` into the screening set cannot slip past unnoticed."""
    availability = [rules.criterion_key(c.text)
                    for c in cc.MEDICAL_CRITERIA["Goalkeeper"] if c.kind == "availability"]
    assert availability
    passes = {key: True for key in _screening_keys("Goalkeeper")}
    passes[availability[0]] = False
    assert rules.screening_failed(passes, "Goalkeeper") is False


def test_screening_failed_treats_an_unanswered_criterion_as_not_a_failure():
    """An omitted key is a blank, not a fail. `medical_status` is what turns a blank into
    `draft`; `screening_failed` itself must stay False so a half-filled form is never
    reported as a screening failure while the assessor is still filling it in."""
    keys = _screening_keys("Centre Back")
    passes = {key: True for key in keys[:-1]}   # last screening key left unanswered
    assert rules.screening_failed(passes, "Centre Back") is False


def test_screening_failure_does_not_change_the_band():
    """Decision 13, the single most important rule in this module. A failed screening
    criterion WARNS. The platform never overwrites a qualified human's number -- if this
    test ever fails, the reversal of Decision 13 has been silently reintroduced."""
    keys = _screening_keys("Centre Back")
    passes = {key: True for key in keys}
    passes[keys[0]] = False
    status = rules.medical_status(4.0, passes, "Centre Back")
    assert status == "submitted"
    assert rules.screening_failed(passes, "Centre Back") is True


def test_medical_status_is_draft_without_a_band():
    passes = {key: True for key in _screening_keys("Centre Back")}
    assert rules.medical_status(None, passes, "Centre Back") == "draft"


def test_medical_status_is_draft_when_a_screening_criterion_is_unanswered():
    keys = _screening_keys("Centre Back")
    passes = {key: True for key in keys[:-1]}
    assert rules.medical_status(3.0, passes, "Centre Back") == "draft"


def test_medical_ceiling_note_explains_why_three_is_the_practical_ceiling():
    note = rules.MEDICAL_CEILING_NOTE
    assert "elite" in note.lower()
    assert "3" in note


def test_band_labels_are_the_clubs_own_wording():
    assert rules.BAND_LABELS == {1: "Unacceptable", 2: "Below Standard",
                                 3: "Meets Standard", 4: "Above Standard", 5: "Elite"}
