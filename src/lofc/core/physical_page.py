"""The web Physical page (TASKS 2.1e): SkillCorner tracking data as the ratings use it.

Every number comes from frames the platform already builds: values from
`loaders.load_metric_values` (the card's "All phases" column), percentiles from
`loaders.load_scorecard_percentiles` (the card's "Percentile" column: within league, season and
position, 450+ minutes, lower-is-better metrics already flipped), players from
`loaders.load_candidates` (exactly the rankable rows, i.e. those the card opens) and Leyton
Orient's squad from `core.squad`. Values are shown as the card shows them (one decimal) and
percentiles rounded as the card rounds them (`detail_section.physical_table`).

Honesty rules kept here:
  * a percentile is shown only when at least MIN_PEERS_FOR_RANKING players in that league and
    position have the metric (the percentile's own divisor); below that the values stay, the
    ranking goes, and the note says why;
  * leagues are never ordered against each other: every list is one league and one position.

Pure: the functions take frames, so tests need no database. The web module
(`lofc.web.api.physical`) reads the frames and caches the answers.
"""
from __future__ import annotations

import pandas as pd

from lofc.model import club_framework as cf
from lofc.model.scorecard import MIN_PEERS_FOR_RANKING

DASH = "—"
DEFAULT_METRIC = "top5_psv99_kmh"        # "Top speed": the Players page's column
DEFAULT_X, DEFAULT_Y = "sprint_count_p90", "top5_psv99_kmh"
LEADERS_SHOWN = 25
NO_PLAYERS = "No players with tracking data."
_POOL_COLS = ["player_id", "competition_id", "season_id", "player_name", "team_name",
              "minutes", "age"]


# --- metrics and wording -----------------------------------------------------------------------
def metric_list() -> list[dict]:
    """The card's physical rows, in the card's order and with the card's labels; `rated` = one
    of the rating's Physical metrics; `lower` = lower is better (`cf.LOWER_IS_BETTER`: the
    timing tests); `definition` = the Glossary's (SkillCorner's) wording."""
    from lofc.dashboard import detail_section as ds
    from lofc.dashboard.glossary_data import PHYSICAL
    rated = set(cf.PHYSICAL_METRICS["Centre Back"])
    entries = list(ds.PHASE_METRICS) + [(m, label) for m, label, _ in ds.SPEED_METRICS]
    return [{"key": m, "label": label, "rated": m in rated, "lower": m in cf.LOWER_IS_BETTER,
             "definition": PHYSICAL[m][1]}
            for m, label in entries]


KEYS = [m["key"] for m in metric_list()]
RATED = [m["key"] for m in metric_list() if m["rated"]]


def positions() -> list[str]:
    """Outfield positions in the Players page's order. Goalkeepers have no tracking data."""
    from lofc.core.players_pool import POSITION_ORDER
    return [p for p in POSITION_ORDER if cf.PHYSICAL_METRICS.get(p)]


def no_data_text(season_name: str) -> str:
    return f"No physical data for {season_name}."


def _missing(v) -> bool:
    return v is None or (isinstance(v, float) and pd.isna(v)) or pd.isna(v)


def value_text(v) -> str:
    """The card's physical format (`core.card._physical_block`): one decimal, "—" for blank."""
    return DASH if _missing(v) else f"{float(v):.1f}"


def pct_value(p) -> int | None:
    """The card's percentile (`detail_section.physical_table`: Python round())."""
    return None if _missing(p) else round(float(p))


def minutes_text(v) -> str:
    """The card's Minutes cell (`core.card.register_cells`): half-up, thousands separator."""
    from lofc.core.card import _half_up
    return DASH if _missing(v) else f"{_half_up(v):,}"


def _num(v) -> float | None:
    return None if _missing(v) else float(v)


def thin_caption(n: int) -> str:
    from lofc.core.card import thin_pool_caption
    return thin_pool_caption(int(n))


# --- age bands (TASKS 2.36) --------------------------------------------------------------------
AGE_BANDS = [("", "All"), ("u21", "Under 21"), ("u23", "Under 23"), ("23-29", "23–29"),
             ("30+", "30+")]


