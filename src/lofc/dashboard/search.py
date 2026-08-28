"""The global player search index: one row per player-season, spanning every position and
every league in a season, so a name can be found without already knowing his position group.

Pure pandas transforms over an already-loaded candidates frame (no Streamlit, no database),
so the shaping logic is directly testable in isolation from the widget that renders it —
matching the project convention (`tabs/players.py::_player_options`, `_metrics_held_by_anyone`)
of keeping data decisions out of the render layer.
"""

from __future__ import annotations

import unicodedata

import pandas as pd

_INDEX_COLUMNS = ["player_id", "competition_id", "season_id", "player_name", "team_name",
                  "position_group", "league"]


def build_search_index(candidates: pd.DataFrame) -> pd.DataFrame:
    """One row per (player, competition, season), labelled for a search dropdown.

    Takes the SEASON-scoped candidates frame before any sidebar filter (position, league,
    age, foot, contract) is applied -- so the index it builds covers every position and every
    league for that season, exactly what the global search needs. A player with no name or
    no position group (should not happen, but a frame is data, not a guarantee) is dropped
    rather than shown as a blank, unlabelled row.
    """
    idx = candidates[_INDEX_COLUMNS].dropna(subset=["player_name", "position_group"])
    idx = idx.drop_duplicates(subset=["player_id", "competition_id", "season_id"])
    idx = idx.reset_index(drop=True)
    club = idx["team_name"].fillna("Unknown club")
    idx["label"] = (idx["player_name"] + " — " + club + "  ·  " + idx["position_group"]
                    + "  ·  " + idx["league"].fillna("—"))
    return idx.sort_values("player_name", kind="stable").reset_index(drop=True)


def search_options(index: pd.DataFrame) -> tuple[list[str], dict[str, int]]:
    """Dropdown labels in index order, and a label -> row-position map (`.iloc` position,
    not the frame's own index) so a caller can do `index.iloc[by_label[picked]]` regardless
    of how `index` was built."""
    labels = index["label"].tolist()
    by_label = {label: pos for pos, label in enumerate(labels)}
    return labels, by_label


def fold(text: str) -> str:
    """Collapse text to a plain, comparable search key: strip diacritics (so 'é' == 'e'),
    casefold (so 'MENDEZ' == 'mendez'), and drop every non-alphanumeric character (so
    "O'Connor", "OConnor" and "O-Connor" -- and "Méndez-Laing", "Mendez Laing" and
    "MendezLaing" -- all fold to the same key).

    Needed because the search widget's own in-browser type-ahead filter matches only the
    literal displayed text: it does not fold accents, and typing an unaccented query against
    an accented name can silently fail to match (or worse, fall back to an unrelated fuzzy
    guess) rather than finding the player -- see `filter_labels`, which uses this to do the
    matching in Python instead. `unicodedata.normalize("NFKD", ...)` decomposes an accented
    character into its base letter plus a separate combining mark; dropping every character
    `unicodedata.combining()` flags then leaves just the base letters.
    """
    if text is None:
        return ""
    decomposed = unicodedata.normalize("NFKD", str(text))
    base_letters = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return "".join(ch for ch in base_letters.casefold() if ch.isalnum())


def filter_labels(labels: list[str], query: str) -> list[str]:
    """Labels whose folded text contains the folded query as a substring -- an accent-,
    case- and punctuation-insensitive search ("Mendez", "mendez" and "Méndez" all find
    "Nathaniel Méndez-Laing"; "OConnor" and "O'Connor" both find "O'Connor").

    A blank query returns every label, unfiltered: this backs a widget that also supports
    browsing without typing anything, not just searching.
    """
    folded_query = fold(query)
    if not folded_query:
        return list(labels)
    return [label for label in labels if folded_query in fold(label)]
