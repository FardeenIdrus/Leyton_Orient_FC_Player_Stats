"""Per-game club scoring (owner 2026-11-23, N21): the club's own Performance / Physical /
Overall formula -- the one that ranks players over a season (`scorecard.build_scorecards`) --
applied to ONE game, so staff can see and check each game on the club's terms.

Inputs per game: Impect's per-match KPIs (game totals; `/matches/{id}/player-kpis`) and
SkillCorner's per-match physical row (`get_physical` without group_by). Each metric is built
exactly as the season metric is (`impect_map`, `skillcorner_map`), but from one game:
  - a rate is per 90 of that game's minutes;
  - a ratio uses that game's counts; with nothing to divide by (no aerial duels) it is left
    out of that game's rating, never estimated;
  - a physical metric SkillCorner has no per-game value for (top-5 peak speed) is left out.
Every game of 45+ minutes at a position, in one league season, is the pool: each metric's
percentile within it (mid-rank, as in the season scoring), the club's 1-5 band, its weights,
Overall = Performance 65 : Physical 35. A game under 45 minutes keeps its values, no rating.

DISPLAY ONLY: nothing here feeds the ranking or any season rating (register P11)."""
from __future__ import annotations

import pandas as pd

from lofc.ingest.impect_map import IMPECT_POSITION_GROUPS, mappable
from lofc.ingest.skillcorner_map import MINUTES_PER_APPEARANCE, PER_APPEARANCE, SKILLCORNER_MAP
from lofc.model import club_framework as cf
from lofc.model import scorecard as sc

MIN_MINUTES = 45
KEY = sc.KEY


def _perf_metrics() -> list[str]:
    seen: list[str] = []
    for pos in cf.PERFORMANCE_METRICS:
        for m in sc._resolved_performance(pos):
            if m not in seen:
                seen.append(m)
    return seen


_MAP = {m.name: m for m in mappable()}
# every stored metric any position's Performance reads, that Impect can build
PERF_METRICS: list[str] = [m for m in _perf_metrics() if m in _MAP]
_SC_SOURCE = {m.name: m.source for m in SKILLCORNER_MAP}
PHYS_METRICS: list[str] = list(cf.PHYSICAL_METRICS["Central Mid"])


def parse_player_kpis(payload: dict, kpi_names: dict) -> pd.DataFrame:
    """One match's player-kpis -> one row per player: every KPI summed over the positions he
    played (Impect lists only the KPIs he registered), minutes summed, his position = the one
    he played longest."""
    recs = []
    for side in ("squadHome", "squadAway"):
        squad = payload.get(side) or {}
        for p in squad.get("players") or []:
            k = {}
            for x in p.get("kpis") or []:
                name = kpi_names.get(x.get("kpiId"))
                if name and x.get("value") is not None:
                    k[name] = float(x["value"])
            recs.append({"impect_player_id": int(p["id"]), "squad_id": squad.get("id"),
                         "position": p.get("position"), "seconds": float(p.get("playDuration") or 0.0),
                         "kpis": k})
    cols = ["match_id", "impect_player_id", "squad_id", "position_group", "minutes", "kpis"]
    if not recs:
        return pd.DataFrame(columns=cols)
    out = []
    for pid, grp in pd.DataFrame(recs).groupby("impect_player_id", sort=False):
        main = grp.sort_values("seconds", ascending=False).iloc[0]
        total: dict = {}
        for k in grp["kpis"]:
            for name, v in k.items():
                total[name] = total.get(name, 0.0) + v
        out.append({"match_id": int(payload.get("matchId")), "impect_player_id": int(pid),
                    "squad_id": main["squad_id"], "position_group": IMPECT_POSITION_GROUPS.get(main["position"]),
                    "minutes": round(grp["seconds"].sum() / 60.0, 1), "kpis": total})
    return pd.DataFrame(out, columns=cols)


def _sum(kpis: dict, pairs) -> float:
    return float(sum(sign * float(kpis.get(col, 0.0)) for col, sign in pairs))


