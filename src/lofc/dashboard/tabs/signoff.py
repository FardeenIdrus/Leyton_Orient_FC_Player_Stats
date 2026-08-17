"""The sign-off queue: submitted assessments awaiting approval.

Sign-off is the ONLY gated assessment action (Decision 16). It changes no number and hides
no player (Decision 14) -- it marks an assessment reviewed, and controls what may leave the
building as final rather than provisional.

Layout (frontend-design skill, spec section 16): each queue card leads with the decision --
player, dimension, band -- then provenance (who entered it, on what date) directly beneath,
then the screening flag if one exists, so a reviewer working under time pressure never has
to hunt across the card for the thing that matters. The screening warning states in words,
in its own bolded lead sentence, that the band was not changed by the flag. A submitted
assessment already scores; signing it off is reviewing it, not deciding it.
"""

from __future__ import annotations

import datetime

import streamlit as st

from lofc.dashboard.auth import can
from lofc.dashboard.session import CurrentUser
from lofc.store import assessments as store_assess


def render(engine, user: CurrentUser, player_names: dict[int, str]) -> None:
    st.subheader("Sign-off queue")

    if not can(user.role, "sign_off"):
        st.info("Sign-off is restricted to the Head of Recruitment and administrators. "
                "You can still assess any player — sign-off is the only gated action.")
        return

    st.caption("Signing off does not change any score and does not hide any player. It "
               "marks the assessment reviewed, so it can be exported as final rather than "
               "provisional.")

    pending = store_assess.pending_signoff(engine)
    if pending.empty:
        st.success("Nothing awaiting sign-off.")
        return

    st.caption(f"{len(pending)} awaiting review, oldest first.")
    for row in pending.itertuples():
        name = player_names.get(row.player_id, f"Player {row.player_id}")
        with st.container(border=True):
            head, action = st.columns([4, 1])
            with head:
                # The decision first: who, which dimension, what band -- before any
                # provenance or evidence detail.
                band = "—" if row.band is None else f"{row.band:.2f}"
                st.markdown(f"**{name}** — {row.dimension} — Band **{band}**")
                # Provenance directly beneath the decision, never optional.
                st.caption(f"Entered by **{row.author_name}** ({row.author_role}) "
                           f"on {row.created_at:%d %b %Y}")
                if row.screening_failed:
                    st.warning("**A screening criterion was not met — the band above is "
                               "unchanged.** This flag records the assessor's disagreement "
                               "for you to weigh; it does not cap or alter the figure.")
                if row.notes:
                    st.caption(f"Notes: {row.notes}")
                if row.author_name == user.full_name:
                    st.caption("You entered this assessment. Approving it is permitted and "
                               "will be recorded as **self-approved**.")
            with action:
                if st.button("Sign off", key=f"signoff_{row.id}", type="primary"):
                    # Two reviewers can work the queue at once, or one person can double-
                    # click before Streamlit reruns -- sign_off then raises because the
                    # row is no longer 'submitted'. That is not a bug to crash the page
                    # over; it means someone else got there first, so say so and refresh.
                    try:
                        store_assess.sign_off(engine, row.id, approver_id=user.id,
                                              now=datetime.datetime.now())
                    except ValueError:
                        st.error("This assessment is no longer awaiting sign-off — most "
                                 "likely someone else just approved it. Refreshing the "
                                 "queue.")
                    st.rerun()
