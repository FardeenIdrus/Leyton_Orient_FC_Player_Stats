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




# --- advisory flags follow the affordability-modelling switch --------------------------
# Financial Fit and Resale Potential are MODELLED, and the sidebar can hide them. Citing
# them in an advisory while they are hidden is unexplainable from what the user can see:
# of 965 flagged players in 25/26, 390 (40%) trip ONLY on those two.

def _veto_row(**bands):
    import pandas as pd
    base = {"performance_band": 3.5, "physical_band": 3.5, "financial_band": 3.5,
            "resale_band": 3.5, "psychological_band": None, "medical_band": None}
    base.update(bands)
    return pd.Series(base)


def test_a_real_dimension_is_always_named():
    from lofc.dashboard.tabs.players import _veto_reasons
    row = _veto_row(performance_band=1.6)
    assert any("Performance" in r for r in _veto_reasons(row, include_modelled=False))


def test_modelled_dimensions_are_dropped_when_affordability_is_off():
    from lofc.dashboard.tabs.players import _veto_reasons
    row = _veto_row(financial_band=1.5, resale_band=1.4)
    assert _veto_reasons(row, include_modelled=True) != []
    assert _veto_reasons(row, include_modelled=False) == []


def test_modelled_dimensions_are_named_when_affordability_is_on():
    from lofc.dashboard.tabs.players import _veto_reasons
    row = _veto_row(financial_band=1.5)
    reasons = _veto_reasons(row, include_modelled=True)
    assert any("Financial" in r for r in reasons)


def test_a_real_dimension_still_shows_with_modelled_ones_hidden():
    """Hiding money must not hide a genuine Performance or Physical shortfall."""
    from lofc.dashboard.tabs.players import _veto_reasons
    row = _veto_row(physical_band=1.2, financial_band=1.5)
    reasons = _veto_reasons(row, include_modelled=False)
    assert len(reasons) == 1 and "Physical" in reasons[0]
