"""The Compare page as plain data (TASKS 2.36): ONE implementation for Streamlit and the web.

Lifted from `dashboard/tabs/compare.py`, which now imports everything here and only draws it:
the slot defaults, the head-to-head rows, the season-change cell text, the radar inputs and the
Performance / Physical tables (`compare_view`). The web API (`web/api/compare.py`) calls the
same `compare_view` with the same frames, so both pages show identical figures and words.

Pure: inputs are frames and loader callables, outputs plain values. Display numbers are
formatted here (Python), never in the browser.
"""
from __future__ import annotations

import re

import pandas as pd

from lofc.dashboard import compare_tables as ct
from lofc.dashboard.formatting import value_or_dash
from lofc.model import club_framework as cf

DASH = "—"
NONE_OPTION = "— none —"                 # = dashboard.theme.NONE_OPTION (theme imports streamlit)
SLOT_KEYS = {"Player A": "cmp_a", "Player B": "cmp_b", "Player C": "cmp_c"}
KEYS = ["player_id", "competition_id", "season_id"]

# The page's messages (Streamlit's wording).
NO_PLAYERS = "No players for this season."
NEED_TWO = "Need at least two players in this position."
PICK_TWO = "Pick two different players to compare."
NO_DATA = "One of these players has no data for this season."
NOT_LIKE = "Compare like with like: these players are not all in one position."
SUMMARY_CAPTION = "Big number: this season. Small: change from last season (green up, red down)."
LEAGUES_NOTE = "Different leagues: percentiles are within each player's own league."


# --- slots ---------------------------------------------------------------------------------
def index_lookup(search_index: pd.DataFrame) -> dict:
    """The search index as dicts, built once per season by the web (each costs ~0.1 s):
    by_key (player, competition, season) -> label, and the labels of each position in order."""
    labels = search_index["label"].tolist()
    keys = zip(search_index["player_id"].astype(int).tolist(),
               search_index["competition_id"].astype(int).tolist(),
               search_index["season_id"].astype(int).tolist())
    by_pos: dict[str, list[str]] = {}
    for pos, lbl in zip(search_index["position_group"].tolist(), labels):
        by_pos.setdefault(pos, []).append(lbl)
    return {"by_key": dict(zip(keys, labels)), "by_position": by_pos,
            "row_of": {lbl: i for i, lbl in enumerate(labels)}}


def default_candidates(pool: pd.DataFrame, search_index: pd.DataFrame, position: str,
                       lookup: dict | None = None) -> list[str]:
    """Search labels to default A/B from: the pool in its (rating) order, then the rest of the
    position, so two defaults exist even when the sidebar filters leave fewer than two.
    `lookup`: `index_lookup(search_index)` when the caller keeps one (same result)."""
    lookup = lookup or index_lookup(search_index)
    by_key = lookup["by_key"]
    out = [by_key[k] for k in zip(pool["player_id"].astype(int), pool["competition_id"].astype(int),
                                  pool["season_id"].astype(int)) if k in by_key]
    return list(dict.fromkeys(out + lookup["by_position"].get(position, [])))


def fill_default_slots(state, labels: list[str]) -> None:
    """Give A and B a default when unset, never the same player as each other or as C
    (verifier, 2026-11-02: picking the player at index 1 into A left B defaulting to index 1)."""
    def taken(*keys):
        return {state.get(k) for k in keys if state.get(k) not in (None, NONE_OPTION)}
    if "cmp_a" not in state:
        skip = taken("cmp_b", "cmp_c")
        state["cmp_a"] = next((x for x in labels if x not in skip), labels[0])
    if "cmp_b" not in state:
        skip = taken("cmp_a", "cmp_c")
        state["cmp_b"] = next((x for x in labels if x not in skip), labels[0])


def sanitize_slots(state, labels: list[str]) -> None:
    """Drop slot values that are not of the sidebar's position (`labels` = that position's
    search labels), e.g. after the sidebar position changed, so they fall back to their default."""
    for key in SLOT_KEYS.values():
        if key in state and state[key] not in labels and state[key] != NONE_OPTION:
            if key == "cmp_c":
                state[key] = NONE_OPTION
            else:
                state.pop(key)


def same_position(frame: pd.DataFrame) -> bool:
    """True when every row is one position -- comparisons are strictly like-for-like."""
    return frame["position_group"].nunique(dropna=False) <= 1


