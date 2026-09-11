"""Season identity and contract-expiry horizons.

Small, dependency-free definitions of "which season is this" and "what does out-of-contract
by X mean", kept out of the loaders so they can be imported (and unit-tested) without a
database.
"""

from __future__ import annotations

import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from lofc.config import SEASON_REF_DATE, settings  # SEASON_REF_DATE re-exported for callers

SEASON_LABELS = {317: "2024/25", 318: "2025/26", 319: "2026/27"}


def season_name_for(season_id: int) -> str:
    return SEASON_LABELS.get(int(season_id), str(season_id))



CONTRACT_EXPIRED = "Contract already expired (free agents)"
CONTRACT_HORIZONS: dict[str, str] = {
    "Any": "",
    "Out of contract summer 2027": "2027-06-30",
    "Out of contract summer 2028": "2028-06-30",
    CONTRACT_EXPIRED: "expired",
}
DEFAULT_CONTRACT_HORIZON = "Any"


def contract_mask(contract_until: pd.Series, horizon: str,
                  today: pd.Timestamp | None = None) -> pd.Series | None:
    """Boolean mask for a contract-expiry horizon; None means 'no filter' ("Any").

    A forward horizon means "still under contract NOW, but expiring on or before the cutoff",
    so already-lapsed deals never pad the list (without the lower bound, "summer 2027" would
    also return every contract that ran out in 2026). The expired option is the opposite:
    deals that have already ended. An unknown date is always excluded -- it cannot be judged --
    and the caller counts those separately so the exclusion is visible, not silent.
    """
    cutoff = CONTRACT_HORIZONS.get(horizon, "")
    if not cutoff:
        return None
    today = today or pd.Timestamp.now().normalize()
    known = contract_until.notna()
    if cutoff == "expired":
        return known & (contract_until < today)
    return known & (contract_until >= today) & (contract_until <= pd.Timestamp(cutoff))



@st.cache_data(ttl=600)
def contract_data_date() -> str | None:
    """When the Transfermarkt scrape (our only contract-date source) last ran, so the UI can
    show its age instead of implying the data is live. None when no snapshot is stored.

    Reads `MAX(transfermarkt_squads.scraped_at)`. This used to stat the scrape CSV's mtime,
    which was a proxy for the same fact and a poor one: any `touch`, copy or checkout moved
    it without the data changing, and on a host where the dashboard does not share a disk
    with the scraper the file is absent entirely, so the date silently vanished. The stamp
    is written by the loader at load time, so it is the real thing.
    """
    try:
        from lofc.dashboard.loaders import get_engine
        from lofc.store import squads as store_squads
        stamp = store_squads.scraped_at(get_engine())
        return stamp.strftime("%d %b %Y") if stamp is not None else None
    except Exception:
        return None


def default_season_id(available: list[int], live_season_id: int | None) -> int:
    """The season the Players page should OPEN on: the most recent COMPLETE one.

    `available_seasons()` returns newest first, so the live season -- the one still being
    played -- used to be the landing default the moment it gained its first rankable player.
    That is the wrong default: a composite is a percentile within a league-position pool, and
    early in a season those pools are tiny. On 2026-09-11, five matches into 2026/27, 19 of
    its 36 pools held fewer than ten players and two held exactly one; a player alone in his
    pool ranks 100th percentile on every metric by construction and scores 4.90, above
    anything earned across a full 46-game season.

    The live season stays in the selector and is one click away -- this decides what opens,
    not what exists. Falls back to the newest season held when every season is live (a fresh
    database mid-season) so the page always opens on something.
    """
    complete = [s for s in available if s != live_season_id]
    return max(complete) if complete else max(available)


def ranking_notice(n_ranked: int, n_withheld: int, season: str, complete_season: str,
                   position: str) -> tuple[str, str] | None:
    """What the Players page must say above a ranked list that is short or empty.

    Returns (level, text) for `st.warning`/`st.info`, or None when the list is healthy.

    Two separate causes produce a thin or blank list, and a recruiter cannot tell them apart
    from the table alone:
      * players were WITHHELD because their league-position pool is below the ranking floor
        (a composite there ranks a player against almost nobody);
      * nobody has reached 450 minutes yet, so no composite exists at all.
    Before this existed, selecting 2026/27 rendered an empty table with no message of any
    kind -- `ranking` was non-empty so the "season under way" notice never fired, while the
    candidate pool was empty. Silence reads as a broken page.

    Both messages point at Squads & loans, which answers "who is at this club right now" with
    current facts and no score -- the question the ranking cannot answer early in a season.
    """
    plural = f"{position.lower()}s"
    if n_ranked == 0:
        alternative = ("" if season == complete_season else
                       f" **{complete_season}** is complete and fully ranked.")
        return ("info",
                f"**No {plural} can be ranked in {season} yet.** A rating is a comparison "
                f"against players in the same league and position, and too few have played "
                f"enough of this season for that comparison to mean anything. "
                f"**Squads & loans** shows who is at each club right now — contract, loan "
                f"status and this season's minutes.{alternative}")
    if n_withheld:
        return ("warning",
                f"**{n_withheld} {plural} are not ranked here.** They have played 450+ "
                f"minutes, but fewer than 10 players in their league and position have — and "
                f"a rating compares a player against those peers, so with a pool that small "
                f"the number would say more about who has played than about the player. "
                f"**Squads & loans** lists them with this season's minutes and last season's "
                f"rating.")
    return None
