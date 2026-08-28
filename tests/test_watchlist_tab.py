"""Tests for the Watchlist tab's pure helpers (dashboard/tabs/watchlist.py).

No Streamlit runtime and no database: plain pandas logic, matching the project convention
(tests/test_players_tab.py) of testing data decisions in isolation from the render layer.
"""

import pandas as pd

from lofc.dashboard.tabs.watchlist import (
    _current_form_text, _summarize_injuries, _watchlist_alerts)
from lofc.model import assessment_status


# --- _current_form_text -------------------------------------------------------------

def _live_rows(rows):
    return pd.DataFrame(rows, columns=["player_id", "competition_id", "season_id",
                                       "minutes", "goals_p90", "assists_p90"])


def test_current_form_text_not_featured_when_no_row():
    rows = _live_rows([(2, 4, 319, 180, 0.50, 0.00)])
    assert _current_form_text(rows, player_id=1) == "Not featured yet"


def test_current_form_text_reports_minutes_and_derived_totals():
    # 0.50 goals/90 * 180 min = 1.0 goal; 1.00 assists/90 * 180 min = 2.0 assists.
    rows = _live_rows([(1, 4, 319, 180, 0.50, 1.00)])
    assert _current_form_text(rows, player_id=1) == "180 min · 1g 2a"


# --- _summarize_injuries -------------------------------------------------------------

def _injuries(rows):
    return pd.DataFrame(rows, columns=["player_id", "date_from", "date_until",
                                       "injury_category", "injury_type_raw",
                                       "days_out", "games_missed"])


def test_summarize_injuries_empty_input_returns_well_formed_empty_frame():
    out = _summarize_injuries(_injuries([]), pd.Timestamp("2026-08-24"))
    assert out.empty
    assert list(out.columns) == ["player_id", "injury_status"]


def test_summarize_injuries_ongoing_spell_reads_as_currently_out():
    injuries = _injuries([
        (1, "2026-07-12", None, "Hamstring", "Hamstring strain", 0, 0),
    ])
    out = _summarize_injuries(injuries, pd.Timestamp("2026-08-24"))
    text = out.loc[out["player_id"] == 1, "injury_status"].iloc[0]
    assert "Currently out" in text
    assert "Hamstring" in text
    assert "12 Jul 2026" in text


def test_summarize_injuries_ongoing_when_date_until_still_in_future():
    injuries = _injuries([
        (1, "2026-07-12", "2026-09-01", "Hamstring", "Hamstring strain", 0, 0),
    ])
    out = _summarize_injuries(injuries, pd.Timestamp("2026-08-24"))
    assert "Currently out" in out.loc[out["player_id"] == 1, "injury_status"].iloc[0]


def test_summarize_injuries_past_spell_reads_as_returned():
    injuries = _injuries([
        (1, "2025-01-01", "2025-02-03", "Ankle", "Ankle sprain", 20, 5),
    ])
    out = _summarize_injuries(injuries, pd.Timestamp("2026-08-24"))
    text = out.loc[out["player_id"] == 1, "injury_status"].iloc[0]
    assert text == "Last injury: Ankle (returned 03 Feb 2025)"


def test_summarize_injuries_takes_the_most_recent_spell_only():
    injuries = _injuries([
        (1, "2024-01-01", "2024-01-20", "Ankle", "Ankle sprain", 10, 2),
        (1, "2026-06-01", "2026-06-15", "Groin", "Groin strain", 10, 2),
    ])
    out = _summarize_injuries(injuries, pd.Timestamp("2026-08-24"))
    text = out.loc[out["player_id"] == 1, "injury_status"].iloc[0]
    assert "Groin" in text
    assert "Ankle" not in text


def test_summarize_injuries_concurrent_diagnoses_pick_one_not_duplicate_rows():
    """Two rows logged for the same absence (matching model/medical.py's documented
    Transfermarkt behaviour) must still yield exactly one summary row per player."""
    injuries = _injuries([
        (1, "2026-01-01", "2026-02-01", "Ankle injury", "Ankle injury", 10, 2),
        (1, "2026-01-01", "2026-02-01", "Broken leg", "Broken leg", 10, 2),
    ])
    out = _summarize_injuries(injuries, pd.Timestamp("2026-08-24"))
    assert len(out) == 1


# --- _watchlist_alerts -------------------------------------------------------------

def test_watchlist_alerts_counts_expiring_soon_within_six_months():
    months_left = pd.Series([2.0, 6.0, 7.0, None, -1.0])
    injury = pd.Series(["No injury spells on record"] * 5)
    status = pd.Series([assessment_status.NOT_ASSESSED] * 5)
    alerts = _watchlist_alerts(months_left, injury, status)
    assert alerts["total"] == 5
    assert alerts["expiring_soon"] == 2   # 2.0 and 6.0 only; 7.0 too far, -1 already expired


def test_watchlist_alerts_counts_currently_injured_by_prefix():
    months_left = pd.Series([10.0, 10.0])
    injury = pd.Series(["🔴 Currently out — Hamstring (since 12 Jul 2026)",
                        "Last injury: Ankle (returned 03 Feb 2025)"])
    status = pd.Series([assessment_status.SIGNED_OFF, assessment_status.SIGNED_OFF])
    alerts = _watchlist_alerts(months_left, injury, status)
    assert alerts["currently_injured"] == 1


def test_watchlist_alerts_counts_not_assessed_only():
    months_left = pd.Series([10.0, 10.0, 10.0])
    injury = pd.Series(["No injury spells on record"] * 3)
    status = pd.Series([assessment_status.NOT_ASSESSED, assessment_status.AWAITING,
                        assessment_status.SIGNED_OFF])
    alerts = _watchlist_alerts(months_left, injury, status)
    assert alerts["not_assessed"] == 1
