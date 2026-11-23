"""Watchlist redesign (owner 2026-11-23): `core.watchlist_page` -- one entry per player, grouped
by position with our best (League One) for reference only, "Suggested from scout reports",
"What changed since added". Plain frames in, plain data out: no database."""
import datetime as dt

import pandas as pd

from lofc.core import watchlist_page as wp

NOW = pd.Timestamp("2026-11-23")


def _reports():
    return pd.DataFrame([
        # player 1 (watched): an older Monitor, then a new Sign after he was added
        dict(id=11, player_id=1, verdict="Monitor", scout="Scout A", fixture_date="2026-10-01",
             submitted_at="2026-10-02", missing_since=None, player_name="One", club_name="C1"),
        dict(id=12, player_id=1, verdict="Sign", scout="Scout B", fixture_date="2026-11-15",
             submitted_at="2026-11-16", missing_since=None, player_name="One", club_name="C1"),
        # player 2: latest is Monitor Priority, 10 days ago -> suggested
        dict(id=21, player_id=2, verdict="Monitor Priority", scout="Scout A", fixture_date="2026-11-13",
             submitted_at="2026-11-14", missing_since=None, player_name="Two", club_name="C2"),
        # player 3: Sign 50 days ago -> only under "All"
        dict(id=31, player_id=3, verdict="Sign", scout="Scout B", fixture_date="2026-10-04",
             submitted_at="2026-10-05", missing_since=None, player_name="Three", club_name="C3"),
        # player 4: Sign then a later Don't sign -> latest decides: not suggested
        dict(id=41, player_id=4, verdict="Sign", scout="Scout A", fixture_date="2026-11-01",
             submitted_at="2026-11-01", missing_since=None, player_name="Four", club_name="C4"),
        dict(id=42, player_id=4, verdict="Don't sign", scout="Scout B", fixture_date="2026-11-10",
             submitted_at="2026-11-10", missing_since=None, player_name="Four", club_name="C4"),
        # player 5: Sign but its report was dismissed
        dict(id=51, player_id=5, verdict="Sign", scout="Scout A", fixture_date="2026-11-20",
             submitted_at="2026-11-20", missing_since=None, player_name="Five", club_name="C5"),
        # unmatched report (no player_id) and a report gone from the sheet: never suggested
        dict(id=61, player_id=None, verdict="Sign", scout="Scout A", fixture_date="2026-11-20",
             submitted_at="2026-11-20", missing_since=None, player_name="Nobody", club_name="C6"),
        dict(id=71, player_id=7, verdict="Sign", scout="Scout A", fixture_date="2026-11-20",
             submitted_at="2026-11-20", missing_since="2026-11-21", player_name="Gone", club_name="C7"),
    ])


def test_latest_report_per_player_by_fixture_date_then_submitted():
    last = wp.latest_reports(_reports())
    assert last.loc[1, "verdict"] == "Sign" and last.loc[4, "verdict"] == "Don't sign"
    assert 7 not in last.index                                      # gone from the sheet
    assert set(last.index) == {1, 2, 3, 4, 5}


def test_suggestions_are_sign_or_monitor_priority_not_watched_not_dismissed():
    last = wp.latest_reports(_reports())
    s30 = wp.suggestions(last, watched={1}, dismissed={51}, now=NOW, days=30)
    assert [r["report_id"] for r in s30] == [21]
    every = wp.suggestions(last, watched={1}, dismissed={51}, now=NOW, days=None)
    assert [r["report_id"] for r in every] == [21, 31]                # newest first
    assert every[0]["verdict"] == "Monitor Priority" and every[0]["report"] == "Scout A · 13 Nov"


def test_changes_since_added_rating_club_new_report_injury_contract():
    rows = pd.DataFrame([dict(player_id=1, player_name="One", created_at=pd.Timestamp("2026-11-01"),
                              added_rating=3.94, added_club="Old FC", months_left=5,
                              injury_status="Currently injured: hamstring (since 12 Nov 2026)")])
    now_rows = {1: {"rating": 4.19, "club": "New FC", "league": "League Two"}}
    got = wp.changes(rows, now_rows, wp.latest_reports(_reports()), _reports(), now=NOW)
    kinds = [c["kind"] for c in got]
    assert kinds == ["report", "rating", "club", "injury", "contract"]
    by = {c["kind"]: c for c in got}
    assert by["rating"]["text"] == "rating 3.94 → 4.19" and by["rating"]["dir"] == "up"
    assert by["club"]["text"] == "moved: Old FC → New FC"
    assert by["report"]["text"] == "new scout report: Sign (Scout B, 15 Nov)"   # after he was added
    assert by["injury"]["text"].startswith("Currently injured")
    assert by["contract"]["text"] == "contract ends in 5 months"


def test_changes_skip_what_is_unknown_or_unchanged():
    rows = pd.DataFrame([dict(player_id=2, player_name="Two", created_at=pd.Timestamp("2026-11-20"),
                              added_rating=None, added_club=None, months_left=30,
                              injury_status="No injury spells on record")])
    got = wp.changes(rows, {2: {"rating": 3.5, "club": "C2", "league": "L2"}},
                     wp.latest_reports(_reports()), _reports(), now=NOW)
    assert got == []                                                # report 21 is before he was added
    tiny = rows.assign(added_rating=3.48)
    assert wp.changes(tiny, {2: {"rating": 3.5, "club": "C2"}}, wp.latest_reports(_reports()),
                      _reports(), now=NOW) == []                    # under 0.10: not a change


def test_group_rows_by_position_with_our_best_for_reference():
    rows = [dict(player_id=1, position="Winger", stage="Shortlisted"),
            dict(player_id=2, position="Defensive Mid", stage="Watching"),
            dict(player_id=3, position="Attacking Mid", stage="Dropped"),
            dict(player_id=4, position=None, stage="Watching")]
    best = {"Winger": {"name": "Yusuf Akhamrich", "rating": 3.10}}
    groups, closed = wp.group_rows(rows, best)
    assert [g["group"] for g in groups] == ["Midfield", "Winger", "Other"]
    assert groups[0]["label"] == "Midfielders" and groups[1]["label"] == "Wingers"
    assert groups[1]["our_best"] == {"name": "Yusuf Akhamrich", "rating": 3.10, "league": "L1"}
    assert groups[0]["our_best"] is None
    assert [r["player_id"] for r in closed] == [3]                   # dropped / signed apart


def test_tiles():
    rows = [dict(stage="Shortlisted", months_left=4, new_report=True),
            dict(stage="Watching", months_left=None, new_report=False),
            dict(stage="Dropped", months_left=2, new_report=True)]
    assert wp.tiles(rows) == [
        {"key": "active", "label": "On the list", "value": 2},
        {"key": "Shortlisted", "label": "Shortlisted", "value": 1},
        {"key": "expiring", "label": "Contract ≤ 6 months", "value": 1},
        {"key": "newrep", "label": "New scout report (14 days)", "value": 1}]
