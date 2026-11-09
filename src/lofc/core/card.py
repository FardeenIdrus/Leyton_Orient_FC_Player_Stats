"""The player card as plain data (TASKS 2.36): everything the Streamlit card decides, with no
page in it, so the web card and the Streamlit card show identical figures and words.

Two halves:

* PURE builders (top of the file): take plain values / frames and return plain values. Lifted
  from `dashboard/tabs/players.py::_render_profile_body`, `player_header.py` and
  `assessment_detail.py`, which now call them -- so there is ONE place that decides, e.g., the
  contract chip's wording or which season-output tiles a goalkeeper gets.
* `build_card` (bottom): fetches through the SAME cached loaders as the Streamlit card and
  assembles one JSON-ready dict. It calls the existing pure functions (`attach_season_scores`,
  `_grand_table`, `rank_in_pool`, ...) rather than recomputing anything.

Heavy imports (loaders, the Streamlit tab) are inside the functions: `dashboard.player_header`
imports the pure half of this module, so a module-level import back into `dashboard` would be a
cycle. Display text carries `**bold**` markers where the Streamlit text had them; pages turn
those into <b> after escaping.
"""
from __future__ import annotations

import datetime
import math

import pandas as pd

from lofc.core import detail_store, webcache
from lofc.model import club_framework as cf

DASH = "—"


# --- long-lived copies of the 60-second scorecard loaders -----------------------------------
# `load_scorecards`, `load_scorecards_archetype` and `_stored_scorecards` live 60 s because the
# Players table shows `assessed_composite`, which changes as scouts work. The card reads only the
# pipeline-written bands, ranks and flags from them, so it keeps them in process until the data
# version changes (`webcache`: any write to player_scorecards changes it): the first card after
# a quiet minute no longer pays ~2 s to rebuild a frame that has not changed.
@webcache.versioned(maxsize=8)
def stored_scorecards(season_id: int | None = None) -> pd.DataFrame:
    from lofc.dashboard import loaders as L
    return L._stored_scorecards(season_id)


def ranking_for(position: str, lens: str, season_id: int) -> pd.DataFrame:
    """The scorecard rows of the player's own position pool (every league) for the season, on
    `lens` -- what the Players page ranks from, narrowed to the one position the card needs
    (peer counts and "Nth of M" are per league and position anyway). Read straight from
    `player_scorecards` rather than through `load_scorecards_archetype`, which rebuilds the
    season's whole frame for every lens (~4 s cold). A lens that is not stored falls back to
    the default, as `loaders._build_scorecard_frame` does."""
    return _ranking(position, lens, int(season_id))


@webcache.versioned(maxsize=96)        # every position x lens x season, with room to spare
def _ranking(position: str, lens: str, season_id: int) -> pd.DataFrame:
    return _ranking_sql(position, lens, season_id)


def _ranking_sql(position: str, lens: str, season_id: int) -> pd.DataFrame:
    from lofc.dashboard import loaders as L
    engine = L.get_engine()
    sql = ("SELECT * FROM player_scorecards WHERE season_id = %(s)s AND position_group = %(p)s "
           "AND archetype = %(a)s")
    out = pd.read_sql(sql, engine, params={"s": season_id, "p": position, "a": lens})
    if out.empty and lens != cf.DEFAULT_ARCHETYPE:
        out = pd.read_sql(sql, engine, params={"s": season_id, "p": position,
                                               "a": cf.DEFAULT_ARCHETYPE})
    return out


# --- small shared helpers ----------------------------------------------------------------
def _missing(v) -> bool:
    if v is None or v is pd.NaT or v is pd.NA:
        return True
    try:
        return bool(pd.isna(v))
    except (TypeError, ValueError):
        return False


def text_or(value, blank: str) -> str:
    """`str(value)`, or `blank` when it is missing or empty. (`value or blank` lets NaN
    through -- NaN is truthy -- and the page then shows "nan".)"""
    return blank if _missing(value) or str(value) == "" else str(value)


def thin_pool_size(reason: str, peer_count, minutes) -> int | None:
    """His league-position pool size when that is why he is not rated (fewer than
    MIN_PEERS_FOR_RANKING), else None -- not for the under-450-minutes case."""
    from lofc.model.scorecard import MIN_PEERS_FOR_RANKING
    if reason != "not_rated" or _missing(peer_count) or (not _missing(minutes) and float(minutes) < 450):
        return None
    n = int(peer_count)
    return n if n < MIN_PEERS_FOR_RANKING else None


def thin_pool_caption(n: int) -> str:
    from lofc.model.scorecard import MIN_PEERS_FOR_RANKING
    return f"Not rated: only {n} comparable players (needs {MIN_PEERS_FOR_RANKING})"


def csv_disposition(name: str) -> str:
    """Content-Disposition for a download whose name may hold any letter ("Baran_Yıldız..."):
    an ASCII-folded `filename` for old clients plus the exact UTF-8 `filename*` (RFC 6266 /
    5987). A header must be Latin-1, so the raw name alone made the response fail (500)."""
    import unicodedata
    from urllib.parse import quote
    ascii_name = unicodedata.normalize("NFKD", name.replace("ı", "i")).encode(
        "ascii", "ignore").decode("ascii").replace('"', "").replace("\\", "") or "download.csv"
    return f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{quote(name, safe="")}'


def _half_up(value) -> int:
    """Whole number, .5 rounds UP (same rule as `loaders.round_half_up`)."""
    return int(float(value) + 0.5)


def gap_to_ours(his, ours) -> int | None:
    """His percentile minus our position median's, in whole points, .5 rounding UP (also
    for negatives: -10.5 -> -10). None when either is missing."""
    import math
    if his is None or ours is None:
        return None
    his, ours = float(his), float(ours)
    if math.isnan(his) or math.isnan(ours):
        return None
    return int(math.floor(his - ours + 0.5))


def vs_ours_column(metrics, prow, orient: dict, thin) -> list:
    """The "vs ours" cell per metric (TASKS 2.36 U15): `gap_to_ours` of his scorecard
    percentile and the Leyton Orient median the radar draws (`squad.orient_median`). All
    blank for a thin peer pool, whose percentiles are not a rating."""
    out = []
    for m in metrics:
        his = None if thin is not None or prow is None or m not in prow.index else prow[m]
        out.append(gap_to_ours(his, orient.get(m)) if his is not None else None)
    return out


def vs_ours_help(position: str, n_orient: int) -> str | None:
    if not n_orient:
        return None
    return (f"Gap to our current {position}s' median "
            f"({n_orient} player{'' if n_orient == 1 else 's'}). "
            "Percentiles are within each player's own league.")


def weight_tiers(metrics, position: str, lens: str) -> list:
    """Each metric's weight tier in the rating (High / Mid / Low, `compare_tables.rating_metrics`)."""
    from lofc.dashboard import compare_tables as ct
    tier = dict(ct.rating_metrics(position, lens))
    return [tier.get(m) for m in metrics]


def clean(obj):
    """JSON-safe copy: numpy scalars -> Python, NaN/NaT -> None, Timestamps -> ISO text,
    tuples/sets -> lists. The API's rule: a blank is null, never "nan" or "None"."""
    import numpy as np
    if isinstance(obj, dict):
        return {str(k): clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [clean(v) for v in obj]
    if isinstance(obj, (pd.Timestamp, datetime.datetime, datetime.date)):
        return None if _missing(obj) else pd.Timestamp(obj).strftime("%Y-%m-%d")
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, (float, np.floating)):
        return None if not math.isfinite(float(obj)) else float(obj)
    if obj is pd.NaT or obj is pd.NA:
        return None
    return obj


