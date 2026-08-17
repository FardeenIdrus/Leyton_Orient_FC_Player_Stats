"""What the page must tell the user (spec section 10).

A HARD requirement, not a nice-to-have: every assumption, caveat and coverage limit behind
these scores belongs on the page, not in a design document nobody opens. Short plain
English -- a recruiter reads this between meetings, so a wall of text fails the requirement
as surely as saying nothing.

Held as data rather than inline markdown so the assessment form, the player profile and the
exported report all show the identical wording, and so the tests can check none has gone
missing.
"""

from __future__ import annotations

import streamlit as st

DISCLOSURES: list[tuple[str, str]] = [
    ("The Medical score is a person's judgement",
     "A member of staff scored this player against the club's requirement checklist, using "
     "their own judgement. No number on this page was turned into that score by the "
     "platform."),
    ("Injury data informs that judgement, never determines it",
     "Availability, matches missed, days out and the injury table are shown to the "
     "assessor as evidence. They are not added up, weighted, or mapped to a band."),
    ("A blank injury record is worth different things in different leagues",
     "Share of players with any injury record: Championship 74%, League One 39%, "
     "League Two 32%, National League 18%; PL2 4%, Scottish Premiership 5%, Scottish "
     "Championship 1%. Empty means 'we have nothing' far more often lower down."),
    ("What is actually knowable",
     "Counting minutes played as a cross-check, availability can be established for "
     "Championship 84%, League One 64%, League Two 58%, National League 49%. About half "
     "of National League targets cannot be established either way."),
    ("What availability counts",
     "Matches missed through injury over the last two seasons, against a 92-match "
     "window. A fit player who simply was not picked is not penalised."),
    ("What minutes played is for",
     "It is not part of availability — 73% of players would fall below the club's 60% "
     "bar on minutes alone, which reflects rotation, not fitness. It is an independent "
     "check: 2,000+ minutes is proof of availability whatever the injury record says."),
    ("What the injury categories do and do not affect",
     "Illness, knocks and unspecified entries land in 'other'. Category never changes "
     "the availability figure, which counts matches missed regardless. Categories matter "
     "only for the club's specific screening criteria."),
    ("Where the 1–5 scale comes from",
     "The club's own rubric — 1 Unacceptable, 2 Below Standard, 3 Meets Standard, "
     "4 Above Standard, 5 Elite. For Medical the club defines minimum requirements but "
     "no elite threshold, so 3 is the practical ceiling. Nothing here is invented."),
    ("A known blind spot",
     "A player who joined part-way through the window is measured against the full 92 "
     "matches, which understates his availability. It affects only players who were also "
     "injured, and the spells behind the figure are shown so you can see it."),
    ("'No injuries recorded' is not 'no injuries'",
     "Where the platform cannot tell, it says 'not known' rather than showing a clean "
     "record."),
    ("Psychological is entirely human judgement",
     "There is no data behind it. It is the scout's assessment against the club's own "
     "criteria for that position."),
    ("Nothing here excludes a player",
     "Every flag is advisory, consistent with the rest of the platform. A flag marks a "
     "player; it never removes them from any list."),
    ("Every figure shows its provenance and its date",
     "Scraped versus entered by hand, who entered it, and when."),
]


def render_panel() -> None:
    """The compact 'what this covers / what it doesn't' panel.

    Collapsed by default so it does not push the assessor's work below the fold, but it sits
    at the TOP of the form rather than in a footer -- a caveat below the thing it qualifies
    has already failed.
    """
    with st.expander("What this covers, and what it doesn't", expanded=False):
        for heading, body in DISCLOSURES:
            st.markdown(f"**{heading}.** {body}")
