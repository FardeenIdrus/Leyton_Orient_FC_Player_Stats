"""The Users page: list every account, create one, reset a password, clear a lockout, and
deactivate/reactivate -- the only user-management surface in the platform that is not a
terminal command (`lofc.admin`, which calls the same `store.users` functions this page
does, so the two never enforce different rules for the same action).

Visible only to `manage_users` (admin) -- gated in `app.py`'s page registration, which is
what actually keeps it out of a non-admin's sidebar, and gated again at the top of `render`
as a second line of defence rather than trusting registration alone.

Deactivate, never delete: `ScoutAssessment` rows reference `users.id` via `author_id` and
`approved_by`, so removing a user who has ever assessed or approved anything would break
that foreign key and erase the attribution the whole assessment system depends on.
`store.users.set_active` only ever flips `is_active`.

An admin cannot deactivate their own account (`model.user_admin.guard_deactivate`) --
otherwise the platform would have no administrator left who could sign back in to undo it,
and recovering would need direct database surgery. Nobody can edit a role from here: the
role is a record of who acted (Decision 16), not a hierarchy to manage.

Layout follows the product's own established language rather than inventing a new one: a
row-selectable `st.dataframe` opening an `st.dialog` for the selected account (the exact
pattern `tabs/watchlist.py` uses), plain-worded status/lockout columns (never colour alone),
and the same form/caption rhythm `tabs/assess.py` and `dashboard/session.py`'s own
password-change form already use. A password is never echoed back to the screen once set.
"""

from __future__ import annotations

import datetime

import pandas as pd
import streamlit as st

from lofc.dashboard.auth import ROLES, can, password_problems
from lofc.dashboard.session import CurrentUser
from lofc.model import user_admin
from lofc.store import users as store_users

_TABLE_VER_KEY = "users_table_ver"
_DIALOG_HANDLED_KEY = "users_dialog_handled"


def _bump_and_rerun() -> None:
    """Bump the table's key before rerunning, the same way `watchlist._close` does -- so the
    dataframe's selection is cleared and the dialog does not immediately reopen on the next
    run just because the previously-picked row is still visually selected."""
    st.session_state[_TABLE_VER_KEY] = st.session_state.get(_TABLE_VER_KEY, 0) + 1
    st.rerun()


def _accounts_frame(rows: list[store_users.UserRow]) -> pd.DataFrame:
    return pd.DataFrame({
        "Username": [r.username for r in rows],
        "Full name": [r.full_name for r in rows],
        "Role": [r.role for r in rows],
        "Status": [user_admin.account_status_label(r.is_active) for r in rows],
        "Lockout": [user_admin.lockout_label(r.locked, r.locked_seconds_remaining) for r in rows],
        "Created": [r.created_at.strftime("%d %b %Y") for r in rows],
    })


def _create_account_form(engine) -> None:
    with st.expander("＋ Create account"):
        with st.form("create_account", clear_on_submit=True):
            username = st.text_input("Username")
            full_name = st.text_input("Full name")
            role = st.selectbox("Role", ROLES)
            password = st.text_input(
                "Temporary password", type="password",
                help="They must change this at their first sign-in — it is never shown "
                     "again once this form closes.")
            confirm = st.text_input("Confirm temporary password", type="password")
            submitted = st.form_submit_button("Create account", type="primary")
        if not submitted:
            return
        if not username.strip() or not full_name.strip():
            st.error("Username and full name are both required.")
            return
        if password != confirm:
            st.error("The two passwords do not match.")
            return
        problems = password_problems(password)
        if problems:
            st.error("Password rejected: " + "; ".join(problems))
            return
        try:
            store_users.create_user(engine, username.strip(), full_name.strip(), role, password)
        except ValueError as exc:
            st.error(str(exc))
            return
        st.success(f"Created {role} account '{username.strip()}'. They must change their "
                   "password at first sign-in.")
        st.rerun()


