"""The 'what this covers / what it doesn't' disclosures (spec section 10).

Spec section 10 is a HARD requirement: every assumption and coverage limit behind these
scores must reach the user on the page. These tests pin the ones that would mislead a
recruiter if they went missing."""

from lofc.dashboard import transparency


def test_there_are_thirteen_disclosures():
    """Spec section 10 lists thirteen. A missing one is a caveat the user never sees."""
    assert len(transparency.DISCLOSURES) == 13


def test_every_disclosure_has_a_heading_and_a_body():
    for heading, body in transparency.DISCLOSURES:
        assert heading.strip()
        assert body.strip()


def test_a_disclosure_says_the_medical_score_is_human_judgement():
    text = " ".join(body for _, body in transparency.DISCLOSURES).lower()
    assert "judgement" in text or "judgment" in text
    assert "turned into that score by the platform" in text


def test_a_disclosure_states_the_league_coverage_figures():
    text = " ".join(body for _, body in transparency.DISCLOSURES)
    for figure in ("74%", "39%", "32%", "18%"):
        assert figure in text


def test_a_disclosure_states_what_is_actually_knowable():
    text = " ".join(body for _, body in transparency.DISCLOSURES)
    for figure in ("84%", "64%", "58%", "49%"):
        assert figure in text


def test_a_disclosure_says_nothing_excludes_a_player():
    text = " ".join(body for _, body in transparency.DISCLOSURES).lower()
    assert "advisory" in text


def test_a_disclosure_distinguishes_no_injuries_from_not_known():
    text = " ".join(body for _, body in transparency.DISCLOSURES).lower()
    assert "not known" in text


def test_the_disclosures_stay_short_enough_to_be_read():
    """A wall of text fails the requirement as surely as saying nothing -- a recruiter reads
    this between meetings."""
    for heading, body in transparency.DISCLOSURES:
        assert len(body) <= 320, f"{heading!r} is too long to be read between meetings"