# --- header: register, contract / loan chips, minutes by position -------------------------
_OTHER_TONES = ["#6E747C", "#8B9199", "#A8ADB4", "#C3C7CC"]      # as player_header
ASSIGNED_TONE = "#C8102E"


def register_cells(row) -> list[tuple[str, str | None]]:
    """The five-cell register (label, text or None). None reads "not recorded" on the page --
    an absent value says so in words and never renders as 0 or '-'."""
    def text(key, fmt=None):
        v = row.get(key)
        if v is None or (not isinstance(v, str) and pd.isna(v)):
            return None
        return fmt(v) if fmt else str(v)

    return [
        ("Age", text("age", lambda v: f"{float(v):.1f}")),
        ("Foot", text("foot", lambda v: str(v).capitalize())),
        ("Height", text("height_cm", lambda v: f"{int(v)} cm")),
        # Contract is the chip beside it (date AND time left), so it is not repeated here.
        ("Nationality", text("nationality")),
        ("Minutes", text("minutes", lambda v: f"{_half_up(v):,}")),
    ]


def months_to(when, today: datetime.date | None = None) -> int | None:
    """Whole months from today to `when`, or None. Negative means already expired.

    pd.isna FIRST and unconditionally: `pd.NaT` passes `isinstance(x, datetime.datetime)`, so
    guarding on the type before the null check let NaT through and broke the card for anyone
    with no contract date."""
    if when is None:
        return None
    try:
        if pd.isna(when):
            return None
    except (TypeError, ValueError):
        return None
    end = pd.Timestamp(when).date()
    today = today or datetime.date.today()
    return (end.year - today.year) * 12 + (end.month - today.month)


def contract_chip(contract_until, today: datetime.date | None = None) -> dict:
    """Contract runway as chip parts: [(text, bold)], plus `expiring` (red) when under 12
    months or already expired. The runway is given in months as well as a date: "Jun 2027" does
    not read as urgent, "9m left" does."""
    months = months_to(contract_until, today)
    if months is None:
        return {"parts": [("Contract ", False), ("not recorded", True)], "expiring": False}
    when = pd.Timestamp(contract_until).strftime("%b %Y")
    if months < 0:
        return {"parts": [("Contract ", False), ("expired", True), (f" ({when})", False)],
                "expiring": True}
    years, rem = divmod(months, 12)
    length = (f"{years}y {rem}m" if years and rem else f"{years}y" if years else f"{rem}m")
    return {"parts": [("Contract to ", False), (when, True), (f" · {length} left", False)],
            "expiring": months < 12}


def loan_chip(loan) -> dict | None:
    """"On loan from <parent> · until Mon YYYY" as chip parts; None when he is not on loan.
    Not season-scoped: whether he is on loan today is what a January decision turns on."""
    if loan is None or not len(loan):
        return None
    parent, ends = loan.get("parent_club"), loan.get("loan_ends")
    parts = [("On loan", False)]
    if parent and not _missing(parent):
        parts += [(" from ", False), (str(parent), True)]
    if ends is not None and not _missing(ends):
        parts.append((f" · until {pd.Timestamp(ends).strftime('%b %Y')}", False))
    return {"parts": parts}


def minutes_split(shares: pd.DataFrame | None, assigned: str) -> dict | None:
    """Minutes by position: the segments (share in percent, minutes, goals), the colour of
    each (club red = the position he is SCORED as, greys for the rest) and the goals line.
    None when there is no split worth drawing -- a player who filled one position all season."""
    if shares is None or len(shares) < 2:
        return None
    other = iter(_OTHER_TONES)
    segs = []
    for r in shares.itertuples():
        is_assigned = r.position_group == assigned
        segs.append({"position": r.position_group, "share_pct": float(r.share) * 100.0,
                     "minutes": None if _missing(r.minutes) else float(r.minutes),
                     "assigned": is_assigned,
                     "colour": ASSIGNED_TONE if is_assigned else next(other, _OTHER_TONES[-1])})
    goals = [(r.position_group, float(r.goals)) for r in shares.itertuples()
             if pd.notna(r.goals) and float(r.goals) >= 0.5]
    goals_line = None
    if len(goals) > 1 or (goals and shares.iloc[0]["position_group"] != goals[0][0]):
        goals_line = "Goals: " + " · ".join(f"{g:.0f} as {p.lower()}" for p, g in goals)
    return {"segments": segs, "goals_line": goals_line}


def scored_as_notice(shares: pd.DataFrame | None) -> str | None:
    """The label names ONE position; for about one player in ten it covers under half his
    season, and every percentile is against that group's peers -- said plainly."""
    if shares is not None and len(shares) > 1 and shares.iloc[0]["share"] < 0.5:
        return (f"Scored as **{shares.iloc[0]['position_group']}** — his largest position, "
                f"but only {shares.iloc[0]['share'] * 100:.0f}% of his minutes. Every "
                f"percentile below compares him with players in that position.")
    return None


def other_league_notes(others, league_name) -> list[str]:
    """One line per other competition he played in this season. A loanee gets a row and a
    score in each league (a percentile is league-relative); labelled, it is a level-step
    signal rather than a duplicate. `league_name(competition_id) -> str | None`."""
    out = []
    for o in others.itertuples():
        league = league_name(int(o.competition_id)) or f"competition {o.competition_id}"
        comp = (f" — rated **{o.objective_composite:.2f}** there"
                if pd.notna(o.objective_composite) else "")
        out.append(f"Also played {o.minutes:,.0f} min for {o.team_name} in "
                   f"**{league}** this season{comp}. Same player, scored separately "
                   f"because percentiles are league-relative.")
    return out


# --- rating block --------------------------------------------------------------------------
COMPOSITE_HELP = ("The club's objective composite (1-5): Performance + Physical, from real "
                  "data. The figure beneath it is his standing among players in the SAME "
                  "league, season and position — the group the composite is a percentile "
                  "within, and the only group it can honestly be ranked in.")
PERFORMANCE_HELP = "The club-framework Performance dimension (1-5)."
PHYSICAL_HELP = "The club-framework Physical dimension (1-5), where tracking data exists."


def rank_text(rank, peers) -> str | None:
    """"3rd of 92 in this league" -- the same words as the report, from `rank_in_pool`."""
    if rank is None:
        return None
    from lofc.report.render import ordinal
    return f"{rank}{ordinal(rank)} of {peers} in this league"


def money_block(row, show_money: bool) -> dict | None:
    """Market / fair value tiles and the modelled-wage and fair-value captions, as the
    Streamlit card words them. None when the affordability layer is off. With it on but no
    market value, only the one-line quality-view note."""
    if not show_money:
        return None
    if _missing(row.get("market_value_eur")):
        return {"tiles": [], "captions": [
            "No market-value or wage data for this league (Scottish / PL2 aren't priced) — "
            "this is a quality view."]}
    fair = row.get("fair_value_eur")
    captions = []
    if not _missing(row.get("estimated_weekly_wage_gbp")) and not _missing(row.get("wage_ceiling_gbp")):
        captions.append(f"Modelled weekly wage £{int(row['estimated_weekly_wage_gbp']):,} vs the "
                        f"wage cap £{int(row['wage_ceiling_gbp']):,} for this player — modelled "
                        "estimate, not an actual salary.")
    if int(row["competition_id"]) == 65 and not _missing(fair):
        captions.append("⚠️ Fair-value note: Transfermarkt prices very few National League "
                        "players, so fair values in this league carry extra uncertainty — trust "
                        "the direction, not the figure.")
    return {"tiles": [
        {"label": "Market value", "value": f"€{row['market_value_eur'] / 1e6:.1f}m"},
        {"label": "Fair value", "value": f"€{fair / 1e6:.1f}m" if not _missing(fair) else "n/a"}],
        "captions": captions}


