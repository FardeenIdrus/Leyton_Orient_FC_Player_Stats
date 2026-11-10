"""Unit tests for the pure helpers in scripts/web_check.py (no browser, no playwright)."""
import importlib.util
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
# The app container only mounts src/ and tests/; the harness itself runs on the Mac host.
if not (_SCRIPTS / "web_check.py").exists():
    pytest.skip("scripts/ not mounted (container); run with the host venv", allow_module_level=True)
sys.path.insert(0, str(_SCRIPTS))
_spec = importlib.util.spec_from_file_location("web_check", _SCRIPTS / "web_check.py")
wc = importlib.util.module_from_spec(_spec)
sys.modules["web_check"] = wc
_spec.loader.exec_module(wc)


def box(text, x, y, w=40, h=10):
    return {"text": text, "x": x, "y": y, "w": w, "h": h}


def test_overlap_detects_intersection_only():
    assert wc.rects_overlap(box("a", 0, 0), box("b", 20, 5))
    assert not wc.rects_overlap(box("a", 0, 0), box("b", 40, 0))      # touching edges
    assert not wc.rects_overlap(box("a", 0, 0), box("b", 0, 30))      # stacked
    assert not wc.rects_overlap(box("a", 0, 0), box("b", 39.8, 5))    # inside tolerance


def test_find_overlaps_lists_pairs():
    items = [box("Passing", 0, 0), box("Pressing", 30, 2), box("Aerial", 200, 200)]
    assert wc.find_overlaps(items) == [("Passing", "Pressing")]
    assert wc.find_overlaps([]) == []


def test_scan_bad_text():
    assert wc.scan_bad_text("Rating — and 12 goals") == []
    assert wc.scan_bad_text("Age: None") and wc.scan_bad_text("xG nan per 90")
    assert wc.scan_bad_text("NaN%") and wc.scan_bad_text("value undefined") and wc.scan_bad_text("null")
    assert wc.scan_bad_text("[object Object]")
    # real words that merely contain a token are fine
    assert wc.scan_bad_text("Nancy Nonexistent Nullarbor Banana") == []
    assert wc.scan_bad_text("") == [] and wc.scan_bad_text(None) == []


def test_timing_classification():
    assert wc.classify_timing(0.99) == "ok"
    assert wc.classify_timing(1.0) == "ok"
    assert wc.classify_timing(1.01) == "slow"
    assert wc.classify_timing(2.9, first_visit=True) == "ok"
    assert wc.classify_timing(3.2, first_visit=True) == "slow"


def test_sample_options():
    assert wc.sample_options([1, 2, 3], 5) == [1, 2, 3]
    s = wc.sample_options(list(range(100)), 5)
    assert s[0] == 0 and s[-1] == 99 and len(s) == 5 and s == sorted(set(s))
    assert wc.sample_options([1, 2, 3], 1) == [1]
    assert wc.sample_options([1, 2, 3], 0) == []
    assert wc.sample_options([1, 2, 3], 2) == [1, 3]


def test_sample_controls_collapses_repeats():
    cs = [{"idx": i, "kind": "button", "label": "Add"} for i in range(50)]
    cs.append({"idx": 50, "kind": "select", "label": "Season"})
    out = wc.sample_controls(cs, per_group=2, max_total=60)
    assert len(out) == 3 and out[-1]["label"] == "Season"
    assert len(wc.sample_controls(cs, per_group=50, max_total=10)) == 10


def test_local_only_and_destructive_and_summary():
    assert wc.is_local_base("http://localhost:8600") and wc.is_local_base("http://127.0.0.1:8600")
    assert not wc.is_local_base("https://lofc.example.com") and not wc.is_local_base("ftp://localhost")
    assert not wc.is_local_base("http://localhost.evil.com")
    assert wc.is_destructive("Sign out") and wc.is_destructive("Save assessment")
    assert not wc.is_destructive("Compare") and not wc.is_destructive("More filters")
    assert wc.summarize([]) == (0.0, 0.0)
    assert wc.summarize([0.1, 0.5, 0.3]) == (0.5, 0.3)


def test_watchlist_buttons_are_writes():
    # "Add to watchlist" writes a row; the generic exerciser must skip it without --allow-writes
    assert wc.is_destructive("☆ Add to watchlist")
    assert wc.is_destructive("★ On watchlist — remove")
    assert wc.is_destructive("Remove from watchlist")
    # the nav link to the Watchlist page only navigates
    assert not wc.is_destructive("Watchlist") and not wc.is_destructive("Rank as")


