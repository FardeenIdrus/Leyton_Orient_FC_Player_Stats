"""Task 2.31 d/e + related: stale page text, flash messages, and the Assess page's list of
existing assessments."""

import inspect

import pandas as pd

from lofc.dashboard import glossary_data as gd
from lofc.dashboard.tabs import assess, glossary, physical, scout_reports, users


# --- Physical page text (2.31d) ----------------------------------------------------------

def test_physical_season_label_is_short():
    assert physical.short_season("2025/2026") == "2025/26"
    assert physical.short_season("2025/26") == "2025/26"


def test_physical_intro_names_the_club_export():
    text = physical.intro_text("2025/2026")
    assert "League One 2025/26 (club export)" in text
    assert "2025/2026" not in text


def test_physical_rank_column_uses_the_real_club_count():
    assert physical.rank_column(20) == "Rank of 20"
    assert "Rank of 24" not in inspect.getsource(physical)


def test_physical_page_has_no_stale_claims():
    src = inspect.getsource(physical._physical)
    assert "Fit score" not in src
    assert "never scores recruitment targets" not in src


# --- Glossary count (2.31e) --------------------------------------------------------------

def test_glossary_caption_count_comes_from_the_scoring_definitions():
    n = len(gd.rating_metrics())
    assert n > 0
    assert f"the {n} metrics that build the rating" in glossary.intro_caption()
    # Secondary guard: the number must not be typed back into the page source.
    assert "39" not in inspect.getsource(glossary)


# --- Scout reports help text -------------------------------------------------------------

def test_scout_reports_no_longer_says_model_view():
    # The help text is an inline literal inside the Streamlit render function, so it cannot
    # be called without a running page; the source check is the only feasible form. It also
    # pins the replacement wording so the pointer cannot simply be deleted.
    # The text now lives in lofc.core.scout_reports_page.column_help (the page calls it).
    from lofc.core import scout_reports_page
    src = inspect.getsource(scout_reports) + inspect.getsource(scout_reports_page)
    assert "Model view" not in src
    assert "Data vs scout says why there is none" in scout_reports_page.column_help(
        "2025/26", "2026/27")["Rating"]


# --- Users flash messages ----------------------------------------------------------------

def test_flash_survives_until_shown_once():
    state = {}
    assert users.pop_flash(state) is None
    users.queue_flash(state, "Lockout cleared.")
    assert users.pop_flash(state) == "Lockout cleared."
    assert users.pop_flash(state) is None


def test_every_success_before_a_rerun_is_queued():
    # The five messages are written inline inside `st.dialog` / `st.form` bodies, which need
    # a live Streamlit run, so they cannot be driven with a stub session dict; the helper
    # behaviour is covered above and this source check guards the call sites.
    # Create, reset password, clear lockout, deactivate, reactivate.
    src = inspect.getsource(users)
    assert src.count("queue_flash(st.session_state") == 5
    assert "st.success(" not in src.replace("st.success(msg)", "")


# --- Assess: existing assessments --------------------------------------------------------

def _frame():
    return pd.DataFrame({
        "author_name": ["Scout One"], "author_role": ["scout"],
        "dimension": ["Psychological"], "band": [4.0], "status": ["submitted"],
        "created_at": pd.to_datetime(["2026-08-01"]),
        "approver_name": [None], "approved_at": pd.to_datetime([None])})


def test_existing_assessments_columns_and_values():
    table = assess.existing_assessments_table(_frame())
    assert list(table.columns) == ["Entered by", "Role", "Dimension", "Band", "Status", "Date"]
    assert table.loc[0, "Dimension"] == "Psychological"
    assert table.loc[0, "Band"] == "4.00"


def test_existing_assessments_empty_is_empty():
    assert assess.existing_assessments_table(pd.DataFrame()).empty