# The six dimensions `veto` can trip on (scorecard.py's dim_bands), in the club's order, with
# the column each lives in on a scored row. Financial Fit and Resale Potential are MODELLED
# (market value / wage estimates): with the affordability layer off neither is on screen.
VETO_DIMENSIONS = [
    (cf.PERFORMANCE, "performance_band"), (cf.PHYSICAL, "physical_band"),
    (cf.FINANCIAL, "financial_band"), (cf.RESALE, "resale_band"),
    (cf.PSYCHOLOGICAL, "psychological_band"), (cf.MEDICAL, "medical_band")]
MODELLED_DIMENSIONS = {cf.FINANCIAL, cf.RESALE}


def veto_reasons(row, include_modelled: bool = True) -> list[str]:
    """Which dimension(s) tripped the veto flag, and by how much -- e.g. 'Resale Potential
    1.58 is below the club minimum of 2.00'. A dimension whose band is absent from `row` is
    skipped, never guessed. With modelling off, Financial / Resale are left out: 40% of the
    flagged players trip only on those two, and an advisory pointing at a number the reader
    has hidden is unexplainable."""
    return [f"{label} {value:.2f} is below the club minimum of {cf.VETO_BAND:.2f}"
            for label, col in VETO_DIMENSIONS
            if include_modelled or label not in MODELLED_DIMENSIONS
            for value in [row.get(col)] if pd.notna(value) and value < cf.VETO_BAND]


def advisory_flags(row, show_money: bool) -> list[str]:
    """Plain-text advisory lines (never exclusions). A veto names its dimension; with the
    affordability layer off a flag that trips only on Financial / Resale says nothing rather
    than falling through to the generic line."""
    flags: list[str] = []
    composite = row.get("objective_composite")
    if row.get("veto"):
        reasons = veto_reasons(row, include_modelled=bool(show_money))
        if reasons:
            flags.extend(reasons)
        elif show_money:
            flags.append("below the club minimum (band < 2.0) on a dimension — "
                         "detail unavailable on this view")
    if row.get("below_min_composite"):
        flags.append(f"Composite {composite:.2f} is below the club's {cf.MIN_COMPOSITE:.2f} "
                     "minimum standard" if pd.notna(composite)
                     else f"composite below the club's {cf.MIN_COMPOSITE:.2f} minimum standard")
    return flags


ADVISORY_TITLE = "Advisory — informational only, the player is not excluded."


def strengths_watchouts(pcts, metrics: list[str], label_for) -> dict | None:
    """Top-3 and bottom-3 percentiles among the metrics that build his rating; None with
    fewer than two. `pcts` is his scorecard-percentile row -- the same numbers as the
    scorecard table, so the card never shows two percentiles for one metric."""
    if pcts is None:
        return None
    pairs = [(m, float(pcts[m])) for m in metrics if m in pcts.index and pd.notna(pcts[m])]
    if len(pairs) < 2:
        return None
    high = sorted(pairs, key=lambda x: x[1], reverse=True)[:3]
    low = sorted(pairs, key=lambda x: x[1])[:3]
    item = lambda m, v: {"metric": label_for(m), "pct": round(v)}
    return {"strengths": [item(m, v) for m, v in high], "watch_outs": [item(m, v) for m, v in low]}


# --- season output ---------------------------------------------------------------------------
def season_output_tiles(role: str, row, mv, metric_values: pd.DataFrame) -> dict:
    """The role's raw output tiles: goals mean nothing on a goalkeeper's card, save % nothing
    on a striker's. Each tile has the `slot` (0-2) of the three-column row it sits in on the
    Streamlit card. A role whose tiles are all retired gets the explanatory `note` instead of
    empty tiles. Returns {"tiles": [...], "note": str | None}."""
    from lofc.dashboard.tabs.players import (_output_tile_plan, empty_tile_note,
                                             season_total_count, whole_minutes)
    minutes = float(row["minutes"]) if pd.notna(row.get("minutes")) else 0.0

    def total(per90_col: str) -> str:
        value = mv.get(per90_col)
        return f"{_half_up(float(value) * minutes / 90):,}" if pd.notna(value) and minutes else DASH

    tiles, note = [], None
    if role == "goalkeeper":
        # save_pct / gk_saves_p90 are retired columns, NULL for every goalkeeper now Impect is
        # the spine: `_output_tile_plan` skips what nobody holds and self-heals if it returns.
        plan = _output_tile_plan(role, metric_values)
        if plan.get("save_pct"):
            sp = mv.get("save_pct")
            tiles.append({"slot": 0, "label": "Save %",
                          "value": f"{float(sp) * 100:.0f}%" if pd.notna(sp) else DASH})
        if plan.get("gk_saves_p90"):
            tiles.append({"slot": 1, "label": "Saves", "value": total("gk_saves_p90")})
        if not any(plan.values()):
            note = empty_tile_note(role)
    elif role == "defender":
        plan = _output_tile_plan(role, metric_values)
        if plan.get("tackles_p90"):
            tiles.append({"slot": 0, "label": "Tackles", "value": total("tackles_p90")})
        if plan.get("interceptions_p90"):
            tiles.append({"slot": 1, "label": "Interceptions", "value": total("interceptions_p90")})
        if not any(plan.values()):
            note = empty_tile_note(role)
    else:
        # EFL rows carry raw season totals; other leagues fall back to the per-90-derived
        # total. Assists prefer the Impect-derived figure (what Season by season shows).
        goals = season_total_count(row.get("goals"), mv.get("goals_p90"), minutes, False)
        assists = season_total_count(row.get("assists"), mv.get("assists_p90"), minutes, True)
        tiles += [{"slot": 0, "label": "Goals", "value": f"{goals:,}"},
                  {"slot": 1, "label": "Assists", "value": f"{assists:,}"}]
    tiles.append({"slot": 2, "label": "Minutes",
                  "value": f"{whole_minutes(row['minutes']):,}" if pd.notna(row.get("minutes"))
                  else DASH})
    return {"tiles": tiles, "note": note}


def underlying_rates_caption(role: str, row) -> str | None:
    """The live (Streamlit) card's sentence -- unchanged; the web card uses `underlying_rates`."""
    npxg, xa = row.get("np_xg_p90"), row.get("xa_p90")
    if role in ("midfielder", "attacker") and pd.notna(npxg) and pd.notna(xa):
        return (f"Underlying rates: {npxg:.2f} non-pen xG per 90 · {xa:.2f} xA per 90 — these "
                "(not raw goals/assists) drive the scores, because they're steadier season to "
                "season.")
    return None


def underlying_rates(role: str, row) -> dict | None:
    """Season output's underlying rates as two tiles and one short line (text rule, 2.36)."""
    npxg, xa = row.get("np_xg_p90"), row.get("xa_p90")
    if role in ("midfielder", "attacker") and pd.notna(npxg) and pd.notna(xa):
        return {"tiles": [{"label": "npxG/90", "value": f"{npxg:.2f}"},
                          {"label": "xA/90", "value": f"{xa:.2f}"}],
                "line": "These rates, steadier than raw goals and assists, drive the scores."}
    return None


