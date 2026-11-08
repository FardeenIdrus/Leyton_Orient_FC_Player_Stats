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
from sqlalchemy import text as sa_text

from lofc.config import SEASON_REF_DATE, settings  # SEASON_REF_DATE re-exported for callers

def season_name_for(season_id: int) -> str:
    """'2025/26' for 318 -- one rule for every season (lofc/leagues.py)."""
    from lofc.leagues import is_season_id, season_label
    return season_label(int(season_id)) if is_season_id(season_id) else str(season_id)



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
    """The season the Players page OPENS on: the newest held, i.e. the one being played.

    Owner, 2026-10-16, about ten matches into 2026/27: open on 2026/27. Early-season pools
    are still small, and that is handled where it matters -- `pool_is_thin` withholds any
    league-position pool under the floor and `ranking_notice` says how many -- not by
    hiding the live season. (September 2026, five matches in, it opened on the last
    complete season instead: 19 of 36 pools were under ten. See `last_complete_season_id`.)
    `live_season_id` is accepted for the call sites' symmetry and does not change the answer.
    """
    return max(available)


def last_complete_season_id(available: list[int], live_season_id: int | None) -> int:
    """The newest season that is NOT still being played. Falls back to the newest held
    when every season is live (a fresh database mid-season)."""
    complete = [s for s in available if s != live_season_id]
    return max(complete) if complete else max(available)


_MAX_NAMED = 6      # players named in the not-ranked line before "+N more"


def ranking_notice(n_ranked: int, withheld: pd.DataFrame, season: str,
                   complete_season: str, position: str) -> tuple[str, str] | None:
    """What the Players page must say above a ranked list that is short or empty.

    Returns (level, text) -- level "caption" (a quiet one-liner) or "info" (explains an empty
    table) -- or None when the list is healthy. `withheld` holds the withheld players, one
    row each, with player_name, team_name and league.

    Two separate causes produce a thin or blank list, and a recruiter cannot tell them apart
    from the table alone:
      * players were WITHHELD because their league-position pool is below the ranking floor
        (a composite there ranks a player against almost nobody);
      * nobody has reached 450 minutes yet, so no composite exists at all.
    Before this existed, selecting 2026/27 rendered an empty table with no message of any
    kind -- silence reads as a broken page. Kept to ONE line: it shows on
    several pages and a yellow paragraph read as an error.
    """
    from lofc.model.scorecard import MIN_PEERS_FOR_RANKING
    plural = f"{position}s"
    n_withheld = len(withheld)
    if n_ranked == 0:
        alternative = ("" if season == complete_season else
                       f" {complete_season} is fully ranked.")
        if n_withheld:
            # They HAVE 450+ minutes; what is missing is peers (smoke test, 2026-11-02:
            # "too few have 450+ minutes" was shown here, which was false).
            noun = position if n_withheld == 1 else plural
            counts = withheld["league"].fillna("Unknown league").value_counts()
            where = " · ".join(f"{lg} ({n})" for lg, n in sorted(counts.items()))
            return ("info",
                    f"No {plural} ranked in {season} yet — {n_withheld} {noun} rated, but "
                    f"fewer than {MIN_PEERS_FOR_RANKING} per league: {where}." + alternative)
        return ("info",
                f"No {plural} ranked in {season} yet — too few have 450+ minutes."
                + alternative)
    if n_withheld:
        noun = position if n_withheld == 1 else plural
        rows = withheld.assign(
            team_name=withheld["team_name"].fillna("Unknown club"),
            league=withheld["league"].fillna("Unknown league")
        ).sort_values(["player_name", "team_name"], kind="stable")   # stable between reruns
        shown = [f"{r.player_name} ({r.team_name}, {r.league})"
                 for r in rows.head(_MAX_NAMED).itertuples()]
        if n_withheld > _MAX_NAMED:
            shown.append(f"+{n_withheld - _MAX_NAMED} more")
        scope = "the league" if n_withheld == 1 else "their league"
        return ("caption",
                f"{n_withheld} {noun} not ranked (fewer than {MIN_PEERS_FOR_RANKING} rated in "
                f"{scope}): " + " · ".join(shown) + ("" if n_withheld > _MAX_NAMED else "."))
    return None