def pick_row(key: tuple[int, int, int], pool: pd.DataFrame, candidates_fn, scorecards_fn,
             blank_unrated: bool = False) -> tuple[pd.Series | None, str]:
    """(row, reason) for a slot's player-season: from the filtered pool when he is in it,
    otherwise resolved from the season-wide data so a pick hidden by age / league / contract /
    minutes filters still shows (`search_target.resolve_search_target`). reason: "ok",
    "not_rated" or "not_found" (row None).

    `blank_unrated` (web page, owner decision D1 2026-11-09): a player with no scorecard or a
    peer pool below MIN_PEERS_FOR_RANKING has his ratings blanked -- a thin pool is never shown
    as a rating; his percentiles stay. Streamlit passes False (live site unchanged)."""
    from lofc.dashboard.search_target import SCORECARD_COLUMNS, resolve_search_target
    pid, cid, sid = (int(k) for k in key)
    hit = pool[(pool["player_id"] == pid) & (pool["competition_id"] == cid)
               & (pool["season_id"] == sid)]
    if not hit.empty:
        return hit.iloc[0], "ok"
    # Default wage multiplier: money columns are only shown when the sidebar money layer is on,
    # and the row is used for display, never for ranking.
    row, reason = resolve_search_target(candidates_fn(sid), scorecards_fn(sid), (pid, cid, sid))
    if row is not None and reason != "ok" and blank_unrated:
        row = row.copy()
        for col in SCORECARD_COLUMNS[len(KEYS):]:
            row[col] = float("nan")
        row["veto"] = row["below_min_composite"] = False
    return row, reason


def not_rated_caption(reason: str, peer_count, minutes) -> str | None:
    """The card's one line for a player without a rating (same words as the card)."""
    if reason == "ok":
        return None
    from lofc.core.card import thin_pool_caption, thin_pool_size
    from lofc.dashboard.search_target import search_caption
    n = thin_pool_size(reason, peer_count, minutes)
    return thin_pool_caption(n) if n is not None else search_caption("not_rated", True, minutes)


def vs_text(position: str, league, thin: int | None) -> str:
    """Who the percentiles are against: "League Two Wingers", or "8 Celtic League Wingers"
    for a thin pool (owner D1: the count goes in the heading)."""
    base = f"{league} {position}s"
    return f"{thin} {base}" if thin is not None else base


def vs_sub(named: list[tuple[str, str]]) -> str:
    """One line for a heading: the shared pool, or each pool with its players in brackets."""
    groups: dict[str, list[str]] = {}
    for name, vs in named:
        groups.setdefault(vs, []).append(name)
    if len(groups) == 1:
        return next(iter(groups))
    return " · ".join(f"{vs} ({', '.join(names)})" for vs, names in groups.items())


# --- the head-to-head table ------------------------------------------------------------------
# Colours for the season-change cells (readable on both light and dark themes).
UP_STYLE = "color: #1a9850; font-weight: 600"
DOWN_STYLE = "color: #d73027; font-weight: 600"
NEUTRAL_STYLE = "color: #888888"

# Physical axes of the radar: the rating's physical metrics, minus "Average match top speed"
# (psv99_kmh), which the Head of Recruitment does not want shown; top5 is labelled "Top speed".
PHYS_RADAR_LABEL = {
    "distance_p90": "Distance", "meters_per_minute": "Metres per minute",
    "hsr_count_p90": "High-speed runs", "hsr_distance_p90": "High-speed distance",
    "sprint_count_p90": "Sprints", "sprint_distance_p90": "Sprint distance",
    "top5_psv99_kmh": "Top speed",
}


def season_change(prev, now, fmt: str = "{:.2f}") -> str:
    """"3.41 → 3.68 (+0.27)". The change is taken from the displayed (rounded) numbers so the
    three figures always add up on screen. No previous season: this season's value alone."""
    now_txt = value_or_dash(now, fmt)
    if pd.isna(prev):
        return now_txt
    prev_txt = value_or_dash(prev, fmt)
    if pd.isna(now):
        return f"{prev_txt} → —"
    delta = float(fmt.format(now)) - float(fmt.format(prev))
    delta_txt = "0.00" if abs(delta) < 0.005 else f"{delta:+.2f}"
    return f"{prev_txt} → {now_txt} ({delta_txt})"


def change_style(cell) -> str:
    """CSS for a season-change cell: green if it rose, red if it fell, grey otherwise (equal,
    no previous season, blank). Reads the sign the text itself carries."""
    text = str(cell)
    if text.endswith("(0.00)") or not text.endswith(")"):
        return NEUTRAL_STYLE
    if "(+" in text:
        return UP_STYLE
    return DOWN_STYLE if "(-" in text else NEUTRAL_STYLE


