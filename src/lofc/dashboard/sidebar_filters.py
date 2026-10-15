"""The sidebar's player filters as one pure function, so every page applies the same rules.

Pages differ in column names and in which facts they hold, so the caller names its columns;
a column passed as None is a filter that page cannot apply.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from lofc.dashboard.seasons import DEFAULT_CONTRACT_HORIZON, LOAN_ANY, contract_mask, loan_mask

MAX_AGE_DEFAULT = 40


@dataclass(frozen=True)
class SidebarFilters:
    max_age: int = MAX_AGE_DEFAULT
    leagues: tuple[str, ...] = ()          # empty = every league
    contract_horizon: str = DEFAULT_CONTRACT_HORIZON
    loan: str = LOAN_ANY
    foot: str = "Any"


def apply_sidebar_filters(frame: pd.DataFrame, f: SidebarFilters, *,
                          age: str | None = None, league: str | None = None,
                          foot: str | None = None, contract: str | None = None,
                          on_loan: str | None = None, loan_ends: str | None = None,
                          today: pd.Timestamp | None = None) -> pd.DataFrame:
    """`frame` narrowed by every sidebar filter it has a column for. Returns a copy's view;
    the input is not mutated."""
    keep = pd.Series(True, index=frame.index)
    if age and f.max_age < MAX_AGE_DEFAULT:
        ages = pd.to_numeric(frame[age], errors="coerce")
        keep &= (ages <= f.max_age) | ages.isna()
    if league and f.leagues:
        keep &= frame[league].isin(f.leagues)
    if foot and f.foot != "Any":
        keep &= frame[foot].str.lower().isin([f.foot.lower(), "both"])
    if contract:
        mask = contract_mask(pd.to_datetime(frame[contract], errors="coerce"),
                             f.contract_horizon, today=today)
        if mask is not None:
            keep &= mask
    if on_loan:
        mask = loan_mask(frame[on_loan], frame[loan_ends] if loan_ends else
                         pd.Series(pd.NaT, index=frame.index), f.loan, today=today)
        if mask is not None:
            keep &= mask
    return frame[keep.fillna(False).astype(bool)]