def in_age_band(age, band: str) -> bool:
    """Age (the Players page's age at the season reference date) inside the band. "" = all;
    an unknown age is in "All" only."""
    if not band:
        return True
    if _missing(age):
        return False
    a = float(age)
    return {"u21": a < 21, "u23": a < 23, "23-29": 23 <= a < 30, "30+": a >= 30}.get(band, False)


def bands_of(age) -> list[str]:
    return [k for k, _ in AGE_BANDS if in_age_band(age, k)]


# --- Physical rating rank (TASKS 2.36) ------------------------------------------------------------
RATING_KEY = "physical_rating"


def physical_ranks(cards: pd.DataFrame, competition_id: int, season_id: int,
                   position: str) -> dict:
    """player_id -> {"band", "rank", "n", "text"}: the Physical rating and its "7th of 45" in
    that league, season and position, by `scorecard.rank_in_pool(..., column="physical_band")`
    on the scorecards (`cards`: the "All Metrics" rows). A pool under MIN_PEERS_FOR_RANKING is
    not a rating: no band, no rank, "—"."""
    from lofc.dashboard.detail_section import ordinal
    from lofc.model.scorecard import rank_in_pool
    if cards is None or not len(cards):
        return {}
    pool = cards[(cards["competition_id"] == competition_id) & (cards["season_id"] == season_id)
                 & (cards["position_group"] == position) & cards["physical_band"].notna()]
    n = int(len(pool))
    thin = n < MIN_PEERS_FOR_RANKING
    out = {}
    for pid, band in zip(pool["player_id"], pool["physical_band"]):
        rank = None if thin else rank_in_pool(pool, int(pid), competition_id, season_id, position,
                                               column="physical_band")[0]
        out[int(pid)] = {"band": None if thin else float(band), "rank": rank, "n": n,
                         "text": DASH if rank is None else f"{ordinal(rank)} of {n}"}
    return out


def rating_leaders(pool: pd.DataFrame, ranks: dict) -> dict:
    """The leaders list for "Physical rating": best band first, ties share a rank (the ranks of
    `physical_ranks`). A thin pool is listed by name, unranked, and says why."""
    ids = [int(p) for p in pool["player_id"]]
    has = [i for i, p in enumerate(ids) if p in ranks]
    n = next(iter(ranks.values()))["n"] if ranks else 0
    if n < MIN_PEERS_FOR_RANKING:
        order = sorted(has, key=lambda i: str(pool.iloc[i]["player_name"]))
        return {"n": n, "thin": thin_caption(n) if n else None, "order": [[i, None] for i in order]}
    order = sorted(has, key=lambda i: (-ranks[ids[i]]["band"], str(pool.iloc[i]["player_name"])))
    return {"n": n, "thin": None, "order": [[i, ranks[ids[i]]["rank"]] for i in order]}


TOP_SHOWN, TOP_MARKED = 8, 5        # "Better on both": rows listed / dots numbered in red
NOBODY_BETTER_ON_BOTH = "Nobody better on both."
MIN_MINUTES = [450, 900, 1350, 1800]   # "Min minutes" on Two metrics (owner 2026-11-13); [0] = default
MINUTES_STEP = 90                      # owner 2026-11-13: a slider from 450 in steps of 90


def min_minutes(v) -> int:
    """The "Min minutes" slider value from the URL: 450 or more in steps of 90; anything else is
    the default (450)."""
    try:
        m = int(v)
    except (TypeError, ValueError):
        return MIN_MINUTES[0]
    return m if m >= MIN_MINUTES[0] and m % MINUTES_STEP == 0 else MIN_MINUTES[0]


def minutes_max(players: list[dict], x: str, y: str, band: str) -> int:
    """The slider's top: the most minutes of anyone the chart plots at 450+, rounded up to a
    multiple of 90 (never below 450)."""
    import math
    mins = [r["mins"] for r in players if r["v"].get(x) is not None and r["v"].get(y) is not None
            and band in r["bands"] and r.get("mins") is not None]
    top = max(mins, default=0)
    return max(MIN_MINUTES[0], int(math.ceil(top / MINUTES_STEP)) * MINUTES_STEP)


