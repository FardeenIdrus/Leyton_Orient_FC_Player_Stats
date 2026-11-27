"""Fixtures page (owner 2026-11-27, phase 5): which games to watch, which players in them, and
why. Pure functions only -- frames and lists in, plain data out; `web/api/fixtures.py` loads.

A player's signals (each one the owner approved, 2026-11-27):
  * Scout verdict -- ANY report (not only the latest); "Scouts disagree" when one says Sign or
    Monitor Priority and another Don't sign. Every report is shown; nothing is rejected.
  * In form -- Top (better than 80% of games at his position, club Overall) in 3+ of his last 5
    rated games, or 6+ of his last 10.
  * Rising -- his last 5 rated games' average "better than %" at least 20 points above the 5
    before (needs 10 rated games).
  * Breaking through -- under 23, 200+ minutes in his club's last 5 games and at least double
    his minutes in the 5 before (the manager trusting him), whatever his ratings.
  * Not seen yet -- season Overall 3.5+ in his own league and never scouted.

Display only: nothing here feeds the ranking (register P11).
"""
from __future__ import annotations

import functools
import re
import unicodedata

import pandas as pd

TOP, LOW = 80, 20
PRIORITY = ("Sign", "Monitor Priority")
NOT_SEEN_OVERALL = 3.5
RISE_POINTS = 20
BREAK_AGE, BREAK_MINUTES = 23, 200

REGIONS = ["London & South East", "Midlands & East", "North", "South West & Wales",
           "Scotland", "Northern Ireland", "Ireland"]
# leagues whose clubs all sit in one region; English clubs come from the club list
LEAGUE_REGION = {901: "Scotland", 902: "Scotland", 10305: "Northern Ireland", 10189: "Ireland"}


def _rated(pcts) -> list:
    return [float(p) for p in pcts if p is not None and not pd.isna(p)]


def form_flags(pcts) -> dict:
    """His rated games' "better than %" (oldest first; None = under 45 minutes, skipped)."""
    f = _rated(pcts)
    l5, l10 = f[-5:], f[-10:]
    t5 = sum(1 for p in l5 if p > TOP)
    t10 = sum(1 for p in l10 if p > TOP)
    rise_by = rise_from = rise_to = None
    if len(l10) == 10:
        rise_from, rise_to = round(sum(l10[:5]) / 5), round(sum(l10[5:]) / 5)
        rise_by = round(sum(l10[5:]) / 5 - sum(l10[:5]) / 5)
    return {"t5": t5, "t10": t10, "f5": t5 >= 3, "f10": len(l10) == 10 and t10 >= 6,
            "rise": rise_by is not None and rise_by >= RISE_POINTS, "rise_by": rise_by,
            "rise_from": rise_from, "rise_to": rise_to}


def breaking_through(age, club_minutes) -> dict:
    """`club_minutes`: his minutes in each of his club's games, oldest first (0 = did not play)."""
    m = [float(x or 0) for x in club_minutes][-10:]
    before, after = (round(sum(m[:5])), round(sum(m[5:]))) if len(m) == 10 else (None, None)
    on = (age is not None and age < BREAK_AGE and before is not None
          and after >= BREAK_MINUTES and after >= 2 * before)
    return {"on": bool(on), "before": before, "after": after}


def verdict_flags(reports) -> dict:
    vs = {r.get("verdict") for r in reports}
    pri = bool(vs & set(PRIORITY))
    return {"priority": pri, "disagree": pri and "Don't sign" in vs, "seen": bool(reports)}


# ---- names ---------------------------------------------------------------------------------
_ALIAS = {"utd": "united", "man": "manchester", "st": "st", "saint": "st", "wednesday": "wednesday"}
_DROP = {"fc", "afc", "cf", "the", "and", "glasgow", "hove", "albion"}


@functools.lru_cache(maxsize=20000)
def _fold(s) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9 ]", " ", s.replace("-", " "))


@functools.lru_cache(maxsize=5000)
def _team_tokens(name) -> frozenset:
    toks = {_ALIAS.get(t, t) for t in _fold(name).split()}
    return frozenset(t for t in toks if t not in _DROP)


def same_team(a, b) -> bool:
    """One source's club name against another's ("Dundee Utd" = "Dundee United FC",
    "Rangers" = "Glasgow Rangers"). The shorter name's words must all appear in the longer
    one, and an under-21/23 side only matches an under-21/23 side."""
    ta, tb = _team_tokens(a), _team_tokens(b)
    if not ta or not tb:
        return False
    youth = {"u21", "u23", "u18", "b"}
    if (ta & youth) != (tb & youth):
        return False
    small, big = sorted((ta, tb), key=len)
    return small <= big and len(small & big) >= 1 and not (small == {"dundee"} and "united" in big)