# "3.41 (League Two) → 3.68 (+0.27)" -> prev, previous league, now, change. The text format is
# owned by `season_change`/`compare_row`, so this is the one place that reads it back.
CHANGE_RE = re.compile(r"^(?:(?P<prev>\S+?)(?: \((?P<lg>.+?)\))? → )?(?P<now>\S+?)"
                       r"(?: \((?P<delta>[+-]?\d+\.\d+|—)\))?$")
_TONE = {UP_STYLE: "up", DOWN_STYLE: "down", NEUTRAL_STYLE: "neutral"}


def change_parts(text: str) -> dict:
    """A value cell as {now, sub, tone}: this season's value (big), the change from last season
    (small; None when there is none) and its colour ("up" / "down" / "neutral"). Streamlit's
    cell HTML and the web page are both drawn from this."""
    m = CHANGE_RE.match(text)
    if not m:
        return {"now": text, "sub": None, "tone": None}
    now, prev, lg, delta = m["now"], m["prev"], m["lg"], m["delta"]
    sub = ""
    if delta == "—":            # not comparable (different rating parts): say so, no number
        sub = "—"
    elif prev is not None:
        was = prev + (f" ({lg})" if lg else "")
        if delta is None:
            sub = f"was {was}"
        else:
            sub = f"no change vs {was}" if delta == "0.00" else f"{delta} vs {was}"
    if not sub:
        return {"now": now, "sub": None, "tone": None}
    return {"now": now, "sub": sub, "tone": "neutral" if sub == "—" else _TONE[change_style(text)]}


TONE_STYLE = {"up": UP_STYLE, "down": DOWN_STYLE, "neutral": NEUTRAL_STYLE}

# Summary rows that are plain text (not "value + change vs last season"), in display order.
TEXT_ROWS_TOP = ()   # Club now / Contract to / Loan removed (owner, 2026-11-02)
TEXT_ROWS_BOTTOM = ("Overall trend", "Performance trend", "Physical trend",
                    "Playing style", "Scout verdicts")
TEXT_ROWS = TEXT_ROWS_TOP + TEXT_ROWS_BOTTOM


def summary_attributes(rows: list[dict]) -> list[str]:
    """The head-to-head's rows, in order, each shown only if any player has it."""
    return [k for k in ("Age", "Minutes", *TEXT_ROWS_TOP, "Overall", "Performance", "Physical",
                        "Market (€m)", *TEXT_ROWS_BOTTOM)
            if any(k in r for r in rows)]


def _half_up_int(v) -> str:
    """Whole minutes, .5 rounds UP (owner D2), with a thousands comma; "—" when missing."""
    return DASH if pd.isna(v) else f"{int(float(v) + 0.5):,}"


def compare_row(r: pd.Series, prev: pd.DataFrame | None, show_money: bool = False) -> dict:
    """One row of the head-to-head table. Every value is pre-formatted text with an em-dash
    fallback. Overall, Performance and Physical read "last season → this season (change)"."""
    prev_row = pd.Series(dtype=object)
    if prev is not None and not prev.empty:
        hit = prev[prev["player_id"] == int(r["player_id"])]
        if not hit.empty:
            prev_row = hit.iloc[0]
    league_now = r.get("league")

    # Overall = Performance + Physical. A change is only meaningful between seasons that both
    # have a physical band (2024/25 has none, so its rating is Performance only); otherwise
    # the change reads "—". Performance is comparable whenever both seasons have one.
    same_parts = pd.notna(prev_row.get("prev_physical")) and pd.notna(r.get("physical_band"))

    def cell(prev_col, now_col, league_note=False, needs_same_parts=False):
        if needs_same_parts and not prev_row.empty and not same_parts:
            now = r.get(now_col)
            return f"{value_or_dash(now, '{:.2f}')} (—)" if pd.notna(now) else "—"
        text = season_change(prev_row.get(prev_col), r.get(now_col))
        prev_league = prev_row.get("prev_league")
        # Only name the league when it differs: a move up or down a division changes what the
        # number means, so the reader needs to see it.
        if league_note and " → " in text and pd.notna(prev_league) and prev_league != league_now:
            head, tail = text.split(" → ", 1)
            text = f"{head} ({prev_league}) → {tail}"
        return text

    row = {"Player": r["player_name"], "Club": r["team_name"],
           "League": value_or_dash(r.get("league"), "{}"),
           "Age": value_or_dash(r.get("age"), "{:.1f}"),
           "Minutes": _half_up_int(r.get("minutes")),
           "Overall": cell("prev_composite", "objective_composite", True, True),
           "Performance": cell("prev_performance", "performance_band"),
           "Physical": cell("prev_physical", "physical_band", needs_same_parts=True)}
    if show_money:
        market_eur = r.get("market_value_eur")
        row["Market (€m)"] = value_or_dash(
            market_eur / 1e6 if pd.notna(market_eur) else market_eur, "{:.1f}")
    return row