def test_sheet_sync_is_never_pressed():
    # Scout reports "Refresh" reads the club's Google scouting sheet: a write, and never pressed
    # by the harness, not even with --allow-writes
    assert wc.is_destructive("Refresh") and wc.is_external("Refresh")
    assert wc.is_external("Sync the scouting sheet")
    assert not wc.is_external("Save") and not wc.is_external("Scout reports")
    assert not wc.is_destructive("Scout reports") and not wc.is_destructive("Open card")


def test_password_is_long_and_random():
    a, b = wc.new_password(), wc.new_password()
    assert a != b and len(a) >= 12


def test_scan_bad_text_ignores_real_sentences_starting_with_none_of():
    """The card's 'None of our wingers has enough minutes…' is English, not a leaked blank."""
    assert wc.scan_bad_text("None of our wingers has enough minutes to compare.") == []
    assert wc.scan_bad_text("Squad note: None of them is rated") == []
    # a standalone blank is still caught, also at the end of a line or before punctuation
    assert wc.scan_bad_text("Age\nNone\nFoot")
    assert wc.scan_bad_text("Club: None.")
    assert wc.scan_bad_text("None")


def test_clipped_tables_flags_a_table_wider_than_its_box():
    """A table (or its scroll wrapper) inside a card whose content is wider than its box hides
    columns: that is a failure, also when the wrapper scrolls."""
    items = [
        {"name": "table #sbs", "scrollWidth": 640, "clientWidth": 523},
        {"name": "div.tw #ph", "scrollWidth": 524, "clientWidth": 523},     # within 1 px
        {"name": "table #pr", "scrollWidth": 500, "clientWidth": 523},
    ]
    out = wc.clipped_tables(items)
    assert len(out) == 1 and "#sbs" in out[0] and "117px" in out[0]
    assert wc.clipped_tables([]) == []


def test_clipped_tables_skips_a_register_marked_to_scroll():
    """Wide registers (Squads, Scout reports, Watchlist) scroll sideways on purpose and say so
    with data-scroll-x; they are not counted as clipped."""
    assert wc.clipped_tables([{"name": "table #tw", "scrollWidth": 1900, "clientWidth": 1104,
                               "scroll_ok": True}]) == []


def col(name, hx, hw, cx, cw, centred=False):
    return {"name": name, "head": {"x": hx, "w": hw}, "cell": {"x": cx, "w": cw}, "centred": centred}


def test_misaligned_columns_needs_overlap_and_centres_for_chip_columns():
    """A body cell's content must sit under its heading: x-ranges overlap; in a centred (chip)
    column the two centres are within 4 px."""
    ok = [col("Age", 100, 30, 104, 26), col("Overall", 200, 60, 206, 48, centred=True)]
    assert wc.misaligned_columns(ok) == []
    off = wc.misaligned_columns([col("Physical", 300, 60, 380, 48, centred=True)])
    assert len(off) == 1 and "Physical" in off[0] and "no overlap" in off[0]
    # left-aligned chip under a wide heading: overlaps, but centres 22 px apart
    left = wc.misaligned_columns([col("Performance", 400, 93, 400, 48, centred=True)])
    assert len(left) == 1 and "centre" in left[0]
    assert wc.misaligned_columns([col("Club", 0, 40, 0, 200)]) == []


def test_account_actions_are_never_pressed_by_the_exerciser():
    for label in ("Clear lockout", "Reactivate account", "Deactivate account", "Reset password",
                  "Create account"):
        assert wc.is_destructive(label), label


def test_radar_sibling_overlap_after_scrolling():
    """Owner bug 2026-11-09 (Compare): a sticky radar slid over the notes written under it in the
    same card. Any overlap between a radar and a sibling in its card is a failure."""
    clean = [{"name": "prad", "radar": box("r", 0, 0, 400, 300), "siblings": [box("note", 0, 310, 400, 20)]}]
    assert wc.radar_sibling_overlaps(clean) == []
    bad = [{"name": "prad", "radar": box("r", 0, 100, 400, 300), "siblings": [box("Different leagues", 0, 310, 400, 20)]}]
    out = wc.radar_sibling_overlaps(bad)
    assert len(out) == 1 and "prad" in out[0] and "Different leagues" in out[0]
