"""The web Scout reports and Watchlist pages show Streamlit's numbers, on the REAL database
(skipped without one). Read-only: nothing is written.

The Streamlit side is the real page code (`tabs/scout_reports.render`, `tabs/watchlist._watchlist`)
run against a recording stand-in for `st`, so what is compared is exactly what Streamlit draws:
the tables, captions, tab labels, counts and the CSV download. The one intended difference is the
honesty rule (owner D1): a last-season rating from a peer pool below MIN_PEERS_FOR_RANKING is
withheld on the web page, and those rows are checked against the player card's own verdict."""
import types

import pandas as pd
import pytest
from sqlalchemy import create_engine

from lofc.config import settings

SR_CASES = {
    "default": {},
    "league": {"League": "League One"},
    "verdict": {"Verdict": "Sign"},
    "disagree": {"Data vs scout": "Data disagrees"},
    "no rating": {"Data vs scout": "No rating"},
    "search": {"Search for a player": "an"},
    "age + foot": {"Max age": 24, "Foot": "Left"},
    "not ours": {"Our data": "Not in our data"},
    "ours + position": {"Our data": "In our data", "Position": "CM"},
    "seen live": {"Seen": "Live"},
}
# widget label -> web query key
WEB_KEY = {"Search for a player": "q", "League": "league", "Max age": "max_age", "Foot": "foot",
           "Scout": "scout", "Verdict": "verdict", "Grade": "grade", "Position": "position",
           "Club": "club", "Seen": "seen", "Our data": "data", "Data vs scout": "dvs"}


@pytest.fixture(scope="module")
def engine():
    try:
        e = create_engine(settings.database_url)
        e.connect().close()
    except Exception:
        pytest.skip("no database")
    return e


class _Ctx:
    def __init__(self, f):
        self.f = f

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def __getattr__(self, n):
        return getattr(self.f, n)


class _Sel:
    selection = types.SimpleNamespace(rows=[])

    def get(self, k, d=None):
        return {"selection": {"rows": []}}.get(k, d)


class FakeSt:
    """Records what a Streamlit page draws; widgets return `picks` (else their default)."""

    def __init__(self, picks=None):
        self.picks, self.log, self.session_state = picks or {}, [], {}

    def _r(self, *a):
        self.log.append(a)

    def subheader(self, t): self._r("subheader", t)
    def info(self, t): self._r("info", t)
    def warning(self, t): self._r("sync", t)
    def error(self, t): self._r("error", t)
    def caption(self, t): self._r("caption", t)
    def markdown(self, t, **k): self._r("markdown", t)
    def metric(self, label, value, **k): self._r("metric", label, value)
    def columns(self, spec, **k): return [_Ctx(self) for _ in range(spec if isinstance(spec, int) else len(spec))]
    def tabs(self, labels): self._r("tabs", list(labels)); return [_Ctx(self) for _ in labels]
    def button(self, *a, **k): return False
    def text_input(self, label, **k): return self.picks.get(label, "")
    def number_input(self, label, **k): return self.picks.get(label, k.get("value"))
    def selectbox(self, label, options, **k): return self.picks.get(label, list(options)[0])
    def multiselect(self, label, options, default=None, **k): return self.picks.get(label, default)
    def dataframe(self, frame, **k): self._r("dataframe", frame.copy(), k.get("key")); return _Sel()
    def download_button(self, label, data=None, **k): self._r("download", data)
    def rerun(self): pass

    class column_config:
        TextColumn = ProgressColumn = LinkColumn = staticmethod(lambda *a, **k: None)

    def get(self, kind, key=None):
        return [x for x in self.log if x[0] == kind and (key is None or x[2] == key)]


def _streamlit_scout(monkeypatch, picks):
    from lofc.core import scout_reports_page as sp
    from lofc.dashboard import loaders as L
    from lofc.dashboard.seasons import season_name_for
    from lofc.dashboard.tabs import scout_reports as sr
    f = FakeSt(picks)
    monkeypatch.setattr(sr, "st", f)
    prev, _ = sp.rating_seasons(L.available_seasons())
    sr.render(prev, season_name_for(prev))
    return f


