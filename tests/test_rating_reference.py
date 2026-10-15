"""Reference page "What goes into each rating": built FROM the scoring code, so it can never
disagree with the ratings it describes. Recruiters asked repeatedly which metrics make each
rating and each archetype; the answers lived only in code (2026-10-11).
"""

import pytest

from lofc.dashboard import rating_reference as rr
from lofc.model import club_framework as cf
from lofc.model.scorecard import _resolved_performance
from lofc.dashboard.labels import metric_label

POSITIONS = list(cf.PERFORMANCE_METRICS)


@pytest.mark.parametrize("position", POSITIONS)
def test_rows_are_exactly_what_the_scoring_uses(position):
    table = rr.rating_ingredients(position)
    perf = table[table["Counts towards"] == "Performance"]["key"].tolist()
    phys = table[table["Counts towards"] == "Physical"]["key"].tolist()
    assert perf == _resolved_performance(position)
    assert phys == cf.PHYSICAL_METRICS[position]


@pytest.mark.parametrize("position", ["Full Back", "Winger"])
def test_archetype_ticks_match_the_archetype_lists(position):
    table = rr.rating_ingredients(position).set_index("key")
    for arch in cf.archetypes_for(position)[1:]:
        used = set(_resolved_performance(position, arch))
        for key, row in table.iterrows():
            expected = key in used or row["Counts towards"] == "Physical"
            assert (row[arch] == "✓") == expected, (arch, key)


def test_positions_without_archetypes_have_no_archetype_columns():
    assert list(rr.rating_ingredients("Centre Back").columns) == [
        "key", "Metric", "Counts towards", "How it's measured"]


@pytest.mark.parametrize("position", POSITIONS)
def test_every_row_has_a_short_definition(position):
    for d in rr.rating_ingredients(position)["How it's measured"]:
        assert d and len(d) <= 240


def test_weights_line_comes_from_the_framework():
    assert rr.weights_line("Centre Back") == "Rating = Performance 57% · Physical 43%"
    assert rr.weights_line("Goalkeeper") == "Rating = Performance 100%"


def test_metric_names_match_the_rest_of_the_platform():
    table = rr.rating_ingredients("Centre Back")
    perf = table[table["Counts towards"] == "Performance"]
    assert perf["Metric"].tolist() == [metric_label(k) for k in perf["key"]]


def test_table_renders_as_wrapping_html_with_every_row():
    """st.dataframe cut long text off even on a full-width monitor (owner, 2026-10-12).
    The page renders a plain HTML table whose cells wrap."""
    table = rr.rating_ingredients("Full Back")
    html = rr.ingredients_html(table)
    assert html.count("<tr") == len(table) + 1            # header + one row per metric
    assert "white-space: normal" in html
    assert "key" not in [h.strip("<>/th ") for h in html.split("<th")[1:2]]
    for text in table["How it's measured"]:
        assert __import__("html").escape(text) in html    # nothing truncated


def test_html_escapes_text():
    import pandas as pd
    t = pd.DataFrame({"key": ["a"], "Metric": ["<b>x</b>"], "Counts towards": ["Performance"],
                      "How it's measured": ["a & b"]})
    out = rr.ingredients_html(t)
    assert "<b>x</b>" not in out and "&lt;b&gt;" in out and "a &amp; b" in out
