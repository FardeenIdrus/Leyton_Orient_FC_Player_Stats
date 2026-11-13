"""The "Club vs League One" page (owner 2026-11-09): where Leyton Orient fall short of a top-6
League One side this season, and who could close the gap.

Every number is a STORED one: ratings are `player_scorecards` (archetype "All Metrics":
objective_composite = Overall, performance_band, physical_band); minutes, club and per-90 values
are `player_metrics_neutral`; percentiles are `scorecard.metric_percentiles` (the card's). This
module only selects, weights by minutes and compares. Pure: frames in, plain data out.

The rules, in the order the page uses them (docs/methodology.md, "Club vs League One"):
  1. Season = the current season.
  2. Rated = has an Overall (objective_composite) that season: 450+ minutes and a peer pool of
     at least MIN_PEERS_FOR_RANKING (thin pools are never rated).
  3. Our level at a position = our best player rated THIS season IN LEAGUE ONE. Players rated
     only last season, or only in another league (on loan), are listed with a tag; they never
     set our level.
  4. Positions: Goalkeeper, Centre Back, Full Back, Midfield (Defensive + Central + Attacking
     Mid), Winger, Centre Forward. A player's rating is always his own position pool's.
  5. Top 6 = the six League One clubs with the highest minutes-weighted average Overall of their
     rated players this season.
  6. The bar at a position = the median of the top-6 clubs' best rated player there (named).
     Needs at least 4 of the 6; otherwise last season's top 6 (same method) for that position.
  7. Gap = bar - our level; biggest first.
"""
from __future__ import annotations

import math

import pandas as pd

LEAGUE_ONE, CHAMPIONSHIP, LEAGUE_TWO = 4, 3, 5
DEFAULT_LEAGUES = [LEAGUE_ONE, CHAMPIONSHIP, LEAGUE_TWO]
# England's leagues, listed first in the Leagues picker (owner 2026-11-10): the three above, then
# the National League and Premier League 2 (lofc.leagues ids).
ENGLAND = DEFAULT_LEAGUES + [65, 903]
TOP_N = 6
MIN_FOR_BAR = 4
STRENGTH_PCT = 70
MIDFIELD = ("Defensive Mid", "Central Mid", "Attacking Mid")
GROUPS = ["Goalkeeper", "Centre Back", "Full Back", "Midfield", "Winger", "Centre Forward"]
PLURAL = {"Goalkeeper": "goalkeepers", "Centre Back": "centre backs", "Full Back": "full backs",
          "Midfield": "midfielders", "Winger": "wingers", "Centre Forward": "centre forwards"}
RATED_COLS = ["player_id", "competition_id", "season_id", "position_group", "objective_composite",
              "performance_band", "physical_band", "minutes", "team_name", "player_name"]


# One plain sentence per term: the page's ⓘ texts, its "How this is worked out" fold-out and
# the Glossary all use these words (owner 2026-11-09).
TERMS = {
    "Top 6": ("The six League One clubs whose players have the highest average Overall rating "
              "this season, weighted by minutes."),
    "Our level": "Our best player at the position rated this season in League One.",
    "Top-6 bar": ("The median rating of the top-6 clubs' best player at the position, "
                  "each named on the page."),
    "Gap": ("How far our level is below the top-6 bar (the bar minus our level); a minus "
            "figure on the page means we fall short."),
    "Top-6 level": "A player whose Overall is at or above the position's top-6 bar.",
    "vs our best": ("His rating minus our best at this position; the gap is closed when this "
                    "reaches the gap size."),
    # owner 2026-11-13: one plain sentence ("our player" covers a picked one too)
    "Gap closed": "How much of our player's shortfall vs the top 6 he would make up. 100% = all of it.",
    "Players who could close the gap": (
        "Players rated above our best at this position, ranked by Overall or Gap closed; the metric "
        "columns show his percentile on each chosen measure."),
}


def group_of(position: str) -> str:
    return "Midfield" if position in MIDFIELD else position


def positions_in(group: str) -> tuple[str, ...]:
    return MIDFIELD if group == "Midfield" else (group,)


def _missing(v) -> bool:
    return v is None or (isinstance(v, float) and math.isnan(v)) or bool(pd.isna(v))


def _num(v):
    return None if _missing(v) else float(v)


def _is_orient(name) -> bool:
    from lofc.core.squad import is_orient_club
    return is_orient_club(name)


