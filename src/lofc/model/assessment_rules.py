"""The scoring rules for a scout assessment. Pure -- no database, no Streamlit.

Two dimensions, two very different rules:

  Psychological -- the equal-weighted mean of the club's criteria for the player's position
                   (Decision 8). Every criterion must be scored, or it stays a draft.
  Medical       -- NO FORMULA (Decision 12). A person enters the band with the injury
                   evidence in front of them. The screening checklist WARNS and never
                   changes that number (Decision 13).
"""

from __future__ import annotations

import re

from lofc.model import club_criteria as cc

# The club's own 1-5 rubric, verbatim. Not invented here and not to be reworded.
BAND_LABELS: dict[int, str] = {
    1: "Unacceptable",
    2: "Below Standard",
    3: "Meets Standard",
    4: "Above Standard",
    5: "Elite",
}

# Shown next to the Medical input. The club's metric tables carry both a "Minimum Standard"
# and an "Elite Threshold" column; Medical & Durability lists minimum requirements only. So
# 4 and 5 have nothing to be measured against. The form SAYS this rather than clamping the
# value -- the ceiling is a consequence of the club's rubric, not a rule the platform imposes.
MEDICAL_CEILING_NOTE = (
    "The club defines minimum medical requirements but no elite threshold, so 4 and 5 have "
    "nothing to be scored against — in practice 3 is the ceiling here. You may still enter "
    "4 or 5; nothing is capped."
)


def criterion_key(text: str) -> str:
    """A stable storage key for one criterion.

    Derived from the criterion's own wording so it survives a reordering of the club's lists,
    which a positional index would not. Kept long enough to stay unique: Full Back carries
    two hamstring criteria whose openings match, and collapsing them would let one silently
    overwrite the other's answer.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:120]


def _psych_keys(position: str) -> list[str]:
    return [criterion_key(t) for t in cc.PSYCHOLOGICAL_CRITERIA[position]]


def _screening_keys(position: str) -> list[str]:
    return [criterion_key(c.text)
            for c in cc.MEDICAL_CRITERIA[position] if c.kind == "screening"]


def psychological_band(scores: dict[str, int], position: str) -> float | None:
    """The equal-weighted mean of this position's criteria, or None if any is unscored.

    Raises KeyError for an unknown position -- spec section 18 requires assessment to be
    BLOCKED with a clear message rather than scored against no criteria, and returning None
    here would be indistinguishable from an incomplete form.

    Keys not belonging to this position are ignored, so a stale answer left over from a
    different position group cannot enter the mean.
    """
    keys = _psych_keys(position)
    answered = [scores[key] for key in keys if scores.get(key) is not None]
    if len(answered) != len(keys):
        return None
    return sum(answered) / len(answered)


def psychological_status(scores: dict[str, int], position: str) -> str:
    """`submitted` once every criterion is scored, `draft` until then."""
    return "draft" if psychological_band(scores, position) is None else "submitted"


def screening_failed(passes: dict[str, bool], position: str) -> bool:
    """True if any `screening` criterion was marked failed.

    Only `screening` criteria count (Decision 7): an `availability` criterion is a computed
    figure shown as evidence, and a `protocol` criterion ("undergo MRI scan") is a club
    process step rather than a player attribute. Neither can raise this flag.

    Unanswered criteria are NOT failures -- an incomplete form is a draft, which
    `medical_status` handles; treating a blank as a failure would flag every half-filled form.
    """
    return any(passes.get(key) is False for key in _screening_keys(position))


def medical_status(band: float | None, passes: dict[str, bool], position: str) -> str:
    """`submitted` once a band is entered and every screening criterion is answered.

    DECISION 13: a failed screening criterion does NOT change the returned status and does
    NOT cap the band. It raises `screening_failed`, which the form, the profile and the
    export all show prominently -- and the assessor's number stands. The platform never
    overrules the better-informed party; it surfaces the disagreement instead.
    """
    if band is None:
        return "draft"
    keys = _screening_keys(position)
    if any(passes.get(key) is None for key in keys):
        return "draft"
    return "submitted"
