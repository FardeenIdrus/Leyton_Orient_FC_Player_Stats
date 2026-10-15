"""The Glossary page shows the COMPLETE content (all four groups) and marks the 40 metrics
that build the rating (2026-10-15: the page still listed only the 45 Impect entries, so the
8 scored physical metrics had no definition on screen)."""

import inspect

from lofc.dashboard import glossary_data as gd
from lofc.dashboard.tabs import glossary
from lofc.model import club_framework as cf
from lofc.model.scorecard import _resolved_performance


def test_page_is_built_from_the_complete_entries():
    src = inspect.getsource(glossary)
    assert "glossary_entries(" in src
    assert "metric_glossary()" not in src


def test_rating_metrics_are_exactly_the_40_the_scoring_uses():
    scored = ({m for p in cf.PERFORMANCE_METRICS for m in _resolved_performance(p)}
              | {m for v in cf.PHYSICAL_METRICS.values() for m in v})
    assert gd.rating_metrics() == scored
    assert len(scored) == 40


def test_search_matches_label_and_text_case_insensitively():
    entries = [{"key": "a", "group": "Physical", "label": "Top speed (PSV-99)",
                "source": "SkillCorner", "text": "Peak speed."},
               {"key": "b", "group": "Physical", "label": "Distance", "source": "SkillCorner",
                "text": "Total distance covered."}]
    assert [e["key"] for e in glossary.search(entries, "PEAK")] == ["a"]
    assert [e["key"] for e in glossary.search(entries, "")] == ["a", "b"]