def ordinal(n: int) -> str:
    from lofc.dashboard.detail_section import ordinal as o
    return o(n)


def pct_int(p) -> int | None:
    """The card's percentile rounding (Python round, `detail_section.physical_table`)."""
    return None if _missing(p) else round(float(p))


# --- inputs -----------------------------------------------------------------------------------
def rated_frame(cards: pd.DataFrame, neutral: pd.DataFrame) -> pd.DataFrame:
    """Rated rows: the "All Metrics" scorecards with an Overall, with minutes, club and name from
    player_metrics_neutral, and the gap-map group."""
    keys = ["player_id", "competition_id", "season_id"]
    c = cards[cards["objective_composite"].notna()]
    out = c.merge(neutral[keys + ["minutes", "team_name", "player_name"]], on=keys, how="left")
    return out[RATED_COLS].reset_index(drop=True)


# --- clubs ------------------------------------------------------------------------------------
def club_table(rated: pd.DataFrame, season_id: int, league: int = LEAGUE_ONE,
               column: str = "objective_composite") -> pd.DataFrame:
    """One row per club of `league` in `season_id`: the minutes-weighted average of `column`
    over its rated players (sum of rating x minutes / sum of minutes), best first."""
    f = rated[(rated["competition_id"] == league) & (rated["season_id"] == season_id)
              & rated[column].notna() & (rated["minutes"] > 0)]
    if f.empty:
        return pd.DataFrame(columns=["team_name", "avg", "n", "minutes", "rank"])
    g = f.assign(_w=f[column] * f["minutes"]).groupby("team_name").agg(
        w=("_w", "sum"), minutes=("minutes", "sum"), n=("player_id", "count"))
    g["avg"] = g["w"] / g["minutes"]
    g = g.sort_values(["avg"], ascending=False).reset_index()
    g["rank"] = g["avg"].rank(ascending=False, method="min").astype(int)
    return g[["team_name", "avg", "n", "minutes", "rank"]]


def club_ratings(rated: pd.DataFrame, season_id: int, league: int = LEAGUE_ONE) -> pd.DataFrame:
    """One row per club: club_table's minutes-weighted average of Overall, Performance and
    Physical (each over the rated players who have that figure), `n` rated players and the
    Overall rank; best Overall first. The Top 6 card (owner 2026-11-10)."""
    out = club_table(rated, season_id, league)[["team_name", "avg", "n", "rank"]].rename(
        columns={"avg": "overall"})
    for col, name in (("performance_band", "performance"), ("physical_band", "physical")):
        t = club_table(rated, season_id, league, column=col).set_index("team_name")["avg"]
        out[name] = out["team_name"].map(t)
    return out[["team_name", "overall", "performance", "physical", "n", "rank"]].reset_index(drop=True)


def orient_club(ratings: pd.DataFrame) -> dict | None:
    """Orient's row of club_ratings, or None."""
    hit = ratings[[_is_orient(t) for t in ratings["team_name"]]]
    return None if hit.empty else hit.iloc[0].to_dict()


def top_clubs(table: pd.DataFrame, n: int = TOP_N) -> list[str]:
    return list(table["team_name"].head(n))


def orient_rank(table: pd.DataFrame) -> tuple[int | None, int]:
    hit = table[[_is_orient(t) for t in table["team_name"]]]
    return (None if hit.empty else int(hit["rank"].iloc[0])), int(len(table))


# --- the bar ----------------------------------------------------------------------------------
def bar(rated: pd.DataFrame, season_id: int, clubs: list[str], group: str,
        league: int = LEAGUE_ONE) -> dict:
    """Each of `clubs`' best rated player in `group` this season, and their median."""
    f = rated[(rated["competition_id"] == league) & (rated["season_id"] == season_id)
              & rated["team_name"].isin(clubs) & rated["position_group"].isin(positions_in(group))]
    best = f.sort_values(["objective_composite", "minutes"], ascending=False).drop_duplicates("team_name")
    order = {c: i for i, c in enumerate(clubs)}
    best = best.assign(_o=best["team_name"].map(order)).sort_values("_o")
    players = [{"club": r.team_name, "player": r.player_name, "rating": float(r.objective_composite),
                "position": r.position_group, "player_id": int(r.player_id),
                "competition_id": int(r.competition_id), "season_id": int(r.season_id)}
               for r in best.itertuples()]
    med = float(pd.Series([p["rating"] for p in players]).median()) if players else None
    return {"players": players, "median": med, "n": len(players), "of": len(clubs)}


