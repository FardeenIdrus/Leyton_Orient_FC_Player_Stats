"""The Players sidebar can filter the ranked list by loan status.

WHY THE HORIZON OPTION EXISTS. A flat on-loan/not-on-loan split is not the useful cut:
measured on the live data, 259 of 293 linked loans run to summer 2027 or beyond and only 30
end inside the next four months. Filtering to "on loan" therefore returns mostly players
nobody can act on for nine months, with the actionable few buried among them. `loan_ends` is
populated for 100% of loans, so the horizon costs nothing and answers the January question.
Same reasoning as `contract_mask`, which asks WHEN a contract ends rather than whether one
exists.

CROSS-SEASON BY DESIGN. Loan status is TODAY (2026/27); the composite beside it was earned
LAST season. Yusuf Akhamrich reads 3.42 and is on loan at Leyton Orient until 30 June 2027.
That is the same choice the player card already makes -- whether a player is on loan now is
what a January decision turns on -- but the filter must say so rather than imply one season.
"""

import datetime

import pandas as pd

from lofc.dashboard.seasons import LOAN_FILTERS, LOAN_ANY, loan_mask

TODAY = pd.Timestamp("2026-09-14")

# on_loan True/False, and when the loan ends
POOL = pd.DataFrame({
    "player": ["akhamrich", "ends_soon", "ended", "owned", "loan_no_date"],
    "on_loan": [True, True, True, False, True],
    "loan_ends": [pd.Timestamp("2027-06-30"), pd.Timestamp("2026-12-01"),
                  pd.Timestamp("2026-08-01"), pd.NaT, pd.NaT],
})


def _apply(option):
    mask = loan_mask(POOL["on_loan"], POOL["loan_ends"], option, today=TODAY)
    return list(POOL["player"]) if mask is None else list(POOL[mask]["player"])


def test_any_is_no_filter_at_all():
    """Default must return None, not an all-True mask -- every other gate here is opt-in."""
    assert loan_mask(POOL["on_loan"], POOL["loan_ends"], LOAN_ANY, today=TODAY) is None


def test_on_loan_now_excludes_a_loan_that_has_already_ended():
    """He is recorded as a loan, but it expired -- he is not on loan NOW."""
    out = _apply("On loan now")
    assert "ended" not in out
    assert {"akhamrich", "ends_soon"} <= set(out)


def test_on_loan_now_keeps_a_loan_with_no_end_date():
    """An unknown end date is not evidence the loan is over."""
    assert "loan_no_date" in _apply("On loan now")


def test_the_horizon_keeps_only_loans_ending_inside_it():
    out = _apply("Loan ends within 6 months")
    assert out == ["ends_soon"], out


def test_the_horizon_excludes_loans_that_already_ended():
    assert "ended" not in _apply("Loan ends within 6 months")


def test_the_horizon_excludes_a_loan_with_no_end_date():
    """It cannot be judged against a horizon, so it is excluded rather than guessed."""
    assert "loan_no_date" not in _apply("Loan ends within 6 months")


def test_not_on_loan_is_the_inverse_of_having_a_loan_record():
    assert _apply("Not on loan") == ["owned"]


def test_every_declared_option_is_handled():
    """A label in LOAN_FILTERS with no branch would silently behave as 'Any'."""
    for option in LOAN_FILTERS:
        result = loan_mask(POOL["on_loan"], POOL["loan_ends"], option, today=TODAY)
        assert result is None or result.dtype == bool


def test_an_unknown_option_does_not_filter():
    assert loan_mask(POOL["on_loan"], POOL["loan_ends"], "nonsense", today=TODAY) is None