def _web_query(picks):
    return {WEB_KEY[label]: str(v) for label, v in picks.items()}


# a report's identity in a shown table (Streamlit's table has no id column)
_KEY = ["Watched", "Player", "Fixture", "Club", "Position", "Scout", "Seen", "Grade", "Verdict"]


def _key(cells):
    return tuple(str(cells[c]).strip() or "—" for c in _KEY)


@pytest.fixture(scope="module")
def thin(engine):
    """{row key: web row} for the reports whose last-season rating the web page withholds --
    each checked against the card: for that league-season it says not rated, pool below 10."""
    from lofc.core import card as card_core
    from lofc.model.scorecard import MIN_PEERS_FOR_RANKING
    from lofc.web.api import scout_reports as api
    b = api._bundle()
    f = b["frame"]
    note = f["Data vs scout"].astype(str).str.startswith("Not rated: only")
    prev, _ = api._seasons()
    for _, r in f[note].iterrows():
        row, _lens, reason = card_core.card_row(int(r["player_id"]), int(r["rated_in"]), prev)
        assert row is not None and reason != "ok"
        assert row["peer_count"] < MIN_PEERS_FOR_RANKING
    web = api.page_json({})["rows"]
    out = {_key(w["cells"]): w for w in web if w["cells"]["Data vs scout"].startswith("Not rated: only")}
    assert len(out) == int(note.sum())
    return out


@pytest.mark.parametrize("case", list(SR_CASES), ids=list(SR_CASES))
def test_scout_rows_are_streamlits(monkeypatch, engine, thin, case):
    """Every row and cell equals Streamlit's, in the same order; the withheld thin-pool rows
    differ only in Rating (blank) and Data vs scout (the note), which can move them between
    the "Average rating" and "No rating" filter groups."""
    from lofc.web.api import scout_reports as api
    picks = SR_CASES[case]
    st_log = _streamlit_scout(monkeypatch, picks)
    shown = st_log.get("dataframe", "scout_all")[0][1].to_dict("records")
    web = api.page_json(_web_query(picks))
    st_rows = [s for s in shown if _key(s) not in thin]
    web_rows = [w for w in web["rows"] if _key(w["cells"]) not in thin]
    assert len(web_rows) == len(st_rows)
    for w, s in zip(web_rows, st_rows):
        for col in api.COLUMNS:
            assert w["cells"][col] == (str(s[col]).strip() or "—"), (case, col)
    for s in shown:                                  # Streamlit shows the thin rating
        if _key(s) in thin:
            assert s["Rating"] != "—"
    for w in web["rows"]:
        if _key(w["cells"]) in thin:
            assert w["cells"]["Rating"] == "—"
    caption = next(x[1] for x in st_log.get("caption") if "reports ·" in str(x[1]))
    st_n = int(caption.split(" of ")[0].replace(",", ""))
    moved = len(web["rows"]) - len(web_rows) - (len(shown) - len(st_rows))
    assert len(web["rows"]) == st_n + moved
    assert web["caption"].split(" of ", 1)[1] == caption.split(" of ", 1)[1]
    assert [t["label"] for t in web["tabs"]] == st_log.get("tabs")[0][1]


def test_scout_disagree_and_activity_are_streamlits(monkeypatch, engine, thin):
    from lofc.web.api import scout_reports as api
    st_log = _streamlit_scout(monkeypatch, {})
    st_dis = st_log.get("dataframe", "scout_disagree")[0][1].reset_index(drop=True)
    web = api.page_json({"tab": "disagree"})
    assert len(web["rows"]) == len(st_dis)
    for w, s in zip(web["rows"], st_dis.to_dict("records")):
        assert w["cells"]["Data vs scout"] == s["Data vs scout"]
        assert w["cells"]["Rating"] == str(s["Rating"])
    act = st_log.get("dataframe", "scout_activity")[0][1]
    web_act = api.page_json({"tab": "activity"})["activity"]
    assert web_act["columns"] == list(act.columns)
    assert web_act["rows"] == [list(r) for r in act.itertuples(index=False)]


