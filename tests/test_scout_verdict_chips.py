"""The verdict summary on a player's profile: what the scouts concluded, with counts.

WHAT WAS WRONG. The profile printed `"Scouts did not agree: Sign · Don't sign"` -- the
DISTINCT verdicts, listed. Three scouts saying Sign against one saying Don't sign produced
exactly the same line as one against one. The 3-1 split was invisible.

That came from a deliberate rule -- disagreement is the signal, and averaging it into a
single verdict would hide the one thing worth discussing -- but the rule was over-applied.
Showing HOW MANY said what is not picking a winner; it is showing the reader the evidence.

ORDER IS DECISIVENESS, NOT COUNT. Sign, then Monitor Priority, then Monitor, then Don't
sign -- the two verdicts where a scout committed sit at the ends, with the two
non-commitments between them. Ordering by count would make the same player's summary
reorder itself as reports arrive, and would read as a ranking of the verdicts themselves.
"""

import pandas as pd

from lofc.dashboard.tabs.scout_reports import VERDICT_ORDER, verdict_counts


def test_one_report_gives_one_chip():
    assert verdict_counts(["Sign"]) == [("Sign", 1)]


def test_repeated_verdicts_are_counted_not_repeated():
    """THE DEFECT. Three Signs used to render the same as one."""
    assert verdict_counts(["Sign", "Sign", "Sign"]) == [("Sign", 3)]


def test_a_three_one_split_shows_both_counts():
    """`Scouts did not agree: Sign · Don't sign` hid this entirely."""
    assert verdict_counts(["Sign", "Sign", "Sign", "Don't sign"]) == [
        ("Sign", 3), ("Don't sign", 1)]


def test_an_even_split_is_shown_as_an_even_split():
    """Nothing is being decided, so a tie needs no rule -- it just reads as 2 and 2."""
    assert verdict_counts(["Sign", "Sign", "Don't sign", "Don't sign"]) == [
        ("Sign", 2), ("Don't sign", 2)]


def test_order_is_decisiveness_not_frequency():
    """One Sign against four Monitors still reads Sign first. Ordering by count would
    reshuffle a player's summary every time a report arrived."""
    assert verdict_counts(["Monitor"] * 4 + ["Sign"]) == [("Sign", 1), ("Monitor", 4)]


def test_the_full_order_is_sign_priority_monitor_dont_sign():
    out = verdict_counts(["Don't sign", "Monitor", "Monitor Priority", "Sign"])
    assert [v for v, _ in out] == ["Sign", "Monitor Priority", "Monitor", "Don't sign"]


def test_the_declared_order_matches_what_is_produced():
    """`VERDICT_ORDER` is the single source of truth for both order and colour."""
    out = verdict_counts(list(VERDICT_ORDER))
    assert [v for v, _ in out] == list(VERDICT_ORDER)


def test_an_unrecognised_verdict_is_kept_and_placed_last():
    """The form's dropdown can gain an option without telling us. Dropping it would make
    a report vanish from its own player's summary."""
    out = verdict_counts(["Sign", "Have another look"])
    assert out == [("Sign", 1), ("Have another look", 1)]


def test_blank_verdicts_are_ignored():
    assert verdict_counts(["Sign", None, "", float("nan")]) == [("Sign", 1)]


def test_no_reports_gives_nothing():
    assert verdict_counts([]) == []
    assert verdict_counts(None) == []


def test_a_pandas_series_works_as_input():
    """It is called with a dataframe column."""
    assert verdict_counts(pd.Series(["Sign", "Sign"])) == [("Sign", 2)]


# --- colour ---------------------------------------------------------------------------

def test_each_verdict_has_a_tone():
    from lofc.dashboard.tabs.scout_reports import verdict_tone
    assert verdict_tone("Sign") == "positive"
    assert verdict_tone("Don't sign") == "negative"
    assert verdict_tone("Monitor") == "neutral"
    assert verdict_tone("Monitor Priority") == "neutral"


def test_dont_sign_is_red_and_not_the_club_red():
    """#C8102E is Leyton Orient's own colour and is used across the platform for emphasis
    and for the club itself. A rejection must read as a judgement, not as branding."""
    from lofc.dashboard import theme
    from lofc.dashboard.tabs.scout_reports import TONE_COLOURS
    fg, _ = TONE_COLOURS["negative"]
    assert fg.lower() != theme.RED.lower()
    # red channel dominant, and darker than the club red
    r, g, b = (int(fg[i:i + 2], 16) for i in (1, 3, 5))
    assert r > g and r > b
