"""Pure decision logic for admin user management -- the Users page and the
`deactivate-user`/`reactivate-user` CLI commands share these rules rather than each
encoding their own copy.

Mirrors `dashboard/auth.py`: no database, no Streamlit, no network -- so who may be
deactivated and how an account's state reads in words are both testable in isolation and
guaranteed to say the same thing wherever they are shown.
"""

from __future__ import annotations


def guard_deactivate(actor_id: int, target_id: int) -> str | None:
    """None if `actor_id` may deactivate `target_id`; otherwise the reason it is refused.

    The one hard rule: nobody may deactivate their own account. Without it, an administrator
    who deactivates themselves has just made the platform unadministrable -- there would be
    no one left who could sign in to undo it, and recovering needs direct database surgery.
    This is checked by id, not by counting remaining admins: even if other admins exist, the
    ACTOR is the one who would be locked out of the browser by their own action, so the
    button is refused regardless of who else could technically do it instead.
    """
    if actor_id == target_id:
        return ("You cannot deactivate your own account — an administrator must always be "
               "able to sign in to undo a mistake.")
    return None


def account_status_label(is_active: bool) -> str:
    """Active/inactive, stated in words. Colour never carries this meaning alone."""
    return "Active" if is_active else "Deactivated"


def lockout_label(locked: bool, seconds_remaining: int) -> str:
    """How a lockout reads in the accounts table and the account dialog, stated in words.

    Rounded UP the same way `dashboard.session.lockout_message` rounds the login page's own
    wait: telling an admin an account clears in 0 minutes when it actually takes 30 more
    seconds is the wrong direction to be wrong in.
    """
    if not locked:
        return "Not locked"
    minutes = max(1, -(-seconds_remaining // 60))
    unit = "minute" if minutes == 1 else "minutes"
    return f"Locked ({minutes} {unit} remaining)"