def region(team_name, competition_id, table: dict) -> str | None:
    """The club's region: by league for Scotland and Ireland, else the club list (`table`:
    folded name -> region). None = not in the list (shown as "Region unknown", never hidden)."""
    if competition_id in LEAGUE_REGION:
        return LEAGUE_REGION[competition_id]
    youth = {"u21", "u23", "u18", "b"}
    toks = _team_tokens(team_name) - youth            # an under-21 side plays where its club is
    for name, reg in table.items():
        if _team_tokens(name) - youth == toks:
            return reg
    return None


def load_regions() -> dict:
    """The English and PL2 club list (`reference/club_regions.csv`, checked by the owner)."""
    from pathlib import Path
    f = pd.read_csv(Path(__file__).resolve().parent.parent / "reference" / "club_regions.csv")
    return dict(zip(f["club"], f["region"]))


def _person(name) -> list:
    return [t for t in _fold(name).split() if t]


def suggest_links(unlinked: pd.DataFrame, players: pd.DataFrame) -> dict:
    """Reports not attached to a player (no birth-date match) -> the ONE player they may be
    about: his club matches the report's club, his name holds the report's surname, and the
    report's first name (or initial) is his. Two candidates -> no suggestion. These are only
    shown as "Possible report"; a person confirms with Link (a name alone is never trusted:
    `model/scout_report_link.py`). Returns player_id -> [submission_id, ...]."""
    out: dict = {}
    if unlinked is None or unlinked.empty or players is None or players.empty:
        return out
    # owner 2026-11-27 (speed): compare each report with the clubs (~200), not every player,
    # then only with that club's players
    by_team: dict = {}
    for p in players.to_dict("records"):
        by_team.setdefault(p.get("team_name"), []).append((int(p["player_id"]), _person(p.get("player_name"))))
    for r in unlinked.to_dict("records"):
        rn = _person(r.get("player_name"))
        if len(rn) < 2:
            continue
        first, last = rn[0], rn[-1]
        cands = []
        for team, roster in by_team.items():
            if not same_team(r.get("club_name"), team):
                continue
            for pid, pn in roster:
                if last in pn[1:] and pn and (pn[0] == first or (len(first) == 1 and pn[0].startswith(first))):
                    cands.append(pid)
        if len(cands) == 1:
            out.setdefault(cands[0], []).append(r["submission_id"])
    return out


# ---- page assembly -------------------------------------------------------------------------
def _age(dob, today) -> int | None:
    if dob is None or pd.isna(dob):
        return None
    dob, today = pd.Timestamp(dob), pd.Timestamp(today)
    return int(today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day)))


