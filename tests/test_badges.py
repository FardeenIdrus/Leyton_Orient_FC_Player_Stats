"""Assessment status badges.

Spec section 16 and Decision 14: colour NEVER carries the meaning alone -- printed reports
and colour-blind readers lose the colour, so every badge must state its status in words.
These tests are what stop that rule quietly regressing into a coloured dot."""

import datetime as dt

from lofc.dashboard import badges
from lofc.model.scout_scores import CONFLICT


def test_no_assessment_badge_says_so_in_words():
    badge = badges.for_status(None)
    assert "Not assessed" in badge.text


def test_submitted_badge_states_awaiting_sign_off_in_words():
    badge = badges.for_status("submitted", author_name="J. Smith")
    assert "Assessed" in badge.text
    assert "awaiting sign-off" in badge.text.lower()


def test_submitted_badge_names_the_assessor():
    """Decision 14 accepts an unsigned assessment moving the ranking ONLY because the
    assessor's name is visible. An anonymous badge would not be acceptable."""
    badge = badges.for_status("submitted", author_name="J. Smith")
    assert "J. Smith" in badge.text


def test_signed_off_badge_names_the_approver_and_the_date():
    badge = badges.for_status("signed_off", author_name="J. Smith",
                              approver_name="A. Approver",
                              approved_at=dt.datetime(2026, 8, 14))
    assert "Signed off" in badge.text
    assert "A. Approver" in badge.text
    assert "2026" in badge.text or "Aug" in badge.text


def test_every_badge_carries_words_not_only_a_colour():
    for status in (None, "draft", "submitted", "signed_off", CONFLICT):
        badge = badges.for_status(status, author_name="J. Smith",
                                  approver_name="A. Approver")
        stripped = "".join(ch for ch in badge.text if ch.isalpha())
        assert len(stripped) > 3, f"{status!r} badge has no words"


def test_conflict_badge_states_the_status_in_words():
    """Decision 17 / task 10 B1: a contested dimension must read as a conflict, not silently
    as 'not assessed' or crash into the unknown-status branch."""
    badge = badges.for_status(CONFLICT)
    assert "conflict" in badge.text.lower()
    assert "not scored" in badge.text.lower()


def test_conflict_badge_is_not_confused_with_an_error():
    """The conflict badge must not fall into the 'unknown status' branch (which would say
    'Unknown status' rather than naming the conflict) and must not be red like an error."""
    badge = badges.for_status(CONFLICT)
    assert "unknown" not in badge.text.lower()
    assert badge.tone == "conflict"


def test_self_approval_is_labelled():
    """One pair of eyes and two must not look identical in a report going to a director."""
    label = badges.signoff_label("J. Smith", "J. Smith")
    assert "self-approved" in label.lower()


def test_a_different_approver_is_not_labelled_self_approved():
    label = badges.signoff_label("J. Smith", "A. Approver")
    assert "self-approved" not in label.lower()
    assert "A. Approver" in label


def test_an_unknown_status_does_not_crash_and_says_it_is_unknown():
    badge = badges.for_status("something-new")
    assert badge.text
    assert "unknown" in badge.text.lower()


def test_a_name_with_angle_brackets_does_not_emit_raw_markup():
    """MINOR 8: `author_name`/`approver_name` come from `users.full_name`, an admin-entered
    value the platform does not validate. Rendered with `unsafe_allow_html=True`, an
    unescaped '<' or '>' would break the badge or inject markup."""
    badge = badges.for_status("submitted", author_name="<script>alert(1)</script>")
    markup = badges._badge_html(badge)
    assert "<script>" not in markup
    assert "&lt;script&gt;" in markup


def test_rejected_badge_states_the_status_in_words():
    """Problem 3: a declined assessment must read as rejected, not silently as 'not
    assessed' or fall into the unknown-status branch."""
    badge = badges.for_status("rejected", author_name="J. Smith", approver_name="A. Approver",
                              approved_at=dt.datetime(2026, 8, 14))
    assert "rejected" in badge.text.lower()
    assert "A. Approver" in badge.text
    assert "unknown" not in badge.text.lower()


def test_rejected_badge_has_its_own_tone():
    badge = badges.for_status("rejected")
    assert badge.tone == "rejected"
