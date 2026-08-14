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

from lofc.config import settings

SEASON_LABELS = {317: "2024/25", 318: "2025/26", 319: "2026/27"}
# Season midpoint (1 Jan of the season's end year), the reference date for deriving age from
# a birth date. Per-season so a player's 2024/25 age reads ~1 year younger than his 2025/26 age.
SEASON_REF_DATE = {317: pd.Timestamp("2025-01-01"), 318: pd.Timestamp("2026-01-01"),
                   319: pd.Timestamp("2027-01-01")}


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
    show its age instead of implying the data is live. None if the file is unreadable."""
    try:
        path = Path(settings.reference_data_dir) / "transfermarkt" / "efl_values.csv"
        return datetime.date.fromtimestamp(path.stat().st_mtime).strftime("%d %b %Y")
    except Exception:
        return None