def better_on_both(players: list[dict], idx: list[int], x: str, y: str, mx, my,
                   rev_x: bool = False, rev_y: bool = False) -> list[int]:
    """Owner 2026-11-13: the plotted players better than BOTH medians, best first by
    x / median_x + y / median_y (ties by name), at most TOP_SHOWN. On a lower-is-better axis
    (`rev_*`) better = below the median and the term is median / value. Nobody when the plotted
    pool is below MIN_PEERS_FOR_RANKING (no ranking from a thin pool) or a median is not
    positive."""
    if len(idx) < MIN_PEERS_FOR_RANKING or mx is None or my is None or mx <= 0 or my <= 0:
        return []

    def term(v, med, rev):                     # None = not better than the median
        if rev:
            return med / v if 0 < v < med else None
        return v / med if v > med else None
    score = {}
    for i in idx:
        a, b = term(players[i]["v"][x], mx, rev_x), term(players[i]["v"][y], my, rev_y)
        if a is not None and b is not None:
            score[i] = a + b
    return sorted(score, key=lambda i: (-score[i], players[i]["name"]))[:TOP_SHOWN]


def scatter_summary(players: list[dict], x: str, y: str, band: str,
                    min_minutes: int = MIN_MINUTES[0], lower=None) -> dict:
    """The two-metric chart's plotted pool (rows with both values, in the age band, with at
    least `min_minutes`), the median of each axis over that pool, which axes are reversed
    (`rev`: lower is better, `lower` defaults to cf.LOWER_IS_BETTER) and the "Better on both"
    list (`better_on_both`); the browser numbers the first `top_marked` of `top` in red."""
    lower = cf.LOWER_IS_BETTER if lower is None else lower
    mm = min_minutes

    def enough(r):
        if mm <= MIN_MINUTES[0]:
            return True                        # the pool is already the 450+ rankable rows
        return r.get("mins") is not None and r["mins"] >= mm
    idx = [i for i, r in enumerate(players) if r["v"].get(x) is not None
           and r["v"].get(y) is not None and band in r["bands"] and enough(r)]
    mx = float(pd.Series([players[i]["v"][x] for i in idx]).median()) if idx else None
    my = float(pd.Series([players[i]["v"][y] for i in idx]).median()) if idx else None
    rev = {"x": x in lower, "y": y in lower}
    top = better_on_both(players, idx, x, y, mx, my, rev["x"], rev["y"])
    note = (None if top or not idx else thin_caption(len(idx)) if len(idx) < MIN_PEERS_FOR_RANKING
            else NOBODY_BETTER_ON_BOTH)
    return {"idx": idx, "top": top, "top_marked": TOP_MARKED, "top_note": note, "rev": rev,
            "median": {"x": mx, "y": my, "x_t": value_text(mx), "y_t": value_text(my)}}


# --- pools -------------------------------------------------------------------------------------
def pool_counts(pcts: pd.DataFrame) -> pd.DataFrame:
    """Players with a percentile per (league, position) and metric: the divisor
    `scorecard.metric_percentiles` used for that percentile."""
    cols = [k for k in KEYS if k in pcts.columns]
    return pcts.groupby(["competition_id", "position_group"])[cols].count()


def count_for(counts: pd.DataFrame, competition_id: int, position: str, metric: str) -> int:
    key = (int(competition_id), position)
    if key not in counts.index or metric not in counts.columns:
        return 0
    return int(counts.at[key, metric])


