"""The Medical dimension's objective input: availability from injury history.

    availability = 1 - (games missed through injury / scheduled games)

Only games missed THROUGH INJURY enter the numerator, so a player who was fit but
simply not selected is not penalised. Deriving availability from minutes played was
tested and rejected as the PRIMARY signal: 73% of rankable 2025/26 players fall
below a 60% bar on minutes / (46 * 90), which measures rotation, not fitness. It is
still used as a secondary, independent confirmation signal for players with no
injury records at all -- see `availability_with_evidence` below.

The club states 60% availability over the prior two seasons as the minimum standard.
The band formula that consumes this lives alongside it (added in the scout
assessment plan).

This module produces more than one number. `availability()` is a bare fraction and
cannot tell "genuinely never injured" from "Transfermarkt never recorded this
player" -- both look like a perfect record. Anything shown to a human (scout,
medical staff) as evidence must go through `availability_with_evidence()` instead,
which carries that distinction explicitly via `AvailabilityStatus`.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import pandas as pd

# League games per season. Held per competition rather than hard-coded so other
# leagues can be added when coverage allows. 46 is correct for all four: the three
# EFL divisions (Championship, League One, League Two) plus the National League,
# which is the tier below League Two but is separately administered, not part of
# the EFL.
SCHEDULED_GAMES: dict[int, int] = {
    3: 46,    # Championship
    4: 46,    # League One
    5: 46,    # League Two
    65: 46,   # National League
}

AVAILABILITY_SEASONS = 2

# Transfermarkt labels seasons "25/26"; our season_ids are 317 = 2024/25 upward.
_SEASON_LABELS: dict[int, str] = {317: "24/25", 318: "25/26", 319: "26/27"}

# Sentinel for an ongoing injury (NULL date_until): treated as still open, so it
# merges with -- and absorbs -- every later spell inside the window, however far
# apart their dates are, rather than being dropped or crashing. That can
# understate a genuinely separate later absence: an ongoing 10-match spell plus
# a truly distinct later 20-match spell merges to max(10, 20) = 20, not 30. That
# is the same conservative direction as the max-not-sum rule in
# _merge_overlapping_spells, and it is correct when the injury really is still
# open. But if a NULL here instead reflects missing/unscraped data rather than a
# genuinely open injury, this sentinel would silently erase a real later
# absence from the total -- there is currently no way to tell the two apart in
# the data, so that is a known limitation, not a bug.
_ONGOING_INJURY_SENTINEL = pd.Timestamp.max


def window_labels(season_id: int, seasons: int = AVAILABILITY_SEASONS) -> tuple[str, ...]:
    """The Transfermarkt season labels in the availability window, oldest first.

    Raises ValueError if any season id in the window is missing from
    _SEASON_LABELS. Silently dropping an unmapped id would shrink the window
    instead of erroring -- in the worst case (every id unmapped) that produces an
    empty window, which matches no injuries and reads the player as 100%
    available. That is a maintenance error (the mapping was not updated for a new
    season), not a genuine data gap, so it must fail loudly rather than guess.
    """
    ids = range(season_id - seasons + 1, season_id + 1)
    missing = [i for i in ids if i not in _SEASON_LABELS]
    if missing:
        raise ValueError(
            f"season_id {missing[0]} is not in _SEASON_LABELS -- add it to "
            "src/lofc/model/medical.py when a new season starts, or availability "
            "will silently under-count injuries"
        )
    return tuple(_SEASON_LABELS[i] for i in ids)


def _merge_overlapping_spells(inside: pd.DataFrame) -> int:
    """Merge overlapping/touching injury spells and sum the merged groups' maxima.

    Transfermarkt lists concurrent diagnoses -- e.g. Charlie Wyke's "Ankle
    injury" and "Broken leg", both logged 2024-10-26 -> 2026-01-30, 64 matches
    each -- as separate rows describing the same absence. Summing them reads
    128 matches missed against an actual 64. The fix: sort spells by
    date_from, merge any whose date ranges overlap or touch into groups, and
    within each merged group take the MAX games_missed rather than the sum,
    then sum across groups.

    Max, not sum, within a group: for the dominant real case -- identical
    concurrent diagnoses -- max is exactly right, since both rows describe one
    absence. For a genuine partial overlap (spell A Jan-Mar/10 matches, spell
    B Feb-Apr/8 matches) max slightly UNDERSTATES the true total, because the
    merged date range covers more calendar time than either spell alone. That
    understatement is the correct direction to err: this figure feeds a human
    medical/scouting judgement, not a score, and overstating a player's
    injury record is worse than being conservative about it. Do not "fix"
    this back to a sum.

    A NULL date_until (an ongoing injury) is treated as extending to
    _ONGOING_INJURY_SENTINEL -- see its definition for why -- rather than
    being dropped or raising.
    """
    if inside.empty:
        return 0
    starts = pd.to_datetime(inside["date_from"])
    ends = pd.to_datetime(inside["date_until"]).fillna(_ONGOING_INJURY_SENTINEL)
    games = inside["games_missed"].fillna(0)
    spells = sorted(zip(starts, ends, games), key=lambda spell: spell[0])

    total = 0
    group_end = None
    group_max = 0
    for start, end, missed in spells:
        if group_end is not None and start <= group_end:
            # Overlaps (or exactly touches) the current group: same absence.
            group_max = max(group_max, missed)
            group_end = max(group_end, end)
        else:
            if group_end is not None:
                total += group_max
            group_max = missed
            group_end = end
    total += group_max
    return int(round(total))


def games_missed_in_window(injuries: pd.DataFrame, season_id: int,
                           seasons: int = AVAILABILITY_SEASONS) -> int:
    """Total games missed through injury inside the window. No injuries -> 0.

    window_labels() is called before the empty-frame check (not after) so that an
    unmapped season id always raises, whether or not the player happens to have any
    injury rows. Checking emptiness first would make the maintenance error
    non-deterministic: it would raise for injured players and silently return 0 --
    a correct-looking number for the wrong reason -- for uninjured ones, so a
    forgotten _SEASON_LABELS update would look like an intermittent bug instead of
    a missing dict entry.

    Overlapping/concurrent spells inside the window are merged before counting
    -- see _merge_overlapping_spells for why summing raw rows double-counts.

    Column contract: a frame with any row surviving the season-label filter
    must have `date_from` and `date_until` columns (real injury rows always
    do -- see the module's column list in docs/DATA_ARCHITECTURE.md); missing
    either raises KeyError. A frame that is empty, or whose rows are all
    outside the window, never reaches the merge step and does not need them.
    """
    labels = window_labels(season_id, seasons)
    if injuries.empty:
        return 0
    inside = injuries[injuries["season_label"].isin(labels)]
    return _merge_overlapping_spells(inside)


def availability(games_missed: int, competition_id: int,
                 seasons: int = AVAILABILITY_SEASONS) -> float | None:
    """Fraction of scheduled games the player was fit for, clamped to [0, 1].

    Returns None for a competition with no scheduled-games constant -- the criterion
    is then unscored rather than defaulted, because a guessed availability feeding a
    medical score is worse than an honest gap.

    Do not call this directly for anything shown to a human. It only ever sees
    an integer `games_missed`, so it cannot tell "genuinely never injured"
    (games_missed=0 because there is real evidence of zero) from "never
    recorded" (games_missed=0 because there is no evidence at all) -- both
    read as a perfect 1.0. Use `availability_with_evidence()` instead, which
    carries that distinction explicitly.
    """
    scheduled = SCHEDULED_GAMES.get(competition_id)
    if not scheduled:
        return None
    total = scheduled * seasons
    return max(0.0, min(1.0, 1.0 - games_missed / total))


# A player who racked up this many minutes in a single season was demonstrably
# on the pitch for the bulk of it, whatever Transfermarkt does or doesn't say
# about injuries -- so it can stand in for a blank injury record. Chosen
# because, measured on real data, it clears ~37% of otherwise-blank records at
# a rate that is near-identical across leagues (Championship 34%, League One
# 39%, League Two 37%, National League 36%). That consistency is what makes it
# trustworthy: TM's injury-record COVERAGE varies wildly by league (74% in the
# Championship vs 18% in the National League), but this confirmation rate
# does not track that gap, so it is measuring fitness, not reporting quality.
#
# `availability_with_evidence()` scales this by its OWN `minutes_seasons`
# parameter, not by `seasons` -- those two are deliberately independent.
# `seasons` sets the availability DENOMINATOR (scheduled games in the window);
# `minutes_seasons` sets how many seasons of minutes the caller is vouching
# for. Conflating them is a real bug we hit once already: telling a caller who
# only holds one season of minutes to pass seasons=1 "for this call" also
# halves the denominator for every MEASURED player sharing that call, since
# `seasons` is forwarded straight into `availability()`. Pass `minutes_seasons`
# instead, and leave `seasons` matching the actual availability window.
MINUTES_CONFIRM_AVAILABILITY_PER_SEASON = 2000


class AvailabilityStatus(Enum):
    """How an availability figure was arrived at, for display to a human."""

    # Injury records exist for the player; the value comes from that evidence.
    MEASURED = "measured"
    # No injury records, but minutes played demonstrably rule out a long
    # absence -- an independent confirmation, not an assumption.
    CONFIRMED_BY_MINUTES = "confirmed_by_minutes"
    # No injury records and nothing else confirms availability. This is a
    # genuine data gap, not a clean record, and must render as such.
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class AvailabilityEvidence:
    """The availability figure plus how it was arrived at.

    `value` is `None` in two distinct cases, not one:
      - status is UNKNOWN: always None -- there is no evidence at all.
      - status is MEASURED and `competition_id` has no SCHEDULED_GAMES entry:
        also None -- there IS injury evidence, but the criterion is unscored
        for this league (see `availability()`), not a data gap about the
        player. Do not assume MEASURED implies a non-None value.
    CONFIRMED_BY_MINUTES is always 1.0.

    Consumers must check `status` before using `value` in arithmetic, and must
    never treat a None as "unavailable" (0.0) or silently coalesce it to
    anything -- it means "not known" or "not scored", and the whole point of
    this type is to stop that distinction from being lost.
    """

    status: AvailabilityStatus
    value: float | None


def availability_with_evidence(
    injuries: pd.DataFrame,
    games_missed: int,
    competition_id: int,
    minutes_played: int | None,
    seasons: int = AVAILABILITY_SEASONS,
    minutes_seasons: int | None = None,
) -> AvailabilityEvidence:
    """Availability plus whether it is measured, confirmed, or unknown.

    `availability()` alone cannot distinguish a player who was genuinely never
    injured from one Transfermarkt simply never recorded -- both produce
    games_missed=0 and read as a perfect record. That is misleading: TM's
    injury-record coverage is 74% in the Championship but only 18% in the
    National League, so a blank record means very different things by league.

    This function resolves that by checking whether `injuries` is non-empty.
    Pass the player's full known injury history here, not a window-filtered
    slice: a player who has records outside the current window but none
    inside it still has genuine TM coverage (he was tracked and had no
    qualifying injury), which is a real MEASURED zero, unlike a player TM
    never tracked at all. Window-filtering happens separately, inside
    `games_missed` (typically via `games_missed_in_window`). Caveat: this
    means a player whose ENTIRE history predates the window also reads
    MEASURED, value 1.0 -- defensible (he was demonstrably tracked and has no
    qualifying absence anywhere on record), but that 1.0 rests on inference
    (no evidence of injury) rather than direct measurement (evidence of zero
    injury inside the window itself). Worth surfacing differently in the
    evidence panel if that distinction matters there.
      - Non-empty -> MEASURED. The value is whatever `availability()` returns
        for `games_missed` (which may itself be None, if `competition_id` has
        no SCHEDULED_GAMES entry -- that pass-through is deliberate, matching
        `availability()`'s own "unscored rather than defaulted" behaviour; see
        AvailabilityEvidence's docstring, MEASURED does not imply non-None).
      - Empty and `minutes_played` clears MINUTES_CONFIRM_AVAILABILITY_PER_SEASON
        scaled by `minutes_seasons` (defaults to `seasons` if not given) ->
        CONFIRMED_BY_MINUTES, value 1.0. This check is independent of
        `competition_id` / SCHEDULED_GAMES: minutes played is a fact about the
        player, not something derived from the league's fixture count, so it
        applies even to competitions with no scheduled-games constant.

        `minutes_seasons` is deliberately separate from `seasons`: `seasons`
        sets the availability DENOMINATOR via `availability()`, so it must
        match the actual window regardless of what minutes data happens to be
        available. If a caller only holds one season of minutes (not the
        full multi-season window), pass `minutes_seasons=1` -- do NOT pass
        `seasons=1` to compensate, since that would also halve the
        denominator for every MEASURED player sharing the call.
      - Empty and minutes don't clear the bar (including `minutes_played`
        being None/missing/NA -- never assume) -> UNKNOWN, value None. A
        blank record must never render as a clean one.
    """
    if not injuries.empty:
        return AvailabilityEvidence(AvailabilityStatus.MEASURED,
                                    availability(games_missed, competition_id, seasons))

    effective_minutes_seasons = seasons if minutes_seasons is None else minutes_seasons
    threshold = MINUTES_CONFIRM_AVAILABILITY_PER_SEASON * effective_minutes_seasons
    if not pd.isna(minutes_played) and minutes_played >= threshold:
        return AvailabilityEvidence(AvailabilityStatus.CONFIRMED_BY_MINUTES, 1.0)

    return AvailabilityEvidence(AvailabilityStatus.UNKNOWN, None)
