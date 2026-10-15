"""The glossary shows Impect's definitions as readable text, and the Methodology page is
hidden (owner, 2026-10-09: too much noise; restore with one flag).

Impect's definitions arrive with HTML (`<br/>`, `<b>`); the glossary printed them literally,
e.g. the Assists entry. StatsBomb is retired, so its lineage is no longer shown."""

import inspect

from lofc.dashboard import labels
from lofc.dashboard.labels import clean_definition, metric_glossary


def test_line_breaks_and_bold_become_markdown():
    raw = "There are four types:<br/><br/>1) <b>Direct Assist:</b> A pass."
    assert clean_definition(raw) == "There are four types:\n\n1) **Direct Assist:** A pass."


def test_other_tags_are_stripped_and_entities_decoded():
    assert clean_definition("A <i>shot</i> &amp; a <span>pass</span>") == "A shot & a pass"


def test_no_glossary_entry_contains_html():
    import re
    for g in metric_glossary().values():
        assert not re.search(r"<[a-zA-Z/][^>]*>", g["text"]), g["label"]


def test_statsbomb_lineage_is_not_shown():
    from lofc.dashboard.tabs import glossary
    assert "Substitute for" not in inspect.getsource(glossary)


def test_methodology_page_is_hidden_behind_a_flag():
    from lofc.dashboard import app
    assert app.SHOW_METHODOLOGY is False
