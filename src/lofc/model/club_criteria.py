"""The club's per-position Psychological and Medical criteria, transcribed verbatim from
`docs/LOFC - Position Archetype.docx`.

This is the companion to `club_framework.py`: that module holds WHAT the club measures from
data, this one holds what a human scores. Both are the club's own words, not our invention.

TEN club profiles map onto our EIGHT position groups (Decision 6). Right/Left Back merge into
Full Back and Left/Right Winger into Winger, de-duplicated where two bullets state the same
requirement. Where they state overlapping but distinct requirements, BOTH are kept -- merging
them would discard a constraint the club wrote.

Full Back, psychological: all six bullets (three Right Back + three Left Back) are distinct.
No merges -> 6 criteria.

Full Back, medical: "Permanent signings undergo MRI scan" and "Minimum 60% availability over
prior 2 seasons" appear identically on both sides -- kept once each. The two hamstring bullets
are NOT identical ("No recurring hamstring injuries within the prior 12 months" is
time-bounded; "No recurring hamstring or calf injuries" is broader by type) -- both kept,
because merging them would discard a constraint the club wrote -> 4 criteria.

Winger, psychological: two genuine near-duplicate pairs merge, using the Right Winger wording
verbatim in both cases:
  - "High pressing work rate in defensive phase" absorbs
    "Work rate in defensive transitions; tracks back when required"
  - "Competitive drive to impact matches consistently" absorbs
    "Competitive edge; wants to be the difference-maker"
The other six (three Left Winger + three Right Winger, minus the two absorbed above) are
distinct -> 8 criteria.

Winger, medical: "No hamstring injury in prior 12 months (sprint-dependent position)" and
"No hamstring injury in prior 12 months" are the same requirement -- kept as the Left Winger
wording, which carries the club's rationale. "Minimum 60% availability..." appears on both --
kept once. "Quadriceps and hip flexor screening clear" and "Hip and groin screening clear for
high-COD activities" concern different structures -- both kept -> 5 criteria.

Criterion counts vary from 2 to 8 by position. That is the club's document. Do not pad.
"""

from __future__ import annotations

from dataclasses import dataclass

POSITION_GROUPS: tuple[str, ...] = (
    "Goalkeeper", "Centre Back", "Full Back", "Defensive Mid",
    "Central Mid", "Attacking Mid", "Winger", "Centre Forward",
)


@dataclass(frozen=True)
class MedicalCriterion:
    """One of the club's Medical & Durability requirements.

    `kind` follows Decision 7 (classified by substring on the bullet text):
      availability -- contains "availability"; computed as a figure and shown as evidence;
                       never produces a band
      protocol     -- contains "undergo"; a club process step, not a player attribute;
                       never scored
      screening    -- everything else; pass/fail, recorded by the assessor; warns, never
                       overrides (Decision 13)
    """

    text: str
    kind: str


def _classify(text: str) -> str:
    if "availability" in text:
        return "availability"
    if "undergo" in text:
        return "protocol"
    return "screening"


def _medical(*texts: str) -> list[MedicalCriterion]:
    return [MedicalCriterion(text=t, kind=_classify(t)) for t in texts]


