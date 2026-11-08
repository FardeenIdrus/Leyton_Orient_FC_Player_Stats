"""Pre-deploy smoke test: drives the REAL dashboard with Streamlit's AppTest, read-only.

    docker compose exec -T app python scripts/smoke_test.py [--quick]

Run it on the Mac before pushing and on the server after deploy.sh (with
`-f /opt/lofc/docker-compose.prod.yml`). It never writes to the database and never calls a
provider API. Login is bypassed with a wrapper that patches `session.require_login` -- no
credentials are involved. Exit code 1 if any check FAILS; WARN (slow, odd) does not fail.

Checks: (1) every navigation page renders, (2) Players for every position x season,
(3) every Players metric slider moved one at a time (the crash class of the failed demo),
(4) global search, (5) Compare search, (6) Report page, (7) data sanity in SQL, (8) timings.

AppTest cannot switch st.navigation pages, so a generated wrapper patches st.navigation to run
ONE page, named by the `_smoke_page` session_state key. Wrappers are written to a temp dir.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import tempfile
import time
import traceback
from dataclasses import dataclass, field

# Warm Players render over this is flagged; cold render over this is flagged (seconds).
WARM_PLAYERS_WARN_S = 3.0
COLD_WARN_S = 25.0

OUTFIELD_FIRST = "Centre Forward"          # the position used for slider / search checks

WRAPPER_SRC = '''
import os
import streamlit as st

# Keep the REAL st.navigation once per process: this wrapper re-runs on every AppTest run,
# and re-reading st.navigation here would wrap the previous run's patch -- after a few
# thousand runs (ui_check --full) that chain hits Python's recursion limit.
_orig = getattr(st, "_lofc_real_navigation", None) or st.navigation
st._lofc_real_navigation = _orig
_LIST_FILE = os.environ.get("SMOKE_PAGE_LIST", "")


def _nav(sections, *a, **k):
    pages = [p for v in sections.values() for p in v] if isinstance(sections, dict) else list(sections)
    _orig(sections, *a, **k)
    if _LIST_FILE:
        with open(_LIST_FILE, "w") as f:
            f.write("\\n".join(p.title for p in pages))
    # Read per run from session_state (set on each AppTest), not from the environment: the
    # script re-executes on every rerun, and a second AppTest would otherwise change the page
    # under the first one.
    target = st.session_state.get("_smoke_page", "")
    page = next((p for p in pages if p.title == target), pages[0])

    class _R:
        # The stand-in carries the real page's title and url_path, like st.navigation's page.
        title = page.title
        url_path = page.url_path

        def run(self):
            page._page()
    return _R()


st.navigation = _nav
from lofc.dashboard import session
from lofc.dashboard.session import CurrentUser
session.require_login = lambda engine: CurrentUser(id=1, full_name="Smoke Test", role="admin")
import lofc.dashboard.app as app
app.require_login = session.require_login
app.main()
'''


# ----------------------------------------------------------------------------- pure helpers
_FORMAT_CODE = re.compile(r"%[a-zA-Z]|\{:[^}]*\}")


def leaked_format_cells(frame) -> list[str]:
    """Text cells that are a format code ("%b %Y", "{:.2f}") instead of a value -- a
    formatting bug that renders without an exception. First hit per column."""
    hits = []
    for col in frame.columns:
        for v in frame[col]:
            if isinstance(v, str) and _FORMAT_CODE.search(v):
                hits.append(f"{col}: {v!r}")
                break
    return hits


@dataclass
class Result:
    check: str
    status: str                 # PASS | WARN | FAIL
    detail: str = ""
    seconds: float = 0.0


@dataclass
class Report:
    results: list[Result] = field(default_factory=list)

    def add(self, check: str, status: str, detail: str = "", seconds: float = 0.0) -> None:
        assert status in ("PASS", "WARN", "FAIL"), status
        self.results.append(Result(check, status, detail, seconds))

    @property
    def failures(self) -> int:
        return sum(1 for r in self.results if r.status == "FAIL")

    @property
    def warnings(self) -> int:
        return sum(1 for r in self.results if r.status == "WARN")


def summary_line(report: Report) -> str:
    n = report.failures
    return "SMOKE: PASS" if n == 0 else f"SMOKE: FAIL ({n})"


def exit_code(report: Report) -> int:
    return 1 if report.failures else 0


def timing_status(kind: str, seconds: float) -> str:
    """PASS/WARN for a render time. kind: 'warm_players' or 'cold'. Never FAIL: a slow page is
    a signal for the owner, not a reason to block a deploy on a noisy laptop."""
    limit = WARM_PLAYERS_WARN_S if kind == "warm_players" else COLD_WARN_S
    return "WARN" if seconds > limit else "PASS"


def position_from_label(label: str) -> str | None:
    """Search labels read 'Name — Club  ·  Position  ·  League' (dashboard/search.py)."""
    parts = label.split("  ·  ")
    return parts[1] if len(parts) >= 3 else None


def pick_label(labels: list[str], position: str, skip: int = 0) -> str | None:
    """The `skip`-th search label whose position is `position`."""
    hits = [lb for lb in labels if position_from_label(lb) == position]
    return hits[skip] if len(hits) > skip else None


def midpoint_value(lo: float, hi: float, step: float) -> float:
    """A slider value strictly off both ends' resting position when possible, on the step grid."""
    if hi <= lo:
        return lo
    n = round((hi - lo) / 2 / step)
    return round(lo + n * step, 6)


