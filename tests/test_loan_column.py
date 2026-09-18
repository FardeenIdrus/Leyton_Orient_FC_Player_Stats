"""The loan filter must show WHERE A PLAYER IS NOW, not just that he is on loan.

The Players page shows one season at a time -- the Club column is the club he played for in
THAT season. The loan filter uses 2026/27, the only season loans exist for. So filtering to
loans produced rows selected by a current-season fact next to a previous-season club:
measured, 208 of 221 rows showed a club the player had already left.

Ben Brereton Díaz is the case: Southampton own him, Sheffield United have him on loan now,
and Derby County is where he played in 2025/26. All three are true and the row showed only
Derby. Nothing was wrong with the data; the row simply did not say where he is today.

This column says it. No caption, no explanation -- the fact itself.
"""

import pandas as pd

from lofc.dashboard.tabs.players import on_loan_at_column


def test_it_names_the_current_club_and_the_owner():
    out = on_loan_at_column(pd.Series(["Sheffield United"]), pd.Series(["Southampton FC"]))
    assert out[0] == "Sheffield United (from Southampton FC)"


def test_a_player_not_on_loan_is_blank():
    """Blank, never "None" or "nan" -- the column renders as text."""
    out = on_loan_at_column(pd.Series([None]), pd.Series([None]))
    assert out[0] == ""


def test_an_unknown_parent_still_names_where_he_is():
    """Where he is playing is the more useful half; do not withhold it for a missing owner."""
    out = on_loan_at_column(pd.Series(["Sheffield United"]), pd.Series([None]))
    assert out[0] == "Sheffield United"


def test_nan_does_not_leak_as_text():
    out = on_loan_at_column(pd.Series([float("nan")]), pd.Series([float("nan")]))
    assert out[0] == ""
    assert "nan" not in out[0].lower()


def test_an_empty_series_is_handled():
    assert list(on_loan_at_column(pd.Series(dtype=object), pd.Series(dtype=object))) == []


def test_the_real_case_reads_correctly():
    """What a recruiter sees on the Brereton Díaz row once this column exists."""
    out = on_loan_at_column(pd.Series(["Sheffield United"]), pd.Series(["Southampton FC"]))
    assert out[0] == "Sheffield United (from Southampton FC)"