# --- Psychological criteria, per position group (verbatim from the club's docx) --------
PSYCHOLOGICAL_CRITERIA: dict[str, list[str]] = {
    "Goalkeeper": [
        "Composure under high-pressure moments (penalty situations, late-game scenarios)",
        "Vocal leadership and defensive organization ability",
        "Emotional regulation after errors; rapid reset capacity",
    ],
    "Centre Back": [
        "Organizational leadership and vocal communication",
        "Composure under pressure; calm decision-making in own box",
        "Accountability for defensive errors; non-blame culture contributor",
        "Aggression channeled appropriately; minimal disciplinary risk",
    ],
    # Full Back = Right Back u Left Back. All six bullets are distinct; no merges.
    "Full Back": [
        "Decision-making speed in transition (when to overlap vs. hold)",
        "Resilience after being beaten 1v1; immediate recovery mentality",
        "Competitive drive and high work rate even in defensive phases",
        "Composure on the ball in deep build-up positions",
        "Willingness to track back and recover after attacking runs",
        "Tactical discipline to hold position when system demands it",
    ],
    "Defensive Mid": [
        "Positional discipline; resists urge to leave station",
        "Tactical intelligence; reads the game proactively",
        "Calm under pressure; rarely panics in possession",
    ],
    "Central Mid": [
        "Relentless work rate; highest-effort player on the pitch",
        "Goal hunger; arrives late in the box with intent",
        "Competitive intensity in pressing and duels",
    ],
    "Attacking Mid": [
        "Creative confidence; tries the difficult pass/dribble when appropriate",
        "Psychological resilience when chances are missed or plays break down",
        "Pressing discipline; contributes defensive effort willingly",
        "High-pressure performance; delivers in decisive moments",
        "Coachable; accepts tactical structure around creative freedom",
    ],
    # Winger = Left Winger u Right Winger. Two near-duplicate pairs merge, keeping the
    # Right Winger wording verbatim in both cases (see module docstring for rationale).
    "Winger": [
        "Confidence to take on defenders repeatedly regardless of outcome",
        "Resilience after failed dribbles; does not hide from the ball",
        "Composure in front of goal; converts opportunities",
        "Direct mentality; takes responsibility for creating chances",
        "High pressing work rate in defensive phase",
        "Ball retention composure when team is under pressure",
        "Competitive drive to impact matches consistently",
        "Adaptability to tactical variation (wide vs. inverted role)",
    ],
    "Centre Forward": [
        "Clinical finishing mentality; converts chances under pressure",
        "Work rate willingness; presses without complaint",
    ],
}

# --- Medical & Durability criteria, per position group (verbatim from the club's docx) -
MEDICAL_CRITERIA: dict[str, list[MedicalCriterion]] = {
    "Goalkeeper": _medical(
        "Permanent signings undergo MRI scan on 8 sites",
        "No chronic shoulder or wrist instability",
        "No history of ACL or significant knee ligament injury within prior 12 months",
        "Minimum 60% availability over prior 2 seasons",
    ),
    "Centre Back": _medical(
        "No history of significant knee ligament injury within prior 12 months",
        "Permanent signings undergo MRI scan",
        "Minimum 60% availability over prior 2 seasons",
    ),
    # Full Back = Right Back u Left Back. "Permanent signings undergo MRI scan" and
    # "Minimum 60% availability..." are identical on both sides -- kept once each. The two
    # hamstring bullets are distinct in scope (time-bounded vs. broader by injury type) --
    # both kept.
    "Full Back": _medical(
        "Permanent signings undergo MRI scan",
        "No recurring hamstring injuries within the prior 12 months",
        "No recurring hamstring or calf injuries",
        "Minimum 60% availability over prior 2 seasons",
    ),
    "Defensive Mid": _medical(
        "No recurring knee or ankle injuries",
        "Permanent signings undergo MRI scan",
        "Minimum 60% availability over prior 2 seasons",
    ),
    "Central Mid": _medical(
        "No recurring soft-tissue injuries (hamstring, calf, groin)",
        "Minimum 60% availability over prior 2 seasons",
        "Permanent signings undergo MRI scan",
    ),
    "Attacking Mid": _medical(
        "Permanent signings undergo MRI scan",
        "Knee stability screening clear",
        "No significant muscle injuries in prior 12 months",
        "Minimum 60% availability over prior 2 seasons",
    ),
    # Winger = Left Winger u Right Winger. The hamstring bullets state the same requirement
    # -- kept as the Left Winger wording (carries the club's rationale). Availability appears
    # on both -- kept once. The two screening bullets concern different structures -- both
    # kept.
    "Winger": _medical(
        "No hamstring injury in prior 12 months (sprint-dependent position)",
        "Ankle stability clear; no chronic sprains",
        "Quadriceps and hip flexor screening clear",
        "Minimum 60% availability over prior 2 seasons",
        "Hip and groin screening clear for high-COD activities",
    ),
    "Centre Forward": _medical(
        "No recurring soft-tissue injuries (hamstring, calf, groin)",
        "Knee and ankle stability screening clear",
        "Minimum 60% availability over prior 2 seasons",
    ),
}
