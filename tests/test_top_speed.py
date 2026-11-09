"""'Top speed' is the average of a player's 5 fastest matches (Head of Recruitment, 2026-10-16).

SkillCorner's season `psv99` is the AVERAGE of every match's PSV-99, not a top speed. Verified
2026-10-16 against Fred Onyedinma's 43 per-match rows (League One 25/26): mean of all matches
30.84 = season psv99; mean of his 5 fastest = 33.34 = season psv99_top5; single fastest 34.60.
We labelled 30.84 "Top speed", so a player SkillCorner shows at 33 read 29 with us.

Display only: the Physical rating still scores both figures (a formula decision).
"""

import inspect

from lofc.dashboard import glossary_data as gd
from lofc.dashboard import metric_filters as mf
from lofc.dashboard.tabs import players


def test_glossary_names_say_what_each_figure_is():
    assert gd.PHYSICAL["top5_psv99_kmh"][0] == "Top speed"
    assert "5 fastest matches" in gd.PHYSICAL["top5_psv99_kmh"][1]
    assert gd.PHYSICAL["psv99_kmh"][0] == "Average match top speed"


def test_players_table_top_speed_is_the_top5_figure():
    src = inspect.getsource(players._players)
    assert 'view["Top speed"] = numeric_or_dash(view["top5_psv99_kmh"]' in src


def test_no_slider_uses_the_all_match_average():
    for position, metrics in mf.PHYSICAL_SLIDERS.items():
        assert "psv99_kmh" not in metrics, position
    for position in ("Centre Back", "Full Back", "Winger", "Centre Forward"):
        assert "top5_psv99_kmh" in mf.PHYSICAL_SLIDERS[position]
    assert mf.PHYSICAL_LABELS["top5_psv99_kmh"][0] == "Top speed (km/h)"


def test_speed_definitions_name_the_unit_once():
    """Owner 2026-11-09: two definitions ended 'km/h. km/h.' / '. km/h.' (stray unit)."""
    top5 = gd.PHYSICAL["top5_psv99_kmh"][1]
    avg = gd.PHYSICAL["psv99_kmh"][1]
    assert top5.endswith("his movement above 15 km/h."), top5
    assert top5.count("km/h") == 1, top5
    assert avg == ("Average of his top speed across all his matches "
                   "(SkillCorner PSV-99), in km/h."), avg