# --- availability, short form (text rule, 2.36): the facts of dashboard.evidence's captions
# (shared with the live site, unchanged) as a label and at most one line each.
def availability_label(window) -> str:
    return "Available, " + " + ".join(window)


def availability_line(ev) -> str | None:
    """The one line the figure needs, or None when the figure and its labels say it all."""
    from lofc.model.medical import AvailabilityStatus
    if ev.status is AvailabilityStatus.UNKNOWN:
        return ("Not known: no injury record, and his minutes do not confirm it — a data gap, "
                "not a clean record.")
    if ev.status is AvailabilityStatus.CONFIRMED_BY_MINUTES:
        return "Available: no injury record, and his minutes rule out a long absence."
    if ev.value is None:
        return "Injury record present; availability is not scored for this competition."
    return None


def coverage_line(figures) -> str:
    """`store.injuries.COVERAGE[competition]` in one line."""
    if figures is None:
        return "No injury coverage figure for this league: an empty record says nothing."
    line = f"League injury coverage: {figures['with_record']:.0%} of players have a record"
    if figures.get("knowable") is not None:
        line += f" · availability knowable for about {figures['knowable']:.0%}"
    return line


def trajectory_view(rows: pd.DataFrame, role: str) -> pd.DataFrame:
    """The season table: ratings (already attached, `Overall` already blanked for a season
    with no physical data) plus the role's own columns. Minutes round half up; goals and
    assists are Impect's, as `loaders.load_trajectory` supplies them."""
    from lofc.dashboard.tabs.players import whole_minutes
    view = pd.DataFrame({
        "Season": rows["season_name"].str.replace("/20", "/", regex=False),
        "League": rows["competition_name"],
        "Club": rows["team_name"],
        "Minutes": rows["minutes"].map(whole_minutes),
        "Overall": rows["Overall"].round(2),
        "Performance": rows["Performance"].round(2),
        "Physical": rows["Physical"].round(2),
    })
    if role == "goalkeeper":
        view["Save %"] = (rows["save_pct"] * 100).round(0)  # stored 0-1
        view["Saves/90"] = rows["gk_saves_p90"].round(2)
    elif role == "defender":
        view["Tackles/90"] = rows["tackles_p90"].round(2)
        view["Interceptions/90"] = rows["interceptions_p90"].round(2)
        view["Pass %"] = (rows["pass_completion_pct"] * 100).round(0)  # stored 0-1
    else:
        view["Goals"] = rows["goals"].fillna(0).astype(int)
        view["Assists"] = rows["assists"].fillna(0).astype(int)
        view["npxG/90"] = rows["np_xg_p90"].round(2)
        view["xA/90"] = rows["xa_p90"].round(2)
    return view


def has_rating_in_season(cards: pd.DataFrame | None, player_id: int) -> bool:
    """Whether he is SCORED in the season those scorecards belong to (decides what the Current
    form caption may claim). Looked up against the live season's own scorecards, not the card's
    season, which may not be the live one."""
    return bool(cards is not None and not cards.empty
                and ((cards["player_id"] == int(player_id))
                     & (cards["objective_composite"].notna())).any())


# --- scout assessment: wording shared with the Streamlit card ---------------------------------
def outstanding_warning(outstanding: list[str]) -> str | None:
    """Decision 9 made visible: one dimension alone is not a partial assessment."""
    if outstanding and len(outstanding) < 2:
        return (f"**{outstanding[0]} is still outstanding**, so this player has no "
                "scout-verified rating yet. Both dimensions are needed before scout "
                "input scores — one alone is not a partial assessment.")
    return None


def dimension_caption(status, n_entries: int, n_scoring: int) -> str | None:
    """The line under a dimension's badge: a conflict, or which of several assessments scores
    (a signed-off row always wins; short of that exactly one `submitted` row scores)."""
    from lofc.model import scout_scores
    if status == scout_scores.CONFLICT:
        return (f"{n_scoring} assessments disagree. Nobody has signed one off, so none of "
                "them scores this dimension. Resolve it from the sign-off queue.")
    if n_entries > 1:
        winner = ("the signed-off one scores" if status == "signed_off"
                  else "the submitted one scores" if status == "submitted"
                  else "none of them currently scores")
        return (f"{n_entries} assessment{'s' if n_entries != 1 else ''} exist for this "
                f"dimension. {winner[0].upper()}{winner[1:]}; the others stay on the record, "
                "attributed.")
    return None


def flag_lines(entries) -> list[str]:
    """Anything a band / status / date does not already say -- a screening disagreement, a
    rejection and its reason, free-text notes -- attributed per assessment so several scouts'
    flags are never run together. `entries`: rows from `.itertuples()`."""
    from lofc.model.scout_scores import REJECTED
    out = []
    for e in entries:
        pieces: list[str] = []
        if getattr(e, "screening_failed", False):
            pieces.append("a screening criterion was not met — the band is unchanged; this "
                          "records the disagreement, it does not cap the figure")
        if e.status == REJECTED:
            reason = getattr(e, "rejection_reason", None)
            pieces.append(f"rejected — {reason}" if (reason and str(reason).strip())
                          else "rejected (no reason recorded)")
        notes = getattr(e, "notes", None)
        if pd.notna(notes) and str(notes).strip():
            pieces.append(f"notes: {notes}")
        if pieces:
            out.append(f"**{e.author_name}**, {e.created_at:%d %b %Y} — " + "; ".join(pieces))
    return out


def report_card(report) -> dict:
    """One scout report as plain parts: the title pieces (absent ones dropped), the match
    line, the squad role and the scout's own words (TEXT, never markup)."""
    date = pd.to_datetime(report["fixture_date"], errors="coerce")
    fixture = (f"{report['home_team']} v {report['away_team']}"
               if pd.notna(report["home_team"]) else "")
    played = (", ".join(report["positions_played"])
              if isinstance(report["positions_played"], list) else "")
    title = [b for b in [
        (report["scout"], True),
        (date.strftime("%d %b %Y") if pd.notna(date) else None, False),
        (report["observation"] if pd.notna(report["observation"]) else None, False),
        (f"Grade {report['grade']}" if pd.notna(report["grade"]) else None, False),
        (report["verdict"] if pd.notna(report["verdict"]) else None, False)] if b[0]]
    return {"title": title,
            "match": " · ".join(b for b in [fixture, f"played {played}" if played else None] if b)
            or None,
            "squad_role": report["squad_role"] if pd.notna(report["squad_role"]) else None,
            "comments": str(report["comments"]) if pd.notna(report["comments"]) else None}


def criterion_detail(engine, position, dimension: str, entries) -> dict | None:
    """The per-criterion table for every entry passed in -- one column per assessment, so a
    reader sees WHERE two scouts diverged, not only THAT they did. {"label", "columns",
    "rows"} or {"label", "empty": text}; {"note": ...} when the position has no club criteria;
    None with no entries."""
    from lofc.dashboard import assessment_detail as ad
    entries = list(entries)
    if not entries:
        return None
    if not position or position not in ad.cc.POSITION_GROUPS:
        return {"note": "No club criteria are configured for this position — per-criterion "
                        "detail is unavailable."}
    columns, scores = [], []
    for e in entries:
        band = DASH if e.band is None or pd.isna(e.band) else f"{e.band:.2f}"
        columns.append(f"{e.author_name} — band {band}")
        scores.append(ad._entry_scores(engine, int(e.id)))
    table = ad.comparison_table(position, dimension, columns, scores)
    label = f"Per-criterion detail ({len(entries)} assessment{'s' if len(entries) != 1 else ''})"
    if table.empty:
        return {"label": label, "empty": "No per-criterion detail recorded."}
    return {"label": label, "columns": ["Criterion"] + list(table.columns),
            "rows": [[idx] + [clean(v) for v in vals]
                     for idx, vals in zip(table.index, table.itertuples(index=False))]}


