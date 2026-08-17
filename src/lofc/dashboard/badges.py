"""Assessment status badges, rendered identically everywhere they appear.

Decision 14 and spec section 16: COLOUR NEVER CARRIES THE MEANING ALONE. Every badge states
its status in words, because printed reports and colour-blind readers lose the colour. The
emoji and the colour reinforce the words; they never replace them.

One module so a watchlist row and a player-profile row can never disagree about a player by
rendering two different badge sets.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass

import streamlit as st

from lofc.dashboard.theme import RED


@dataclass(frozen=True)
class AssessmentBadge:
    text: str          # always carries the status in words
    colour: str        # reinforcement only
    tone: str          # "none" | "draft" | "pending" | "approved" | "unknown"


def signoff_label(author_name: str, approver_name: str | None) -> str:
    """How to name the approver. Self-approval is permitted (Decision 16) and LABELLED:
    with three people, requiring a different approver would jam the queue, but a second pair
    of eyes and one pair must not look identical in a report going to a director."""
    if approver_name is None:
        return ""
    if approver_name == author_name:
        return f"{approver_name} (self-approved)"
    return approver_name


def for_status(status: str | None, author_name: str | None = None,
               approver_name: str | None = None,
               approved_at: datetime.datetime | None = None) -> AssessmentBadge:
    """The badge for one assessment's status."""
    if status is None:
        return AssessmentBadge("Not assessed", "#6b6b6b", "none")
    if status == "draft":
        return AssessmentBadge("Draft — does not score", "#6b6b6b", "draft")
    if status == "submitted":
        who = f" by {author_name}" if author_name else ""
        return AssessmentBadge(f"🟠 Assessed{who} — awaiting sign-off", "#E8A33D", "pending")
    if status == "signed_off":
        who = signoff_label(author_name or "", approver_name)
        when = f", {approved_at:%d %b %Y}" if approved_at else ""
        tail = f" by {who}{when}" if who else when
        return AssessmentBadge(f"🟢 Signed off{tail}", "#2E7D32", "approved")
    # An unrecognised status must be visible, not silently rendered as one of the known ones.
    return AssessmentBadge(f"Unknown status ({status})", RED, "unknown")


def render(badge: AssessmentBadge) -> None:
    st.markdown(
        f'<span style="background:{badge.colour}1A;color:{badge.colour};'
        f'border:1px solid {badge.colour}55;border-radius:4px;padding:.15rem .5rem;'
        f'font-size:.8rem;font-weight:600;">{badge.text}</span>',
        unsafe_allow_html=True)
