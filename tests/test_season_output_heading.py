"""The season-output tiles must name their season, like every other block on the profile.

The profile renders two sets of Goals / Assists / Minutes tiles, stacked. The lower set is
headed "Current form - 2026/27". The upper set -- the SELECTED season's totals -- had no
heading at all, so two identically-labelled groups sat adjacent with only one saying which
season it belonged to. Alfie May showed "Goals 7, Assists 7, Minutes 2,371" above
"Minutes 475, Goals 1, Assists 0" with nothing distinguishing them but position on the page.

Same defect, and same fix, as the Composite tile: put the season in the label rather than
adding another caption to explain the adjacency.
"""

from lofc.dashboard.tabs.players import season_output_heading


def test_it_names_the_selected_season():
    assert season_output_heading(318) == "**Season output — 2025/26**"


def test_the_live_season_is_named_too():
    assert season_output_heading(319) == "**Season output — 2026/27**"


def test_it_matches_the_current_form_heading_format():
    """Both blocks must read the same way, or the pair still looks inconsistent:
    "Current form - 2026/27" against "Season output - 2025/26"."""
    assert season_output_heading(318).startswith("**") and "—" in season_output_heading(318)


def test_an_unknown_season_still_labels_something():
    assert "999" in season_output_heading(999)
