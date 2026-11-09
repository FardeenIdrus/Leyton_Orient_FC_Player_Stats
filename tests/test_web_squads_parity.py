"""The web Squads & loans page shows what the Streamlit page shows, on the REAL database
(skipped without one).

Streamlit's page is `tabs/squads.render`, driven here with a recording stand-in for `st` that
answers the widgets (League / Club / Position / Player / Show) and keeps what the page draws:
the four tiles, the table handed to `st.dataframe` and the CSV handed to the download button.
The web page's `/api/squads` must give the same tiles and, cell for cell, the same table, for
the same inputs. Two deliberate differences, both owner rules, are checked rather than skipped:
minutes are whole numbers rounded half-up, and a composite from a peer pool under
MIN_PEERS_FOR_RANKING is never shown (its cell is "—" with the "Not rated: only N ..." note).
"""
import datetime as dt
import io

import pandas as pd
import pytest
from sqlalchemy import create_engine

from lofc.config import settings
from web_fakes import FakeStore, login, make

DASH = "—"

# (label, sidebar filters, page controls)
CASES = [
    ("default", {}, {}),
    ("League Two", {}, {"league": "League Two"}),
    ("Leyton Orient", {}, {"league": "League One", "club": "Leyton Orient"}),
    ("Centre Backs", {}, {"position": "Centre Back"}),
    ("name search", {}, {"q": "smith"}),
    ("on loan only", {}, {"show": "On loan only"}),
    ("loans, League One forwards", {}, {"show": "On loan only", "league": "League One",
                                        "position": "Centre Forward"}),
    ("contract expiring", {}, {"show": "Contract expiring (under 12 months)"}),
    ("sidebar: age + foot", {"max_age": 23, "foot": "Left"}, {}),
    ("sidebar: contract", {"contract_horizon": "Out of contract summer 2027"}, {}),
    ("sidebar: loan now", {"loan": "On loan now"}, {}),
    ("sidebar: leagues", {"leagues": ("League One",)}, {}),
]
IDS = [c[0] for c in CASES]
SHOW_CODE = {"Everyone": None, "On loan only": "loan",
             "Contract expiring (under 12 months)": "expiring"}


def _need_db():
    try:
        create_engine(settings.database_url).connect().close()
    except Exception:
        pytest.skip("no database")


class _Sel:
    def __init__(self, rows):
        self.rows = rows


class _Picked:
    def __init__(self):
        self.selection = _Sel([])


class _Col:
    def __init__(self, rec):
        self.rec = rec

    def selectbox(self, label, options, **kw):
        want = self.rec.controls.get(label.lower())
        self.rec.options[label] = list(options)
        return want if want in options else options[0]

    def text_input(self, label, **kw):
        return self.rec.controls.get("q", "")

    def radio(self, label, options, **kw):
        want = self.rec.controls.get("show")
        return want if want in options else options[0]

    def metric(self, label, value):
        self.rec.metrics.append((label, value))

    def download_button(self, label, data=None, file_name=None, **kw):
        self.rec.download = (label, data, file_name)


class StRecorder:
    """Records what `tabs/squads.render` draws."""

    def __init__(self, controls):
        self.controls = controls
        self.options, self.metrics, self.calls = {}, [], []
        self.table = None
        self.download = None
        from lofc.dashboard.tabs import squads as T
        self.column_config = T.st.column_config      # real config objects (plain dicts)

    def subheader(self, t): self.calls.append(("subheader", t))
    def caption(self, t): self.calls.append(("caption", t))
    def error(self, t): self.calls.append(("error", t))
    def info(self, t): self.calls.append(("info", t))

    def columns(self, spec, **kw):
        return [_Col(self) for _ in range(spec if isinstance(spec, int) else len(spec))]

    def dataframe(self, table, **kw):
        self.table = table.copy()
        return _Picked()


def streamlit_page(sidebar: dict, controls: dict) -> StRecorder:
    """Draw the Streamlit Squads & loans page for these inputs; return the recorder."""
    from lofc.dashboard import loaders as L
    from lofc.dashboard.seasons import season_name_for
    from lofc.dashboard.sidebar_filters import SidebarFilters
    from lofc.dashboard.tabs import squads as T
    seasons = L.available_seasons()
    cur = max(seasons)
    prev = max(s for s in seasons if s < cur)
    rec = StRecorder(controls)
    real = T.st
    T.st = rec
    try:
        T.render(cur, prev, season_name_for(cur), season_name_for(prev), SidebarFilters(**sidebar))
    finally:
        T.st = real
    return rec


def _api_params(sidebar: dict, controls: dict) -> list[tuple[str, str]]:
    q = [(k, str(v)) for k, v in controls.items() if k != "show"]
    if SHOW_CODE.get(controls.get("show")):
        q.append(("show", SHOW_CODE[controls["show"]]))
    for k, v in sidebar.items():
        key = {"contract_horizon": "contract"}.get(k, k)
        q += [(key, x) for x in v] if isinstance(v, tuple) else [(key, str(v))]
    return q


@pytest.fixture(scope="module")
def client():
    _need_db()
    s = FakeStore()
    s.add(username="u", full_name="Ann Scout", role="head_of_recruitment", password="correct-horse-1")
    c, *_ = make(s)
    login(c, "u", "correct-horse-1")
    return c


def _streamlit_text(col: str, v) -> str:
    """The cell as Streamlit draws it: text columns as given; Minutes / Months left typed
    numbers ("%d"); the dates "MMM YYYY"."""
    if v is None or (not isinstance(v, str) and pd.isna(v)) or v == DASH:
        return DASH
    if col in ("Contract to", "Loan ends"):
        return pd.Timestamp(v).strftime("%b %Y")
    if col == "Minutes":
        return f"{int(float(v) + 0.5):,}"            # owner rule: half-up (Streamlit "%d" cut)
    if col == "Months left":
        return str(int(v))
    return str(v)


