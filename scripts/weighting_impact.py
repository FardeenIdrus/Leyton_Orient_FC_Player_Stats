"""Rating weights change: Performance 57% -> 65%, Physical 43% -> 35% (outfield; owner 2026-11-16).

READ-ONLY. Compares the Overall stored today with the new Overall recomputed in memory from the
same stored Performance and Physical scores, and writes an Excel workbook to STDOUT. Run it on
the server BEFORE the rescore, so "current" is what the live site shows:

    ssh root@165.22.122.157 "docker compose -f /opt/lofc/docker-compose.prod.yml exec -T app python -" \\
        < scripts/weighting_impact.py > ~/Desktop/Rating_weights_65_35_impact.xlsx

The club document writes the outfield weights as Performance 0.40 and Physical 0.30 of a 0.70
share; divided by 0.70 that is 57% / 43%. The new split keeps the same 0.70: 0.455 / 0.245 =
65% / 35%. The report only ever shows the percentages.

Self-contained on purpose (weights written here, not read from the deployed code), so it gives
the same answer before and after deploy. The current recompute equals the stored Overall for
every possible pair of 2-dp scores (tests/test_weighting_impact.py) and the Summary re-checks it
on the live rows.

Sheets: Summary (one row per league) · one sheet per league (biggest risers and fallers) ·
Leyton Orient. Season: the current one. Only the .xlsx goes to stdout; anything printed while it
runs goes to stderr.
"""
from __future__ import annotations

import io
import sys
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Callable

import pandas as pd

OLD = (0.40, 0.30)      # current outfield Performance : Physical = 57% : 43%
NEW = (0.455, 0.245)    # new = 65% : 35% (owner 2026-11-16)
MIN_PEERS = 10          # scorecard.MIN_PEERS_FOR_RANKING
CLUB_STANDARD = 3.00
TOP_N = 15
KEY3 = ["competition_id", "season_id", "position_group"]
LEAGUES = ["League One", "League Two", "Championship", "National League",
           "Scottish Premiership", "Scottish Championship", "Irish Premier Division"]
CUR = "Current Overall (57/43)"
NEW_COL = "New Overall (65/35)"
CHANGE = "Change"
WEIGHTS_LINE = ("Rating weights change for outfield players: Performance 57% \u2192 65%, "
                "Physical 43% \u2192 35%. Goalkeepers: unchanged (Performance only).")