def test_scout_open_targets_are_the_streamlit_button(engine):
    """Every linked player's name opens the card the Streamlit "Open … in Players" button opens."""
    from lofc.dashboard.tabs.squads import best_profile_target, player_rated_rows
    from lofc.web.api import scout_reports as api
    b = api._bundle()
    ids = sorted(b["frame"]["player_id"].dropna().astype(int).unique().tolist())
    assert len(ids) > 50
    for pid in ids:
        assert b["targets"].get(pid) == best_profile_target(player_rated_rows(pid)), pid


def test_scout_detail_is_the_report(engine):
    from lofc.dashboard.tabs import scout_reports as sr
    from lofc.web.api import scout_reports as api
    frame = api._bundle()["frame"]
    for _, row in frame.head(80).iterrows():
        d = api.detail_json(str(row["submission_id"]))
        assert d["card"]["body"] == ("" if pd.isna(row["comments"]) else row["comments"])
        assert d["card"]["player"] == row["player_name"]
        html = sr.report_card_html(row)
        assert d["card"]["accent"] in html


# --- watchlist ---------------------------------------------------------------------------------
def _streamlit_watch(monkeypatch, money, picks=None):
    from lofc.dashboard.tabs import watchlist as wl
    f = FakeSt(picks)
    monkeypatch.setattr(wl, "st", f)
    wl._watchlist(_Ctx(f), money)
    return f


@pytest.mark.parametrize("money", [False, True], ids=["plain", "market value"])
def test_watchlist_is_streamlits(monkeypatch, engine, money):
    from lofc.model import assessment_status as AS
    from lofc.web.api import watchlist as api
    st_log = _streamlit_watch(monkeypatch, money)
    web = api.page_json(list(AS.STATUSES), money)
    if web["empty"]:
        pytest.skip("watchlist is empty in this database")
    frame = st_log.get("dataframe")[0][1].reset_index(drop=True)
    assert web["columns"] == list(frame.columns)
    assert [(t["label"], t["value"]) for t in web["tiles"]] == [x[1:] for x in st_log.get("metric")]
    assert len(web["rows"]) == len(frame)
    for w, s in zip(web["rows"], frame.to_dict("records")):
        if w["not_rated"]:
            continue                                     # D1: withheld on the web only
        for col in frame.columns:
            if col in ("Composite", "Performance", "Physical"):
                v = s[col]
                assert w["cells"][col] == ("—" if v == "—" or pd.isna(v) else f"{float(v):.2f}"), col
            elif col == "Note":
                assert w["note"] == s[col]
            elif col == "Transfermarkt":
                assert (w["tm"] or "") == s[col]
            else:
                assert w["cells"][col] == str(s[col]), col
    # the CSV is Streamlit's download, byte for byte, when nobody's rating is withheld
    if not any(r["not_rated"] for r in web["rows"]):
        state, _src, _df, wframe, *_ = api.build(list(AS.STATUSES), money)
        assert wframe.drop(columns=[c for c in ("thin_n",) if c in wframe.columns]).to_csv(
            index=False).encode("utf-8") == st_log.get("download")[0][1]


def test_watchlist_status_filter_is_streamlits(monkeypatch, engine):
    from lofc.model import assessment_status as AS
    from lofc.web.api import watchlist as api
    for chosen in ([AS.NOT_ASSESSED], [AS.SIGNED_OFF], []):
        st_log = _streamlit_watch(monkeypatch, False, {"Assessment status": chosen})
        web = api.page_json(chosen, False)
        if web["empty"]:
            pytest.skip("watchlist is empty in this database")
        frames = st_log.get("dataframe")
        if not frames:
            assert web["rows"] == [] and web["none_match"] == st_log.get("info")[0][1]
        else:
            assert [r["cells"]["Player"] for r in web["rows"]] == list(frames[0][1]["Player"])