def pool_frame(cands: pd.DataFrame, values: pd.DataFrame, pcts: pd.DataFrame,
               competition_id: int, position: str) -> pd.DataFrame:
    """One league and position: the rankable players (`cands`) with tracking data, their values
    and (as `<metric>__pct`) their percentiles. Index 0..n-1."""
    c = cands[(cands["competition_id"] == competition_id) & (cands["position_group"] == position)]
    c = c[[x for x in _POOL_COLS if x in c.columns]]
    keys = [k for k in KEYS if k in values.columns]
    v = values[values["competition_id"] == competition_id][["player_id", "competition_id"] + keys]
    p = pcts[(pcts["competition_id"] == competition_id) & (pcts["position_group"] == position)]
    p = p[["player_id"] + [k for k in KEYS if k in p.columns]].rename(
        columns={k: f"{k}__pct" for k in KEYS})
    out = c.merge(v, on=["player_id", "competition_id"], how="left").merge(
        p, on="player_id", how="left")
    for k in KEYS:
        for col in (k, f"{k}__pct"):
            if col not in out.columns:
                out[col] = float("nan")
    out = out[out[keys].notna().any(axis=1)] if keys else out.iloc[0:0]
    return out.reset_index(drop=True)


def leaders(pool: pd.DataFrame, metric: str) -> dict:
    """The ranked list for one metric: {"n", "thin", "order": [[row, rank], ...]}. Ranked by
    percentile (so lower-is-better metrics put the quickest first), ties share the best rank.
    A pool below MIN_PEERS_FOR_RANKING is listed by name with no rank, and says why."""
    has = pool[pool[metric].notna()]
    n = int(len(has))
    if n < MIN_PEERS_FOR_RANKING:
        order = has.sort_values("player_name", kind="stable").index
        return {"n": n, "thin": thin_caption(n) if n else None,
                "order": [[int(i), None] for i in order]}
    pct = has[f"{metric}__pct"]
    ranks = pct.rank(ascending=False, method="min")
    order = has.assign(_p=pct).sort_values(["_p", "player_name"], ascending=[False, True],
                                           kind="stable").index
    return {"n": n, "thin": None,
            "order": [[int(i), None if pd.isna(ranks[i]) else int(ranks[i])] for i in order]}


def pool_players(pool: pd.DataFrame, counts: dict, orient_ids, href,
                 ranks: dict | None = None, matches: dict | None = None) -> list[dict]:
    """Rows for the page: name, club, age (the Players page's format), minutes, and per metric
    the value, its text and the percentile (None where the metric's pool is thin).
    `counts`: metric -> players with that metric in this pool. `href(p, c, s)` -> card link."""
    out = []
    ok = {k: counts.get(k, 0) >= MIN_PEERS_FOR_RANKING for k in KEYS}
    for r in pool.itertuples(index=False):
        rd = r._asdict()
        p, c, s = int(rd["player_id"]), int(rd["competition_id"]), int(rd["season_id"])
        age = rd.get("age")
        out.append({
            "name": str(rd["player_name"]), "club": None if _missing(rd["team_name"]) else str(rd["team_name"]),
            "age": DASH if _missing(age) else f"{float(age):.1f}",
            "mins": _num(rd["minutes"]), "mins_t": minutes_text(rd["minutes"]), "href": href(p, c, s), "orient": p in orient_ids,
            "v": {k: _num(rd[k]) for k in KEYS},
            "t": {k: value_text(rd[k]) for k in KEYS},
            "p": {k: pct_value(rd[f"{k}__pct"]) if ok[k] else None for k in KEYS},
            "bands": bands_of(age),
            "phys": (ranks or {}).get(p, {}).get("band"),
            "phys_t": (ranks or {}).get(p, {}).get("text", DASH),
            "matches": (matches or {}).get((p, c))})
    return out