def players(F: dict, today) -> tuple[dict, dict]:
    """Every player of every club we hold this season, with the facts that never depend on a
    user's action (cached by the API): his club now (the club of his latest game, else where
    he has most minutes), position, age, his last 10 rated games, form, rising, breaking
    through, season Overall and his rank at the position in his league.

    F: matches (the season's fixtures), rows (his game rows: player_id, match_id, squad_id,
    competition_id, minutes, position_group), club (club Overall per game: player_id,
    match_id, minutes, overall_pct), squadmin (impect_squad_minutes), people, cards."""
    m = F["matches"].set_index("match_id")
    when = m["scheduled_at"]
    rows = F["rows"].dropna(subset=["player_id"]).copy()
    rows["player_id"] = rows["player_id"].astype(int)
    rows["at"] = rows["match_id"].map(when)
    sm = F["squadmin"].dropna(subset=["player_id"]).copy()
    sm["player_id"] = sm["player_id"].astype(int)

    squads: dict = {}
    for r in sm.to_dict("records"):
        squads.setdefault(int(r["impect_squad_id"]), {"name": r["team_name"], "comp": int(r["competition_id"])})
    for r in F["matches"].to_dict("records"):
        for side in ("home", "away"):
            sid = r.get(f"{side}_squad_id")
            if sid is not None and not pd.isna(sid):
                squads.setdefault(int(sid), {"name": r.get(f"{side}_name"), "comp": int(r["competition_id"])})

    home = {}                                   # player -> (squad, competition, position)
    for pid, g in rows.sort_values("at").groupby("player_id"):
        last = g.iloc[-1]
        home[pid] = (int(last["squad_id"]), int(last["competition_id"]), last.get("position_group"))
    for pid, g in sm.sort_values("minutes").groupby("player_id"):
        if pid not in home:
            last = g.iloc[-1]
            home[pid] = (int(last["impect_squad_id"]), int(last["competition_id"]), last.get("position_group"))

    cards = F["cards"].dropna(subset=["objective_composite"]).copy()
    cards["rk"] = cards.groupby(["competition_id", "position_group"])["objective_composite"].rank(ascending=False, method="min")
    cards["of"] = cards.groupby(["competition_id", "position_group"])["objective_composite"].transform("count")
    card = {(int(r["player_id"]), int(r["competition_id"])): r for r in cards.to_dict("records")}

    club = F["club"].dropna(subset=["player_id"]).copy()
    club["player_id"] = club["player_id"].astype(int)
    club["at"] = club["match_id"].map(when)
    form = {pid: [None if (pd.isna(mi) or mi < 45 or pd.isna(p)) else int(round(p))
                  for mi, p in zip(g["minutes"], g["overall_pct"])]
            for pid, g in club.sort_values("at").groupby("player_id")}
    mins = {(int(p), int(mt)): float(mi or 0) for p, mt, mi in zip(rows["player_id"], rows["match_id"], rows["minutes"])}
    played = F["matches"][F["matches"]["available"].fillna(False).astype(bool)].sort_values("scheduled_at")
    club_games: dict = {}
    for r in played.to_dict("records"):
        for side in ("home_squad_id", "away_squad_id"):
            if r.get(side) is not None and not pd.isna(r.get(side)):
                club_games.setdefault((int(r[side]), int(r["competition_id"])), []).append(int(r["match_id"]))
    people = F["people"].drop_duplicates("player_id").set_index("player_id")

    out = {}
    for pid, (sq, comp, pos) in home.items():
        c = card.get((pid, comp))
        if c is not None and c.get("position_group"):
            pos = c["position_group"]
        age = _age(people["birth_date"].get(pid), today) if pid in people.index else None
        f = form.get(pid, [])[-10:]
        cm = [mins.get((pid, g), 0.0) for g in club_games.get((sq, comp), [])]
        out[pid] = {"n": people["player_name"].get(pid) if pid in people.index else None, "sq": sq, "lg": comp,
                    "pos": pos, "age": age, "f": f, **form_flags(f), "br": breaking_through(age, cm),
                    "ov": None if c is None else round(float(c["objective_composite"]), 2),
                    "rk": None if c is None else int(c["rk"]), "of": None if c is None else int(c["of"])}
    return out, squads


def _reports_by_player(reports: pd.DataFrame) -> dict:
    out: dict = {}
    if reports is None or reports.empty:
        return out
    r = reports[reports["player_id"].notna()].sort_values("submitted_at", ascending=False)
    for x in r.to_dict("records"):
        d = x.get("submitted_at")
        out.setdefault(int(x["player_id"]), []).append({
            "v": x.get("verdict"), "d": None if d is None or pd.isna(d) else str(pd.Timestamp(d).date()),
            "s": x.get("scout"), "g": f"{x.get('home_team') or '?'} v {x.get('away_team') or '?'}"})
    return out


def attach(P: dict, reports: pd.DataFrame, watch: dict) -> dict:
    """The facts a user's action can change (read fresh on every request): every scout
    report (newest first), verdict flags, "Not seen yet", the watchlist stage. Returns new
    dicts; the cached players are left as they were."""
    by = _reports_by_player(reports)
    out = {}
    for pid, p in P.items():
        reps = by.get(pid, [])
        v = verdict_flags([{"verdict": r["v"]} for r in reps])
        out[pid] = {**p, "rep": reps, "pri": v["priority"], "dis": v["disagree"], "seen": v["seen"],
                    "ns": (not v["seen"]) and p.get("ov") is not None and p["ov"] >= NOT_SEEN_OVERALL,
                    "watch": watch.get(pid)}
    return out


def reports_at(reports: pd.DataFrame, at, home: str, away: str) -> list:
    """The scout reports filed at one played game: same date (a day either side, for a late
    kick-off entered as the next day) and both clubs."""
    if reports is None or reports.empty:
        return []
    day = pd.Timestamp(at).normalize()
    out = []
    for x in reports.to_dict("records"):
        fd = x.get("fixture_date")
        if fd is None or pd.isna(fd) or abs((pd.Timestamp(fd).normalize() - day).days) > 1:
            continue
        if same_team(x.get("home_team"), home) and same_team(x.get("away_team"), away):
            pid = x.get("player_id")
            out.append({"p": x.get("player_name"), "v": x.get("verdict"), "s": x.get("scout"),
                        "pid": None if pid is None or pd.isna(pid) else int(pid)})
    return out
