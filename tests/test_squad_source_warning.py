"""A missing squad scrape must announce itself, never degrade quietly.

`Squads & loans` is built on the Transfermarkt squad scrape
(`data/reference/transfermarkt/efl_values.csv`), which is gitignored licensed data and so is
absent from a freshly cloned server until the pipeline runs or the file is copied across.
When it is absent `registered_squad_frame` falls back to `player_metrics_neutral` -- players
who have APPEARED -- which drops every registered member who has not yet played: new
signings, the injured, the unselected. Measured on 2026-09-11: 3,783 squad rows become 2,966,
and Leyton Orient's 33 become 21.

That is precisely the defect fixed on 2026-09-07, and the reason it survived as long as it
did is that it looks completely normal on screen. A degraded page is acceptable; a degraded
page that claims to be complete is not.
"""

from lofc.dashboard.tabs.squads import squad_source_warning


def test_a_present_scrape_says_nothing():
    assert squad_source_warning(scrape_rows=3783, shown_rows=3783) is None


def test_a_missing_scrape_warns_and_names_what_is_missing():
    text = squad_source_warning(scrape_rows=0, shown_rows=2966)
    assert text is not None
    assert "incomplete" in text.lower()
    assert "2,966" in text          # says how many it IS showing
    assert "efl_values.csv" in text  # says exactly what is absent


def test_the_warning_explains_WHO_is_missing_not_just_that_data_is():
    """'Data missing' tells a recruiter nothing. Which players is the whole point."""
    text = squad_source_warning(scrape_rows=0, shown_rows=2966)
    lowered = text.lower()
    assert "signing" in lowered or "not yet played" in lowered


def test_an_empty_page_still_warns_when_the_scrape_is_absent():
    """Nothing to show AND no scrape: the cause is still the missing file."""
    assert squad_source_warning(scrape_rows=0, shown_rows=0) is not None