# --- our players --------------------------------------------------------------------------------
def our_players(squad: pd.DataFrame, rated: pd.DataFrame, cur: int, prev: int,
                league_names: dict) -> list[dict]:
    """Every current Orient player with the rating the page shows for him. `counts` = rated this
    season in League One (the only ratings that set our level); otherwise `tag` says where the
    rating is from ("25/26" for last season, or the other league's name)."""
    from lofc.leagues import season_label
    out = []
    for s in squad.itertuples():
        pid = int(s.player_id)
        mine = rated[rated["player_id"] == pid]
        now = mine[mine["season_id"] == cur]
        row, tag, counts = None, None, False
        if not now.empty:
            l1 = now[now["competition_id"] == LEAGUE_ONE]
            if not l1.empty:
                row, counts = l1.sort_values("objective_composite", ascending=False).iloc[0], True
            else:
                row = now.sort_values("minutes", ascending=False).iloc[0]
                tag = league_names.get(int(row["competition_id"]), f"League {int(row['competition_id'])}")
        else:
            last = mine[mine["season_id"] == prev]
            if not last.empty:
                row = last.sort_values("minutes", ascending=False).iloc[0]
                tag = season_label(prev, short=True)
        position = str(row["position_group"]) if row is not None else str(s.position_group)
        out.append({
            "player_id": pid, "name": str(s.player_name), "position": position,
            "group": group_of(position), "counts": counts, "tag": tag,
            "rating": None if row is None else float(row["objective_composite"]),
            "performance": None if row is None else _num(row["performance_band"]),
            "physical": None if row is None else _num(row["physical_band"]),
            "minutes": None if row is None else _num(row["minutes"]),
            "competition_id": None if row is None else int(row["competition_id"]),
            "season_id": None if row is None else int(row["season_id"])})
    return out


def our_level(ours: list[dict], group: str) -> dict | None:
    """Our best player in `group` rated this season in League One, or None."""
    counted = [o for o in ours if o["group"] == group and o["counts"]]
    return max(counted, key=lambda o: o["rating"]) if counted else None


def compared_player(ours: list[dict], group: str, vs=None) -> dict | None:
    """The player a position is measured against (owner 2026-11-13): `vs` (a player_id, from
    the URL) when he is one of ours in `group` rated this season in League One -- the same rule
    as our best; anything else (rated elsewhere or last season only, another position, not ours,
    junk) is ignored and our best is used."""
    best = our_level(ours, group)
    try:
        pid = int(str(vs).strip()) if vs is not None and str(vs).strip().isdigit() else None
    except ValueError:
        pid = None
    hit = next((o for o in ours if o["player_id"] == pid and o["group"] == group and o["counts"]), None)
    return hit or best


def measure_against(row: dict, player: dict | None, detail: dict | None) -> dict:
    """A gap_map row measured against `player` (compared_player): a copy with `level` = him,
    gap = bar - his Overall and his shortfalls (`detail` = gap_detail over his percentiles);
    `best` keeps our best and `vs` is his player_id, or None when he is our best (the row is
    then unchanged)."""
    out = dict(row)
    best = row.get("level")
    out["best"], out["vs"] = best, None
    if player is None or best is None or player["player_id"] == best["player_id"]:
        return out
    med = (row.get("bar") or {}).get("median")
    out.update(level=player, vs=player["player_id"],
               gap=None if med is None else float(med) - player["rating"],
               shortfalls=list((detail or {}).get("shortfalls", [])),
               all_shortfalls=list((detail or {}).get("all_shortfalls", [])))
    return out


def vs_terms(name: str) -> dict:
    """The column help when the list is measured against one of our players other than our
    best (owner 2026-11-13): "vs him" and Gap closed, naming him."""
    return {"vs him": f"His rating minus {name}'s; the gap is closed when this reaches the gap size.",
            "Gap closed": TERMS["Gap closed"]}


