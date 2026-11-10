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
REC_N = 15
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
    "Players who could close the gap": (
        "Players rated above our best at this position, best first; the three right-hand columns "
        "show how each scores on the areas where we're weakest."),
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


def _behind(ours: pd.Series, bar_rows: list[pd.Series], metrics: list[str], label) -> list[dict]:
    """Every metric where our player's percentile is below the median percentile of the named
    top-6 players, biggest first. `short` ("Behind" on the page) is the ONE whole-number figure
    both lists show: the unrounded difference, .5 rounding up (owner 2026-11-10)."""
    out = []
    for m in metrics:
        mine = ours.get(m) if ours is not None else None
        theirs = [r.get(m) for r in bar_rows if r is not None and not _missing(r.get(m))]
        if _missing(mine) or not theirs:
            continue
        med = float(pd.Series(theirs).median())
        if med > float(mine):
            out.append((med - float(mine), {"metric": m, "label": label(m), "ours": pct_int(mine),
                                            "top6": pct_int(med), "short": _half_up(med - float(mine))}))
    out.sort(key=lambda t: -t[0])
    return [r for _d, r in out]


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
                    tag_metrics=(), label=str, n: int = REC_N, strong2: bool = False,
                    bar: float | None = None, top6_only: bool = False) -> dict:
    """This season's rated players in `group` (not Orient's) with an Overall above our level,
    ONE LIST PER LEAGUE (ratings compare players within their own league), top `n` by Overall in
    each. Age band and contract horizon filter the players first. Each row carries his percentile
    on each of the position's shortfall metrics (`weak`, one column each on the page)."""
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
    p = None
    if pcts is not None and len(tag_metrics):
        p = pcts.set_index(keys + ["position_group"])

    def weak_of(r) -> list:
        """His percentile on each shortfall metric, in order (None where he has no figure)."""
        if p is None:
            return [None] * len(tag_metrics)
        k = (r.player_id, r.competition_id, r.season_id, r.position_group)
        if k not in p.index:
            return [None] * len(tag_metrics)
        pr = p.loc[k]
        if isinstance(pr, pd.DataFrame):
            pr = pr.iloc[0]
        return [None if m not in pr.index or _missing(pr[m]) else pct_int(pr[m]) for m in tag_metrics]
    f = f.assign(weak_list=[weak_of(r) for r in f.itertuples()])
    if strong2:
        # owner 2026-11-09: 70th percentile or better on at least 2 of the shortfall metrics
        f = f[f["weak_list"].map(lambda w: sum(v is not None and v >= STRENGTH_PCT for v in w)) >= 2]
    leagues = []
    order = {c: i for i, c in enumerate(ENGLAND)}
    for comp, g in sorted(f.groupby("competition_id"),
                          key=lambda kv: (order.get(int(kv[0]), 99), league_names.get(int(kv[0]), ""))):
        g = g.sort_values(["objective_composite", "minutes"], ascending=False)
        rows = []
        for r in g.head(n).itertuples():
            rows.append({"name": r.player_name, "club": r.team_name, "position": r.position_group,
                         "age": _num(r.age), "minutes": _num(r.minutes),
                         "overall": float(r.objective_composite),
                         "vs_best": vs_best(r.objective_composite, level), "performance": _num(r.performance_band),
                         "physical": _num(r.physical_band), "weak": r.weak_list,
                         "ids": [int(r.player_id), int(r.competition_id), int(r.season_id)]})
        leagues.append({"competition_id": int(comp),
                        "league": league_names.get(int(comp), f"League {int(comp)}"),
                        "count": int(len(g)), "rows": rows})
    return {"group": group, "level": level, "leagues": leagues, "default_leagues": list(DEFAULT_LEAGUES),
            "weak_metrics": [{"metric": m, "label": label(m)} for m in tag_metrics]}


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


def big_picture(rated: pd.DataFrame, neutral: pd.DataFrame, cur: int, prev: int,
                metrics: list[str], label, sections: dict | None = None) -> list[dict]:
    """Orient's rank among League One clubs, this season and last: the minutes-weighted club
    averages of Overall, Performance and Physical, then of each physical metric per 90."""
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
    return rows