# --- Leyton Orient's squad ---------------------------------------------------------------------
def squad_rows(squad: pd.DataFrame, rows: pd.DataFrame, values: pd.DataFrame,
               pcts: pd.DataFrame, counts: pd.DataFrame, league_names: dict, href,
               rank_of=None, matches: dict | None = None) -> list[dict]:
    """Every current Orient outfielder for the season. `squad` = `core.squad.squad()`; `rows` =
    `core.squad.rated_rows(season)` (his most-minutes row, the peer floor applied); the
    percentile is against that row's league and position. No rating and no percentiles from a
    thin peer pool; a metric whose own pool is thin has no percentile."""
    order = {p: i for i, p in enumerate(positions())}
    val = values.set_index(["player_id", "competition_id"])
    pct = pcts.set_index(["player_id", "competition_id", "position_group"])
    out = []
    for s in squad.itertuples(index=False):
        pid = int(s.player_id)
        r = rows.loc[pid] if pid in rows.index else None
        pos = str(r["position_group"]) if r is not None else str(s.position_group)
        if not cf.PHYSICAL_METRICS.get(pos):
            continue                                  # goalkeepers: no tracking data
        cells = {k: {"t": DASH, "v": None, "p": None} for k in RATED}
        row = {"name": str(s.player_name), "pos": pos, "league": None, "mins": None, "mins_t": DASH,
               "phys": None, "phys_t": DASH, "matches": None, "note": None, "href": None,
               "cells": cells,
               "_o": (order.get(pos, 99), )}
        if r is not None:
            comp = int(r["competition_id"])
            thin = bool(r["thin"])
            row["matches"] = (matches or {}).get((pid, comp))
            row.update(league=league_names.get(comp), mins=_num(r["minutes"]),
                       mins_t=minutes_text(r["minutes"]),
                       phys=None if thin else _num(r["physical_band"]))
            if rank_of is not None and not thin:
                row["phys_t"] = rank_of(pid, comp, pos)
            if thin and not _missing(r["peer_count"]):
                row["note"] = thin_caption(int(r["peer_count"]))
            sid = int(pcts["season_id"].iloc[0]) if len(pcts) else None
            vr = val.loc[(pid, comp)] if (pid, comp) in val.index else None
            pr = pct.loc[(pid, comp, pos)] if (pid, comp, pos) in pct.index else None
            if isinstance(vr, pd.DataFrame):
                vr = vr.iloc[0]
            if isinstance(pr, pd.DataFrame):
                pr = pr.iloc[0]
            for k in RATED:
                v = None if vr is None else vr.get(k)
                ok = (not thin and pr is not None
                      and count_for(counts, comp, pos, k) >= MIN_PEERS_FOR_RANKING)
                cells[k] = {"t": value_text(v), "v": _num(v),
                            "p": pct_value(pr.get(k)) if ok else None}
            if pr is not None and sid is not None:
                row["href"] = href(pid, comp, sid)
        out.append(row)
    out.sort(key=lambda x: (x["_o"][0], -(x["mins"] or -1), x["name"]))
    for x in out:
        del x["_o"]
    return out


def default_league(squad_ids, rows: pd.DataFrame, leagues: list[int]) -> int | None:
    """The league most of Orient's squad played in this season, among `leagues` (those with
    tracking data); else the first of `leagues`."""
    if not leagues:
        return None
    ids = [i for i in squad_ids if i in rows.index]
    comps = rows.loc[ids, "competition_id"].astype(int) if ids else pd.Series(dtype=int)
    comps = comps[comps.isin(leagues)]
    if comps.empty:
        return leagues[0]
    counts = comps.value_counts()
    return int(min(counts[counts == counts.max()].index, key=leagues.index))


# --- the squad card's "Performance" view (owner 2026-11-13) ----------------------------------
UNRATED_WHY = "(under 450 minutes or too few peers)"


def unrated_text(n: int, season_name: str) -> str | None:
    """The line under the Performance view; names the season shown (owner 2026-11-13)."""
    if not n:
        return None
    return f"{n} squad player{'' if n == 1 else 's'} not rated in {season_name} {UNRATED_WHY}"


def strong_weak(prow, metrics: list[str], label_for) -> dict:
    """Strongest / weakest over his rated metrics with a percentile: the card's Strengths /
    Watch-outs rule itself (`card.split_strong_weak`, one function so the two always agree)."""
    from lofc.core.card import split_strong_weak
    high, low = split_strong_weak(prow, metrics)
    item = lambda m, v: {"label": label_for(m), "pct": round(v)}
    return {"strong": [item(m, v) for m, v in high], "weak": [item(m, v) for m, v in low]}


