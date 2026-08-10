"""The Medical dimension's objective input: availability from injury history.

    availability = 1 - (games missed through injury / scheduled games)

Only games missed THROUGH INJURY enter the numerator, so a player who was fit but
simply not selected is not penalised. Deriving availability from minutes played was
tested and rejected: 73% of rankable 2025/26 players fall below a 60% bar on
minutes / (46 * 90), which measures rotation, not fitness.

The club states 60% availability over the prior two seasons as the minimum standard.
The band formula that consumes this lives alongside it (added in the scout
assessment plan).
"""

from __future__ import annotations

import pandas as pd

# League games per season. All four EFL leagues play 46. Held per competition rather
# than hard-coded so other leagues can be added when coverage allows.
SCHEDULED_GAMES: dict[int, int] = {
    3: 46,    # Championship
    4: 46,    # League One
    5: 46,    # League Two
    65: 46,   # National League
}

AVAILABILITY_SEASONS = 2

# Transfermarkt labels seasons "25/26"; our season_ids are 317 = 2024/25 upward.
_SEASON_LABELS: dict[int, str] = {317: "24/25", 318: "25/26", 319: "26/27"}


def window_labels(season_id: int, seasons: int = AVAILABILITY_SEASONS) -> tuple[str, ...]:
    """The Transfermarkt season labels in the availability window, oldest first."""
    ids = range(season_id - seasons + 1, season_id + 1)
    return tuple(_SEASON_LABELS[i] for i in ids if i in _SEASON_LABELS)


def games_missed_in_window(injuries: pd.DataFrame, season_id: int,
                           seasons: int = AVAILABILITY_SEASONS) -> int:
    """Total games missed through injury inside the window. No injuries -> 0."""
    if injuries.empty:
        return 0
    labels = window_labels(season_id, seasons)
    inside = injuries[injuries["season_label"].isin(labels)]
    return int(inside["games_missed"].fillna(0).sum())


def availability(games_missed: int, competition_id: int,
                 seasons: int = AVAILABILITY_SEASONS) -> float | None:
    """Fraction of scheduled games the player was fit for, clamped to [0, 1].

    Returns None for a competition with no scheduled-games constant -- the criterion
    is then unscored rather than defaulted, because a guessed availability feeding a
    medical score is worse than an honest gap.
    """
    scheduled = SCHEDULED_GAMES.get(competition_id)
    if not scheduled:
        return None
    total = scheduled * seasons
    return max(0.0, min(1.0, 1.0 - games_missed / total))