# =============================== assembly (cached loaders only) ===============================
def as_table(frame: pd.DataFrame) -> dict:
    """{"columns", "rows"} with blanks as null."""
    return {"columns": [str(c) for c in frame.columns],
            "rows": [[clean(v) for v in r] for r in frame.itertuples(index=False)]}


@webcache.versioned(maxsize=12)
def _season_frame(name: str, *args):
    """`loaders.<name>(*args)` kept as one object until the data changes (the Streamlit cache
    unpickles a fresh copy on every call: ~0.2 s per card for these three). Read-only."""
    from lofc.dashboard import loaders as L
    return getattr(L, name)(*args)


def card_row(player_id: int, competition_id: int, season_id: int, archetype: str | None = None,
             wage_multiplier: float = 1.0):
    """(row, lens, reason) -- the Series `_render_profile_body` receives, built from the same
    season-wide frames the Players page builds its pool from (`load_candidates`, the scorecard
    ranking for the chosen lens, loan status, style labels, current club), for ONE player-season.

    `lens` is the archetype actually used: `archetype` if it is one of his position's, else the
    default. `reason` as `search_target.resolve_search_target`: "ok", "not_rated" (no scorecard,
    under 450 minutes, or a peer pool below MIN_PEERS_FOR_RANKING -- his ratings are blanked,
    a thin pool is never shown as a rating) or "not_found" (row None)."""
    from lofc.dashboard import loaders as L
    from lofc.dashboard.search_target import KEYS, SCORECARD_COLUMNS
    from lofc.model.scorecard import MIN_PEERS_FOR_RANKING, peer_pool_sizes

    pid, cid, sid = int(player_id), int(competition_id), int(season_id)
    cand = _season_frame("load_candidates", wage_multiplier, sid)
    hit = cand[(cand["player_id"] == pid) & (cand["competition_id"] == cid)
               & (cand["season_id"] == sid)]
    if hit.empty:
        return None, cf.DEFAULT_ARCHETYPE, "not_found"
    row = hit.iloc[0].copy()
    position = row["position_group"]
    lens = archetype if archetype in cf.archetypes_for(position) else cf.DEFAULT_ARCHETYPE
    ranking = ranking_for(position, lens, sid)
    mine = (ranking[(ranking["player_id"] == pid) & (ranking["competition_id"] == cid)
                    & (ranking["season_id"] == sid)]
            if len(ranking) else pd.DataFrame())
    for col in SCORECARD_COLUMNS[len(KEYS):]:
        row[col] = mine.iloc[0][col] if not mine.empty and col in mine.columns else float("nan")
    for flag in ("veto", "below_min_composite"):
        # NaN is truthy: a player with no rating must not get a "below the minimum" advisory
        row[flag] = bool(row[flag]) if pd.notna(row[flag]) else False
    pool = peer_pool_sizes(ranking).get((cid, sid, position)) if len(ranking) else None
    row["peer_count"] = pool if pool is not None else float("nan")
    rated = (not mine.empty and pd.notna(row["objective_composite"])
             and pool is not None and pool >= MIN_PEERS_FOR_RANKING)
    if not rated:
        # Honesty rule: no composite from a pool below MIN_PEERS_FOR_RANKING (and none where
        # there is no scorecard). The Streamlit list withholds him; a searched card keeps his
        # facts, so here his ratings and every flag derived from them are blanked.
        for col in SCORECARD_COLUMNS[len(KEYS):]:
            row[col] = float("nan")
        row["veto"] = row["below_min_composite"] = False
    loan = _season_frame("load_loan_status")
    row["on_loan"] = bool((loan["player_id"] == pid).any()) if len(loan) else False
    style = _season_frame("load_style_labels", sid)
    if not style.empty:
        s_hit = style[(style["player_id"] == pid) & (style["competition_id"] == cid)
                      & (style["season_id"] == sid)]
        if not s_hit.empty:
            for col in ["style_label", "tier", "strong_styles", "leans_styles"] + \
                    [c for c in style.columns if c.startswith("fit.")]:
                row[col] = s_hit.iloc[0][col]
    return row, lens, ("ok" if rated else "not_rated")


def _style_block(row, league: str, season: str) -> dict:
    """Playing-style pills and the Style fit bars. `fit` is None when he has no style fits (no
    minutes, or a position without styles)."""
    from lofc.dashboard import style_card
    from lofc.model import styles as sm
    as_list = lambda v: [x for x in v] if isinstance(v, (list, tuple)) else []
    label = row.get("style_label")
    pills = {"strong": as_list(row.get("strong_styles")), "leans": as_list(row.get("leans_styles")),
             "label": label if isinstance(label, str) else None}
    group = sm.style_group(row.get("position_group"))
    groups = sm.STYLES.get(group)
    fits = {s: row.get(f"fit.{s}") for g in (groups or {}).values() for s in g}
    if not groups or all(_missing(v) for v in fits.values()):
        return {"pills": pills, "fit": None}
    out = []
    for gname, members in groups.items():
        styles = []
        for style, sigs in members.items():
            v = fits.get(style)
            if _missing(v):
                continue                              # a style with no fit value is skipped
            v = float(v)
            styles.append({"style": style, "fit": v,
                           "tag": "Strong" if v >= sm.STRONG else "Leans" if v >= sm.FLOOR else None,
                           "signals": [sm.SIGNAL_LABELS[s] for s in sigs]})
        out.append({"title": style_card._GROUP_TITLES.get(gname, gname) if len(groups) > 1 else None,
                    "styles": styles})
    peers = style_card._PEERS.get(group, "players")
    return {"pills": pills, "fit": {
        "sub": f"vs {league} {peers}, {season} · how he plays, not how well",
        "groups": out, "strong": sm.STRONG, "floor": sm.FLOOR,
        "key": f"Fit = average percentile of the style's signals, against players in the same "
               f"position, league and season."}}


def _assessment_block(engine, row) -> dict:
    """The two human bands, who entered them, who approved them, and when -- EVERY assessment,
    not just the one that scores, because two assessors who disagree must both be visible."""
    from lofc.dashboard import assessment_detail as ad
    from lofc.dashboard import badges
    from lofc.model import scout_scores
    from lofc.store import assessments as store_assess
    pid, cid, sid = int(row["player_id"]), int(row["competition_id"]), int(row["season_id"])
    frame = store_assess.load_for_player(engine, pid, cid, sid)
    position = row.get("position_group")
    dims = (scout_scores.PSYCHOLOGICAL, scout_scores.MEDICAL)
    out: dict = {"warning": None, "empty": None, "dimensions": []}
    if frame.empty:
        b = badges.for_status(None)
        out["empty"] = {"badge": b.text, "tone": b.tone, "caption":
                        "No psychological or medical assessment has been recorded for this "
                        "player-season."}
        return out
    out["warning"] = outstanding_warning(scout_scores.missing_dimensions(
        {d: ad.dimension_status(frame, d) for d in dims}))
    for dimension in dims:
        dim_rows = frame[frame["dimension"] == dimension]
        d: dict = {"name": dimension, "badge": None, "tone": None, "caption": None,
                   "entries": None, "flags": [], "notes": [], "criteria": None}
        if dim_rows.empty:
            b = badges.for_status(None)
            d["badge"], d["tone"] = b.text, b.tone
            out["dimensions"].append(d)
            continue
        entries = list(dim_rows.itertuples())
        status = ad.dimension_status(frame, dimension)
        scoring = [e for e in entries if e.status in ("submitted", "signed_off")]
        if status == scout_scores.CONFLICT:
            b = badges.for_status(scout_scores.CONFLICT)
            d["badge"], d["tone"] = b.text, b.tone
        d["caption"] = dimension_caption(status, len(entries), len(scoring))
        d["entries"] = as_table(ad.entries_table(dim_rows))
        d["flags"] = flag_lines(entries)
        d["notes"] = [{"author": getattr(e, "author_name", "Unknown"),
                       "blocks": [{"heading": h, "text": t} for h, t in ad.narrative_for(e)]}
                      for e in entries if ad.narrative_for(e)]
        d["criteria"] = criterion_detail(engine, str(position) if pd.notna(position) else None,
                                         dimension, entries)
        out["dimensions"].append(d)
    return out


