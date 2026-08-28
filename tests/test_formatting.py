"""Tests for dashboard/formatting.py -- the em-dash-safe table-cell formatters.

I1/I3 (audit-dashboard.md): `st.column_config.NumberColumn`/`LinkColumn` render a missing
cell as the literal text "None" or "nan" in this deployment rather than leaving it blank
(confirmed directly against the running app -- see formatting.py's docstring). These
helpers are the fix: format to text (or a blank string for a link) before the value ever
reaches a NumberColumn/LinkColumn.
"""

import numpy as np
import pandas as pd

from lofc.dashboard.formatting import link_or_blank, numeric_or_dash, value_or_dash


def test_value_or_dash_formats_a_present_scalar():
    assert value_or_dash(23.456, "{:.1f}") == "23.5"


def test_value_or_dash_blanks_missing_scalars_as_em_dash():
    assert value_or_dash(np.nan, "{:.1f}") == "—"
    assert value_or_dash(None, "{:.1f}") == "—"
    assert value_or_dash(pd.NA, "{:.1f}") == "—"


def test_numeric_or_dash_formats_present_values():
    out = numeric_or_dash(pd.Series([23.0, 9.5]), "{:.1f}")
    assert list(out) == ["23.0", "9.5"]


def test_numeric_or_dash_blanks_nan_as_em_dash():
    out = numeric_or_dash(pd.Series([23.0, np.nan]), "{:.1f}")
    assert list(out) == ["23.0", "—"]


def test_numeric_or_dash_blanks_none_and_pd_na_too():
    """The actual defect: a missing value is not always a numpy NaN -- a Python None or
    pandas' own pd.NA must be caught exactly the same way, not just np.nan."""
    out = numeric_or_dash(pd.Series([1.0, None, pd.NA], dtype="object"), "{:.0f}")
    assert list(out) == ["1", "—", "—"]


def test_numeric_or_dash_never_shows_zero_for_missing():
    """The platform's hard rule: absent must never read as zero."""
    out = numeric_or_dash(pd.Series([np.nan]), "{:.0f}")
    assert list(out) == ["—"]
    assert "0" not in out.iloc[0]


def test_numeric_or_dash_returns_nullable_string_dtype():
    out = numeric_or_dash(pd.Series([1.0, np.nan]), "{:.1f}")
    assert out.dtype == "string"


def test_link_or_blank_formats_present_ids():
    out = link_or_blank(pd.Series([627248.0, 572810.0]),
                        "https://www.transfermarkt.com/-/profil/spieler/{:.0f}")
    assert out.iloc[0] == "https://www.transfermarkt.com/-/profil/spieler/627248"
    assert out.iloc[1] == "https://www.transfermarkt.com/-/profil/spieler/572810"


def test_link_or_blank_is_empty_string_not_none_for_missing():
    """The defect this replaces: a `None` in a LinkColumn cell renders the literal text
    "None" rather than a blank cell -- an empty string does not."""
    out = link_or_blank(pd.Series([627248.0, np.nan]),
                        "https://www.transfermarkt.com/-/profil/spieler/{:.0f}")
    assert out.iloc[1] == ""
    assert out.iloc[1] is not None
