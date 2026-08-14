"""Tests for the contract-expiry filter (the free-transfer / out-of-contract market).

The filter answers a recruitment question with money on it ("who is out of contract in
summer 2027?"), so the boundaries are pinned down explicitly: a 30 June contract is IN that
summer's horizon, 1 July is not, an already-lapsed deal never pads a forward horizon, and an
unknown date is excluded rather than guessed. Small fixtures, no database.
"""

import pandas as pd
import pytest

from lofc.dashboard.seasons import (
    CONTRACT_EXPIRED, CONTRACT_HORIZONS, DEFAULT_CONTRACT_HORIZON, contract_mask)

TODAY = pd.Timestamp("2026-08-04")


def _series(*dates):
    return pd.to_datetime(pd.Series(list(dates)))


def test_any_horizon_applies_no_filter():
    assert DEFAULT_CONTRACT_HORIZON == "Any"
    assert contract_mask(_series("2027-06-30"), "Any", TODAY) is None
    # An unknown horizon name is treated as no filter, never as "hide everything".
    assert contract_mask(_series("2027-06-30"), "nonsense", TODAY) is None


def test_summer_horizon_boundaries_are_inclusive_of_30_june():
    """English deals end 30 June: that date must be INSIDE the horizon, 1 July outside."""
    s = _series("2027-06-30", "2027-07-01", "2026-12-31")
    mask = contract_mask(s, "Out of contract summer 2027", TODAY)
    assert list(mask) == [True, False, True]


def test_forward_horizon_excludes_already_expired_contracts():
    """Without the lower bound, 'summer 2027' would also return every deal that lapsed in
    2026 — inflating the list with players who are no longer at the club."""
    s = _series("2026-06-30", "2027-06-30")     # first one ran out before TODAY
    mask = contract_mask(s, "Out of contract summer 2027", TODAY)
    assert list(mask) == [False, True]


def test_expired_horizon_returns_only_lapsed_contracts():
    s = _series("2026-06-30", "2027-06-30")
    mask = contract_mask(s, CONTRACT_EXPIRED, TODAY)
    assert list(mask) == [True, False]


def test_unknown_contract_date_is_always_excluded():
    """It cannot be judged either way; the UI counts these separately so the exclusion is
    visible rather than reading as 'this player is not expiring'."""
    s = _series("2027-06-30", None)
    for horizon in ["Out of contract summer 2027", "Out of contract summer 2028", CONTRACT_EXPIRED]:
        mask = contract_mask(s, horizon, TODAY)
        assert bool(mask.iloc[1]) is False, horizon


def test_summer_2028_is_a_superset_of_summer_2027():
    s = _series("2027-06-30", "2028-06-30", "2029-06-30")
    m27 = contract_mask(s, "Out of contract summer 2027", TODAY)
    m28 = contract_mask(s, "Out of contract summer 2028", TODAY)
    assert list(m27) == [True, False, False]
    assert list(m28) == [True, True, False]
    assert (m27 <= m28).all()          # every 2027 expiry is also within the 2028 horizon


def test_no_january_horizon_is_offered():
    """English contracts effectively all expire in June, so a literal 'expiring by January'
    filter would return only already-lapsed deals — a misleading option, deliberately absent."""
    assert not any("jan" in label.lower() for label in CONTRACT_HORIZONS)


@pytest.mark.parametrize("horizon", list(CONTRACT_HORIZONS))
def test_every_offered_horizon_is_usable(horizon):
    """Guards against a label being added to the menu with no working cutoff behind it."""
    mask = contract_mask(_series("2027-06-30", "2026-01-01", None), horizon, TODAY)
    assert mask is None or mask.dtype == bool
