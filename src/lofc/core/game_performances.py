"""Game performances (owner 2026-11-23, phase 4): a player's last games -- each game's IMPECT,
Offensive and Defensive IMPECT percentile and level, as in Impect's "Game performances" -- for
the player page, and "Last 5" / "In form" for the Watchlist.

Each percentile is shown as a whole number and the level is worked out from that shown number
(Top above 80, Low below 20), so a dot never reads "20%" while coloured Low. Only games of 45+
minutes are counted; a shorter one is shown hollow. Raw match totals, as in Impect (owner
2026-11-23). MONITORING ONLY: never part of a rating (P11)."""
from __future__ import annotations

import math

import pandas as pd

LAST = 10
MIN_MINUTES = 45
SCORES = ("overall", "performance", "physical", "impect", "offensive", "defensive")
IMPECT_SCORES = ("impect", "offensive", "defensive")
CLUB_SCORES = ("overall", "performance", "physical")
LABELS = {"overall": "Overall", "performance": "Performance", "physical": "Physical",
          "impect": "IMPECT", "offensive": "Offensive", "defensive": "Defensive"}


def _whole(p):
    return None if p is None or pd.isna(p) else int(math.floor(float(p) + 0.5))


def level(p) -> str | None:
    """On the SHOWN whole number: Top above 80, Low below 20, Average between."""
    p = _whole(p) if isinstance(p, float) else p
    if p is None:
        return None
    return "Top" if p > 80 else "Low" if p < 20 else "Average"


def _num(v, dp=2):
    return None if v is None or (isinstance(v, float) and math.isnan(v)) or pd.isna(v) else round(float(v), dp)


def _score(r: dict, s: str) -> dict:
    pct = _whole(r.get(f"{s}_pct"))
    out = {"pct": pct, "level": level(pct)}
    if s in CLUB_SCORES:
        out["value"] = _num(r.get(s))
    return out


def block(games: pd.DataFrame, league_names: dict) -> dict | None:
    """The player page's section from his game rows (player_match_scores joined to
    impect_matches): the last LAST games oldest first, the counts per level over the counted
    ones, and one line saying what the numbers are."""
    if games is None or games.empty:
        return None
    g = games.sort_values("scheduled_at").tail(LAST)
    rows = []
    for r in g.to_dict("records"):
        home = r.get("home_squad_id") == r.get("squad_id")
        mins = r.get("minutes")
        rows.append({"match_id": int(r["match_id"]),
                     "date": pd.Timestamp(r["scheduled_at"]).strftime("%-d %b"),
                     "opponent": r["away_name"] if home else r["home_name"], "home": bool(home),
                     "minutes": None if mins is None or pd.isna(mins) else int(round(mins)),
                     "counted": bool(mins is not None and not pd.isna(mins) and mins >= MIN_MINUTES),
                     "position": r.get("position_group"),
                     "scores": {s: _score(r, s) for s in SCORES}})
    counts = {s: {"Top": 0, "Average": 0, "Low": 0} for s in SCORES}
    for x in rows:
        if x["counted"]:
            for s in SCORES:
                if x["scores"][s]["level"]:
                    counts[s][x["scores"][s]["level"]] += 1
    league = league_names.get(int(g.iloc[-1]["competition_id"]), "his league")
    # each game is measured at the position he played in THAT game
    has_club = any(x["scores"]["overall"]["value"] is not None or x["scores"]["performance"]["value"] is not None
                   for x in rows)
    return {"games": rows, "counts": counts, "labels": LABELS, "has_club": has_club,
            "club_note": (f"Our club formula applied to one game (per 90). Each game: better than X% of games "
                          f"at the position he played, in {league} this season ({MIN_MINUTES}+ minutes). "
                          f"Never changes the ranking."),
            "note": (f"Match totals, as in Impect (not scaled to 90). Each game: better than X% of games "
                     f"at the position he played, in {league} this season ({MIN_MINUTES}+ minutes).")}


def last_five(games: pd.DataFrame, score: str = "impect") -> list:
    """His last five counted games' percentiles (whole numbers), oldest first."""
    if games is None or games.empty:
        return []
    g = games[pd.to_numeric(games["minutes"], errors="coerce").fillna(0) >= MIN_MINUTES]
    g = g.sort_values("scheduled_at").tail(5)
    return [_whole(v) for v in g[f"{score}_pct"]]


def in_form(last: list) -> bool:
    """Top level in 3 or more of his last five counted games."""
    return sum(1 for p in last if level(p) == "Top") >= 3


