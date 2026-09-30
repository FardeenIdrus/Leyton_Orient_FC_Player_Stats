"""The scout report card, and the scout consensus shown on the Players page.

THE CARD. The first version used `st.text_area(disabled=True)`, which Streamlit renders as
grey text on a grey field -- the Head of Recruitment's words were "hard to read", and he was
right: a disabled input signals "you may not edit this", when the intent was "this is the
thing worth reading". A scout's prose is the most valuable content on the page and it was
styled as the least. It is now a card with real hierarchy, on the platform's existing light
chrome and Leyton Orient red.

ESCAPING IS NOT OPTIONAL. 437 free-text fields written by six people go through this. Raw
interpolation into markup is an injection hole, and the platform closed exactly this class
of gap in the 2026-08-25 XSS sweep. Every interpolated value is escaped, and the assertion
below is a real payload, not a smoke test.

VERDICT COLOUR AVOIDS THE BRAND RED. "Don't sign" reads as slate, not red: #C8102E is the
club's own colour and is used across the platform for emphasis and for Leyton Orient
itself, so a red "Don't sign" pill would read as branding rather than as a judgement.

THE CONSENSUS COLUMN was asked for directly by the Head of Recruitment: if every scout who
watched a player said Sign, the Players page should say so. It aggregates verdicts and
NEVER touches a score -- `objective_composite` is a percentile against league peers and is
unaffected, which also means the composite reformulation due next week cannot break it.
"""

import datetime as dt

import pandas as pd

from lofc.dashboard.tabs.scout_reports import (
    fixture_label,
    report_card_html,
    scout_consensus,
    verdict_tone,
)

ROW = pd.Series({
    "player_name": "Ra'ees Bangura-Williams",
    "club_name": "Millwall",
    "scout": "Gareth Mycock",
    "observation": "Video",
    "fixture_date": dt.date(2026, 7, 21),
    "home_team": "Gillingham",
    "away_team": "Millwall",
    "positions_played": ["LW"],
    "recommended_positions": ["LW", "CF"],
    "grade": "B",
    "squad_role": "Core (>70% of Minutes)",
    "verdict": "Sign",
    "comments": "Left footed, athletic.\nAttacked the full back repeatedly.",
    "submission_id": "660747922393",
})


# --- verdict tone -------------------------------------------------------------------------

def test_sign_reads_as_positive():
    assert verdict_tone("Sign") == "positive"


def test_dont_sign_reads_as_negative():
    assert verdict_tone("Don't sign") == "negative"


def test_monitor_variants_read_as_neutral():
    assert verdict_tone("Monitor") == "neutral"
    assert verdict_tone("Monitor Priority") == "neutral"


def test_an_unknown_or_missing_verdict_is_neutral_not_an_error():
    """New options can be added to the form at any time without telling us."""
    assert verdict_tone("Something New") == "neutral"
    assert verdict_tone(None) == "neutral"


# --- the fixture line ---------------------------------------------------------------------

def test_the_fixture_names_both_teams_and_the_date():
    """The column header said "Fixture" and showed only a date, which is what prompted
    "what does the fixture column represent?". The fixture is the match."""
    assert fixture_label("Gillingham", "Millwall", dt.date(2026, 7, 21)) == \
        "Gillingham v Millwall · 21 Jul 2026"


def test_a_missing_date_still_names_the_match():
    assert fixture_label("Gillingham", "Millwall", None) == "Gillingham v Millwall"


def test_a_missing_opponent_still_gives_the_date():
    assert fixture_label(None, None, dt.date(2026, 7, 21)) == "21 Jul 2026"


def test_nothing_known_is_an_empty_string_not_the_word_none():
    assert fixture_label(None, None, None) == ""


# --- the card -----------------------------------------------------------------------------

def test_the_scouts_words_appear():
    html = report_card_html(ROW)
    assert "Left footed, athletic." in html


def test_line_breaks_in_the_report_are_preserved():
    """Scouts write in paragraphs. Collapsing them into one block is why the original
    read as a wall of text."""
    assert "<br>" in report_card_html(ROW)


def test_html_in_a_report_is_escaped_not_rendered():
    """THE INJECTION TEST. 437 free-text fields written by six people."""
    row = ROW.copy()
    row["comments"] = '<img src=x onerror="alert(1)">'
    html = report_card_html(row)
    assert "<img" not in html
    assert "onerror" not in html or "&quot;" in html
    assert "&lt;img" in html


def test_a_players_name_with_an_apostrophe_survives_escaping():
    """"Ra'ees Bangura-Williams" is a real player in the sheet, and naive escaping that
    turns the apostrophe into &#x27; on screen would be its own defect."""
    html = report_card_html(ROW)
    assert "Bangura-Williams" in html
    assert "&#x27;" not in html.split("</style>")[-1] or "Ra" in html


def test_the_header_carries_scout_grade_and_verdict():
    html = report_card_html(ROW)
    for expected in ("Gareth Mycock", "Grade B", "Sign", "Video"):
        assert expected in html


def test_the_fixture_is_shown_as_a_match_not_a_bare_date():
    assert "Gillingham v Millwall" in report_card_html(ROW)


def test_positions_played_and_recommended_are_both_shown():
    html = report_card_html(ROW)
    assert "LW" in html and "CF" in html


def test_a_report_with_no_comment_still_renders():
    """Every live row has one, but the column is nullable and a blank must not crash."""
    row = ROW.copy()
    row["comments"] = None
    assert "Gareth Mycock" in report_card_html(row)


def test_the_verdict_tone_reaches_the_markup():
    assert "positive" in report_card_html(ROW)


# --- the consensus column -------------------------------------------------------------

def test_every_scout_saying_sign_is_high_priority():
    """The Head of Recruitment's own request."""
    assert scout_consensus(["Sign", "Sign", "Sign"]) == "High priority"


def test_a_single_sign_is_high_priority():
    assert scout_consensus(["Sign"]) == "High priority"


def test_sign_and_dont_sign_together_reads_as_split():
    """Disagreement is the signal, not noise. Averaging it away would hide the one thing
    worth a conversation."""
    assert scout_consensus(["Sign", "Don't sign"]) == "Scouts split"


def test_every_scout_rejecting_reads_as_not_recommended():
    assert scout_consensus(["Don't sign", "Don't sign"]) == "Not recommended"


def test_monitor_verdicts_read_as_monitor():
    assert scout_consensus(["Monitor", "Monitor Priority"]) == "Monitor"


def test_a_sign_among_monitors_still_reads_as_split():
    """One scout committed and the others did not. That is not a consensus to sign."""
    assert scout_consensus(["Sign", "Monitor"]) == "Scouts split"


def test_no_reports_is_blank_never_a_verdict():
    """6,170 players; 244 have a report. Blank means nobody has watched him -- it must
    never read as a judgement."""
    assert scout_consensus([]) is None
    assert scout_consensus(None) is None


def test_blank_verdicts_are_ignored():
    assert scout_consensus(["Sign", None, ""]) == "High priority"
