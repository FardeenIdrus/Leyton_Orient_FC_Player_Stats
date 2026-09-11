"""Result columns must be labelled by what they ARE, not by list position.

`_frame` built its DataFrame as `pd.DataFrame(rows, columns=columns)` -- a positional map
from a hand-maintained list. Adding the three prose columns to `pending_signoff`'s SELECT
but appending their names to the END of that list silently shifted every label after
`created_at`: `summary` received the author's NAME, `author_name` received the (NULL)
summary. Nothing raised. The sign-off queue showed "None" as the assessor and rendered the
author's name and role as if they were the scout's written notes.

A mislabelled column is worse than a missing one: it is wrong data wearing the right name.
"""

import pandas as pd
from sqlalchemy import Column, Integer, MetaData, String, Table, create_engine, insert, select

from lofc.store.assessments import _frame

_META = MetaData()
_T = Table("thing", _META,
           Column("id", Integer, primary_key=True),
           Column("alpha", String),
           Column("omega", String))


def _engine():
    engine = create_engine("sqlite://")
    _META.create_all(engine)
    with engine.begin() as conn:
        conn.execute(insert(_T), [{"id": 1, "alpha": "A-value", "omega": "O-value"}])
    return engine


def test_columns_are_labelled_from_the_query_not_from_call_order():
    """The regression: a SELECT whose order differs from the caller's list must still
    label every value correctly."""
    engine = _engine()
    query = select(_T.c.id, _T.c.omega, _T.c.alpha)      # note: omega BEFORE alpha
    with engine.connect() as conn:
        frame = _frame(conn, query, ["id", "alpha", "omega"])   # list in the WRONG order
    assert frame.loc[0, "alpha"] == "A-value"
    assert frame.loc[0, "omega"] == "O-value"


def test_labelled_expressions_keep_their_label():
    engine = _engine()
    query = select(_T.c.id, _T.c.alpha.label("renamed"))
    with engine.connect() as conn:
        frame = _frame(conn, query, ["id", "renamed"])
    assert frame.loc[0, "renamed"] == "A-value"


def test_an_empty_result_still_has_its_columns():
    """A caller selecting from an empty frame must not hit a KeyError."""
    engine = _engine()
    query = select(_T.c.id, _T.c.alpha).where(_T.c.id == 999)
    with engine.connect() as conn:
        frame = _frame(conn, query, ["id", "alpha"])
    assert frame.empty
    assert list(frame.columns) == ["id", "alpha"]


def test_the_signoff_queue_selects_and_labels_the_prose_columns():
    """The specific query the bug lived in: every declared name must line up with the
    SELECT, so this asserts the two agree rather than trusting them to."""
    from lofc.store import assessments as store
    import inspect
    source = inspect.getsource(store.pending_signoff)
    order_in_list = [n for n in ("created_at", "summary", "why_sign", "considerations",
                                 "author_name", "author_role")
                     if f'"{n}"' in source]
    assert order_in_list == ["created_at", "summary", "why_sign", "considerations",
                             "author_name", "author_role"], (
        "pending_signoff's `columns` list no longer matches its SELECT order")