def load(engine, player_ids, season_id: int) -> pd.DataFrame:
    """Every game row of `player_ids` in `season_id` (any English league), with the fixture."""
    ids = [int(i) for i in player_ids]
    if not ids:
        return pd.DataFrame()
    return pd.read_sql(
        "SELECT s.player_id, s.match_id, s.squad_id, s.competition_id, s.position_group, s.minutes, "
        "s.impect, s.offensive, s.defensive, s.impect_pct, s.offensive_pct, s.defensive_pct, "
        "m.scheduled_at, m.home_squad_id, m.home_name, m.away_name, "
        "c.overall, c.performance, c.physical, c.overall_pct, c.performance_pct, c.physical_pct "
        "FROM player_match_scores s JOIN impect_matches m USING (match_id) "
        "LEFT JOIN player_match_club c ON c.match_id = s.match_id AND c.impect_player_id = s.impect_player_id "
        "WHERE s.season_id = %(s)s AND s.player_id = ANY(%(i)s)",
        engine, params={"s": int(season_id), "i": ids})


# --- the club's per-game scoring: one game's tables, and the workbook (owner 2026-11-23, N21) ---
def _json(v):
    import json
    if isinstance(v, str):
        return json.loads(v)
    return v if isinstance(v, dict) else None


def _formula(m) -> str:
    def side(pairs):
        s = " + ".join(c if sign > 0 else f"- {c}" for c, sign in pairs).replace("+ - ", "- ")
        return f"({s})" if len(pairs) > 1 else s
    return side(m.numer) if m.kind == "rate" else f"{side(m.numer)} / {side(m.denom)}"


def _fmt(v, dp=0) -> str:
    return f"{v:,.{dp}f}"


def detail_tables(row: dict) -> dict:
    """One game's Performance and Physical tables for the player page: every metric of his
    position in the club's order, with the game value, per 90, percentile in the pool of 45+
    minute games, the club's 1-5 band, its weight tier and where it comes from. A metric the
    game has no value for says why; nothing is estimated."""
    from lofc.dashboard.labels import PHYS_COMPARE_LABEL, metric_label
    from lofc.ingest.impect_map import mappable
    from lofc.ingest.skillcorner_map import PER_APPEARANCE, SKILLCORNER_MAP
    from lofc.model import club_framework as cf
    from lofc.model import performance_weights as pw
    from lofc.model import scorecard as sc
    pos = row.get("position_group")
    perf, phys = _json(row.get("perf")) or {}, _json(row.get("phys"))
    pcts = _json(row.get("metric_pcts")) or {}
    imap = {m.name: m for m in mappable()}
    tiers = {m: tier for m, (tier, _w) in (pw.WEIGHTS.get((pos, cf.DEFAULT_ARCHETYPE)) or {}).items()}
    out_perf = []
    for name in sc._resolved_performance(pos) if pos else []:
        m, x = imap.get(name), perf.get(name)
        pct = _whole(pcts.get(name))
        rec = {"metric": name, "label": metric_label(name), "weight": tiers.get(name),
               "source": _formula(m) if m else "", "lower_better": name in cf.LOWER_IS_BETTER,
               "pct": pct, "band": None if pct is None else round(cf.band(pcts[name]), 2),
               "per90": None, "game": None, "out": False}
        if x is None:
            rec.update(game="no data", out=True)
        elif m is not None and m.kind == "ratio":
            if not x.get("d"):
                rec.update(game="none in this game", out=True)
            else:
                rec["game"] = f"{_fmt(x['n'])} of {_fmt(x['d'])} ({x['n'] / x['d'] * 100:.0f}%)"
        else:
            n = float(x.get("n") or 0.0)
            rec["game"] = _fmt(n, 0 if n == int(n) else 2)
            rec["per90"] = _num(x.get("v"))
        if rec["pct"] is None and not rec["out"]:
            rec["band"] = None
        out_perf.append(rec)
    src = {m.name: m.source for m in SKILLCORNER_MAP}
    units = {k: u for k, (_l, u) in PHYS_COMPARE_LABEL.items()}
    out_phys = []
    for name in cf.PHYSICAL_METRICS.get(pos, []) if pos else []:
        label = PHYS_COMPARE_LABEL.get(name, (metric_label(name), ""))[0]
        unit = "km/h" if "km/h" in units.get(name, "") else ("m" if units.get(name, "").startswith("m/") else "")
        pct = _whole(pcts.get(name))
        rec = {"metric": name, "label": label, "source": src.get(name, ""), "pct": pct,
               "band": None if pct is None else round(cf.band(pcts[name]), 2),
               "per90": None, "game": None, "out": False}
        x = (phys or {}).get(name)
        if name == "top5_psv99_kmh":
            rec.update(game="not available per game", out=True)
        elif x is None:
            rec.update(game="no SkillCorner data", out=True)
        else:
            dp = 1 if unit == "km/h" else 0
            rec["game"] = _fmt(float(x["n"]), dp) + (f" {unit}" if unit else "")
            if name in PER_APPEARANCE:
                rec["per90"] = _num(x.get("v"), 0)
        out_phys.append(rec)
    return {"perf": out_perf, "phys": out_phys}


