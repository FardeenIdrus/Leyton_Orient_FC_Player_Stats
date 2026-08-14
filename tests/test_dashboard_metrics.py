"""Tests for the dashboard's metric vocabulary (dashboard/labels.py): the searchable glossary
and the honest StatsBomb-lineage labels. No database, so these run offline like the rest of
the suite."""

import pandas as pd
import pytest

from lofc.dashboard import labels
from lofc.model.score import IMPECT_SUCCESSOR


@pytest.fixture(autouse=True)
def _clear_caches():
    """Streamlit @cache_data persists within the process; clear so monkeypatched inputs
    and settings actually take effect per test."""
    for fn in (labels.metric_glossary,):
        clear = getattr(fn, "clear", None)
        if clear:
            clear()
    yield


def test_glossary_labels_successors_honestly():
    """Every live Impect successor is named for what it truly is AND carries the StatsBomb
    stat it stands in for — never dressed up as that StatsBomb stat."""
    g = labels.metric_glossary()
    # ground_duels_won stands in for Tackles, is labelled 'Ground duels won', sourced Impect.
    entry = g["ground_duels_won_p90"]
    assert entry["label"] == "Ground duels won"
    assert entry["source"] == "Impect"
    assert "Tackles" in entry["stands_in_for"]
    assert entry["lineage"]  # non-empty explanation
    # Every successor target that we display has a lineage note.
    for successor in set(IMPECT_SUCCESSOR.values()):
        if successor in g:
            assert g[successor]["stands_in_for"], f"{successor} missing StatsBomb lineage"


def test_glossary_native_metric_has_no_false_lineage():
    """An Impect-native metric (no StatsBomb twin) is shown plainly, with no invented lineage."""
    g = labels.metric_glossary()
    assert g["counterpressures_p90"]["stands_in_for"] == ""
    assert g["counterpressures_p90"]["lineage"] == ""


def test_metric_label_falls_back_readably():
    assert labels.metric_label("np_xg_p90") == "Non-pen xG"          # known
    assert labels.metric_label("ball_wins_p90") == "Ball wins"       # added successor label
    assert labels.metric_label("some_new_metric_p90") == "Some New Metric"  # humanised fallback