def impect_game_metrics(kpis: dict, minutes: float) -> dict:
    """{metric: {"v": value used for scoring, "n": game total (numerator), "d": denominator or
    None}} for every Performance metric. A KPI Impect did not list counts as 0 (none
    happened); a ratio with a zero denominator has v None (left out)."""
    out = {}
    for name in PERF_METRICS:
        m = _MAP[name]
        n = _sum(kpis, m.numer)
        if m.kind == "ratio":
            d = _sum(kpis, m.denom)
            out[name] = {"v": (n / d if d > 0 else None), "n": n, "d": d}
        else:
            out[name] = {"v": (n / minutes * 90.0 if minutes and minutes > 0 else None), "n": n, "d": None}
    return out


def physical_game_metrics(row: dict) -> dict | None:
    """One SkillCorner per-match row -> the club's Physical metrics for that game (volumes per
    90 of SkillCorner's own minutes, peak speed as measured). None when SkillCorner flags the
    game as failing its physical check. A metric with no per-game column is left out."""
    if not row.get("physical_check_passed", True):
        return None
    mins = row.get(MINUTES_PER_APPEARANCE)
    out = {}
    for name in PHYS_METRICS:
        col = _SC_SOURCE.get(name)
        val = row.get(col) if col else None
        if val is None or pd.isna(val):
            continue
        val = float(val)
        if name in PER_APPEARANCE:
            out[name] = {"v": (val / float(mins) * 90.0 if mins and mins > 0 else None), "n": val, "d": None}
        else:
            out[name] = {"v": val, "n": val, "d": None}
    return out or None


def score_games(games: pd.DataFrame) -> pd.DataFrame:
    """Rate every game in `games` (rows: competition_id, season_id, position_group, minutes,
    perf {metric: {"v",...}}, phys {...} or None) on the club framework, within each league
    season + position's pool of 45+ minute games. Returns the frame with performance,
    physical, overall (1-5), their "better than X%" (share of the OTHER pool games strictly
    lower) and metric_pcts {metric: percentile}."""
    from lofc.ingest.impect_matches import add_percentiles
    g = games.reset_index(drop=True).copy()
    neutral = pd.DataFrame({"player_id": g.index, "competition_id": g["competition_id"],
                            "season_id": g["season_id"], "position_group": g["position_group"],
                            "minutes": g["minutes"],
                            "rankable": pd.to_numeric(g["minutes"], errors="coerce").fillna(0) >= MIN_MINUTES})
    for m in PERF_METRICS:
        neutral[m] = [(p or {}).get(m, {}).get("v") for p in g["perf"]]
    for m in PHYS_METRICS:
        neutral[m] = [(p or {}).get(m, {}).get("v") for p in g["phys"]]
    metric_cols = PERF_METRICS + PHYS_METRICS
    neutral[metric_cols] = neutral[metric_cols].apply(pd.to_numeric, errors="coerce")
    neutral = neutral.dropna(subset=["position_group"])

    cards = sc.build_scorecards(neutral) if neutral["rankable"].any() else pd.DataFrame()
    pcts = sc.metric_percentiles(neutral) if neutral["rankable"].any() else pd.DataFrame()
    by = cards.set_index("player_id") if len(cards) else pd.DataFrame()
    g["performance"] = [by["performance_band"].get(i) if len(by) else None for i in g.index]
    g["physical"] = [by["physical_band"].get(i) if len(by) else None for i in g.index]
    g["overall"] = [by["objective_composite"].get(i) if len(by) else None for i in g.index]
    g[["performance", "physical", "overall"]] = g[["performance", "physical", "overall"]].apply(
        pd.to_numeric, errors="coerce")
    pmap: dict = {}
    if len(pcts):
        flat = pcts.reset_index().set_index("player_id")
        for i, r in flat[metric_cols].iterrows():
            pmap[i] = {m: round(float(v), 1) for m, v in r.items() if pd.notna(v)}
    g["metric_pcts"] = [pmap.get(i, {}) for i in g.index]
    # Short games are scored nowhere above; keep them out of the "better than" pools too.
    g = add_percentiles(g, cols=("performance", "physical", "overall"))
    return g
