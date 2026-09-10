"""The player card's identity header.

It replaced a run-on grey caption in which a scout scanning twenty players could not find
the contract date. These tests pin the things that would mislead a reader, and the one
thing that would be a security hole -- provider-supplied names go into markup rendered
with unsafe_allow_html.
"""

import datetime as dt

import pandas as pd
import pytest

from lofc.dashboard import player_header as ph


def _markup(html: str) -> str:
    """Just the rendered markup, with the stylesheet stripped.

    The CSS block legitimately contains class names like `expiring` and the club red, so
    a naive substring search over the whole string matches the stylesheet rather than the
    element and passes (or fails) for the wrong reason."""
    return html.split("</style>")[-1]


def _row(**over):
    base = {"player_name": "Luka Lynch", "team_name": "Aston Villa U21",
            "position_group": "Full Back", "league": "Premier League 2",
            "age": 19.6, "foot": "left", "height_cm": 183,
            "contract_until": dt.date(2028, 6, 30), "minutes": 964.0,
            "nationality": "England"}
    base.update(over)
    return pd.Series(base)


def _shares(rows):
    return pd.DataFrame(rows, columns=["position_group", "minutes", "share",
                                       "goals", "assists"])


def test_every_bio_field_is_labelled():
    out = ph.build(_row())
    for label in ("Age", "Foot", "Height", "Contract to", "Minutes"):
        assert label in out


def test_an_absent_field_says_not_recorded_never_zero():
    """A player with no recorded height is not 0 cm."""
    out = ph.build(_row(height_cm=None, contract_until=None))
    assert "not recorded" in out
    assert "0 cm" not in out


def test_the_player_name_is_escaped():
    """Names come from provider data and this markup is rendered with
    unsafe_allow_html. A 2026-08-25 audit found a stored XSS in this exact pattern."""
    out = ph.build(_row(player_name="<script>alert(1)</script>"))
    assert "<script>alert" not in out
    assert "&lt;script&gt;" in out


def test_the_club_name_is_escaped():
    out = ph.build(_row(team_name="<img src=x onerror=alert(1)>"))
    assert "<img src=x" not in out


def test_a_position_group_from_data_is_escaped_in_the_bar():
    out = ph.build(_row(), _shares([("<b>X</b>", 500.0, 0.6, 0.0, 0.0),
                                    ("Winger", 300.0, 0.4, 1.0, 0.0)]))
    assert "<b>X</b>" not in out


def test_a_single_position_player_gets_no_bar():
    """One position all season is no split. An empty bar would imply one."""
    out = ph.build(_row(), _shares([("Full Back", 964.0, 1.0, 0.0, 0.0)]))
    assert "Minutes by position" not in out


def test_the_bar_is_drawn_when_he_filled_more_than_one():
    out = ph.build(_row(), _shares([("Full Back", 373.0, 0.387, 0.0, 0.0),
                                    ("Attacking Mid", 282.0, 0.293, 2.0, 2.0)]))
    assert "Minutes by position" in out
    assert "Attacking Mid 29%" in out


def test_the_assigned_position_is_the_red_segment():
    """The colour states which comparison every percentile below rests on. If red landed
    on the wrong segment it would assert the opposite of the truth."""
    out = ph.build(_row(position_group="Full Back"),
                   _shares([("Full Back", 373.0, 0.387, 0.0, 0.0),
                            ("Attacking Mid", 282.0, 0.293, 2.0, 2.0)]))
    body = _markup(out)
    red_seg = body.index(ph.RED, body.index("lofc-ph-bar"))
    assert "Full Back" in body[red_seg:red_seg + 120]


def test_goals_scored_outside_the_assigned_position_are_named():
    """Lynch scored 0 of his 4 goals as a full back. A reader comparing him with full
    backs has to be told."""
    out = ph.build(_row(position_group="Full Back"),
                   _shares([("Full Back", 373.0, 0.387, 0.0, 0.0),
                            ("Attacking Mid", 282.0, 0.293, 2.0, 2.0),
                            ("Winger", 189.0, 0.196, 2.0, 1.0)]))
    assert "2 as attacking mid" in out and "2 as winger" in out


