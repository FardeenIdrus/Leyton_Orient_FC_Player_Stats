"""Assessment status badges, rendered identically everywhere they appear.

Decision 14 and spec section 16: COLOUR NEVER CARRIES THE MEANING ALONE. Every badge states
its status in words, because printed reports and colour-blind readers lose the colour. The
emoji and the colour reinforce the words; they never replace them.

One module so a watchlist row and a player-profile row can never disagree about a player by
rendering two different badge sets.
"""

from __future__ import annotations

import datetime
import html
from dataclasses import dataclass

import streamlit as st

from lofc.dashboard.theme import RED
from lofc.model.scout_scores import CONFLICT, REJECTED


@dataclass(frozen=True)
class AssessmentBadge:
    text: str          # always carries the status in words
    colour: str        # reinforcement only
    tone: str          # "none" | "draft" | "pending" | "approved" | "conflict" | "rejected"
                       # | "unknown"


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
    if status == CONFLICT:
        # Decision 17: two or more unsigned assessments disagree, so nothing scores. Grey,
        # not red -- this is not an error state, it is an honest "nobody has decided yet",
        # and it renders identically wherever a badge appears (profile, watchlist, queue).
        return AssessmentBadge("⚪ Assessments conflict — not scored", "#6b6b6b", "conflict")
    if status == REJECTED:
        # Problem 3: a reviewer declined this one. Red IS warranted here -- unlike CONFLICT,
        # this is a decided, negative outcome, not a neutral "nobody has decided yet" -- but
        # the reason itself is too long for a badge and is shown separately by the caller
        # (`dashboard/assessment_detail.py`), never only implied by the colour.
        who = f" by {approver_name}" if approver_name else ""
        when = f", {approved_at:%d %b %Y}" if approved_at else ""
        return AssessmentBadge(f"🔴 Rejected{who}{when}", RED, "rejected")
    # An unrecognised status must be visible, not silently rendered as one of the known ones.
    return AssessmentBadge(f"Unknown status ({status})", RED, "unknown")


def _badge_html(badge: AssessmentBadge) -> str:
    """The escaped markup for one badge. Pulled out of `render` so it is testable without a
    Streamlit runtime.

    MINOR 8: `badge.text` can carry `author_name` / `approver_name`, which come from
    `users.full_name` -- an admin-entered value, not one the platform validates. Interpolated
    unescaped into HTML rendered with `unsafe_allow_html=True`, a name containing '<' or '>'
    breaks the badge (at best) or injects markup (at worst). Escaping the whole composed
    string here, not just the name at its call site, closes this regardless of which field
    `badge.text` was built from.
    """
    return (f'<span style="background:{badge.colour}1A;color:{badge.colour};'
            f'border:1px solid {badge.colour}55;border-radius:4px;padding:.15rem .5rem;'
            f'font-size:.8rem;font-weight:600;">{html.escape(badge.text)}</span>')


def render(badge: AssessmentBadge) -> None:
    st.markdown(_badge_html(badge), unsafe_allow_html=True)
