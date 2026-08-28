"""Table-cell formatting shared by `tabs/players.py` and `tabs/watchlist.py`.

`st.column_config.NumberColumn` and `LinkColumn` do not leave a missing cell blank in
this deployment -- confirmed directly (a bare float64 NaN, a Python `None`, and pandas'
nullable `pd.NA` were all tried, in both a `NumberColumn` and a plain auto-inferred
column, and every one rendered the literal text "None"; a raw numpy NaN reaching a
%-style format string renders "nan" instead, since `"%.1f" % float("nan")` succeeds and
just stringifies it). `ProgressColumn` and `TextColumn` do not have this problem, and a
`LinkColumn` given an empty string (not `None`/`pd.NA`) renders a genuinely blank cell
too. So any table column that can be missing is built here as pre-formatted text with an
em dash standing in for "unknown" -- exactly how the "Contract" column
(`contract_until.dt.strftime(...).fillna("—")`) has always correctly shown a missing
date -- and rendered via `TextColumn`, rather than trusted to `NumberColumn`'s own null
handling. The platform's own rule (never render a missing value as a real one, e.g. a
zero) is exactly why this matters: "None"/"nan" is not a zero, but it is just as much a
fabricated-looking value where the honest answer is "we don't know".
"""

from __future__ import annotations

import pandas as pd


def value_or_dash(value, fmt: str) -> str:
    """One scalar rendered as text: `fmt` (a `str.format` spec, e.g. "{:.1f}") applied if
    present, "—" if `pd.isna`. The scalar sibling of `numeric_or_dash`, for callers
    building a row dict (e.g. a small head-to-head comparison table) one value at a time
    rather than transforming a whole Series -- `tabs/compare.py`'s row/table dicts feed a
    bare `st.dataframe(...)` with no `column_config` at all, and even that auto-inferred
    rendering prints "None" for a missing cell rather than leaving it blank (confirmed
    directly), so the same fix applies there too."""
    return "—" if pd.isna(value) else fmt.format(value)


def numeric_or_dash(values: pd.Series, fmt: str) -> pd.Series:
    """A numeric Series rendered as text: `fmt` (a `str.format` spec, e.g. "{:.1f}") is
    applied to every present value; anything `pd.isna` becomes "—". Returns pandas'
    nullable "string" dtype so the result is never accidentally re-inferred as numeric
    (and so a genuinely empty result stays a clean, typed Series)."""
    return values.map(lambda v: value_or_dash(v, fmt)).astype("string")


def link_or_blank(values: pd.Series, url_fmt: str) -> pd.Series:
    """An id-like Series turned into URLs for `LinkColumn`: `url_fmt` (a `str.format`
    spec taking the value, e.g. "https://example.com/{:.0f}") is applied to every
    present value; anything `pd.isna` becomes an empty string -- `LinkColumn` renders
    that as a genuinely blank cell, unlike `None`/`pd.NA` (both render the literal text
    "None"; see this module's docstring)."""
    return values.map(lambda v: "" if pd.isna(v) else url_fmt.format(v)).astype("string")