# --- the arithmetic -------------------------------------------------------------------------------
def _round2(value: float) -> float:
    """Two decimals, exact halves up (scorecard._round2)."""
    return float(Decimal(f"{value:.9f}").quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _missing(v) -> bool:
    return v is None or bool(pd.isna(v))


def composite(perf, phys, split) -> float | None:
    """Overall from the two stored bands: weighted by `split`, over the bands present (a player
    with no Physical -- every goalkeeper -- is rated on Performance alone)."""
    wp, wh = split
    have = [(float(perf), wp)] if not _missing(perf) else []
    if not _missing(phys):
        have.append((float(phys), wh))
    if not have:
        return None
    return _round2(sum(b * w for b, w in have) / sum(w for _b, w in have))


def compare(cards: pd.DataFrame, neutral: pd.DataFrame) -> pd.DataFrame:
    """One row per stored "All Metrics" scorecard with an Overall: current (57/43) and new
    (65/35) Overall, the change, whether the current recompute equals the stored value, whether he is
    rated (pool of MIN_PEERS+) and his rank in his league + position before and after."""
    f = cards.copy()
    if "archetype" in f.columns:
        f = f[f["archetype"] == "All Metrics"]
    f = f[f["objective_composite"].notna()].copy()
    keys = ["player_id", "competition_id", "season_id"]
    f = f.merge(neutral[keys + ["minutes", "team_name", "player_name"]].drop_duplicates(keys),
                on=keys, how="left")
    f["old"] = [composite(p, h, OLD) for p, h in zip(f["performance_band"], f["physical_band"])]
    f["new"] = [composite(p, h, NEW) for p, h in zip(f["performance_band"], f["physical_band"])]
    f["change"] = (f["new"] - f["old"]).round(2)
    f["stored_matches"] = (f["old"] - f["objective_composite"]).abs() < 1e-9
    size = f.groupby(KEY3)["player_id"].transform("count")
    if "peer_pool_size" in f.columns:
        size = pd.to_numeric(f["peer_pool_size"], errors="coerce").fillna(size)
    scope = f["peer_pool"].fillna("position") if "peer_pool" in f.columns else "position"
    f["pool"] = size.astype(int)
    f["rated"] = size >= MIN_PEERS
    f["rankable"] = f["rated"] & (scope != "midfield")
    for col in ("old", "new"):
        r = f[f["rankable"]].groupby(KEY3)[col].rank(ascending=False, method="min")
        f[f"{col}_rank"] = r.reindex(f.index)
    return f.reset_index(drop=True)


def league_summary(frame: pd.DataFrame, season: int, leagues: dict) -> list[dict]:
    """One row per listed league (current season, rated players), then every league together."""
    f = frame[(frame["season_id"] == season) & frame["rated"]]
    by_name = {v: k for k, v in leagues.items()}

    def row(name, g):
        ch = g["change"]
        return {"League": name, "Rated players": int(len(g)),
                "Rose": int((ch > 0).sum()), "Fell": int((ch < 0).sum()),
                "Moved 0.10 or more": int((ch.abs() >= 0.10 - 1e-9).sum()),
                "Moved 0.25 or more": int((ch.abs() >= 0.25 - 1e-9).sum()),
                "Rose to 3.00 or above": int(((g["old"] < CLUB_STANDARD) & (g["new"] >= CLUB_STANDARD)).sum()),
                "Fell below 3.00": int(((g["old"] >= CLUB_STANDARD) & (g["new"] < CLUB_STANDARD)).sum()),
                "Biggest rise": float(ch.max()) if len(g) and ch.max() > 0 else None,
                "Biggest fall": float(ch.min()) if len(g) and ch.min() < 0 else None,
                "Note": ("No physical data: no change"
                         if len(g) and g["physical_band"].isna().all() else None)}

    out = [row(n, f[f["competition_id"] == by_name[n]] if n in by_name else f.iloc[0:0])
           for n in LEAGUES]
    out.append(row(f"All {f['competition_id'].nunique()} leagues", f))
    return out


def _rank(v):
    return None if _missing(v) else int(v)


def _player_row(r: dict) -> dict:
    rated = bool(r.get("rated"))
    return {"Player": r.get("player_name"), "Club": r.get("team_name"),
            "Position": r["position_group"],
            "Minutes": None if _missing(r.get("minutes")) else round(float(r["minutes"])),
            "Performance": r["performance_band"],
            "Physical": None if _missing(r["physical_band"]) else r["physical_band"],
            CUR: r["old"] if rated else None, NEW_COL: r["new"] if rated else None,
            CHANGE: r["change"] if rated else None,
            "Rank now": _rank(r.get("old_rank")), "Rank new": _rank(r.get("new_rank")),
            "Players in position": int(r["pool"])}


def movers(frame: pd.DataFrame, season: int, competition_id: int, rising: bool) -> list[dict]:
    f = frame[(frame["season_id"] == season) & (frame["competition_id"] == competition_id)
              & frame["rated"]]
    f = f[f["change"] > 0] if rising else f[f["change"] < 0]
    f = f.sort_values(["change", "new"], ascending=[not rising, False]).head(TOP_N)
    return [_player_row(r) for r in f.to_dict("records")]


def orient_rows(frame: pd.DataFrame, squad: pd.DataFrame, season: int, leagues: dict) -> list[dict]:
    """Every current Orient player's rows this season (any league), A-Z."""
    out = []
    for s in squad.sort_values("player_name").itertuples():
        mine = frame[(frame["player_id"] == int(s.player_id)) & (frame["season_id"] == season)]
        if mine.empty:
            out.append({"Player": s.player_name, "Position": s.position_group,
                        "Note": "No rating this season"})
            continue
        for r in mine.sort_values("minutes", ascending=False).to_dict("records"):
            row = _player_row(r)
            row["League"] = leagues.get(int(r["competition_id"]), str(r["competition_id"]))
            row["Note"] = None
            if not r["rated"]:
                row["Note"] = f"Not rated: only {int(r['pool'])} in his position"
            elif not r["rankable"]:
                row["Note"] = "Rated against all midfielders (no rank)"
            out.append(row)
    return out


# --- the workbook ---------------------------------------------------------------------------------
RATING_COLS = {"Performance", "Physical", CUR, NEW_COL}
CHANGE_COLS = {CHANGE, "Biggest rise", "Biggest fall"}
PLAYER_HEAD = ["Player", "Club", "Position", "Minutes", "Performance", "Physical", CUR, NEW_COL,
               CHANGE, "Rank now", "Rank new", "Players in position"]
WIDTH = {"Player": 26, "Club": 24, "League": 22, "Position": 20, "Note": 40}


def _style():
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    return {"title": Font(bold=True, size=14), "sub": Font(italic=True, color="5D6470"),
            "section": Font(bold=True, size=12), "head": Font(bold=True, color="FFFFFF"),
            "head_fill": PatternFill("solid", fgColor="15171C"),
            "total": Font(bold=True), "wrap": Alignment(wrap_text=True, vertical="center",
                                                         horizontal="center"),
            "line": Border(bottom=Side(style="thin", color="D5D8DD")),
            "up": Font(color="1E7B34", bold=True), "down": Font(color="B3261E", bold=True)}


def _lines(ws, row: int, title: str, subs: list[str]) -> int:
    st = _style()
    ws.cell(row, 1, title).font = st["title"]
    for i, t in enumerate(subs, 1):
        ws.cell(row + i, 1, t).font = st["sub"]
    return row + len(subs) + 2


def _table(ws, start: int, headers: list[str], rows: list[dict], title: str | None = None,
           empty: str = "None", bold_last: bool = False) -> int:
    st = _style()
    r = start
    if title:
        ws.cell(r, 1, title).font = st["section"]
        r += 1
    for c, h in enumerate(headers, 1):
        cell = ws.cell(r, c, h)
        cell.font, cell.fill, cell.alignment = st["head"], st["head_fill"], st["wrap"]
    ws.row_dimensions[r].height = 32
    if not rows:
        ws.cell(r + 1, 1, empty).font = st["sub"]
        r += 1
    for k, row in enumerate(rows):
        r += 1
        for c, h in enumerate(headers, 1):
            v = row.get(h)
            if v is not None and not isinstance(v, str) and pd.isna(v):
                v = None
            cell = ws.cell(r, c, "\u2014" if v is None and h not in ("Note",) else v)
            cell.border = st["line"]
            if bold_last and k == len(rows) - 1:
                cell.font = st["total"]
            if v is None:
                continue
            if h in RATING_COLS:
                cell.number_format = "0.00"
            elif h in CHANGE_COLS:
                cell.number_format = "+0.00;-0.00;0.00"
                if v != 0:
                    cell.font = st["up"] if v > 0 else st["down"]
            elif h == "Minutes":
                cell.number_format = "#,##0"
    for c, h in enumerate(headers, 1):
        letter = ws.cell(1, c).column_letter
        ws.column_dimensions[letter].width = max(ws.column_dimensions[letter].width or 0,
                                                 WIDTH.get(h, 13))
    return r + 3


def workbook(frame, squad, leagues, season_names) -> bytes:
    from openpyxl import Workbook
    season = int(frame["season_id"].max())
    sname = season_names.get(season, str(season))
    by_name = {v: k for k, v in leagues.items()}
    every = frame[frame["season_id"] == season]
    wb = Workbook()

    ws = wb.active
    ws.title = "Summary"
    nxt = _lines(ws, 1, f"Rating weights change \u2014 impact by league, {sname}", [
        WEIGHTS_LINE,
        "Rated players only (10+ in their league and position). Change = new Overall \u2212 current Overall.",
        "Each league is rated within itself, so the numbers compare players inside a league, not across leagues."])
    summ = league_summary(frame, season, leagues)
    nxt = _table(ws, nxt, list(summ[0].keys()), summ, bold_last=True)
    ws.cell(nxt - 1, 1, (f"Check: the current Overall recomputed from the stored scores matches the live site "
                         f"for {int(every['stored_matches'].sum()):,} of {len(every):,} players.")).font = _style()["sub"]
    ws.column_dimensions["A"].width = 26

    for name in LEAGUES:
        sh = wb.create_sheet(name[:31])
        cid = by_name.get(name)
        nxt = _lines(sh, 1, f"{name} \u2014 {sname}", [
            WEIGHTS_LINE,
            "Rank = rank in his position in this league (1 = best). \u2014 = no rank (thin or shared pool)."])
        if cid is None:
            sh.cell(nxt, 1, "No data for this league.")
            continue
        nxt = _table(sh, nxt, PLAYER_HEAD, movers(frame, season, cid, True),
                     title=f"Biggest risers (top {TOP_N})", empty="Nobody rose.")
        _table(sh, nxt, PLAYER_HEAD, movers(frame, season, cid, False),
               title=f"Biggest fallers (top {TOP_N})", empty="Nobody fell.")
        sh.freeze_panes = "B1"

    sh = wb.create_sheet("Leyton Orient")
    nxt = _lines(sh, 1, f"Leyton Orient squad \u2014 {sname}", [
        WEIGHTS_LINE, "Each player in the league he played in this season; ranks within that league."])
    _table(sh, nxt, ["Player", "League", "Club", "Position", "Minutes", "Performance", "Physical",
                     CUR, NEW_COL, CHANGE, "Rank now", "Rank new", "Players in position", "Note"],
           orient_rows(frame, squad, season, leagues))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# --- sources --------------------------------------------------------------------------------------
@dataclass
class Sources:
    cards: Callable[[], pd.DataFrame]
    neutral: Callable[[list], pd.DataFrame]
    squad: Callable[[], pd.DataFrame]
    league_names: Callable[[], dict]
    season_name: Callable[[int], str]


def live_sources() -> Sources:
    from sqlalchemy import text
    from lofc.store.load import get_engine
    engine = get_engine()

    def cards():
        return pd.read_sql(text("SELECT * FROM player_scorecards WHERE archetype = 'All Metrics'"), engine)

    def neutral(seasons):
        return pd.read_sql(text("SELECT player_id, competition_id, season_id, minutes, team_name, player_name "
                                "FROM player_metrics_neutral WHERE season_id = ANY(:s)"),
                           engine, params={"s": [int(s) for s in seasons]})

    def squad():
        from lofc.core.squad import squad as load
        return load()

    def league_names():
        from lofc.leagues import league_names as ln
        return ln()

    def season_name(s):
        from lofc.dashboard.seasons import season_name_for
        return season_name_for(s)

    return Sources(cards, neutral, squad, league_names, season_name)


def build(src: Sources) -> bytes:
    cards = src.cards()
    seasons = sorted({int(s) for s in cards["season_id"].unique()})
    frame = compare(cards, src.neutral(seasons))
    names = {s: src.season_name(s) for s in seasons}
    return workbook(frame, src.squad(), src.league_names(), names)


def main(src: Sources | None = None, out=None, err=None) -> None:
    """The .xlsx bytes to `out` (stdout's binary stream) and nothing else: while it runs, text
    printed by anything goes to `err` (stderr)."""
    out = out if out is not None else sys.stdout.buffer
    err = err if err is not None else sys.stderr
    real = sys.stdout
    sys.stdout = err
    try:
        data = build(src if src is not None else live_sources())
    finally:
        sys.stdout = real
    out.write(data)
    out.flush()


if __name__ == "__main__":
    main()