# --- the gap map --------------------------------------------------------------------------------
def gap_map(rated: pd.DataFrame, ours: list[dict], cur: int, prev: int,
            season_names: dict) -> list[dict]:
    """One row per group: our level (and everyone we have there), the bar (named players; last
    season's top 6 when fewer than MIN_FOR_BAR of this season's have a rated player there) and
    the gap. Biggest gap first; groups without an Orient level last."""
    top_now = top_clubs(club_table(rated, cur))
    top_prev = top_clubs(club_table(rated, prev))
    rows = []
    for group in GROUPS:
        b = bar(rated, cur, top_now, group)
        b.update(season_id=cur, fallback=False, label=None)
        if b["n"] < MIN_FOR_BAR:
            n_now = b["n"]
            b = bar(rated, prev, top_prev, group)
            b.update(season_id=prev, fallback=True,
                     label=(f"Bar from {season_names[prev]} — not enough rated {PLURAL[group]} at "
                            f"this season's top-6 clubs yet ({n_now} of {TOP_N})"))
        level = our_level(ours, group)
        gap = None if level is None or b["median"] is None else float(b["median"]) - level["rating"]
        rows.append({"group": group, "level": level, "bar": b, "gap": gap,
                     "players": [o for o in ours if o["group"] == group],
                     "note": None if level is not None else "No Orient player rated here this season"})
    rows.sort(key=lambda r: (r["gap"] is None, -(r["gap"] if r["gap"] is not None else 0)))
    return rows


def gap_profile(ours: pd.Series | None, bar_rows: list[pd.Series], metrics: list[str]) -> dict:
    """metric -> (our percentile, the named top-6 players' median percentile), unrounded, for
    every metric where we are behind (the median is above ours) -- the "Every shortfall" set.
    A metric is skipped when our player or all of the top-6 players lack a figure."""
    out = {}
    for m in metrics:
        mine = ours.get(m) if ours is not None else None
        theirs = [r.get(m) for r in bar_rows if r is not None and not _missing(r.get(m))]
        if _missing(mine) or not theirs:
            continue
        med = float(pd.Series(theirs).median())
        if med > float(mine):
            out[m] = (float(mine), med)
    return out


def _behind(ours: pd.Series, bar_rows: list[pd.Series], metrics: list[str], label,
            profile: dict | None = None) -> list[dict]:
    """Every metric where our player's percentile is below the median percentile of the named
    top-6 players, biggest first. `short` ("Behind" on the page) is the ONE whole-number figure
    both lists show: the unrounded difference, .5 rounding up (owner 2026-11-10)."""
    prof = gap_profile(ours, bar_rows, metrics) if profile is None else profile
    out = [(med - mine, {"metric": m, "label": label(m), "ours": pct_int(mine), "top6": pct_int(med),
                         "short": _half_up(med - mine)})
           for m, (mine, med) in prof.items()]
    out.sort(key=lambda t: -t[0])
    return [r for _d, r in out]


def gap_detail(ours: pd.Series | None, bar_rows: list[pd.Series], metrics: list[str], label,
               n: int = 3) -> dict:
    """One player's shortfalls against the named top-6 players, worked out once: `profile`
    (gap_profile, for Gap closed), `all_shortfalls` ("Every shortfall") and `shortfalls` (its
    `n` biggest, the Gap map's "Biggest shortfalls" and the default metric columns)."""
    profile = gap_profile(ours, bar_rows, metrics)
    every = _behind(ours, bar_rows, metrics, label, profile)
    return {"profile": profile, "all_shortfalls": every, "shortfalls": every[:n]}


# --- gap closed (owner 2026-11-13) ---------------------------------------------------------------
def overall_weights(position: str) -> dict[str, float]:
    """metric -> its share of the position's Overall rating (sums to 1), as the scorecard builds
    Overall (model.scorecard.build_scorecards, archetype "All Metrics"): Overall is the
    Performance and Physical bands averaged with DIMENSION_WEIGHTS (outfield 40:30 -> 4/7 and
    3/7; goalkeepers Performance only); inside Performance the club's per-metric weights
    (performance_weights, All Metrics), inside Physical an equal share. A metric's weight is
    its weight inside its dimension x that dimension's share."""
    from lofc.model import club_framework as cf
    from lofc.model import performance_weights as pw
    from lofc.model.scorecard import _resolved_performance
    dims = cf.DIMENSION_WEIGHTS.get(position, {})
    phys = list(cf.PHYSICAL_METRICS.get(position, []))
    d_perf, d_phys = dims.get(cf.PERFORMANCE, 0.0), (dims.get(cf.PHYSICAL, 0.0) if phys else 0.0)
    total = d_perf + d_phys
    if total <= 0:
        return {}
    perf_w = pw.weights_for(position, cf.DEFAULT_ARCHETYPE)
    if not perf_w:                                   # no club weights: equal, as the scorecard
        perf = _resolved_performance(position)
        perf_w = {m: 1.0 for m in perf}
    s = sum(perf_w.values())
    out = {m: w / s * d_perf / total for m, w in perf_w.items()}
    for m in phys:
        out[m] = out.get(m, 0.0) + d_phys / total / len(phys)
    return out