def _scout_reports_block(engine, player_id: int) -> dict:
    from lofc.dashboard.tabs.scout_reports import reports_for_player, verdict_counts, verdict_tone
    reports = reports_for_player(engine, int(player_id))
    return {"heading": f"Scout reports ({len(reports)})" if len(reports) else "Scout reports",
            "verdicts": [{"verdict": v, "count": n, "tone": verdict_tone(v)}
                         for v, n in verdict_counts(reports["verdict"])],
            "reports": [report_card(r) for _, r in reports.iterrows()],
            "open_single": len(reports) == 1,
            "empty": None if len(reports) else "No scout reports for this player."}


def _availability_block(engine, row) -> dict:
    from lofc.dashboard import evidence
    from lofc.model.medical import (AVAILABILITY_SEASONS, availability_with_evidence,
                                    games_missed_in_window)
    pid, cid, sid = int(row["player_id"]), int(row["competition_id"]), int(row["season_id"])
    minutes = int(row["minutes"]) if pd.notna(row.get("minutes")) else None
    injuries = evidence.load_for_player(engine, pid)
    window = evidence.resolve_window(sid)
    out: dict = {"window": list(window) if window else None, "warning": None, "tiles": None,
                 "caption": None, "coverage": None, "empty": None, "single": None,
                 "in_window": None, "earlier": None, "footnote": None, "n_spells": len(injuries)}
    if window is None:
        # This season is not yet in the season-label map (a maintenance gap): degrade, no
        # figure, no crash, and still show whatever injury history exists.
        out["warning"] = "**No availability window for this season yet**: injury record only."
    else:
        missed = games_missed_in_window(injuries, sid)
        ev = availability_with_evidence(injuries, missed, cid, minutes,
                                        seasons=AVAILABILITY_SEASONS, minutes_seasons=1)
        out["tiles"] = [
            {"label": availability_label(window),
             "value": DASH if ev.value is None else f"{ev.value:.0%}"},
            # injury only: a fit player who was not selected is not counted
            {"label": "Matches missed (injury)", "value": missed if not injuries.empty else DASH},
            # `is not None`, not truthiness: zero minutes must read "0", not "—".
            {"label": "Minutes played", "value": f"{minutes:,}" if minutes is not None else DASH}]
        from lofc.store.injuries import COVERAGE
        out["caption"] = availability_line(ev)
        out["coverage"] = coverage_line(COVERAGE.get(cid))
    if injuries.empty:
        out["empty"] = ("No injury spells on record: absence of evidence, not evidence of "
                        "fitness.")
        return out
    if window is None:
        out["single"] = as_table(evidence._format_table(injuries))
        out["footnote"] = "No scored window for this season: spells are not split."
        return out
    spells = evidence.spell_rows(injuries, window)
    in_window, earlier = spells[spells["in_window"]], spells[~spells["in_window"]]
    plural = lambda n: f"{n} spell{'' if n == 1 else 's'}"
    out["in_window"] = {"heading": f"In the scored window ({' and '.join(window)}) — {plural(len(in_window))}",
                        "table": None if in_window.empty else as_table(evidence._format_table(in_window)),
                        "empty": "No spells recorded in the scored window."}
    out["earlier"] = {"heading": f"Earlier seasons, not counted — {plural(len(earlier))}",
                      "table": None if earlier.empty else as_table(evidence._format_table(earlier)),
                      "empty": "No earlier spells on record."}
    return out


def _physical_block(row, mv_row, prow, position: str, orient: dict, n_orient: int) -> dict:
    """Physical tables, the one line saying why there are none, and the radar. A goalkeeper has
    no physical gap line: physical never counts in his rating."""
    from lofc.dashboard import detail_section as ds
    from lofc.dashboard.glossary_data import PHYSICAL
    cid, sid = int(row["competition_id"]), int(row["season_id"])
    phys = detail_store.player_rows(row, "phys_")
    scored = cf.PHYSICAL_METRICS.get(position, [])
    rated = other = None
    gap = None
    if mv_row is not None:
        table = ds.physical_table(phys, mv_row, prow, scored)
        if not table.empty:
            r, o = ds.split_physical(table)
            fm = lambda v: DASH if _missing(v) else f"{v:.1f}"
            fmt = lambda t, band: {
                "columns": list(t.columns),
                "rows": [[x["Metric"], fm(x["All phases"]), fm(x["In possession"]),
                          fm(x["Out of possession"]), clean(x["Percentile"])]
                         + ([clean(x["Band"])] if band else []) for _, x in t.iterrows()]}
            rated, other = fmt(r, True), fmt(o, False)
            # the metric key of each rated row, by its label (for "vs ours"; popped by the caller)
            key_of = {label: m for m, label in ds.PHASE_METRICS}
            key_of.update({label: m for m, label, _ in ds.SPEED_METRICS})
            rated["metrics"] = [key_of.get(x) for x in r["Metric"]]
    if rated is None:
        gap = ds.physical_gap(detail_store.league_has_physical(cid, sid), position)
        if gap is not None:
            gap = gap[0].upper() + gap[1:] + "."
    axes = [m for m in scored if m != "meters_per_minute"
            and prow is not None and m in prow.index and pd.notna(prow[m])]
    radar = None
    if len(axes) >= 3:
        radar = {"labels": [PHYSICAL[m][0] for m in axes], "metrics": axes,
                 "player": [float(prow[m]) for m in axes],
                 "orient": [orient.get(m) for m in axes],
                 "orient_label": f"Leyton Orient median ({n_orient}), {position}s" if n_orient else None}
    return {"in_rating": rated, "other": other, "gap": gap, "radar": radar,
            "caption": "Per 90 minutes played. Metres per minute is a rate."}


def _impect_block(row) -> dict:
    from lofc.dashboard import detail_section as ds
    scores = detail_store.player_rows(row, "score.")
    out = {"tiles": [], "by_position": None}
    if scores.empty:
        return out
    by = scores.set_index("metric")
    for key in ds.SCORE_TILES:
        name = f"score.{key}"
        if name in by.index:
            pct = by.at[name, "pct"]
            out["tiles"].append({
                "label": ds.SCORES[key][1],
                "value": f"{by.at[name, 'value_p90']:.2f}",
                "pct_text": None if pd.isna(pct) else f"{ds.ordinal(pct)} percentile"})
    per_pos = detail_store.player_rows(row, "score_pos.")
    if not per_pos.empty:
        t = ds.position_breakdown(per_pos)
        f2 = lambda v: DASH if _missing(v) else f"{v:.2f}"
        out["by_position"] = {
            "caption": "All positions, weighted by minutes. By position:",
            "columns": list(t.columns),
            "rows": [[r["Position"], None if _missing(r["Minutes"]) else _half_up(r["Minutes"]),
                      f2(r["Offensive IMPECT"]), f2(r["Defensive IMPECT"])]
                     for _, r in t.iterrows()]}
    return out