def format_table(results: list[Result]) -> str:
    w = max([len(r.check) for r in results] + [5])
    d = 70
    lines = [f"{'check'.ljust(w)} | result | {'detail'.ljust(d)} | secs"]
    lines.append("-" * len(lines[0]))
    for r in results:
        det = r.detail.replace("\n", " ")
        det = det if len(det) <= d else det[: d - 1] + "…"
        lines.append(f"{r.check.ljust(w)} | {r.status.ljust(6)} | {det.ljust(d)} | {r.seconds:5.1f}")
    return "\n".join(lines)


def exc_text(at) -> str:
    return " || ".join(str(getattr(e, "value", e))[:300] for e in at.exception)


# --------------------------------------------------------------------------------- the checks
class Smoke:
    def __init__(self, quick: bool):
        from streamlit.testing.v1 import AppTest
        self.AppTest = AppTest
        self.quick = quick
        self.report = Report()
        self.tmp = tempfile.mkdtemp(prefix="lofc_smoke_")
        self.wrapper = os.path.join(self.tmp, "smoke_wrapper.py")
        with open(self.wrapper, "w") as f:
            f.write(WRAPPER_SRC)
        self.list_file = os.path.join(self.tmp, "pages.txt")
        os.environ["SMOKE_PAGE_LIST"] = self.list_file
        self.timings: list[tuple[str, str, float]] = []
        self.first_run = 0.0

    # one AppTest per target page; the default timeout is generous for the cold cache fill
    def app(self, page: str, **state):
        at = self.AppTest.from_file(self.wrapper, default_timeout=300)
        at.session_state["_smoke_page"] = page
        for k, v in state.items():
            at.session_state[k] = v
        return at

    def guard(self, name: str, fn) -> None:
        t0 = time.time()
        try:
            fn()
        except Exception:                                      # noqa: BLE001
            self.report.add(name, "FAIL", "harness error: " + traceback.format_exc().strip().splitlines()[-1],
                            time.time() - t0)

    # -- 1 -------------------------------------------------------------------------------
    def check_pages(self) -> None:
        at = self.app("")
        t0 = time.time()
        at.run()
        self.first_run = time.time() - t0               # the genuinely cold render
        titles = open(self.list_file).read().split("\n") if os.path.exists(self.list_file) else []
        if not titles:
            self.report.add("1 pages", "FAIL", "could not enumerate navigation pages")
            return
        self.report.add("1 pages", "PASS", f"{len(titles)} pages: " + ", ".join(titles))
        self.titles = titles
        for t in titles:
            t0 = time.time()
            try:
                at = self.app(t)
                at.run()
                dt = time.time() - t0
                if len(at.exception):
                    self.report.add(f"1 page: {t}", "FAIL", exc_text(at), dt)
                elif leaks := [h for df in at.dataframe for h in leaked_format_cells(df.value)]:
                    self.report.add(f"1 page: {t}", "FAIL", "format code shown: " + "; ".join(leaks)[:200], dt)
                elif len(at.error):
                    self.report.add(f"1 page: {t}", "WARN", "st.error: " + str(at.error[0].value)[:200], dt)
                else:
                    self.report.add(f"1 page: {t}", "PASS", "", dt)
                self.timings.append((t, "cold-ish", dt))
            except Exception as e:                              # noqa: BLE001
                self.report.add(f"1 page: {t}", "FAIL", f"harness: {e!r}"[:300], time.time() - t0)

    # -- helpers for the Players page --------------------------------------------------------
    @staticmethod
    def table_rows(at) -> int:
        """Rows in the largest dataframe on the page (the ranked table)."""
        best = 0
        for df in at.dataframe:
            try:
                best = max(best, len(df.value))
            except Exception:                                   # noqa: BLE001
                pass
        return best

    # -- 2 -------------------------------------------------------------------------------
    def check_players_grid(self, seasons: list[int], positions: list[str], expected) -> None:
        from lofc.dashboard.seasons import season_name_for
        at = self.app("Players")
        at.run()                                                 # cold
        for sid in seasons:
            for pos in positions:
                name = f"2 players {season_name_for(sid)} / {pos}"
                t0 = time.time()
                try:
                    at.selectbox(key="sidebar_season").select(sid)
                    at.selectbox(key="sidebar_position").select(pos)
                    at.run()
                    dt = time.time() - t0
                    rows = self.table_rows(at)
                    want = expected(sid, pos)
                    if len(at.exception):
                        self.report.add(name, "FAIL", exc_text(at), dt)
                    elif want > 0 and rows == 0 and any(("ranked in" in i.value and "yet" in i.value) for i in at.info):
                        # Thin league-position pools are withheld on purpose (MIN_PEERS_FOR_RANKING)
                        # and the page says so; that is the honesty rule working, not a bug.
                        self.report.add(name, "PASS", f"withheld by design (thin pool; {want} scored)", dt)
                    elif want > 0 and rows == 0:
                        self.report.add(name, "FAIL", f"empty table but {want} scored players in DB", dt)
                    else:
                        self.report.add(name, "PASS", f"{rows} rows shown ({want} scored in DB)", dt)
                except Exception as e:                           # noqa: BLE001
                    self.report.add(name, "FAIL", f"harness: {e!r}"[:300], time.time() - t0)

    # -- 3 -------------------------------------------------------------------------------
    def check_sliders(self, sid: int, pos: str) -> None:
        at = self.app("Players", sidebar_season=sid, sidebar_position=pos)
        at.run()
        if len(at.exception):
            self.report.add("3 sliders", "FAIL", "base render: " + exc_text(at))
            return
        prefix = f"mf_{pos}_"
        sliders = [s for s in at.slider if str(s.key).startswith(prefix)]
        if not sliders:
            self.report.add("3 sliders", "FAIL", f"no sliders found with prefix {prefix!r}")
            return
        keys = [s.key for s in sliders]
        pct = [k for k in keys if "_pct_" in k]
        raw = [k for k in keys if "_raw_" in k]
        self.report.add("3 sliders found", "PASS", f"{len(pct)} percentile, {len(raw)} physical")
        bad, t_all = [], time.time()
        prev = None                                              # (key, default) to restore
        for k in pct + raw:
            s = at.slider(key=k)
            default = s.value
            if prev:
                at.slider(key=prev[0]).set_value(prev[1])
            if "_pct_" in k:
                s.set_value(50)
            else:
                s.set_value(midpoint_value(float(s.min), float(s.max), float(s.step)))
            prev = (k, default)
            try:
                at.run()
                if len(at.exception):
                    bad.append(f"{k.removeprefix(prefix)}: {exc_text(at)[:160]}")
            except Exception as e:                               # noqa: BLE001
                bad.append(f"{k.removeprefix(prefix)}: harness {e!r}"[:200])
        dt = time.time() - t_all
        if bad:
            self.report.add("3 sliders", "FAIL", f"{len(bad)}/{len(keys)} crashed; first: {bad[0]}", dt)
            for b in bad[1:6]:
                self.report.add("3 sliders (more)", "FAIL", b)
        else:
            self.report.add("3 sliders", "PASS", f"{len(keys)} sliders moved one at a time on {pos}, no exception", dt)

    # -- 4 -------------------------------------------------------------------------------
    def check_search(self, sid: int) -> None:
        at = self.app("Players", sidebar_season=sid, sidebar_position=OUTFIELD_FIRST)
        at.run()
        labels = list(at.selectbox(key="global_player_search").options)
        for tag, target, skip in (("other position", "Full Back", 0), ("same position", OUTFIELD_FIRST, 3)):
            name = f"4 search ({tag}: {target})"
            t0 = time.time()
            at = self.app("Players", sidebar_season=sid, sidebar_position=OUTFIELD_FIRST)
            at.run()
            label = pick_label(labels, target, skip) or pick_label(labels, target, 0)
            if not label:
                self.report.add(name, "WARN", f"no {target} in search options")
                continue
            at.selectbox(key="global_player_search").select(label)
            at.run()
            dt = time.time() - t0
            pos_now = at.selectbox(key="sidebar_position").value
            detail = any("Player detail" in m.value for m in at.markdown)
            problems = []
            if len(at.exception):
                problems.append("exception: " + exc_text(at))
            if pos_now != target:
                problems.append(f"sidebar_position is {pos_now!r}, expected {target!r}")
            if not detail:
                problems.append("'Player detail' not shown")
            self.report.add(name, "FAIL" if problems else "PASS",
                            "; ".join(problems) or label[:60], dt)

    # -- 5 -------------------------------------------------------------------------------
    def check_compare(self, sid: int, engine) -> None:
        import sqlalchemy as sa
        name = "5 compare search"
        t0 = time.time()
        at = self.app("Compare", sidebar_season=sid, sidebar_position=OUTFIELD_FIRST)
        at.run()
        if len(at.exception):
            self.report.add(name, "FAIL", "base render: " + exc_text(at), time.time() - t0)
            return
        labels = list(at.selectbox(key="cmp_a").options)
        label = pick_label(labels, "Full Back")
        if not label:
            self.report.add(name, "WARN", "no Full Back in search options")
            return
        at.selectbox(key="cmp_a").select(label)
        at.run()
        dt = time.time() - t0
        problems = []
        if len(at.exception):
            problems.append("exception: " + exc_text(at))
        pos_now = at.selectbox(key="sidebar_position").value
        if pos_now != "Full Back":
            problems.append(f"sidebar_position is {pos_now!r}")
        # Every slot is a "Name — Club" label from the one-position pool; confirm in SQL.
        slots = [at.selectbox(key=k).value for k in ("cmp_a", "cmp_b", "cmp_c")]
        with engine.connect() as c:
            for s in slots:
                if not s or " — " not in s or s == "—":
                    continue
                nm, club = s.split(" — ", 1)
                got = {r[0] for r in c.execute(sa.text(
                    "SELECT DISTINCT position_group FROM player_metrics_neutral "
                    "WHERE season_id=:s AND player_name=:n AND team_name=:t"),
                    {"s": sid, "n": nm, "t": club})}
                if got and got != {"Full Back"}:
                    problems.append(f"slot {s!r} is {sorted(got)}")
        self.report.add(name, "FAIL" if problems else "PASS", "; ".join(problems) or label[:60], dt)

    # -- 6 -------------------------------------------------------------------------------
    def check_report(self, sid: int) -> None:
        name = "6 report"
        t0 = time.time()
        at = self.app("Report", sidebar_season=sid, sidebar_position=OUTFIELD_FIRST)
        at.run()
        # A search term every dataset has a hit for would be brittle; take the first option the
        # Players-page search offers instead and type its name.
        pat = self.app("Players", sidebar_season=sid, sidebar_position=OUTFIELD_FIRST)
        pat.run()
        label = pick_label(list(pat.selectbox(key="global_player_search").options), OUTFIELD_FIRST, 5)
        if not label:
            self.report.add(name, "WARN", "no player to report on")
            return
        player = label.split(" — ")[0]
        at.text_input(key="report_search").input(player)
        at.run()
        dt = time.time() - t0
        problems = []
        if len(at.exception):
            problems.append("exception: " + exc_text(at))
        if len(at.error):
            problems.append("st.error: " + str(at.error[0].value)[:200])
        n_dl = len(at.get("download_button"))
        if n_dl < 1:
            problems.append("no download button")
        self.report.add(name, "FAIL" if problems else "PASS", "; ".join(problems) or f"{player}: {n_dl} download buttons", dt)

        # Fill the free-text form fields, which reshape the rendered report.
        t1 = time.time()
        problems = []
        filled = 0
        for ta in at.text_area:
            ta.input("Smoke test summary — ünïcode & <b>html</b> \"quotes\"")
            filled += 1
        at.run()
        if len(at.exception):
            problems.append("exception: " + exc_text(at))
        if len(at.error):
            problems.append("st.error: " + str(at.error[0].value)[:200])
        if len(at.get("download_button")) < 1:
            problems.append("download button gone")
        if filled == 0:
            problems.append("no text areas found")
        self.report.add("6 report (form filled)", "FAIL" if problems else "PASS",
                        "; ".join(problems) or f"{filled} text areas filled", time.time() - t1)

    # -- 7 -------------------------------------------------------------------------------
    def check_data(self, engine, seasons: list[int]) -> None:
        import sqlalchemy as sa

        def q(c, sql, **p):
            return c.execute(sa.text(sql), p).scalar()

        with engine.connect() as c:
            for sid in seasons:
                t0 = time.time()
                tag = f"7 data s{sid}"
                n_sc = q(c, "SELECT count(*) FROM player_scorecards WHERE season_id=:s", s=sid)
                bad_range = q(c, "SELECT count(*) FROM player_scorecards WHERE season_id=:s "
                                 "AND objective_composite IS NOT NULL "
                                 "AND (objective_composite<1 OR objective_composite>5)", s=sid)
                # Rankable = the neutral row says so; such a player must have a composite.
                null_comp = q(c, "SELECT count(*) FROM player_scorecards s JOIN player_metrics_neutral m "
                                 "ON m.player_id=s.player_id AND m.competition_id=s.competition_id "
                                 "AND m.season_id=s.season_id AND m.position_group=s.position_group "
                                 "WHERE s.season_id=:s AND s.archetype='All Metrics' AND m.rankable "
                                 "AND s.objective_composite IS NULL", s=sid)
                dup = q(c, "SELECT count(*) FROM (SELECT 1 FROM player_scorecards WHERE season_id=:s "
                           "GROUP BY player_id, competition_id, season_id, archetype "
                           "HAVING count(*)>1) d", s=sid)
                orphan = q(c, "SELECT count(*) FROM player_scorecards s LEFT JOIN players p "
                              "ON p.player_id=s.player_id WHERE s.season_id=:s AND p.player_id IS NULL", s=sid)
                leagues_sc = q(c, "SELECT count(DISTINCT competition_id) FROM player_scorecards WHERE season_id=:s", s=sid)
                # Only leagues where someone has reached the 450-minute minimum can have ratings: a league
                # whose season has just started (e.g. A-League, Oct 2026) legitimately has none.
                leagues_nm = q(c, "SELECT count(DISTINCT competition_id) FROM player_metrics_neutral "
                                  "WHERE season_id=:s AND rankable", s=sid)
                problems = []
                if n_sc == 0:
                    problems.append("no scorecards")
                if bad_range:
                    problems.append(f"{bad_range} composites outside [1,5]")
                if null_comp:
                    problems.append(f"{null_comp} rankable players with NULL composite")
                if dup:
                    problems.append(f"{dup} duplicate scorecard keys")
                if orphan:
                    problems.append(f"{orphan} scorecards with no players row")
                if leagues_sc != leagues_nm:
                    problems.append(f"leagues: scorecards {leagues_sc} != neutral {leagues_nm}")
                self.report.add(tag, "FAIL" if problems else "PASS",
                                "; ".join(problems) or f"{n_sc} scorecards, {leagues_sc} leagues, ranges ok",
                                time.time() - t0)
                self.check_percentiles(sid)

    def check_percentiles(self, sid: int) -> None:
        # Percentiles are computed on the fly from player_metrics_neutral (not stored), exactly as
        # the dashboard does, so range-check what the page would actually show.
        t0 = time.time()
        from lofc.dashboard.loaders import load_scorecard_percentiles
        df = load_scorecard_percentiles.__wrapped__(sid) if hasattr(load_scorecard_percentiles, "__wrapped__") \
            else load_scorecard_percentiles(sid)
        num = df.select_dtypes("number").drop(columns=["player_id", "competition_id", "season_id"], errors="ignore")
        lo, hi = float(num.min().min()), float(num.max().max())
        ok = lo >= 0 and hi <= 100
        self.report.add(f"7 percentiles s{sid}", "PASS" if ok else "FAIL",
                        f"{len(df)} rows, min {lo:.1f}, max {hi:.1f}", time.time() - t0)

    # -- 8 -------------------------------------------------------------------------------
    def check_timings(self, sid: int) -> None:
        at = self.app("Players", sidebar_season=sid, sidebar_position=OUTFIELD_FIRST)
        t0 = time.time()
        at.run()
        cold = time.time() - t0
        warm = []
        for _ in range(2):
            t0 = time.time()
            at.run()
            warm.append(time.time() - t0)
        w = min(warm)
        self.report.add("8 first render (cold)", timing_status("cold", self.first_run),
                        f"default page, empty caches; limit {COLD_WARN_S:.0f}s", self.first_run)
        self.report.add("8 players re-render", timing_status("cold", cold), f"limit {COLD_WARN_S:.0f}s", cold)
        self.report.add("8 players warm", timing_status("warm_players", w), f"best of 2; limit {WARM_PLAYERS_WARN_S:.0f}s", w)
        slow = [(t, s) for t, _, s in self.timings if timing_status("cold", s) == "WARN"]
        for t, s in slow:
            self.report.add(f"8 page {t}", "WARN", f"first render over {COLD_WARN_S:.0f}s", s)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--quick", action="store_true", help="one season, two positions")
    args = ap.parse_args()

    # Quieten Streamlit's "missing ScriptRunContext" chatter when run outside `streamlit run`.
    import logging
    logging.disable(logging.WARNING)

    import sqlalchemy as sa
    from lofc.config import settings
    from lofc.store.load import get_engine
    engine = get_engine()

    with engine.connect() as c:
        all_seasons = [r[0] for r in c.execute(sa.text(
            "SELECT DISTINCT season_id FROM player_metrics_neutral ORDER BY season_id DESC"))]
    live = settings.live_season_id
    data_seasons = [s for s in all_seasons if s in (live, live - 1)] or all_seasons[:2]
    page_season = all_seasons[0]

    from lofc.dashboard.app import POSITION_ORDER

    def expected(sid, pos):
        with engine.connect() as c:
            return c.execute(sa.text("SELECT count(*) FROM player_metrics_neutral "
                                     "WHERE season_id=:s AND position_group=:p AND rankable"),
                             {"s": sid, "p": pos}).scalar() or 0

    seasons = all_seasons[:1] if args.quick else all_seasons
    positions = ["Centre Forward", "Full Back"] if args.quick else POSITION_ORDER

    t_start = time.time()
    s = Smoke(args.quick)
    s.guard("1 pages", s.check_pages)
    s.guard("2 players grid", lambda: s.check_players_grid(seasons, positions, expected))
    s.guard("3 sliders", lambda: s.check_sliders(page_season, OUTFIELD_FIRST))
    s.guard("4 search", lambda: s.check_search(page_season))
    s.guard("5 compare", lambda: s.check_compare(page_season, engine))
    s.guard("6 report", lambda: s.check_report(page_season))
    s.guard("7 data", lambda: s.check_data(engine, data_seasons))
    s.guard("8 timings", lambda: s.check_timings(page_season))

    print()
    print(format_table(s.report.results))
    print(f"\n{len(s.report.results)} checks, {s.report.warnings} warnings, "
          f"total {time.time() - t_start:.0f}s"
          f"{' (quick)' if args.quick else ''}")
    print(summary_line(s.report))
    return exit_code(s.report)


if __name__ == "__main__":
    sys.exit(main())
