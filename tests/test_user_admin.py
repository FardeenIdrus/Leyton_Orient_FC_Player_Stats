"""Pure decision logic for admin user management. No database, no Streamlit."""

from lofc.model import user_admin


def test_an_admin_cannot_deactivate_their_own_account():
    reason = user_admin.guard_deactivate(actor_id=1, target_id=1)
    assert reason is not None
    assert "own account" in reason


def test_an_admin_can_deactivate_someone_else():
    assert user_admin.guard_deactivate(actor_id=1, target_id=2) is None


def test_account_status_label_states_the_state_in_words():
    assert user_admin.account_status_label(True) == "Active"
    assert user_admin.account_status_label(False) == "Deactivated"


def test_lockout_label_when_not_locked():
    assert user_admin.lockout_label(False, 0) == "Not locked"


def test_lockout_label_rounds_seconds_up_to_whole_minutes():
    # 61 seconds must not read as "0 minutes remaining" (a false "clear now").
    assert user_admin.lockout_label(True, 61) == "Locked (2 minutes remaining)"


def test_lockout_label_singular_minute():
    assert user_admin.lockout_label(True, 30) == "Locked (1 minute remaining)"


def test_lockout_label_never_reports_zero_minutes():
    # Even a lockout with under a second left must round up to 1, never 0 -- telling an
    # admin an account is already clear when it is not is the wrong direction to be wrong in.
    assert user_admin.lockout_label(True, 1) == "Locked (1 minute remaining)"