def _zones_block(row, position: str, league: str) -> dict | None:
    """Packing-zone cells for every metric family x unit, so choosing one on the page needs no
    round trip: value text exactly as `detail_section` shows it, plus the percentile."""
    from lofc.dashboard import detail_section as ds
    zones = detail_store.player_rows(row, "zone.")
    if zones.empty:
        return None
    meta = detail_store.player_rows(row, "meta.")
    matches = meta["total"].iloc[0] if not meta.empty else None
    by = zones.set_index("metric")
    key = {"Per match": "per_match", "Per 90": "per_90", "Season total": "season_total"}
    measures = {}
    for family in ds.FAMILY_ORDER:
        cells = {}
        for code in ds.ZONES:
            name = f"zone.{family}.{code}"
            if name not in by.index:
                continue
            pct = by.at[name, "pct"]
            c = {"percentile": None if _missing(pct) else round(float(pct)),
                 "percentile_text": None if _missing(pct) else f"{ds.ordinal(pct)} percentile"}
            for mode in ds.MODES:
                value = ds.unit_value(by.at[name, "total"], by.at[name, "value_p90"], matches, mode)
                c[key[mode]] = ds.fmt_value(value, mode, family)
            cells[code] = c
        measures[family] = {"cells": cells}
    return {"caption": f"All positions. Colour: percentile vs {position}s in {league}, per 90.",
            "metric_options": [{"key": f, "label": ds.FAMILY_LABELS[f]} for f in ds.FAMILY_ORDER],
            "value_modes": [{"key": key[m], "label": m} for m in ds.MODES],
            "zones": [{"code": z, "name": ds.ZONE_NAMES[z]} for z in ds.ZONES],
            "measures": measures}


def _receptions_block(row) -> dict | None:
    from lofc.dashboard import detail_section as ds
    from lofc.ingest.impect_detail import AVAILABILITY
    avail = detail_store.player_rows(row, "avail.")
    if avail.empty:
        return None
    by = avail.set_index("metric")
    rows = [[label, DASH if _missing(by.at[f"avail.receptions.{k}", "value_p90"])
             else f"{by.at[f'avail.receptions.{k}', 'value_p90']:.2f}",
             clean(by.at[f"avail.receptions.{k}", "pct"])]
            for k, (_, label) in AVAILABILITY.items() if f"avail.receptions.{k}" in by.index]
    return {"columns": ["Receptions", "Per 90", "Percentile"], "rows": rows}


def _current_form_block(row, pid: int, engine_clubs=None) -> dict | None:
    from lofc.config import settings
    from lofc.dashboard import loaders as L
    from lofc.dashboard.seasons import season_name_for
    from lofc.dashboard.tabs.players import _current_form_summary, current_form_empty_caption
    live = settings.live_season_id
    if live is None:
        return None
    name = season_name_for(live)
    summary = _current_form_summary(L.load_current_form(), pid)
    out = {"heading": f"Current form · {name}", "sub": "All clubs and leagues",
           "tiles": None, "empty": None, "not_scored": None, "split": None}
    if summary is None:
        out["empty"] = current_form_empty_caption(name)
        return out
    out["tiles"] = [{"label": "Minutes", "value": f"{summary['minutes']:,}"},
                    {"label": "Goals", "value": str(summary["goals"])},
                    {"label": "Assists", "value": str(summary["assists"])}]
    if not has_rating_in_season(stored_scorecards(live), pid):
        out["not_scored"] = "Not enough minutes yet to be scored this season (450 needed)."
    out["split"] = engine_clubs
    return out


def _live_club_split(engine, pid: int, live) -> list[dict] | None:
    """Current form adds up every club he played for this season; this names them (TASKS 2.34).
    None when he has a single club -- there is nothing to split."""
    from lofc.dashboard import loaders as L
    if live is None:
        return None
    d = pd.read_sql("SELECT team_name, competition_id, minutes FROM player_metrics_neutral "
                    "WHERE player_id = %(p)s AND season_id = %(s)s ORDER BY minutes DESC",
                    engine, params={"p": int(pid), "s": int(live)})
    if len(d) < 2:
        return None
    names = L.competition_name_by_id()
    return [{"club": r.team_name, "league": names.get(int(r.competition_id)),
             "minutes": _half_up(r.minutes) if pd.notna(r.minutes) else None}
            for r in d.itertuples()]