@pytest.mark.parametrize("label,sidebar,controls", CASES, ids=IDS)
def test_api_equals_streamlit(client, label, sidebar, controls):
    from lofc.core import squads as S
    rec = streamlit_page(sidebar, controls)
    r = client.get("/api/squads", params=_api_params(sidebar, controls))
    assert r.status_code == 200, r.text
    p = r.json()
    assert rec.table is not None, f"{label}: Streamlit drew no table ({rec.calls})"

    # tiles: same labels, same numbers
    assert [(t["label"], t["value"]) for t in p["tiles"]] == rec.metrics

    # the resolved controls and their option lists
    for name, key in (("League", "league"), ("Club", "club"), ("Position", "position")):
        assert p["options"][key] == rec.options[name], name

    # the table: same rows, same order, cell for cell
    keys = [c["key"] for c in p["columns"]]
    assert keys == S.DISPLAY_COLUMNS
    assert len(p["rows"]) == len(rec.table), label
    gated = 0
    for i, (row, (_, want)) in enumerate(zip(p["rows"], rec.table.iterrows())):
        for j, col in enumerate(keys):
            cell, expect = row[j], _streamlit_text(col, want[col])
            if isinstance(cell, dict):                   # a thin pool's composite: withheld
                assert col in ("This season", "Last season", "Also rated"), col
                assert cell["t"] == DASH and cell["note"].startswith("Not rated: only ")
                assert cell["note"].endswith("comparable players (needs 10)")
                gated += expect != DASH          # Streamlit showed a composite here
                continue
            assert cell == expect, (label, i, col, cell, expect)
    # the download: Streamlit's file, with only the withheld composites blanked
    s_label, s_data, s_name = rec.download
    assert p["csv"]["name"] == s_name
    web = pd.read_csv(io.BytesIO(client.get("/api/squads.csv", params=_api_params(
        sidebar, controls)).content), dtype=str, keep_default_na=False)
    old = pd.read_csv(io.BytesIO(s_data), dtype=str, keep_default_na=False)
    assert list(web.columns) == list(old.columns) and len(web) == len(old)
    diff = (web != old)
    assert set(diff.columns[diff.any()]) <= {"This season", "Last season", "Also rated"}
    assert int(diff.to_numpy().sum()) == gated
    # a withheld composite is "—", or empty in a column the export rounds (as Streamlit's blanks)
    assert set(web.to_numpy()[diff.to_numpy()]) <= {DASH, ""}


def test_withheld_composites_are_exactly_the_thin_pools(client):
    """Every "Not rated" cell is a pool under MIN_PEERS_FOR_RANKING, with its real size."""
    from lofc.core import squads as S
    from lofc.dashboard import loaders as L
    from lofc.model.scorecard import MIN_PEERS_FOR_RANKING, peer_pool_sizes
    seasons = L.available_seasons()
    cur = max(seasons)
    prev = max(s for s in seasons if s < cur)
    sizes = {**peer_pool_sizes(S.season_scorecards(cur)), **peer_pool_sizes(S.season_scorecards(prev))}
    thin = {k: v for k, v in sizes.items() if v < MIN_PEERS_FOR_RANKING}
    p = client.get("/api/squads").json()
    notes = {c["note"] for row in p["rows"] for c in row if isinstance(c, dict)}
    assert notes, "no thin-pool composite in the squad list (data changed?)"
    assert notes <= {f"Not rated: only {n} comparable players (needs 10)" for n in thin.values()}


def test_row_links_are_streamlits_click_targets(client):
    """A row opens the card where Streamlit's click would have opened the player
    (`best_profile_target` of `player_rated_rows`), and the two click messages fall on the
    same rows as Streamlit's."""
    from lofc.dashboard.tabs import squads as T
    for params in ([], [("league", "League Two")], [("show", "loan")]):
        p = client.get("/api/squads", params=params).json()
        pids = p["player_ids"]
        checked = 0
        for i, pid in enumerate(pids):
            if i % 25:
                continue
            link, msg = p["links"][i], p["messages"][i]
            if pid is None:
                assert link is None and msg and "no performance record" in msg
                continue
            target = T.best_profile_target(T.player_rated_rows(int(pid)))
            if target is None:
                assert link is None and msg and "no rating" in msg
            else:
                assert link == f"/player/{int(pid)}/{target[0]}/{target[1]}" and msg is None
            checked += 1
        assert checked > 5


def test_streamlit_page_is_unchanged_by_the_extraction():
    """The page drawn after moving its logic into `core/squads.py` is the page drawn before it:
    a snapshot taken from the original module (scratch, before the move) is compared when it
    exists; otherwise this only checks the page draws."""
    import json
    import os
    snap = os.environ.get("LOFC_SQUADS_SNAPSHOT")
    _need_db()
    for label, sidebar, controls in CASES:
        rec = streamlit_page(sidebar, controls)
        assert rec.table is not None, label
        if snap and os.path.exists(snap):
            want = json.load(open(snap))[label]
            got = snapshot_of(rec)
            assert got == want, label


def snapshot_of(rec: StRecorder) -> dict:
    t = rec.table.astype(object).where(rec.table.notna(), None)
    return {"metrics": [list(m) for m in rec.metrics], "options": rec.options,
            "calls": [list(c) for c in rec.calls],
            "table": [[None if v is None else str(v) for v in row] for row in t.itertuples(index=False)],
            "columns": list(rec.table.columns),
            "download": [rec.download[0], rec.download[1].decode("utf-8"), rec.download[2]]}