@st.dialog("Account")
def _account_dialog(engine, actor: CurrentUser, row: store_users.UserRow) -> None:
    st.markdown(f"**{row.full_name}** — @{row.username} — {row.role}")
    st.caption(f"{user_admin.account_status_label(row.is_active)} · "
               f"{user_admin.lockout_label(row.locked, row.locked_seconds_remaining)} · "
               f"created {row.created_at:%d %b %Y}")

    st.divider()
    st.markdown("**Reset password**")
    st.caption("The only password-recovery route — there is no email on file, so this is "
               "how a forgotten password is recovered. Clears any lockout and forces a "
               "change at their next sign-in. Tell them the new password directly; it is "
               "never shown again once this closes.")
    with st.form(f"reset_pw_{row.id}"):
        new_password = st.text_input("New temporary password", type="password",
                                     key=f"reset_pw_input_{row.id}")
        confirm = st.text_input("Confirm", type="password", key=f"reset_pw_confirm_{row.id}")
        reset_submitted = st.form_submit_button("Reset password")
    if reset_submitted:
        if new_password != confirm:
            st.error("The two passwords do not match.")
        else:
            problems = password_problems(new_password)
            if problems:
                st.error("Password rejected: " + "; ".join(problems))
            else:
                store_users.reset_password(engine, row.id, new_password)
                st.success("Password reset. They must change it at their next sign-in.")
                _bump_and_rerun()

    st.divider()
    st.markdown("**Lockout**")
    if row.locked:
        st.write(user_admin.lockout_label(row.locked, row.locked_seconds_remaining))
        st.caption("Clears the lockout without changing the password — for the ordinary "
                   "case of a mistyped password five times.")
        if st.button("Clear lockout", key=f"clear_lock_{row.id}"):
            store_users.clear_lockout(engine, row.id)
            st.success("Lockout cleared.")
            _bump_and_rerun()
    else:
        st.write("Not locked.")

    st.divider()
    st.markdown("**Account status**")
    if row.is_active:
        reason = user_admin.guard_deactivate(actor.id, row.id)
        if reason:
            st.warning(reason)
        else:
            st.caption("Blocks sign-in immediately. Every past assessment stays attributed "
                       "to them — nothing is deleted.")
        if st.button("Deactivate account", key=f"deactivate_{row.id}", disabled=bool(reason)):
            store_users.set_active(engine, row.id, False)
            st.success(f"{row.username} deactivated.")
            _bump_and_rerun()
    else:
        st.info("This account is deactivated and cannot sign in. Every past assessment "
                "stays attributed to them.")
        if st.button("Reactivate account", key=f"reactivate_{row.id}", type="primary"):
            store_users.set_active(engine, row.id, True)
            st.success(f"{row.username} reactivated.")
            _bump_and_rerun()

    st.divider()
    if st.button("Close", key=f"close_{row.id}"):
        _bump_and_rerun()


def render(engine, actor: CurrentUser) -> None:
    st.subheader("Users")
    if not can(actor.role, "manage_users"):
        # Belt and braces: `app.py` never registers this page for a non-admin, so this
        # branch should be unreachable in normal use -- but the page must never trust its
        # own registration as the only gate.
        st.error("This page is restricted to administrators.")
        return

    st.caption("Every account on the platform. No password is ever shown here, logged, or "
               "stored anywhere but as a one-way hash — resetting one sets a new temporary "
               "password that must be changed at the next sign-in.")

    _create_account_form(engine)

    rows = store_users.list_users(engine, datetime.datetime.now())
    if not rows:
        st.info("No accounts yet.")
        return

    frame = _accounts_frame(rows)
    version = st.session_state.get(_TABLE_VER_KEY, 0)
    selection = st.dataframe(
        frame, hide_index=True, width="stretch",
        on_select="rerun", selection_mode="single-row", key=f"users_table_{version}")

    picked = list(selection.selection.rows) if selection and selection.selection else []
    if picked and picked[0] < len(rows):
        row = rows[picked[0]]
        marker = (row.id, version)
        if st.session_state.get(_DIALOG_HANDLED_KEY) != marker:
            st.session_state[_DIALOG_HANDLED_KEY] = marker
            _account_dialog(engine, actor, row)
    else:
        st.session_state[_DIALOG_HANDLED_KEY] = None

    st.caption("Click a row to reset its password, clear a lockout, or deactivate/"
               "reactivate the account. Accounts are never deleted.")
