"""\"Against our <position>s\" on the player card (TASKS 2.32, owner approved option B 2026-11-08).

Where would this player sit among the players Leyton Orient have NOW at his position, each rated
in his own league? (Mockup: club_docs/design/mockup_squad_fit.html.) Moved here, rule for rule,
from the set-aside Streamlit module `club_docs/streamlit_v2_archive/.../squad_fit.py`; the HTML
and plotly builders became plain data (`table_rows`, `gap_items`, `metric_matrix`) that the web
card draws, so nothing here knows about a page.

OUR PLAYERS = `player_current_club` rows whose club is Leyton Orient (Impect squad id 966 --
NOT FC Lorient), at the `position_group` where they played most over the last complete season
and the current one together. A January signing or a returning loanee is "ours" from the day
Impect says so, and a player who has left is not.

No league-strength adjustment is made (owner decision): each player carries his league as a tag,
and the percentiles are within his own league and position, exactly as everywhere else. A
league-position pool below MIN_PEERS_FOR_RANKING is never rated here either.

The pure functions up to the "data" banner take plain values, so tests need no database; the
loaders below it are version-cached like `loaders.py` (`_versioned`).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import pandas as pd

from lofc.config import settings
from lofc.model import club_framework as cf
from lofc.model.scorecard import pool_is_thin

ORIENT_NAME = "leyton orient"
ORIENT_SQUAD_ID = 966            # Impect's id for Leyton Orient (player_current_club)
DASH = "—"
MIN_RATED_MINUTES = 450          # the platform's rankable threshold, quoted in the unrated row
BETTER_MAX, WORSE_MAX = 5, 4     # list lengths (mockup)


# --- who is "ours" -----------------------------------------------------------------------
def is_orient_club(name, squad_id=None) -> bool:
    """Leyton Orient by name OR by Impect squad id. The name is matched as a prefix ("Leyton
    Orient", "Leyton Orient FC") so spelling drift cannot lose a player, and never as a
    substring: "FC Lorient" contains "orient"."""
    if squad_id is not None and not pd.isna(squad_id) and int(squad_id) == ORIENT_SQUAD_ID:
        return True
    return isinstance(name, str) and name.strip().lower().startswith(ORIENT_NAME)


def current_positions(neutral: pd.DataFrame, seasons=None) -> pd.DataFrame:
    """One row per player: his position_group. With `seasons` (the last complete and the
    current one) it is the group with the most minutes summed over those seasons together, so
    one short season cannot reclassify a player (Connolly: 1,872 centre-forward minutes in
    2025/26, 337 as a winger in 2026/27 -> centre forward). A player with no minutes in those
    seasons falls back to the most-minutes row of the most recent season he has data.
    Needs player_id, player_name, season_id, position_group, minutes."""
    if neutral.empty:
        return pd.DataFrame(columns=["player_id", "player_name", "position_group"])
    f = neutral.assign(_m=pd.to_numeric(neutral["minutes"], errors="coerce").fillna(0))
    f = f.sort_values(["player_id", "season_id", "_m"], ascending=[True, False, False])
    out = f.drop_duplicates("player_id")[["player_id", "player_name", "position_group"]]
    if seasons:
        w = f[f["season_id"].isin(list(seasons))]
        tot = w.groupby(["player_id", "position_group"], as_index=False)["_m"].sum()
        tot = tot[tot["_m"] > 0].sort_values(["player_id", "_m"], ascending=[True, False])
        best = tot.drop_duplicates("player_id").set_index("player_id")["position_group"]
        out = out.assign(position_group=out["player_id"].map(best).fillna(out["position_group"]))
    return out.reset_index(drop=True)


def fill_tm_ids(squad: pd.DataFrame, tm: pd.DataFrame) -> pd.Series:
    """`players.tm_player_id`, else the Transfermarkt squad row with the same name (any case)
    and the same date of birth. Nothing is guessed beyond that: no match stays blank."""
    key = {(str(n).strip().lower(), pd.Timestamp(d).date()): i
           for i, n, d in zip(tm["tm_id"], tm["tm_name"], tm["date_of_birth"]) if pd.notna(d)}

    def one(r):
        if pd.notna(r["tm_player_id"]):
            return r["tm_player_id"]
        if pd.isna(r["birth_date"]):
            return None
        return key.get((str(r["player_name"]).strip().lower(), pd.Timestamp(r["birth_date"]).date()))
    return squad.apply(one, axis=1)


def loans_to_orient(loans: pd.DataFrame, squad: pd.DataFrame) -> dict:
    """player_id -> parent club for players on loan AT Leyton Orient. A loan row is tied to a
    player by player_id, or by Transfermarkt id where the row has no player_id."""
    mine = loans[[is_orient_club(c) for c in loans["club_name"]]]
    by_tm = {int(t): int(p) for p, t in zip(squad["player_id"], squad["tm_player_id"])
             if pd.notna(t)}
    out = {}
    for r in mine.itertuples():
        pid = int(r.player_id) if pd.notna(r.player_id) else by_tm.get(
            int(r.tm_player_id) if pd.notna(r.tm_player_id) else -1)
        if pid is not None:
            out[pid] = r.parent_club
    return out


def ours_at(squad: pd.DataFrame, position: str, exclude_player_id=None) -> pd.DataFrame:
    """Our players at `position`; the card's own player is left out when he is one of them."""
    out = squad[squad["position_group"] == position]
    if exclude_player_id is not None:
        out = out[out["player_id"] != exclude_player_id]
    return out.reset_index(drop=True)


# --- wording -------------------------------------------------------------------------------
def plural(position: str) -> str:
    return f"{position}s"


def title(position: str, target_is_ours: bool) -> str:
    return f"Against our {'other ' if target_is_ours else ''}{plural(position)}"


def subtitle(position: str, archetype: str | None = None) -> str:
    base = f"Leyton Orient's current {plural(position).lower()} · each rated in his own league"
    # the rank-as lens: say so, or the numbers read as the default rating
    return base + (f" · Rated as {archetype}"
                   if archetype and archetype != cf.DEFAULT_ARCHETYPE else "")


def median_label(position: str, n: int) -> str:
    """The radar key for our line: how many of our players the median is over."""
    return f"Our current {position.lower()}s' median ({n})"


def ordinal(n: int) -> str:
    n = int(n)
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def among_text(n_ours: int, n_unrated: int, position: str) -> str:
    who = f"only {position.lower()}" if n_ours == 1 else f"{n_ours} {plural(position).lower()}"
    tail = f" ({n_unrated} not rated this season)" if n_unrated else ""
    return f"among our {who}{tail}"


def gap_note(n_compared: int, position: str) -> str:
    who = (f"our only rated {position.lower()}" if n_compared == 1
           else f"the best of our {n_compared} {plural(position).lower()}")
    return f"Gap in percentile points vs {who} on that metric."


def better_heading(n_compared: int, position: str) -> str:
    return (f"Better than our only rated {position.lower()}" if n_compared == 1
            else f"Better than all our {plural(position)}")


def unrated_text(minutes) -> str:
    """Why a row has no rating. 450+ minutes with no rating means his league-position pool is
    below the peer floor (the honesty rule: no composite from a pool under MIN_PEERS)."""
    if minutes is None or pd.isna(minutes) or minutes <= 0:
        return "No minutes this season"
    return ("Not rated: under 450 minutes" if minutes < MIN_RATED_MINUTES
            else "Not rated: too few peers in his league")


def _round_half_up(x: float) -> int:
    """Half away from zero (Python's round() goes to the even number: 10.5 -> 10)."""
    return int(math.copysign(math.floor(abs(x) + 0.5), x))


# --- the comparison -------------------------------------------------------------------------
@dataclass
class SfPlayer:
    """One row of the section: the target or one of ours, in one season. `pct` holds the
    percentile per metric (performance and physical together; the keys do not overlap)."""
    name: str
    overall: float | None = None          # All Metrics objective composite; None = not rated
    perf: float | None = None
    phys: float | None = None
    minutes: float | None = None
    club: str | None = None               # his club that season
    league: str | None = None
    league_abbr: str | None = None
    age: float | None = None              # age now
    contract: str | None = None           # "Jun 2030"
    note: str | None = None               # "On loan from X" / "Joined from X"
    style: str | None = None
    pct: dict = field(default_factory=dict)
    is_target: bool = False

    @property
    def rated(self) -> bool:
        return self.overall is not None and not pd.isna(self.overall)


def order_ours(ours: list[SfPlayer]) -> list[SfPlayer]:
    """Rated players best first, then the unrated by minutes played."""
    rated = sorted((p for p in ours if p.rated), key=lambda p: -p.overall)
    rest = sorted((p for p in ours if not p.rated), key=lambda p: -(p.minutes or 0))
    return rated + rest


def summary(target: SfPlayer, ours: list[SfPlayer]) -> dict:
    """Where the target would sit by rating among our rated players. A tie shares the better
    place (only players strictly above him count)."""
    rated = [p for p in ours if p.rated]
    best = max(rated, key=lambda p: p.overall) if rated else None
    out = {"n_ours": len(ours), "n_unrated": len(ours) - len(rated), "best": best,
           "rank": None, "of": len(rated) + 1, "rank_text": DASH}
    if target.rated:
        out["rank"] = sum(1 for p in rated if p.overall > target.overall) + 1
        out["rank_text"] = f"{ordinal(out['rank'])} of {out['of']}"
    return out


def _val(p: SfPlayer, metric: str):
    v = p.pct.get(metric)
    return None if v is None or pd.isna(v) else float(v)


def _with_pct(ours: list[SfPlayer], metrics: list[str]) -> list[SfPlayer]:
    return [p for p in ours if any(_val(p, m) is not None for m in metrics)]


@dataclass
class Gap:
    metric: str
    gap: int          # his percentile minus the best of ours, whole points (+ = he is better)
    his: int
    theirs: int
    who: str          # the one of ours with the best figure


def gap_lists(target: SfPlayer, ours: list[SfPlayer], metrics: list[str]):
    """(better, worse, n_compared): the metrics where he beats the best of ours (top 5, biggest
    gap first) and where one of ours beats him (top 4, biggest gap first, naming that player).
    Only players with percentiles are compared; a metric either side lacks is skipped."""
    pool = _with_pct(ours, metrics)
    gaps = []
    for m in metrics:
        his = _val(target, m)
        theirs = [(v, p.name) for p in pool if (v := _val(p, m)) is not None]
        if his is None or not theirs:
            continue
        best, who = max(theirs, key=lambda t: t[0])
        # the gap is the difference of the two SHOWN (rounded) figures, so "▲ N" always adds up
        h, b = _round_half_up(his), _round_half_up(best)
        gaps.append((his - best, Gap(m, h - b, h, b, who)))
    better = [g for d, g in sorted((x for x in gaps if x[1].gap > 0), key=lambda x: -x[0])]
    worse = [g for d, g in sorted((x for x in gaps if x[1].gap < 0), key=lambda x: x[0])]
    return better[:BETTER_MAX], worse[:WORSE_MAX], len(pool)


def gap_line(g: Gap, label: str | None = None) -> tuple[str, str, str, str]:
    """(kind, "▲ 17", label, "him 65, our best 48") for one list item."""
    label = label or g.metric
    if g.gap > 0:
        return "up", f"▲ {g.gap}", label, f"him {g.his}, our best {g.theirs}"
    return "dn", f"▼ {abs(g.gap)}", label, f"him {g.his}, {g.who.split()[-1]} {g.theirs}"


def gap_items(gaps, label_for) -> list[dict]:
    """One gap list as plain items for the page; an empty list stays empty (the page writes
    the "—")."""
    out = []
    for g in gaps:
        kind, arrow, label, detail = gap_line(g, label_for(g.metric))
        out.append({"kind": kind, "arrow": arrow, "label": label, "detail": detail})
    return out


def median_pct(ours: list[SfPlayer], metrics: list[str]) -> tuple[dict[str, float], int]:
    """Median percentile per metric over the players who have percentiles, and how many."""
    pool = _with_pct(ours, metrics)
    out = {}
    for m in metrics:
        vals = [v for p in pool if (v := _val(p, m)) is not None]
        if vals:
            out[m] = float(pd.Series(vals).median())
    return out, len(pool)


# --- plain data for the page ---------------------------------------------------------------
def _num(x) -> float | None:
    return None if x is None or pd.isna(x) else float(x)


def _minutes(m) -> int | None:
    """Whole minutes, .5 up (format() rounds half to even); blank when none."""
    return None if m is None or pd.isna(m) or m <= 0 else int(float(m) + 0.5)


def table_rows(players: list[SfPlayer]) -> list[dict]:
    """The section's table, the target first then each of ours (the caller orders them).
    Blanks are None -- the page writes "—". An unrated row carries `unrated`, the reason."""
    rows = []
    for p in players:
        rows.append({
            "name": p.name, "is_target": p.is_target, "note": p.note or None,
            "age": None if p.age is None or pd.isna(p.age) else round(float(p.age), 1),
            "club": p.club or None, "league_abbr": p.league_abbr or None, "league": p.league,
            "minutes": _minutes(p.minutes),
            "overall": _num(p.overall) if p.rated else None,
            "performance": _num(p.perf) if p.rated else None,
            "physical": _num(p.phys) if p.rated else None,
            "style": (p.style or None) if p.rated else None,
            "contract": p.contract or None,
            "unrated": None if p.rated else unrated_text(p.minutes),
        })
    return rows


def metric_matrix(players: list[SfPlayer], perf: list[tuple[str, str]],
                  phys: list[tuple[str, str]]) -> dict:
    """Percentile per metric per player (players with none are left out); the best figure in
    each row is flagged. A section with no value at all (e.g. no SkillCorner cover in that
    league/season) is left out."""
    keys = [k for k, _ in perf + phys]
    cols = _with_pct(players, keys)

    def section(name, metrics):
        if not metrics or not any(_val(p, k) is not None for p in cols for k, _ in metrics):
            return None
        rows = []
        for key, label in metrics:
            vals = [_val(p, key) for p in cols]
            top = max((v for v in vals if v is not None), default=None)
            rows.append({"label": label,
                         "cells": [{"pct": None if v is None else _round_half_up(v),
                                    "raw": v, "best": v is not None and v == top}
                                   for v in vals]})
        return {"name": name, "rows": rows}

    return {"players": [{"name": p.name, "short": p.name.split()[-1], "is_target": p.is_target}
                        for p in cols],
            "sections": [s for s in (section("Performance", perf), section("Physical", phys)) if s]}


# =============================== data (cached loaders only) ===================================
# Every query below is kept in process per data version (`core.webcache`: a pipeline write
# refreshes it, nothing runs or unpickles on a repeat request; callers never mutate the frames). The
# percentile and style frames come from the loaders the Players page already warms.
from lofc.dashboard import compare_tables as ct            # noqa: E402
from lofc.core import webcache                             # noqa: E402
from lofc.dashboard import loaders as L                    # noqa: E402
from lofc.dashboard import seasons as seasons_mod          # noqa: E402

_KEYS = ["player_id", "competition_id", "season_id", "position_group"]


@webcache.versioned(maxsize=2)
def squad() -> pd.DataFrame:
    """Our current players: position (see module doc), birth date, contract end, and the club of
    his latest season row (for "Joined from")."""
    engine = L.get_engine()
    cols = ["player_id", "player_name", "position_group", "birth_date", "contract_until",
            "last_club", "tm_player_id"]
    cur = pd.read_sql("SELECT player_id, impect_squad_id, club_name FROM player_current_club "
                      "WHERE impect_squad_id = %(sid)s OR lower(club_name) LIKE %(pat)s",
                      engine, params={"sid": ORIENT_SQUAD_ID, "pat": ORIENT_NAME + "%"})
    cur = cur[[is_orient_club(n, s) for n, s in zip(cur["club_name"], cur["impect_squad_id"])]]
    ids = sorted({int(i) for i in cur["player_id"]})
    if not ids:
        return pd.DataFrame(columns=cols)
    neutral = pd.read_sql(
        "SELECT player_id, player_name, season_id, position_group, minutes, team_name "
        "FROM player_metrics_neutral WHERE player_id = ANY(%(ids)s)", engine, params={"ids": ids})
    bio = pd.read_sql("SELECT player_id, birth_date, contract_until, tm_player_id FROM players "
                      "WHERE player_id = ANY(%(ids)s)", engine, params={"ids": ids})
    # Some of our players have no Transfermarkt id in `players` (Dovin): take it from the
    # Transfermarkt squad rows for Leyton Orient by exact name + date of birth.
    tm = pd.read_sql("SELECT tm_player_id AS tm_id, player_name AS tm_name, date_of_birth "
                     "FROM transfermarkt_squads WHERE lower(club_name) LIKE %(pat)s",
                     engine, params={"pat": ORIENT_NAME + "%"}).drop_duplicates("tm_id")
    pos = current_positions(neutral, season_options())
    # the club of his latest season row, for "Joined from"
    m = neutral.assign(_m=pd.to_numeric(neutral["minutes"], errors="coerce").fillna(0))
    last = (m.sort_values(["player_id", "season_id", "_m"], ascending=[True, False, False])
            .drop_duplicates("player_id")[["player_id", "team_name"]]
            .rename(columns={"team_name": "last_club"}))
    out = pos.merge(last, on="player_id", how="left").merge(bio, on="player_id", how="left")
    out["birth_date"] = pd.to_datetime(out["birth_date"], errors="coerce")
    out["contract_until"] = pd.to_datetime(out["contract_until"], errors="coerce")
    out["tm_player_id"] = fill_tm_ids(out, tm)
    return out[cols]


@webcache.versioned(maxsize=8)
def season_rows(season_id: int) -> pd.DataFrame:
    """One row per player for a season -- the one with the most minutes (a mid-season mover
    appears twice in the source) -- with club, league id, minutes and the All Metrics bands.
    Indexed by player_id."""
    f = pd.read_sql(
        "SELECT n.player_id, n.competition_id, n.position_group, n.team_name, n.minutes, "
        "       s.objective_composite, s.performance_band, s.physical_band, pc.peer_count "
        "FROM player_metrics_neutral n LEFT JOIN player_scorecards s "
        "  ON s.player_id = n.player_id AND s.competition_id = n.competition_id "
        " AND s.season_id = n.season_id AND s.position_group = n.position_group "
        " AND s.archetype = %(a)s "
        # peers counted over the season's FULL scorecard set, as app.py does (peer_pool_sizes)
        "LEFT JOIN (SELECT competition_id, position_group, COUNT(*) AS peer_count "
        "           FROM player_scorecards WHERE season_id = %(s)s AND archetype = %(a)s "
        "           GROUP BY competition_id, position_group) pc "
        "  ON pc.competition_id = n.competition_id AND pc.position_group = n.position_group "
        "WHERE n.season_id = %(s)s",
        L.get_engine(), params={"a": cf.DEFAULT_ARCHETYPE, "s": int(season_id)})
    f = f.assign(_m=pd.to_numeric(f["minutes"], errors="coerce").fillna(0))
    return (f.sort_values("_m", ascending=False).drop_duplicates("player_id")
            .drop(columns="_m").set_index("player_id"))


def apply_pool_floor(rows: pd.DataFrame) -> pd.DataFrame:
    """Blank the ratings of anyone whose league-position pool is below MIN_PEERS_FOR_RANKING
    (unknown pool counts as thin) and flag him `thin`: he is not rated in this section, so no
    chip, no place in "Nth of M", no "Our best", no percentiles."""
    out = rows.copy()
    out["thin"] = [pool_is_thin(None if pd.isna(n) else n) for n in out["peer_count"]]
    cols = ["objective_composite", "performance_band", "physical_band"]
    for c in cols:
        out[c] = out[c].astype("float64").mask(out["thin"])
    return out


def overlay_lens(rows: pd.DataFrame, lens: pd.DataFrame, position: str) -> pd.DataFrame:
    """Swap the three ratings of the players at `position` for the archetype lens's (only that
    position's rows differ in a lens frame); a player the lens does not rate becomes unrated."""
    out = rows.copy()
    cols = ["objective_composite", "performance_band", "physical_band"]
    at = out["position_group"] == position
    key = lens.drop_duplicates(["player_id", "competition_id"]).set_index(
        ["player_id", "competition_id"])[cols]
    for pid in out.index[at]:
        k = (pid, out.at[pid, "competition_id"])
        for c in cols:
            out.at[pid, c] = key.at[k, c] if k in key.index else float("nan")
    return out


def rated_rows(season_id: int, position: str | None = None,
               archetype: str = cf.DEFAULT_ARCHETYPE) -> pd.DataFrame:
    """The season's best-minutes rows with the peer floor applied, scored on `archetype`'s
    lens for `position` when it is not the default."""
    if archetype != cf.DEFAULT_ARCHETYPE and position:
        return _lens_rows(season_id, position, archetype)
    return apply_pool_floor(season_rows(season_id))


@webcache.versioned(maxsize=96)
def _lens_rows(season_id: int, position: str, archetype: str) -> pd.DataFrame:
    """`rated_rows` on a lens, kept for the data version: the overlay is a Python loop over
    every player at the position (~0.4 s), and Rank as is a click."""
    from lofc.core.card import ranking_for
    rows = season_rows(season_id)
    lens = ranking_for(position, archetype, season_id)
    if not lens.empty:
        rows = overlay_lens(rows, lens, position)
    return apply_pool_floor(rows)


@webcache.versioned(maxsize=8)
def style_map(season_id: int) -> dict:
    """(player_id, competition_id) -> style label for the season. Cached as a small dict on
    purpose: the full style frame (list-valued columns) is slow to unpickle from the cache on
    every request, and only a handful of labels are needed."""
    f = L.load_style_labels(season_id)
    if f.empty or "style_label" not in f.columns:
        return {}
    f = f.dropna(subset=["style_label"])
    return {(int(p), int(c)): str(lab) for p, c, lab in
            zip(f["player_id"], f["competition_id"], f["style_label"])}


def season_options() -> list[int]:
    """The last complete season and the one being played (when held), oldest first."""
    avail = L.available_seasons()
    live = settings.live_season_id
    last = seasons_mod.last_complete_season_id(avail, live)
    return [last] + ([live] if live in avail and live != last else [])


def season_label(season_id: int) -> str:
    live = settings.live_season_id
    return seasons_mod.season_name_for(season_id) + (" so far" if season_id == live else "")


def _metric_cols(pf: pd.DataFrame) -> list[str]:
    return [c for c in pf.columns if c not in _KEYS]


def _pct_dict(pf: pd.DataFrame, player_id: int, comp, pos, metrics: list[str]) -> dict:
    hit = pf[(pf["player_id"] == player_id) & (pf["competition_id"] == comp)
             & (pf["position_group"] == pos)]
    if hit.empty:
        return {}
    r = hit.iloc[0]
    return {m: float(r[m]) for m in metrics if m in r.index and pd.notna(r[m])}


def _age_now(birth) -> float | None:
    if birth is None or pd.isna(birth):
        return None
    a = (pd.Timestamp.today().normalize() - pd.Timestamp(birth)).days / 365.25
    return round(a, 1) if 14 <= a <= 50 else None


def _contract(when) -> str | None:
    return None if when is None or pd.isna(when) else pd.Timestamp(when).strftime("%b %Y")


def make_player(player_id: int, name: str, season_id: int, metrics: list[str] | None,
                birth=None, contract=None, last_club=None, is_target: bool = False,
                pf: pd.DataFrame | None = None, styles: dict | None = None,
                loans: dict | None = None, rows: pd.DataFrame | None = None) -> SfPlayer:
    """One section row from the cached season frames. `metrics` None = every metric column."""
    # frames passed in by the callers: a cached frame is copied out of the cache on each call
    rows = rated_rows(season_id) if rows is None else rows
    pf = L.load_scorecard_percentiles(season_id) if pf is None else pf
    p = SfPlayer(name=name, age=_age_now(birth), contract=_contract(contract),
                 is_target=is_target)
    r = rows.loc[player_id] if player_id in rows.index else None
    if r is not None:
        comp = int(r["competition_id"])
        p.minutes = float(r["minutes"]) if pd.notna(r["minutes"]) else None
        p.club = r["team_name"] if pd.notna(r["team_name"]) else None
        p.league = L.competition_name_by_id().get(comp)
        p.league_abbr = ct._abbr(p.league) or None
        for attr, col in (("overall", "objective_composite"), ("perf", "performance_band"),
                          ("phys", "physical_band")):
            setattr(p, attr, float(r[col]) if pd.notna(r[col]) else None)
        # Percentiles exist for rankable players only (450+ minutes); none for the rest.
        if not r["thin"]:        # a thin pool's percentiles are not shown either
            p.pct = _pct_dict(pf, player_id, comp, r["position_group"],
                              _metric_cols(pf) if metrics is None else metrics)
        if styles is not None and p.rated:
            p.style = styles.get((player_id, comp))
    loan = (loans or {}).get(player_id)
    if is_target:
        pass                      # the note describes how one of OURS arrived
    elif loan is not None and pd.notna(loan):
        p.note = f"On loan from {loan}"
    else:
        came_from = p.club if r is not None else last_club
        if isinstance(came_from, str) and not is_orient_club(came_from):
            p.note = f"Joined from {came_from}"
    return p


def _loans_to_orient() -> dict:
    """player_id -> parent club for players on loan AT Leyton Orient this season."""
    loans = L.load_loans(settings.live_season_id)
    return {} if loans.empty else loans_to_orient(loans, squad())


def _ours(position: str, season_id: int, exclude_player_id=None, metrics=None,
          styles=None, pf=None, sq_all=None, rows=None) -> list[SfPlayer]:
    sq = ours_at(squad() if sq_all is None else sq_all, position, exclude_player_id)
    if sq.empty:
        return []
    pf = L.load_scorecard_percentiles(season_id) if pf is None else pf
    rows = rated_rows(season_id) if rows is None else rows
    loans = _loans_to_orient()
    return [make_player(int(r.player_id), str(r.player_name), season_id, metrics,
                        birth=r.birth_date, contract=r.contract_until, last_club=r.last_club,
                        pf=pf, styles=styles, loans=loans, rows=rows)
            for r in sq.itertuples()]


def orient_median(position: str, season_id: int,
                  exclude_player_id=None) -> tuple[dict[str, float], int]:
    """Median percentile per metric across Leyton Orient's CURRENT players at `position`
    who have percentiles in `season_id`, and how many that is. ({}, 0) when none.
    `exclude_player_id`: leave one player out (the card passes its own player when he is ours,
    so his own figures never move the line he is drawn against)."""
    ours = _ours(position, season_id, exclude_player_id=exclude_player_id)
    pf = L.load_scorecard_percentiles(season_id)
    return median_pct(ours, _metric_cols(pf))


# --- the section ---------------------------------------------------------------------------
def season_choices() -> list[dict]:
    return [{"id": s, "label": season_label(s)} for s in season_options()]


def section(player_id: int, player_name: str, position: str, season_id: int,
            archetype: str = cf.DEFAULT_ARCHETYPE, birth=None, contract=None) -> dict:
    """The whole "Against our <position>s" section as plain data, shown for `season_id`
    (callers pass one of `season_options()`; anything else falls back to the last complete
    season). `archetype`: rate everyone (him and ours) on that lens instead of All Metrics."""
    pid = int(player_id)
    options = season_options()
    sid = season_id if season_id in options else options[0]
    sq_all = squad()
    target_is_ours = pid in set(sq_all["player_id"].astype(int))
    out: dict = {"title": title(position, target_is_ours),
                 "subtitle": subtitle(position, archetype),
                 "position": position, "season": sid, "seasons": season_choices(),
                 "target_is_ours": target_is_ours, "empty": None, "compare_note": None,
                 "verdict": None, "table": [], "radar": None, "better": None, "worse": None,
                 "gap_note": None, "metrics": None}

    radar_keys = ct.radar_metrics(position, archetype)
    perf_keys = [m for m, _t in ct.rating_metrics(position, archetype)]
    phys_keys = ct.physical_rating_metrics(position)
    styles = style_map(sid)
    pf = L.load_scorecard_percentiles(sid)
    rows = rated_rows(sid, position, archetype)
    ours = _ours(position, sid, exclude_player_id=pid if target_is_ours else None,
                 metrics=perf_keys + phys_keys, styles=styles, pf=pf, sq_all=sq_all, rows=rows)
    if not ours:
        out["empty"] = (f"Leyton Orient have no other current {plural(position).lower()} "
                        "to compare with." if target_is_ours else
                        f"Leyton Orient have no current {plural(position).lower()} "
                        "to compare with.")
        return out

    target = make_player(pid, player_name, sid, perf_keys + phys_keys, birth=birth,
                         contract=contract, is_target=True, pf=pf, styles=styles, rows=rows)
    ours = order_ours(ours)
    s = summary(target, ours)
    best = s["best"]
    out["verdict"] = {
        "rank_text": s["rank_text"], "rank": s["rank"], "of": s["of"],
        "among": among_text(s["n_ours"], s["n_unrated"], position),
        "his_rating": _num(target.overall) if target.rated else None,
        "his_league": target.league if target.rated else None,
        "our_best": _num(best.overall) if best else None,
        "our_best_sub": f"{best.name} · {best.league or DASH}" if best else None}
    out["table"] = table_rows([target] + ours)

    better, worse, n_cmp = gap_lists(target, ours, radar_keys)
    if not n_cmp:
        out["compare_note"] = (f"None of our {plural(position).lower()} has enough minutes "
                               "this season to compare metric by metric.")
        return out
    if not any(target.pct.get(m) is not None for m in radar_keys):
        out["compare_note"] = ("He has no percentiles this season, so there is no "
                               "metric-by-metric comparison.")
        return out
    med, n_med = median_pct(ours, radar_keys)
    out["radar"] = {"labels": [ct.row_label(m) for m in radar_keys], "metrics": radar_keys,
                    "target": [target.pct.get(m) for m in radar_keys],
                    "ours_median": [med.get(m) for m in radar_keys], "target_name": target.name,
                    "median_label": median_label(position, n_med)}
    out["better"] = {"heading": better_heading(n_cmp, position),
                     "items": gap_items(better, ct.row_label)}
    out["worse"] = {"heading": "Where one of ours is better",
                    "items": gap_items(worse, ct.row_label)}
    out["gap_note"] = gap_note(n_cmp, position)
    out["metrics"] = metric_matrix([target] + ours, [(m, ct.row_label(m)) for m in perf_keys],
                                   [(m, ct.row_label(m)) for m in phys_keys])
    return out