def safe(fn, default):
    """A display extra must never take the page down: any failure reads as "no data"."""
    try:
        return fn()
    except Exception:                                     # noqa: BLE001
        return default


def summary_extras(r: pd.Series, ctx: dict) -> dict:
    """The history / style / scout rows of one player's summary column. `ctx` holds the
    already-loaded frames, keyed by player id; every value is text, a missing source "—"."""
    pid, cid, sid = int(r["player_id"]), int(r["competition_id"]), int(r["season_id"])
    hist = ctx.get("history", {}).get(pid, {})
    by_season = {**hist, sid: (r.get("objective_composite"), r.get("performance_band"),
                               r.get("physical_band"), r.get("league"))}
    return {
        **ct.rating_trend_rows(by_season, [sid - 2, sid - 1, sid],
                               no_physical_seasons=ctx.get("no_physical", ()),
                               current_league=r.get("league")),
        "Playing style": ct.style_text(ctx.get("styles", {}).get((pid, cid))),
        "Scout verdicts": ct.scout_text(ctx.get("scouts", {}).get(pid)),
    }


def extras_context(pids: tuple[int, ...], season_id: int, styles_fn, history_fn, scouts_fn,
                   names_fn) -> dict:
    """What the extra summary rows read, narrowed to the compared players. The loaders are
    passed in: Streamlit gives its cached loaders, the web its version-keyed copies."""
    styles = safe(lambda: styles_fn(season_id), pd.DataFrame())
    hist = safe(lambda: history_fn(season_id), pd.DataFrame())
    scouts = safe(lambda: scouts_fn(pids), pd.DataFrame())
    ctx: dict = {"styles": {}, "history": {}, "scouts": {},
                 "no_physical": ct.seasons_without_physical(hist) if not hist.empty else []}
    if not styles.empty and "player_id" in styles.columns:
        st_rows = styles[styles["player_id"].isin(pids)]
        ctx["styles"] = {(int(x["player_id"]), int(x["competition_id"])): x
                         for _, x in st_rows.iterrows()}
    if not hist.empty:
        names = names_fn()
        for pid, grp in hist[hist["player_id"].isin(pids)].groupby("player_id"):
            # One entry per season; the grouped rows are already the league with most minutes.
            ctx["history"][int(pid)] = {
                int(x.season_id): (x.objective_composite, x.performance_band, x.physical_band,
                                   names.get(int(x.competition_id)))
                for x in grp.sort_values("season_id").itertuples()}
    if not scouts.empty:
        for pid, grp in scouts.groupby("player_id"):
            ctx["scouts"][int(pid)] = list(grp["verdict"])
    return ctx


# --- radars ----------------------------------------------------------------------------------
def physical_radar_metrics(pcts_by_label: dict, position: str):
    """(metric keys, traces, missing) for the physical radar.

    Axes are the rating's physical metrics (club_framework.PHYSICAL_METRICS) minus psv99_kmh,
    present for EVERY player who has data. A player with fewer than three physical percentiles
    (SkillCorner does not cover everyone) is returned in `missing`, not plotted."""
    metrics = [m for m in cf.PHYSICAL_METRICS.get(position, []) if m in PHYS_RADAR_LABEL]
    if not metrics:
        return [], [], []
    have, missing = {}, []
    for name, s in pcts_by_label.items():
        vals = {m: s[m] for m in metrics if s is not None and m in s.index and pd.notna(s[m])}
        if len(vals) >= 3:
            have[name] = vals
        else:
            missing.append(name)
    shared = [m for m in metrics if all(m in v for v in have.values())] if have else []
    if len(shared) < 3:
        return [], [], missing + ([] if not have else list(have))
    return shared, [(n, [float(v[m]) for m in shared]) for n, v in have.items()], missing