def gap_closed(profile: dict, cand, weights: dict, metrics=None) -> int | None:
    """"Gap closed": the share (0-100, whole number, .5 up) of our weighted shortfall against
    the top 6 that this player would close. For each shortfall m in `profile` (restricted to
    `metrics` when given): gap = top-6 median - ours; closed = his percentile - ours, clipped
    to [0, gap] (no credit beyond the top-6 level, none for being worse than ours); a missing
    percentile closes nothing. Score = 100 x sum(w x closed) / sum(w x gap). None when he has
    no percentiles at all, or there is no weighted shortfall to close."""
    if cand is None:
        return None
    keep = set(metrics) if metrics is not None else None
    num = den = 0.0
    for m, (mine, med) in profile.items():
        if keep is not None and m not in keep:
            continue
        w = float(weights.get(m, 0.0))
        gap = med - mine
        if w <= 0 or gap <= 0:
            continue
        v = cand.get(m) if hasattr(cand, "get") else None
        closed = 0.0 if _missing(v) else min(max(float(v) - mine, 0.0), gap)
        num += w * closed
        den += w * gap
    return None if den <= 0 else _half_up(100.0 * num / den)


def shortfalls(ours: pd.Series, bar_rows: list[pd.Series], metrics: list[str], label,
               n: int = 3) -> list[dict]:
    """Where the gap comes from: our player's percentile per metric against the median
    percentile of the named top-6 players; the `n` biggest shortfalls (any size)."""
    return _behind(ours, bar_rows, metrics, label)[:n]


def weak_label(label):
    """`label`, plus " (fewer is better)" for a lower-is-better metric (cf.LOWER_IS_BETTER,
    e.g. turnovers). Their percentiles are already inverted by the scorecard (higher = better),
    so "Turnovers: ours 1st" means many turnovers; the label says which way is good."""
    def lab(m):
        from lofc.model import club_framework as cf
        return f"{label(m)} (fewer is better)" if m in cf.LOWER_IS_BETTER else label(m)
    return lab


def _half_up(x: float) -> int:
    """Whole points, .5 rounding UP also for negatives (the card's "vs ours": -10.5 -> -10)."""
    import math
    return int(math.floor(round(x, 6) + 0.5))


def all_shortfalls(ours: pd.Series, bar_rows: list[pd.Series], metrics: list[str], label) -> list[dict]:
    """The "Every shortfall" list: every metric where our player's percentile is below the median
    percentile of the named top-6 players, biggest first -- no cut-off (owner 2026-11-10), so it
    always contains the summary's top 3 and its heading is always true. Same rows and `short` as
    shortfalls()."""
    return _behind(ours, bar_rows, metrics, label)


def vs_best(overall, level) -> float | None:
    """His Overall minus our level, to 2 decimals, .5 rounding UP as the card's "vs ours"."""
    if overall is None or level is None or _missing(overall) or _missing(level):
        return None
    return _half_up((float(overall) - float(level)) * 100) / 100


