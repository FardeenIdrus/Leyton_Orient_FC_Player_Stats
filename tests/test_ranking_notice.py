"""The ranked list must always say why it is short, or why it is empty.

Selecting 2026/27 on 2026-09-11 produced a completely blank table with no message: `ranking`
was non-empty (378 scorecards existed) so the "season under way" notice never fired, while
the candidate pool WAS empty, so there was nothing on screen and nothing explaining it. A
recruiter cannot tell that from a broken page.

Pure, so the decision about WHAT to say is testable without a Streamlit runtime -- the same
convention `_veto_reasons` and `_current_form_summary` already follow.
"""

from lofc.dashboard.seasons import ranking_notice

CF = "Centre Forward"


def _w(*rows):
    """Withheld players as (name, club, league) tuples -> the frame app.py passes."""
    import pandas as pd
    return pd.DataFrame(list(rows), columns=["player_name", "team_name", "league"])


def _notice(n_ranked=13, withheld=None, season="2026/27", complete="2025/26", position=CF):
    return ranking_notice(n_ranked=n_ranked, withheld=withheld if withheld is not None else _w(),
                          season=season, complete_season=complete, position=position)


def test_a_healthy_list_says_nothing():
    assert _notice(n_ranked=105, season="2025/26") is None


def test_one_withheld_player_is_singular_and_named():
    level, text = _notice(withheld=_w(("J. Smith", "Shelbourne", "Irish Premier Division")))
    assert level == "caption"          # one quiet line, not a yellow warning
    assert text == ("1 Centre Forward not ranked (fewer than 10 rated in the league): "
                    "J. Smith (Shelbourne, Irish Premier Division).")


def test_several_players_are_named_with_club_and_league():
    level, text = _notice(withheld=_w(("A. Sato", "Iwaki", "J2 League"),
                                      ("J. Smith", "Shelbourne", "Irish Premier Division"),
                                      ("B. Ito", "Tokyo", "J2 League")))
    assert level == "caption"
    assert text == ("3 Centre Forwards not ranked (fewer than 10 rated in their league): "
                    "A. Sato (Iwaki, J2 League) · B. Ito (Tokyo, J2 League) · "
                    "J. Smith (Shelbourne, Irish Premier Division).")


def test_more_than_six_are_truncated_with_a_count():
    rows = [(f"P{i}", "Club", "J2 League") for i in range(9)]
    _, text = _notice(withheld=_w(*rows), position="Full Back")
    assert text.startswith("9 Full Backs not ranked (fewer than 10 rated in their league): ")
    assert text.count(" · ") == 6 and text.endswith(" · +3 more")
    assert "P5 (" in text and "P6 (" not in text


def test_missing_club_or_league_does_not_break_the_line():
    _, text = _notice(withheld=_w(("J. Smith", None, None)))
    assert text.endswith("J. Smith (Unknown club, Unknown league).")


def test_an_empty_list_explains_itself_in_one_line():
    level, text = _notice(n_ranked=0, withheld=_w(*[(f"P{i}", "C", "J2 League") for i in range(24)]))
    assert level == "info"
    # 24 were withheld for thin pools: they HAVE 450+ minutes, so the reason is peers.
    assert text == ("No Centre Forwards ranked in 2026/27 yet — 24 Centre Forwards rated, but "
                    "fewer than 10 per league: J2 League (24). 2025/26 is fully ranked.")


def test_an_empty_list_with_nothing_withheld_still_explains_itself():
    level, text = _notice(n_ranked=0, position="Winger")
    assert level == "info" and text.startswith("No Wingers ranked in 2026/27")


def test_the_complete_season_is_not_offered_as_an_alternative_to_itself():
    """Viewing the complete season and finding it empty must not say '2025/26 is fully ranked'."""
    level, text = _notice(n_ranked=0, season="2025/26", position="Winger")
    assert level == "info"
    assert text == "No Wingers ranked in 2025/26 yet — too few have 450+ minutes."


def test_an_empty_list_caused_by_thin_pools_says_so_not_minutes():
    """Smoke test, 2026-11-02: 2026/27 Central Mid showed "too few have 450+ minutes" while 7
    players HAD 450+ minutes -- they were withheld because each league had fewer than 10.
    The two causes must read differently."""
    from lofc.dashboard.seasons import ranking_notice
    level, text = ranking_notice(0, _w(*([("a", "c", "League One")] * 3 + [("b", "c", "League Two")] * 4)),
                                 "2026/27", "2025/26", "Central Mid")
    assert level == "info"
    assert "450" not in text
    assert "7 Central Mids rated" in text and "fewer than 10" in text
    assert "League One (3) · League Two (4)" in text and "2025/26 is fully ranked" in text
    level, text = ranking_notice(0, _w(), "2026/27", "2025/26", "Central Mid")
    assert "too few have 450+ minutes" in text