def performance_rows(squad: pd.DataFrame, rows: pd.DataFrame, pcts: pd.DataFrame,
                     season_id: int, league_names: dict, href, season_name: str = "") -> dict:
    """Our current squad's RATED players (an Overall on his `rows` row: `core.squad.rated_rows`,
    the peer floor applied, as the Physical view and the workbook), grouped as Club vs League
    One groups positions (GK, CB, FB, Midfield, W, CF), best Overall first. Strongest / weakest
    three = `strong_weak` (the card's Strengths / Watch-outs order, no metric in both) over his
    position's Performance metrics (the card's list), from the scorecard percentiles `pcts` (league,
    position and season; lower-is-better already inverted, labelled "(fewer is better)").
    A player rated outside League One carries his league as `league` (his percentiles are vs
    that league). Unrated players are only counted."""
    from lofc.core.club_vs_league import GROUPS, LEAGUE_ONE, group_of, weak_label
    from lofc.dashboard.labels import LABELS
    from lofc.model.scorecard import _resolved_performance
    label = weak_label(lambda m: LABELS.get(m, m))
    if pcts is None or "player_id" not in getattr(pcts, "columns", []):
        pcts = pd.DataFrame(columns=["player_id", "competition_id"])
    sc = pcts[pcts["season_id"] == season_id] if "season_id" in pcts.columns else pcts
    sc = sc.drop_duplicates(["player_id", "competition_id"]).set_index(
        ["player_id", "competition_id"])
    groups: dict[str, list] = {g: [] for g in GROUPS}
    unrated = 0
    for s in squad.itertuples(index=False):
        pid = int(s.player_id)
        r = rows.loc[pid] if pid in rows.index else None
        if isinstance(r, pd.DataFrame):
            r = r.iloc[0]
        if r is None or _missing(r.get("objective_composite")) or bool(r.get("thin", False)):
            unrated += 1
            continue
        comp, pos = int(r["competition_id"]), str(r["position_group"])
        prow = sc.loc[(pid, comp)] if (pid, comp) in sc.index else None
        sw = strong_weak(prow, _resolved_performance(pos), label)
        league = None if comp == LEAGUE_ONE else league_names.get(comp, f"League {comp}")
        group = group_of(pos)
        groups.setdefault(group, []).append({
            "name": str(s.player_name), "href": href(pid, comp, season_id), "pos": pos,
            "pos_tag": pos if group != pos else None,
            "league": league, "league_tip": None if league is None else f"Percentiles vs {league} {pos}s",
            "mins": _num(r["minutes"]), "mins_t": minutes_text(r["minutes"]),
            "overall": _num(r["objective_composite"]), "perf": _num(r.get("performance_band")),
            "phys": _num(r.get("physical_band")),
            "strong": sw["strong"], "weak": sw["weak"]})
    out = []
    for g, rs in groups.items():
        if rs:
            rs.sort(key=lambda x: (-x["overall"], -(x["mins"] or 0), x["name"]))
            out.append({"group": g, "rows": rs})
    return {"groups": out, "unrated": unrated, "unrated_t": unrated_text(unrated, season_name)}


# --- "Download squad (Excel)" (owner R5) -------------------------------------------------------
EXPORT_COLUMNS = ["Player", "Position", "Age", "Contract until", "Minutes", "Overall",
                  "Performance", "Physical", "League One rank (position)", "Availability"]
EXPORT_SHEET = "Leyton Orient squad"
# owner R5: GK, CB, FB, midfield, W, CF
EXPORT_POSITION_ORDER = ["Goalkeeper", "Centre Back", "Full Back", "Defensive Mid", "Central Mid",
                         "Attacking Mid", "Winger", "Centre Forward"]
_WIDTHS = {"Player": 26, "Position": 16, "Age": 7, "Contract until": 15, "Minutes": 10,
           "Overall": 10, "Performance": 13, "Physical": 10, "League One rank (position)": 26,
           "Availability": 13}