# --- recommendations ----------------------------------------------------------------------------
def recommendations(rated: pd.DataFrame, candidates: pd.DataFrame, season_id: int, group: str,
                    level: float | None, exclude_ids, league_names: dict, *, age: str = "",
                    contract: str = "", today=None, pcts: pd.DataFrame | None = None,
                    tag_metrics=(), label=str, n: int | None = None, strong2: bool = False,
                    bar: float | None = None, top6_only: bool = False, gap: dict | None = None,
                    weights: dict | None = None, score_metrics=None, strong_metrics=None,
                    rank: str = "") -> dict:
    """This season's rated players in `group` (not Orient's) with an Overall above our level,
    ONE LIST PER LEAGUE (ratings compare players within their own league), every one of them
    (owner 2026-11-13: no top-15 cap; `n` limits it), by Overall in each (`rank="gap"`: by Gap
    closed, ties by Overall). Age band and contract horizon filter the players first. Each row carries his percentile on each metric column (`tag_metrics`, one
    column each on the page) and `gap_closed` over `gap` (gap_profile; only `score_metrics`
    when given). "Strong on 2+" uses `strong_metrics` (default: the columns)."""
    from lofc.core.physical_page import in_age_band
    from lofc.dashboard import seasons as S
    keys = ["player_id", "competition_id", "season_id"]
    f = rated[(rated["season_id"] == season_id) & rated["position_group"].isin(positions_in(group))
              & ~rated["player_id"].isin(list(exclude_ids))
              & ~rated["team_name"].map(_is_orient)]
    if level is not None:
        f = f[f["objective_composite"] > level]
    if top6_only and bar is not None:
        # owner 2026-11-09: "Top-6 level only" -- at or above the position's top-6 bar
        f = f[f["objective_composite"] >= bar]
    f = f.merge(candidates[keys + ["age", "contract_until"]], on=keys, how="left")
    if age:
        f = f[[in_age_band(a, age) for a in f["age"]]]
    mask = S.contract_mask(f["contract_until"], contract, today) if contract else None
    if mask is not None:
        f = f[mask.values]
    strong_metrics = list(tag_metrics if strong_metrics is None else strong_metrics)
    lookup = None
    need = list(dict.fromkeys(list(tag_metrics) + strong_metrics + list(gap or {})))
    if pcts is not None and need:
        # one dict per player-league-season-position (the first, as .loc[...].iloc[0] did), only
        # the metrics needed: a per-row DataFrame lookup cost ~0.5 s per request
        kk = keys + ["position_group"]
        sub = pcts[kk + [m for m in need if m in pcts.columns]].drop_duplicates(kk, keep="first")
        lookup = {tuple(r[:4]): dict(zip(sub.columns[4:], r[4:]))
                  for r in sub.itertuples(index=False, name=None)}

    def pct_row(r):
        """His percentiles (his own position pool) as a dict, or None."""
        if lookup is None:
            return None
        return lookup.get((r.player_id, r.competition_id, r.season_id, r.position_group))

    def pcts_of(pr, ms) -> list:
        """His percentile on each metric, in order (None where he has no figure)."""
        if pr is None:
            return [None] * len(ms)
        return [None if _missing(pr.get(m)) else pct_int(pr[m]) for m in ms]
    prs = [pct_row(r) for r in f.itertuples()]
    f = f.assign(_pr=prs, weak_list=[pcts_of(pr, tag_metrics) for pr in prs],
                 strong_list=[pcts_of(pr, strong_metrics) for pr in prs],
                 gap_closed=[None if not gap else gap_closed(gap, pr, weights or {}, score_metrics)
                             for pr in prs])
    if strong2:
        # owner 2026-11-09: 70th percentile or better on at least 2 of the shortfall metrics
        f = f[f["strong_list"].map(lambda w: sum(v is not None and v >= STRENGTH_PCT for v in w)) >= 2]
    rank = "gap" if rank == "gap" else ""
    leagues = []
    order = {c: i for i, c in enumerate(ENGLAND)}
    for comp, g in sorted(f.groupby("competition_id"),
                          key=lambda kv: (order.get(int(kv[0]), 99), league_names.get(int(kv[0]), ""))):
        g = g.sort_values(["objective_composite", "minutes"], ascending=False)
        # owner 2026-11-13: Gap closed high first, ties by Overall; no figure last
        by_gap = g.assign(_gc=g["gap_closed"].map(lambda v: -1 if v is None or _missing(v) else v))
        by_gap = by_gap.sort_values(["_gc", "objective_composite", "minutes"], ascending=False, kind="stable")
        if rank == "gap":
            g = by_gap
        rows = []
        for r in (g if n is None else g.head(n)).itertuples():
            rows.append({"name": r.player_name, "club": r.team_name, "position": r.position_group,
                         "age": _num(r.age), "minutes": _num(r.minutes),
                         "overall": float(r.objective_composite),
                         "vs_best": vs_best(r.objective_composite, level), "performance": _num(r.performance_band),
                         "physical": _num(r.physical_band), "weak": r.weak_list,
                         "gap_closed": None if r.gap_closed is None or _missing(r.gap_closed) else int(r.gap_closed),
                         "ids": [int(r.player_id), int(r.competition_id), int(r.season_id)]})
        leagues.append({"competition_id": int(comp),
                        "league": league_names.get(int(comp), f"League {int(comp)}"),
                        "count": int(len(g)), "rows": rows, "top_gap": _top_gap(by_gap, gap)})
    return {"group": group, "level": level, "leagues": leagues, "default_leagues": list(DEFAULT_LEAGUES),
            "weak_metrics": [{"metric": m, "label": label(m)} for m in tag_metrics], "rank": rank}


