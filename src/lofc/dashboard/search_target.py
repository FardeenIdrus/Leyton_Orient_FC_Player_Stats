"""Opening a searched player regardless of the sidebar.

The search index is season-wide (every position and league); the ranked list is not -- it is
cut by Position, age, league, contract, foot, loan, minutes and the thin-pool gate. A pick
used to be resolved against that cut list, so anyone outside it silently failed to open.
These helpers resolve him from the season-wide data instead. Pure pandas / dict logic (no
Streamlit, no database) so it is testable on its own.
"""

from __future__ import annotations

import re

import pandas as pd

from lofc.model.scorecard import MIN_PEERS_FOR_RANKING, peer_pool_sizes

KEYS = ["player_id", "competition_id", "season_id"]
# Same columns app.py merges onto the pool, so the card finds what it reads.
SCORECARD_COLUMNS = KEYS + [
    "objective_composite", "full_composite", "objective_weight_covered",
    "performance_band", "physical_band", "financial_band", "resale_band",
    "psychological_band", "medical_band", "veto", "below_min_composite"]

NOT_IN_LIST_CAPTION = "Not in your current list (sidebar filters)."


def resolve_search_target(candidates: pd.DataFrame, scorecards: pd.DataFrame,
                          key: tuple[int, int, int]) -> tuple[pd.Series | None, str]:
    """(row, reason) for one searched player-season, ignoring every sidebar filter.

    `candidates` and `scorecards` are the season's FULL frames. Reasons: "ok" (rated),
    "not_rated" (row returned without scores: no scorecard, or a peer pool below
    MIN_PEERS_FOR_RANKING, which the list withholds for the same reason), "not_found"
    (row None).
    """
    pid, cid, sid = (int(k) for k in key)
    hit = candidates[(candidates["player_id"] == pid) & (candidates["competition_id"] == cid)
                     & (candidates["season_id"] == sid)]
    if hit.empty:
        return None, "not_found"
    row = hit.iloc[0].copy()

    cards = scorecards
    # One scorecard row per archetype in the stored table; the card's default is All Metrics.
    if cards is not None and "archetype" in cards.columns:
        cards = cards[cards["archetype"] == "All Metrics"]
    mine = (cards[(cards["player_id"] == pid) & (cards["competition_id"] == cid)
                  & (cards["season_id"] == sid)]
            if cards is not None and len(cards) else pd.DataFrame())
    for col in SCORECARD_COLUMNS[len(KEYS):]:
        row[col] = mine.iloc[0][col] if not mine.empty and col in mine.columns else float("nan")
    # Advisory flags are booleans on the card; NaN is truthy and would raise a false warning
    # ("composite below the club minimum") on a player who simply has no rating.
    for flag in ("veto", "below_min_composite"):
        row[flag] = bool(row[flag]) if pd.notna(row[flag]) else False
    # Peer pool from the season's whole scorecard set, as app.py counts it.
    pool_size = (peer_pool_sizes(cards).get((cid, sid, row.get("position_group")))
                 if cards is not None and len(cards) else None)
    row["peer_count"] = pool_size if pool_size is not None else float("nan")

    rated = (not mine.empty and pd.notna(row["objective_composite"])
             and pool_size is not None and pool_size >= MIN_PEERS_FOR_RANKING)
    return row, ("ok" if rated else "not_rated")


def search_caption(reason: str, in_view: bool, minutes=None) -> str | None:
    """The ONE short line shown above a searched player's card, or None."""
    if reason == "not_rated":
        under = minutes is not None and pd.notna(minutes) and float(minutes) < 450
        return ("Not rated: under 450 minutes" if under
                else "Not rated: too few peers in his league and position")
    return None if in_view else NOT_IN_LIST_CAPTION


def clear_table_selection(state, base_key: str) -> None:
    """Reset the ranked table's row selection (its key carries this nonce), so a fresh search
    pick wins over an earlier click. A later click on the table still wins over the search."""
    state[base_key + "__nonce"] = state.get(base_key + "__nonce", 0) + 1


_TABLE_KEY = re.compile(r"^(?P<base>players_.+)__(?P<n>\d+)$")


def clear_all_table_selections(state) -> None:
    """Clear the selection of every ranked-table instance this session has rendered.

    A pick usually switches the sidebar Position, which changes the table's base key -- the
    table about to render may be one that holds an old click from earlier, so clearing only
    the current base key would miss it. Each base key seen as a `<base>__<n>` widget key is
    moved past its highest used nonce."""
    seen: dict[str, int] = {}
    for k in list(state.keys()):
        m = _TABLE_KEY.match(str(k))
        if m:
            seen[m["base"]] = max(seen.get(m["base"], 0), int(m["n"]))
    for base, n in seen.items():
        state[base + "__nonce"] = max(state.get(base + "__nonce", 0), n) + 1


def choose_detail_row(selected_rows: list[int], view: pd.DataFrame, search_row):
    """A clicked table row beats the searched player; otherwise the searched player."""
    if selected_rows and selected_rows[0] < len(view):
        return view.iloc[selected_rows[0]]
    return search_row