def test_no_goals_line_when_he_scored_only_in_his_own_position():
    out = ph.build(_row(position_group="Winger"),
                   _shares([("Winger", 900.0, 0.75, 3.0, 1.0),
                            ("Centre Forward", 300.0, 0.25, 0.0, 0.0)]))
    assert "Goals:" not in out


def test_segment_widths_are_the_shares():
    out = ph.build(_row(), _shares([("Full Back", 373.0, 0.387, 0.0, 0.0),
                                    ("Attacking Mid", 282.0, 0.293, 0.0, 0.0)]))
    assert "width:38.70%" in out and "width:29.30%" in out


# --- contract runway and loan status --------------------------------------------------
# These decide whether a player is GETTABLE, a different question from how good he is.
# The runway is shown in months as well as a date: "Jun 2027" does not read as urgent to
# someone scanning a list; "9m left" does.

def test_contract_shows_the_date_and_the_time_remaining():
    out = ph.build(_row(contract_until=dt.date(2028, 6, 30)))
    assert "Jun 2028" in out and "left" in out


def test_a_contract_inside_a_year_is_marked():
    """Under 12 months is the window in which a player can be approached."""
    soon = dt.date.today() + dt.timedelta(days=200)
    assert "expiring" in _markup(ph.build(_row(contract_until=soon)))


def test_a_long_contract_is_not_marked_as_expiring():
    far = dt.date.today() + dt.timedelta(days=900)
    assert "expiring" not in _markup(ph.build(_row(contract_until=far)))


def test_an_expired_contract_says_expired_rather_than_a_negative_length():
    out = ph.build(_row(contract_until=dt.date(2020, 6, 30)))
    assert "expired" in out.lower()
    assert "-" not in out.split("Contract")[1][:40]


def test_a_missing_contract_says_not_recorded():
    """78% is Transfermarkt's own ceiling -- the blank must read as unknown, not as
    'no contract'."""
    assert "not recorded" in ph.build(_row(contract_until=None))


def test_loan_status_names_the_parent_club_and_end_date():
    """The one fact a recruiter needs before approaching anyone."""
    loan = pd.Series({"parent_club": "Brighton & Hove Albion",
                      "loan_ends": dt.date(2027, 5, 31)})
    out = ph.build(_row(), None, loan)
    assert "On loan" in out and "May 2027" in out


def test_a_parent_club_name_is_escaped():
    loan = pd.Series({"parent_club": "<script>alert(1)</script>", "loan_ends": None})
    out = ph.build(_row(), None, loan)
    assert "<script>alert" not in out


def test_no_loan_chip_when_the_player_is_not_on_loan():
    assert "On loan" not in ph.build(_row(), None, None)


def test_the_contract_appears_exactly_once():
    """It was rendered twice — as a bio cell AND as the chip — so every card printed
    "Contract to" two rows apart. The chip wins: it carries the date, the time remaining
    and the urgency colour."""
    body = _markup(ph.build(_row(contract_until=dt.date(2028, 6, 30))))
    assert body.count("Contract to") == 1


def test_nationality_takes_the_freed_cell():
    """It reached ~100% coverage in the 2026-09-07 backfill and had nowhere to show."""
    out = _markup(ph.build(_row()))
    assert "Nationality" in out and "England" in out


def test_a_missing_contract_does_not_raise():
    """pd.NaT passes isinstance(x, datetime.datetime) -- it subclasses datetime -- so a
    type check before the null check let it through and the caller raised "NaTType does
    not support strftime", breaking the whole card for anyone with no contract date."""
    assert ph._months_to(pd.NaT) is None
    assert ph._months_to(None) is None
    body = _markup(ph.build(_row(contract_until=pd.NaT)))
    assert "not recorded" in body


def test_a_card_renders_with_every_bio_field_missing():
    """Players carried from the current-season squad often have almost nothing stored."""
    out = ph.build(_row(contract_until=None, foot=None, height_cm=None,
                        nationality=None, age=None, minutes=None))
    assert "not recorded" in out