def games_xlsx(games: pd.DataFrame, player_name: str, league: str) -> bytes:
    """Every game this season as a workbook (owner 2026-11-23): sheet "Games" -- one row per
    game: the club scores and Impect's, then each metric's game value, per 90, % and band;
    sheet "Sources" -- each metric's Impect formula or SkillCorner column and its weight."""
    import io

    from openpyxl import Workbook
    from openpyxl.styles import Font
    g = games.sort_values("scheduled_at")
    first = g.iloc[-1].to_dict() if len(g) else {}
    tables = [detail_tables(r) for r in g.to_dict("records")]
    head = ["Date", "Opponent", "H/A", "Minutes", "Position", "Overall", "Overall %", "Performance",
            "Performance %", "Physical", "Physical %", "IMPECT %", "Offensive %", "Defensive %"]
    metrics = []
    for t in tables:
        for kind in ("perf", "phys"):
            for r in t[kind]:
                if r["label"] not in metrics:
                    metrics.append(r["label"])
    for lab in metrics:
        head += [f"{lab} · game", f"{lab} · per 90", f"{lab} · %", f"{lab} · band"]
    wb = Workbook()
    ws = wb.active
    ws.title = "Games"
    ws.append(head)
    for c in ws[1]:
        c.font = Font(bold=True)
    sources = {}
    for r, t in zip(g.to_dict("records"), tables):
        home = r.get("home_squad_id") == r.get("squad_id")
        row = [pd.Timestamp(r["scheduled_at"]).to_pydatetime(), r["away_name"] if home else r["home_name"],
               "H" if home else "A", _num(r.get("minutes"), 0), r.get("position_group")]
        for s in ("overall", "performance", "physical"):
            row += [_num(r.get(s)), _whole(r.get(f"{s}_pct"))]
        row += [_whole(r.get(f"{s}_pct")) for s in IMPECT_SCORES]
        by = {x["label"]: x for kind in ("perf", "phys") for x in t[kind]}
        for lab in metrics:
            x = by.get(lab)
            if x is None:
                row += [None] * 4
                continue
            game = x["game"]
            if isinstance(game, str) and " of " in game and "(" in game:
                game = game.split(" (")[0]
            row += [game, x["per90"], x["pct"], x["band"]]
            sources.setdefault(lab, (("SkillCorner: " if x in t["phys"] else "Impect: ") + x["source"],
                                     x.get("weight") or ("equal" if x in t["phys"] else "")))
        ws.append(row)
        ws.cell(row=ws.max_row, column=1).number_format = "dd mmm yyyy"
    ws.freeze_panes = "C2"
    src = wb.create_sheet("Sources")
    src.append(["Metric", "Source", "Weight"])
    for c in src[1]:
        c.font = Font(bold=True)
    for lab in metrics:
        if lab in sources:
            src.append([lab, *sources[lab]])
    src.append([])
    src.append([f"{player_name} · {league} · per game: the club formula applied to one game; % = vs every "
                f"45+ min game at the position this season. Never changes the ranking."])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def load_club(engine, player_id: int, season_id: int, match_id: int | None = None) -> pd.DataFrame:
    """His games this season with the club's per-game rows in full (metric values, percentiles)
    beside Impect's scores -- for one game's tables or the workbook."""
    sql = ("SELECT s.match_id, s.squad_id, s.competition_id, s.position_group, s.minutes, "
           "s.impect_pct, s.offensive_pct, s.defensive_pct, "
           "m.scheduled_at, m.home_squad_id, m.home_name, m.away_name, "
           "c.overall, c.performance, c.physical, c.overall_pct, c.performance_pct, c.physical_pct, "
           "c.perf, c.phys, c.metric_pcts, pl.player_name "
           "FROM player_match_scores s JOIN impect_matches m USING (match_id) "
           "LEFT JOIN players pl ON pl.player_id = s.player_id "
           "LEFT JOIN player_match_club c ON c.match_id = s.match_id AND c.impect_player_id = s.impect_player_id "
           "WHERE s.season_id = %(s)s AND s.player_id = %(p)s")
    params = {"s": int(season_id), "p": int(player_id)}
    if match_id is not None:
        sql += " AND s.match_id = %(m)s"
        params["m"] = int(match_id)
    return pd.read_sql(sql, engine, params=params)