def age_reference_date(season_id: int, live_season_id: int | None = None,
                       today: datetime.date | None = None):
    """The date a player's age is measured at, for one season. None for an unknown season.

    A COMPLETED season uses its fixed midpoint (`SEASON_REF_DATE`), so the age stays put: a
    player WAS 24.2 while producing his 2025/26 numbers, and that does not change because
    time passes. The age sits beside the performance it belongs to.

    The LIVE season uses TODAY. Its midpoint is in the future -- `SEASON_REF_DATE[319]` is
    2027-01-01 -- so measuring against it made every 2026/27 player up to a year too old:
    Leon Chambers-Parillon read 25.2 on 2026-09-14 against an actual 24.9 (born 2001-11-05,
    Transfermarkt says 24). Age is a recruitment FILTER, so an inflated age pushes a player
    across a maximum-age threshold he has not reached.

    `today` is injectable so the behaviour is testable without freezing the clock.
    """
    if live_season_id is not None and season_id == live_season_id:
        return pd.Timestamp(today or datetime.date.today())
    return SEASON_REF_DATE.get(season_id)


# --- loan status -----------------------------------------------------------------------
# The sidebar's loan filter, shaped like CONTRACT_HORIZONS above. The HORIZON option is the
# one that earns its place: measured on the live data, 259 of 293 linked loans run to summer
# 2027 or later and only 30 end within four months, so a flat "on loan" filter returns mostly
# players nobody can act on for nine months. `loan_ends` is populated for 100% of loans.
LOAN_ANY = "Any"
LOAN_ON_NOW = "On loan now"
LOAN_ENDING = "Loan ends within 6 months"
LOAN_NOT = "Not on loan"
LOAN_FILTERS = [LOAN_ANY, LOAN_ON_NOW, LOAN_ENDING, LOAN_NOT]
_LOAN_HORIZON_DAYS = 183


def loan_mask(on_loan: pd.Series, loan_ends: pd.Series, option: str,
              today: pd.Timestamp | None = None) -> pd.Series | None:
    """Boolean mask for a loan-status option; None means "no filter" (the default).

    Returns None rather than an all-True mask for "Any", matching `contract_mask`: every gate
    on this platform is opt-in, and a caller can skip the filtering entirely.

    "On loan now" excludes a loan whose end date has already passed -- it is on record, but he
    is not on loan today -- while KEEPING a loan with no end date, since an unknown date is not
    evidence the loan is over. The horizon excludes both: a loan with no end date cannot be
    judged against a deadline, so it is left out rather than guessed at, the same rule
    `contract_mask` applies to an unknown contract date.

    NOTE the cross-season fact this encodes: loan status is TODAY, while the composite beside
    it was earned last season. Deliberate -- whether a player is on loan now is what a January
    decision turns on -- but the caller must say so on screen.
    """
    today = today or pd.Timestamp.now().normalize()
    has_loan = on_loan.fillna(False).astype(bool)
    ends = pd.to_datetime(loan_ends, errors="coerce")
    live = has_loan & (ends.isna() | (ends >= today))

    if option == LOAN_ON_NOW:
        return live
    if option == LOAN_ENDING:
        return live & ends.notna() & (ends <= today + pd.Timedelta(days=_LOAN_HORIZON_DAYS))
    if option == LOAN_NOT:
        return ~has_loan
    return None


@st.cache_data(ttl=600)
def loan_data_date() -> str | None:
    """When the loan scrape last ran, from `MAX(player_loans.scraped_at)`.

    Shown in the loan filter's own help text rather than in the page's "About this list"
    expander, where the contract snapshot date sits: that expander is collapsed and below the
    table, so in practice nobody reads it. The date matters at the moment someone filters on
    it. It matters MORE for loans than for contracts -- loans change constantly during a
    window, and Transfermarkt cannot be scraped from the server (AWS WAF), so this data only
    moves when a human runs the scrape on a workstation and pushes it. See register M1.
    """
    try:
        from lofc.dashboard.loaders import get_engine
        with get_engine().connect() as conn:
            value = conn.execute(
                sa_text("SELECT MAX(scraped_at) FROM player_loans")).scalar()
        return pd.to_datetime(value).strftime("%d %b %Y") if value is not None else None
    except Exception:
        return None


def calendar_months_left(when, today: datetime.date | None = None) -> int | None:
    """Whole calendar months from today to a contract expiry; negative = already expired.

    The one rule for Squads and Watchlist: days / 30.44 gave Nils Ramming (31 May 2027) 7 on
    one page and 6 on the other. None when the date is unknown -- never 0.
    """
    if when is None or pd.isna(when):
        return None
    today = today or datetime.date.today()
    end = pd.Timestamp(when).date()
    return (end.year - today.year) * 12 + (end.month - today.month)