def _top_gap(by_gap: pd.DataFrame, gap: dict | None) -> dict | None:
    """The league's first player by Gap closed (the "Rank by: Gap closed" order, over every
    player who passed the filters, not only the shown top n) with his unrounded percentiles on
    our shortfalls -- the live example's candidate. None when nobody has a Gap closed."""
    if by_gap.empty:
        return None
    r = by_gap.iloc[0]
    if r["gap_closed"] is None or _missing(r["gap_closed"]):
        return None
    pr = r["_pr"] or {}
    return {"name": str(r["player_name"]), "club": str(r["team_name"]), "gap_closed": int(r["gap_closed"]),
            "pcts": {m: float(pr[m]) for m in (gap or {}) if m in pr and not _missing(pr[m])}}


GX_HEADING = "Gap closed: how much of our player's shortfall a target would make up."
GX_SCALE = "Scores are out of 100 (100 = best at his position in his league)."
GX_WHY = "Why: it ranks players by how much they fix our weaknesses, not just by how good they are."
GX_ROWS = 3


def _signed(n: int) -> str:
    return f"−{-n}" if n < 0 else str(n)


def _r1(x: float) -> float:
    """One decimal, .5 rounding up (as _half_up)."""
    import math
    return math.floor(round(float(x) * 10, 6) + 0.5) / 10


def _d1(x: float) -> str:
    """One decimal; a minus sign as on the page ("−10.0"); never "-0.0"."""
    x = round(x, 1) + 0.0
    return f"−{-x:.1f}" if x < 0 else f"{x:.1f}"


def gap_example(group: str, player: dict | None, bar_median, profile: dict, top: dict | None,
                weights: dict, league: str, label=str, metrics=None) -> dict | None:
    """"How this is worked out": Gap closed as a mini table from the page's own figures (owner
    2026-11-13). `player` = the one the position is measured against (compared_player),
    `profile` his gap_profile, `top` the active league's first player by Gap closed (_top_gap; his
    Gap closed is the list's figure, not worked out again). Rows: his GX_ROWS biggest weighted
    shortfalls (weight x gap) the target has a figure for, among `metrics` when the recruiter
    chose the columns; "Counted" = Target - Ours kept between 0 and the gap, as gap_closed. None
    (the page then shows the one-line definition) without a player, bar, shortfall, target or a
    figure to show."""
    if player is None or bar_median is None or not profile or top is None or top.get("gap_closed") is None:
        return None
    keep = set(metrics) if metrics is not None else None
    have = top.get("pcts") or {}
    short = sorted(((float(weights.get(m, 0.0)) * (med - mine), m, mine, med)
                    for m, (mine, med) in profile.items()
                    if (keep is None or m in keep) and float(weights.get(m, 0.0)) > 0),
                   key=lambda t: -t[0])
    # owner 2026-11-13: one decimal, worked out from the figures shown so every row adds up exactly
    rows = []
    for _w, m, mine, med in [t for t in short if t[1] in have][:GX_ROWS]:
        o, t6, tg = _r1(mine), _r1(med), _r1(have[m])
        gap, diff = round(t6 - o, 1), round(tg - o, 1)
        counted = min(max(diff, 0.0), gap)
        rows.append({"label": label(m), "ours": _d1(o), "top6": _d1(t6), "gap": _d1(gap),
                     "target": _d1(tg), "diff": _d1(diff),
                     "counted": f"{_d1(counted)} (capped at the gap)" if diff > gap else _d1(counted)})
    if not rows:
        return None
    n_more = len(short) - len(rows)
    surname = lambda name: str(name).split()[-1]          # noqa: E731
    return {"heading": GX_HEADING, "scale": GX_SCALE, "why": GX_WHY, "league": league,
            "candidate": {"name": top["name"], "club": top["club"]},
            "columns": ["Measure", f"Ours ({surname(player['name'])})", "Top 6", "Gap (Top 6 − Ours)",
                        f"Target ({surname(top['name'])})", "Target − Ours", "Counted"],
            "rows": rows,
            "more": None if n_more <= 0 else f"…and {n_more} more measure{'s' if n_more != 1 else ''}",
            # owner 2026-11-13: already above the bar -> the % is of what is left on these measures
            "total": (f"Gap closed = total Counted ÷ total Gap = {top['gap_closed']}%"
                      + (" of his remaining shortfalls on these measures"
                         if float(bar_median) <= float(player["rating"]) else "")
                      + f". Measures that count more in the {group} rating count more.")}


