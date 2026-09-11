"""The scout's own words must reach the people deciding, not only the exported PDF.

`summary`, `why_sign` and `considerations` are written on the Assess form and stored, and the
player report renders them. Nothing on screen did: neither the sign-off queue nor the player
profile, and the queue's own query did not even SELECT them. So a reviewer approved a band
without being able to read the reasoning behind it, while the chairman's PDF carried it.

These decide WHAT to show; `render_narrative` only draws it.
"""

import pandas as pd

from lofc.dashboard.assessment_detail import narrative_for


class Entry:
    """Stands in for an .itertuples() row."""

    def __init__(self, **kw):
        self.__dict__.update(kw)


def test_every_prose_field_present_is_returned_in_a_fixed_order():
    blocks = narrative_for(Entry(summary="Composed.", why_sign="Wins his duels.",
                                 considerations="Struggles in transition."))
    assert blocks == [("Summary", "Composed."),
                      ("Why sign him", "Wins his duels."),
                      ("Considerations", "Struggles in transition.")]


def test_only_the_fields_actually_written_appear():
    blocks = narrative_for(Entry(summary=None, why_sign="Quick.", considerations=None))
    assert blocks == [("Why sign him", "Quick.")]


def test_an_assessment_with_no_prose_returns_nothing():
    assert narrative_for(Entry(summary=None, why_sign=None, considerations=None)) == []


def test_whitespace_is_not_prose():
    """An empty text area that was tabbed through must not render a blank heading."""
    assert narrative_for(Entry(summary="   ", why_sign="\n", considerations="")) == []


def test_a_missing_value_is_not_rendered_as_the_text_nan():
    """pandas hands back NaN for a NULL column, which str() turns into 'nan'."""
    assert narrative_for(Entry(summary=float("nan"), why_sign=None,
                               considerations=pd.NA)) == []


def test_a_row_without_the_columns_at_all_does_not_crash():
    """A frame loaded before these columns were selected must degrade, not raise."""
    assert narrative_for(Entry(band=3.0)) == []


def test_surrounding_whitespace_is_trimmed_but_internal_line_breaks_survive():
    """Scouts write bullet lists; the line breaks are the structure."""
    blocks = narrative_for(Entry(summary="  one\ntwo  ", why_sign=None, considerations=None))
    assert blocks == [("Summary", "one\ntwo")]
