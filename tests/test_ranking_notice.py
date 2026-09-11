"""The ranked list must always say why it is short, or why it is empty.

Selecting 2026/27 on 2026-09-11 produced a completely blank table with no message: `ranking`
was non-empty (378 scorecards existed) so the "season under way" notice never fired, while
the candidate pool WAS empty, so there was nothing on screen and nothing explaining it. A
recruiter cannot tell that from a broken page.

Pure, so the decision about WHAT to say is testable without a Streamlit runtime -- the same
convention `_veto_reasons` and `_current_form_summary` already follow.
"""

from lofc.dashboard.seasons import ranking_notice


def test_a_healthy_list_says_nothing():
    assert ranking_notice(n_ranked=105, n_withheld=0, season="2025/26",
                          complete_season="2025/26", position="Centre Forward") is None


def test_a_short_list_names_how_many_were_withheld_and_why():
    level, text = ranking_notice(n_ranked=13, n_withheld=11, season="2026/27",
                                 complete_season="2025/26", position="Centre Forward")
    assert level == "warning"
    assert "11" in text
    assert "Squads & loans" in text


def test_an_empty_list_explains_itself_rather_than_rendering_blank():
    level, text = ranking_notice(n_ranked=0, n_withheld=24, season="2026/27",
                                 complete_season="2025/26", position="Centre Forward")
    assert level == "info"
    assert "2026/27" in text
    assert "Squads & loans" in text
    assert "2025/26" in text


def test_an_empty_list_with_nothing_withheld_still_explains_itself():
    """Nobody past 450 minutes yet — a different cause, but a blank table either way."""
    level, text = ranking_notice(n_ranked=0, n_withheld=0, season="2026/27",
                                 complete_season="2025/26", position="Winger")
    assert level == "info"
    assert "Squads & loans" in text


def test_the_complete_season_is_not_offered_as_an_alternative_to_itself():
    """Viewing the complete season and finding it empty must not say 'try 2025/26'."""
    level, text = ranking_notice(n_ranked=0, n_withheld=0, season="2025/26",
                                 complete_season="2025/26", position="Winger")
    assert level == "info"
    assert "is complete and fully ranked" not in text