def physical_radar_inputs(pcts_by_label: dict, position: str):
    """`physical_radar_metrics` with the axes as display labels (the Streamlit chart)."""
    keys, traces, missing = physical_radar_metrics(pcts_by_label, position)
    return [PHYS_RADAR_LABEL[m] for m in keys], traces, missing


def no_physical_caption(names: list[str]) -> str:
    return "No physical data: " + ", ".join(names)


# --- the whole page --------------------------------------------------------------------------
def mv_series(metric_values: pd.DataFrame | None, r: pd.Series) -> pd.Series | None:
    """The player's per-90 / physical values in his league (None when not held)."""
    if metric_values is None or metric_values.empty:
        return None
    mv = metric_values[(metric_values["player_id"] == int(r["player_id"]))
                       & (metric_values["competition_id"] == int(r["competition_id"]))]
    return mv.iloc[0] if not mv.empty else None


def display_names(recs: list) -> list[str]:
    """Column heads: the name, plus the club only when two players share a name."""
    raw = [r["player_name"] for r in recs]
    return [f'{n} ({r["team_name"]})' if raw.count(n) > 1 else n for n, r in zip(raw, recs)]


def compare_view(recs: list, position: str, archetype: str, show_money: bool,
                 metric_values: pd.DataFrame | None, sc_pcts: pd.DataFrame,
                 prev: pd.DataFrame | None, ctx: dict) -> dict:
    """Everything below the slot pickers, for 2-3 resolved player rows of one position.
    Percentiles come from the scorecard (position + league + season), the same source the
    player profile and the composite use, so Compare agrees with the rest of the platform."""
    from lofc.dashboard.seasons import season_name_for
    from lofc.dashboard.tabs.players import _sc_pct_series
    names = display_names(recs)
    pcts = {n: _sc_pct_series(sc_pcts, int(r["player_id"]), int(r["competition_id"]),
                              int(r["season_id"])) for n, r in zip(names, recs)}
    values = {n: mv_series(metric_values, r) for n, r in zip(names, recs)}
    rows = [{**compare_row(r, prev, show_money), **summary_extras(r, ctx)} for r in recs]
    lens = archetype != cf.DEFAULT_ARCHETYPE
    has_physical = bool(cf.PHYSICAL_METRICS.get(position))
    axes, traces, no_data = ct.radar_inputs(pcts, ct.radar_metrics(position, archetype))
    phys_keys, phys_traces, no_phys = (physical_radar_metrics(pcts, position) if has_physical
                                       else ([], [], []))
    rated = ct.rating_metrics(position, archetype)
    tiers = dict(rated)
    value_cols = metric_values.columns if metric_values is not None else []
    other = ct.other_performance_metrics(
        position, archetype, [m for m in sc_pcts.columns if m in value_cols])
    phys_rows = (ct.build_rows(ct.physical_rating_metrics(position), {}, names, values,
                               pcts, drop_empty=True) if has_physical else [])
    return {
        "names": names, "pcts": pcts, "values": values, "rows": rows,
        "note": ct.comparison_note([season_name_for(s_) for s_ in ctx["no_physical"]]),
        "lens": lens, "has_physical": has_physical,
        "different_leagues": len({int(r["competition_id"]) for r in recs}) > 1,
        "perf_heading": "Performance" + (f" · {archetype}" if lens else ""),
        "radar": {"axes": axes, "traces": traces, "no_data": no_data},
        "phys_radar": {"axes": phys_keys, "traces": phys_traces, "no_data": no_phys},
        "perf_rows": ct.build_rows([m for m, _ in rated], tiers, names, values, pcts),
        "other_rows": ct.build_rows(other, {}, names, values, pcts, drop_empty=True),
        "phys_rows": phys_rows,
        "phys_more": (ct.build_rows(ct.other_physical_metrics(position), {}, names, values,
                                    pcts, drop_empty=True) if phys_rows else []),
    }


# --- packing zones ---------------------------------------------------------------------------
def zone_measures(recs: list, slice_fn) -> dict:
    """{family: [cells or None per player]} for every measure, built with `compare_tables`'
    own `zone_cells` (per 90, the card's formatting). `slice_fn(row)` returns his zone rows
    (Streamlit: `compare_tables._zone_slice`; web: `core.detail_store`, the same rows)."""
    slices = [slice_fn(r) for r in recs]
    if all(s.empty for s in slices):
        return {}
    return {fam: [ct.zone_cells(s, fam) for s in slices] for fam in ct.ZONE_FAMILIES}