def build_card(engine, player_id: int, competition_id: int, season_id: int,
               rank_as: str | None = None, show_money: bool = False) -> dict | None:
    """Every section of the player card for one player-season, as JSON-ready data (blanks are
    null). None if there is no such player-season. `rank_as`: the "Rank as" lens; it applies
    only if it is one of his position's archetypes."""
    from lofc.config import settings
    from lofc.core import squad
    from lofc.dashboard import loaders as L
    from lofc.dashboard import player_header
    from lofc.dashboard.labels import LABELS
    from lofc.dashboard.seasons import season_name_for
    from lofc.dashboard.tabs import players as P
    from lofc.model import scorecard as scorecard_mod
    from lofc.model.score import POSITION_ROLE
    from lofc.store import watchlist

    row, lens, reason = card_row(player_id, competition_id, season_id, rank_as)
    if row is None:
        return None
    pid, cid, sid = int(row["player_id"]), int(row["competition_id"]), int(row["season_id"])
    position = row["position_group"]
    role = POSITION_ROLE[position]
    season_name = season_name_for(sid)
    league = text_or(row.get("league"), "")
    live = settings.live_season_id

    shares = L.load_position_shares(pid, cid, sid)
    loan = L.load_loan_for_player(pid)
    hrow = player_header.with_current_club(row, L.load_current_clubs())
    tm_id = row.get("tm_player_id")
    header = {
        "position": position, "league": league, "season_name": season_name,
        "name": str(row["player_name"]),
        "club_text": player_header.club_text(text_or(row.get("team_name"), ""), hrow.get("current_club")),
        "register": [{"label": k, "value": v} for k, v in register_cells(row)],
        "contract": contract_chip(row.get("contract_until")),
        "loan": loan_chip(loan),
        "minutes_by_position": minutes_split(shares, str(position)),
        "scored_as": scored_as_notice(shares),
        "other_leagues": other_league_notes(L.load_other_league_seasons(pid, cid, sid),
                                            lambda c: L.competition_name_by_id().get(c)),
        "transfermarkt_url": (f"https://www.transfermarkt.com/-/profil/spieler/{int(tm_id)}"
                              if pd.notna(tm_id) else None),
        "assess_url": f"/assess?player={pid}&competition={cid}&season={sid}",
        "watched": bool(watchlist.is_watched(engine, pid, cid, sid)),
    }

    # --- rating ---
    metric_values = L.load_metric_values(sid)
    sc_pcts = L.load_scorecard_percentiles(sid)
    prow = P._sc_pct_series(sc_pcts, pid, cid, sid)
    perf_metrics, _phys = P._club_metrics_for(position, lens)
    cards = ranking_for(position, lens, sid)
    rank, peers = scorecard_mod.rank_in_pool(cards, pid, cid, sid, position)
    if reason != "ok":
        rank = None                      # not rated: no place in a ranking
    # Thin peer pool (owner 2026-11-09, web card only): still no rating, but the percentiles
    # stay and every heading over them says how many players they are against.
    thin = thin_pool_size(reason, row.get("peer_count"), row.get("minutes"))
    vs = f"{thin} {league} {position}s" if thin is not None else f"{league} {position}s"
    composite, performance, physical = (row.get("objective_composite"), row.get("performance_band"),
                                        row.get("physical_band"))
    from lofc.dashboard.search_target import search_caption
    rating = {
        "heading": f"Composite · {season_name}",
        "sub": f"Against {league} {position}s · {P.RANKABLE_MINUTES}+ minutes",
        "lens": None if lens == cf.DEFAULT_ARCHETYPE else lens,
        "overall": {"label": "Composite" if lens == cf.DEFAULT_ARCHETYPE else f"Composite ({lens})",
                    "value": composite, "rank_text": rank_text(rank, peers),
                    "help": COMPOSITE_HELP},
        "performance": {"label": "Performance", "value": performance, "help": PERFORMANCE_HELP},
        "physical": {"label": "Physical", "value": physical, "help": PHYSICAL_HELP},
        "not_rated": (None if reason == "ok" else thin_pool_caption(thin) if thin is not None
                      else search_caption("not_rated", True, row.get("minutes"))),
        "money": money_block(row, show_money),
        "advisory": ({"title": ADVISORY_TITLE, "flags": advisory_flags(row, show_money)}
                     if advisory_flags(row, show_money) else None),
        "strengths": strengths_watchouts(prow, perf_metrics, lambda m: LABELS.get(m, m)),
    }

    # --- season by season + current form ---
    traj = L.load_trajectory()
    traj = traj[traj["player_id"] == pid]
    sbs = {"sub": f"{position} · each rating against that season's league", "table": None,
           "note": None, "empty": "Only one season on record."}
    if len(traj) >= 2:
        stored = stored_scorecards()
        traj = P.attach_season_scores(traj, stored)
        no_phys = P.card_no_physical_seasons(traj, stored)
        traj = P.season_rating_columns(traj, no_phys)
        from lofc.dashboard import compare_tables as ct
        sbs.update(table=as_table(trajectory_view(traj, role)), empty=None,
                   note=ct.comparison_note([season_name_for(int(s_)) for s_ in no_phys]))
    current_form = _current_form_block(row, pid, _live_club_split(engine, pid, live))

    # --- playing style ---
    style = _style_block(row, league, season_name)

    # --- season output ---
    mv_df = metric_values[(metric_values["player_id"] == pid)
                          & (metric_values["competition_id"] == cid)]
    mv = mv_df.iloc[0] if not mv_df.empty else pd.Series(dtype=float)
    out_tiles = season_output_tiles(role, row, mv, metric_values)
    season_output = {
        "heading": f"Season output · {text_or(row.get('team_name'), DASH)} · {league} · {season_name}",
        "sub": "Totals, this club and league only. Current form counts every club.",
        "tiles": out_tiles["tiles"], "note": out_tiles["note"],
        "rates": underlying_rates(role, row)}
    impect = _impect_block(row)

    # --- performance ---
    grand = P._grand_table(row, position, lens, sc_pcts, metric_values)
    full = P._full_stats_table(row, sc_pcts, metric_values)
    orient, n_orient = squad.orient_median(position, sid, exclude_player_id=pid)
    chart_metrics = [m for m in perf_metrics if prow is not None and m in prow.index
                     and pd.notna(prow[m])]
    performance = {
        "sub": f"Percentile vs {vs} · band 1–5",
        "table": None if grand.empty else as_table(grand.drop(columns=["Dimension"])),
        # one entry per table row (rows follow `perf_metrics`): weight group + gap to our median
        "tiers": None if grand.empty else weight_tiers(perf_metrics, position, lens),
        "vs_ours": None if grand.empty or not n_orient
        else vs_ours_column(perf_metrics, prow, orient, thin),
        "vs_ours_help": vs_ours_help(position, n_orient),
        "scored_on_lens": None if lens == cf.DEFAULT_ARCHETYPE else lens,
        "all_tracked": None if full is None or full.empty else as_table(full),
        "profile": None if len(chart_metrics) < 3 else {
            "sub": f"Percentile vs {vs}",
            "metrics": chart_metrics, "labels": [LABELS.get(m, m) for m in chart_metrics],
            "player": [float(prow[m]) for m in chart_metrics],
            "orient": [orient.get(m) for m in chart_metrics],
            "orient_label": f"Leyton Orient median ({n_orient}), {position}s" if n_orient else None},
        "csv_name": f"{str(row['player_name']).replace(' ', '_')}_{sid}",
    }

    physical_block = _physical_block(row, mv_df.iloc[0] if not mv_df.empty else None, prow,
                                     position, orient, n_orient)
    if physical_block["in_rating"] is not None:
        keys = physical_block["in_rating"].pop("metrics")
        physical_block["in_rating"]["vs_ours"] = (vs_ours_column(keys, prow, orient, thin)
                                                  if n_orient else None)
        physical_block["in_rating"]["vs_ours_help"] = vs_ours_help(position, n_orient)
    physical_block["sub"] = f"Percentile vs {vs} · rated physical metrics"
    physical_block["table_sub"] = f"SkillCorner · per 90 · percentile vs {vs}"
    out = {
        "meta": {"player_id": pid, "competition_id": cid, "season_id": sid,
                 "season_name": season_name, "position": position, "league": league,
                 "rank_as": lens, "rank_as_options": cf.archetypes_for(position),
                 "thin_pool": thin,
                 "money": bool(show_money), "back_label": f"{position}s",
                 "live_season_name": season_name_for(live) if live is not None else None},
        "header": header,
        "rating": rating,
        "season_by_season": sbs,
        "current_form": current_form,
        "style": style,
        "season_output": season_output,
        "impect": impect,
        "performance": performance,
        "packing_zones": _zones_block(row, position, league),
        "receptions": _receptions_block(row),
        "physical": physical_block,
        "scout_reports": _scout_reports_block(engine, pid),
        "scout_assessment": _assessment_block(engine, row),
        "availability": _availability_block(engine, row),
        "glossary_note": "Definitions on the Glossary page",
    }
    return clean(out)


def scorecard_csv(engine, player_id: int, competition_id: int, season_id: int,
                  kind: str, rank_as: str | None = None) -> tuple[str, str] | None:
    """(file name, CSV text) for the two downloads the Streamlit card offers: "scorecard"
    (the metrics that build the rating) or "metrics" (every tracked metric). Same tables, same
    names (`<Name>_<season>_scorecard_metrics.csv` / `_metrics.csv`). None if no such player or
    nothing to download."""
    from lofc.dashboard import loaders as L
    from lofc.dashboard.tabs import players as P
    row, lens, _ = card_row(player_id, competition_id, season_id, rank_as)
    if row is None:
        return None
    sid = int(row["season_id"])
    sc_pcts, metric_values = L.load_scorecard_percentiles(sid), L.load_metric_values(sid)
    base = f"{str(row['player_name']).replace(' ', '_')}_{sid}"
    if kind == "scorecard":
        table = P._grand_table(row, row["position_group"], lens, sc_pcts, metric_values)
        name = f"{base}_scorecard_metrics.csv"
    else:
        table = P._full_stats_table(row, sc_pcts, metric_values)
        name = f"{base}_metrics.csv"
    if table is None or table.empty:
        return None
    return name, table.to_csv(index=False)