def _rating(v) -> float | None:
    """Two decimals, half-up (the site's rating chips)."""
    from decimal import ROUND_HALF_UP, Decimal
    return None if _missing(v) else float(Decimal(repr(float(v))).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP))


def squad_export_rows(squad: pd.DataFrame, rows: pd.DataFrame, rank_of, availability_of,
                      age_of=None) -> list[dict]:
    """One row per current Orient player (goalkeepers too). `squad` = `core.squad.squad()`;
    `rows` = `core.squad.rated_rows(season)` (his most-minutes row, the peer floor applied: the
    ratings the page and the card show). `rank_of(pid, comp, pos)` -> (rank, n) among rated
    League One players at his position (`scorecard.rank_in_pool`); asked only for a rated
    League One row. `availability_of(pid, comp, minutes)` -> the card's availability (0-1) or
    None. `age_of(birth)` -> age (default `core.squad._age_now`, as Squads and Compare)."""
    from lofc.core.card import _half_up
    from lofc.core.club_vs_league import LEAGUE_ONE
    if age_of is None:
        from lofc.core.squad import _age_now as age_of
    order = {p: i for i, p in enumerate(EXPORT_POSITION_ORDER)}
    out = []
    for s in squad.itertuples(index=False):
        pid = int(s.player_id)
        r = rows.loc[pid] if pid in rows.index else None
        if isinstance(r, pd.DataFrame):
            r = r.iloc[0]
        pos = str(r["position_group"]) if r is not None else str(s.position_group)
        contract = getattr(s, "contract_until", None)
        row = {"Player": str(s.player_name), "Position": pos,
               "Age": age_of(getattr(s, "birth_date", None)),
               "Contract until": None if _missing(contract) else pd.Timestamp(contract).date(),
               "Minutes": None, "Overall": None, "Performance": None, "Physical": None,
               "League One rank (position)": None, "Availability": None}
        if r is not None:
            comp = int(r["competition_id"])
            minutes = None if _missing(r["minutes"]) else _half_up(r["minutes"])
            thin = bool(r.get("thin", False))
            row.update(Minutes=minutes,
                       Overall=None if thin else _rating(r["objective_composite"]),
                       Performance=None if thin else _rating(r["performance_band"]),
                       Physical=None if thin else _rating(r["physical_band"]))
            if comp == LEAGUE_ONE and row["Overall"] is not None:
                rank, n = rank_of(pid, comp, pos)
                if rank is not None:
                    row["League One rank (position)"] = f"{rank} of {n}"
            a = availability_of(pid, comp, None if _missing(r["minutes"]) else float(r["minutes"]))
            row["Availability"] = None if _missing(a) else float(a)
        out.append(row)
    out.sort(key=lambda x: (order.get(x["Position"], 99),
                            -(x["Overall"] if x["Overall"] is not None else -1), x["Player"]))
    return out


def squad_xlsx(rows: list[dict]) -> bytes:
    """The workbook: one sheet, bold frozen header, numbers as numbers."""
    import io

    from openpyxl import Workbook
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter
    wb = Workbook()
    ws = wb.active
    ws.title = EXPORT_SHEET
    ws.append(EXPORT_COLUMNS)
    for c in ws[1]:
        c.font = Font(bold=True)
    fmt = {"Age": "0.0", "Contract until": "dd mmm yyyy", "Minutes": "#,##0", "Overall": "0.00",
           "Performance": "0.00", "Physical": "0.00", "Availability": "0%"}
    for r in rows:
        ws.append([r[k] for k in EXPORT_COLUMNS])
        for i, k in enumerate(EXPORT_COLUMNS, start=1):
            if k in fmt and r[k] is not None:
                ws.cell(row=ws.max_row, column=i).number_format = fmt[k]
    for i, k in enumerate(EXPORT_COLUMNS, start=1):
        ws.column_dimensions[get_column_letter(i)].width = _WIDTHS[k]
    ws.freeze_panes = "A2"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
