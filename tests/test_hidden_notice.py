from lofc.dashboard.tabs.players import hidden_notice


def test_hidden_notice_is_bold_and_large():
    # "####" = a level-4 heading: bold and larger than body text.
    assert hidden_notice(12) == "#### 12 hidden: no data for an active metric filter."


def test_no_notice_when_nothing_hidden():
    assert hidden_notice(0) is None
