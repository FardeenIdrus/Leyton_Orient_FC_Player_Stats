"""Pure helpers of scripts/smoke_test.py (the pre-deploy smoke test). Loaded by path because
scripts/ is not a package; the module has no import-time side effects beyond stdlib."""

import importlib.util
from pathlib import Path

_PATH = Path(__file__).resolve().parents[1] / "scripts" / "smoke_test.py"
import sys
_spec = importlib.util.spec_from_file_location("smoke_test", _PATH)
st = importlib.util.module_from_spec(_spec)
sys.modules['smoke_test'] = st      # dataclasses look the module up here
_spec.loader.exec_module(st)


def test_report_aggregation_and_exit_code():
    r = st.Report()
    r.add("a", "PASS")
    r.add("b", "WARN", "slow")
    assert (r.failures, r.warnings) == (0, 1)
    assert st.summary_line(r) == "SMOKE: PASS" and st.exit_code(r) == 0
    r.add("c", "FAIL", "boom")
    r.add("d", "FAIL", "boom")
    assert st.summary_line(r) == "SMOKE: FAIL (2)" and st.exit_code(r) == 1


def test_timing_thresholds_warn_not_fail():
    assert st.timing_status("warm_players", 3.0) == "PASS"
    assert st.timing_status("warm_players", 3.01) == "WARN"
    assert st.timing_status("cold", 25.0) == "PASS"
    assert st.timing_status("cold", 25.5) == "WARN"


def test_position_from_label_and_pick():
    labels = ["A B — X FC  ·  Full Back  ·  League One", "C D — Y FC  ·  Winger  ·  League Two",
              "E F — Z FC  ·  Full Back  ·  League Two", "bad label"]
    assert st.position_from_label(labels[0]) == "Full Back"
    assert st.position_from_label("bad label") is None
    assert st.pick_label(labels, "Full Back") == labels[0]
    assert st.pick_label(labels, "Full Back", 1) == labels[2]
    assert st.pick_label(labels, "Goalkeeper") is None


def test_midpoint_is_on_grid_and_inside_range():
    assert st.midpoint_value(0, 10, 1) == 5
    assert st.midpoint_value(3.0, 4.0, 0.01) == 3.5
    assert st.midpoint_value(5, 5, 0.1) == 5


def test_format_table_truncates_detail():
    out = st.format_table([st.Result("x", "FAIL", "y" * 500, 1.2)])
    assert "FAIL" in out and len(out.splitlines()[-1]) < 200


def test_leaked_format_cells_finds_format_codes_only():
    import pandas as pd
    leaked_format_cells = st.leaked_format_cells
    ok = pd.DataFrame({"A": ["Jun 2027", "—", "4.10"], "B": [1, 2, 3]})
    assert leaked_format_cells(ok) == []
    bad = pd.DataFrame({"Contract to": ["%b %Y", "Jun 2027"], "R": ["{:.2f}", "x"]})
    assert leaked_format_cells(bad) == ["Contract to: '%b %Y'", "R: '{:.2f}'"]
