"""The dimension tiles must name the season they belong to.

The profile renders "Current form - 2026/27" (this season's minutes, goals, assists) and then,
directly beneath it, the Composite tile -- which is the SELECTED season, normally 2025/26. A
reader attaches a number to the heading above it, so 3.33 read as a 2026/27 figure. The
caption there made it worse: it said "not a rating" and a rating appeared immediately below.

Fixed in the LABEL rather than with another caption. A caption explaining an adjacency means
the adjacency is the defect; a label cannot drift out of sync with the data, which is exactly
how two hard-coded captions on this page went stale.
"""

from lofc.dashboard.tabs.players import composite_tile_label


def test_the_label_names_the_season():
    assert composite_tile_label(318, "All Metrics") == "Composite · 2025/26"


def test_the_live_season_is_named_too():
    assert composite_tile_label(319, "All Metrics") == "Composite · 2026/27"


def test_an_archetype_lens_is_named_alongside_the_season():
    """Both qualifiers matter: which metrics, and which season."""
    label = composite_tile_label(318, "Attacking")
    assert "2025/26" in label and "Attacking" in label


def test_the_season_is_always_present_whatever_the_archetype():
    for archetype in ("All Metrics", "Attacking", "Progressive Build & Recovery"):
        assert "2025/26" in composite_tile_label(318, archetype)


def test_an_unknown_season_still_labels_something_rather_than_lying():
    """A season with no label must not silently drop the qualifier and read as current."""
    assert "999" in composite_tile_label(999, "All Metrics")