# --- big picture ----------------------------------------------------------------------------------
def _rank_text(table: pd.DataFrame) -> dict | None:
    r, n = orient_rank(table)
    return None if r is None else {"rank": r, "of": n, "text": f"{ordinal(r)} of {n}"}


def metric_table(neutral: pd.DataFrame, season_id: int, metric: str,
                 league: int = LEAGUE_ONE) -> pd.DataFrame:
    """Clubs by the minutes-weighted per-90 value of `metric` (higher first)."""
    f = neutral[(neutral["competition_id"] == league) & (neutral["season_id"] == season_id)
                & neutral[metric].notna() & (neutral["minutes"] > 0)]
    if f.empty:
        return pd.DataFrame(columns=["team_name", "avg", "rank"])
    g = f.assign(_w=f[metric] * f["minutes"]).groupby("team_name").agg(w=("_w", "sum"), m=("minutes", "sum"))
    g["avg"] = g["w"] / g["m"]
    g = g.sort_values("avg", ascending=False).reset_index()
    g["rank"] = g["avg"].rank(ascending=False, method="min").astype(int)
    return g


PHASES = {"tip": "phys_tip.", "otip": "phys_otip."}      # SkillCorner: in / out of possession


def phase_frame(detail: pd.DataFrame, neutral: pd.DataFrame, phase: str, metrics: list[str]) -> pd.DataFrame:
    """`neutral`'s players (minutes, club) with `metrics` replaced by SkillCorner's `phase` split
    ("tip" = in possession, "otip" = out of possession: player_detail_metrics rows
    "phys_tip.<metric>" / "phys_otip.<metric>", value_p90), so metric_table ranks clubs on it
    the same way. A metric with no split (top speed) is all-missing; so is a player without a
    figure, who then does not count."""
    keys = ["player_id", "competition_id", "season_id"]
    base = neutral[keys + ["minutes", "team_name"]]
    prefix = PHASES[phase]
    want = {prefix + m: m for m in metrics}
    d = detail[detail["metric"].astype(str).isin(list(want))] if len(detail) else detail
    if d is None or d.empty:
        return base.assign(**{m: float("nan") for m in metrics})
    wide = d.assign(metric=d["metric"].astype(str).map(want)).pivot_table(
        index=keys, columns="metric", values="value_p90", aggfunc="first").reset_index()
    wide.columns.name = None
    out = base.merge(wide, on=keys, how="left")
    for m in metrics:
        if m not in out.columns:
            out[m] = float("nan")
    return out


def big_picture(rated: pd.DataFrame, neutral: pd.DataFrame, cur: int, prev: int,
                metrics: list[str], label, sections: dict | None = None,
                phases: dict | None = None) -> list[dict]:
    """Orient's rank among League One clubs, this season and last: the minutes-weighted club
    averages of Overall, Performance and Physical, then of each measure per 90. With `phases`
    ({"tip"|"otip": phase_frame}), each Physical-section row also carries its rank in and out of
    possession (owner 2026-11-13); None where there is no split."""
    rows = []
    for measure, col in (("Overall", "objective_composite"), ("Performance", "performance_band"),
                         ("Physical", "physical_band")):
        rows.append({"measure": measure, "kind": "rating", "section": "Ratings",
                     "now": _rank_text(club_table(rated, cur, column=col)),
                     "prev": _rank_text(club_table(rated, prev, column=col))})
    for m in metrics:
        rows.append({"measure": m, "label": label(m), "kind": "metric",
                     "section": (sections or {}).get(m, ""),
                     "now": _rank_text(metric_table(neutral, cur, m)),
                     "prev": _rank_text(metric_table(neutral, prev, m))})
        if phases and rows[-1]["section"] == "Physical":
            rows[-1]["phases"] = {k: {s: (_rank_text(metric_table(f, sid, m)) if m in f.columns else None)
                                      for s, sid in (("now", cur), ("prev", prev))}
                                  for k, f in phases.items()}
    return rows
