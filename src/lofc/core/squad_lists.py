"""Squads & loans (web page), rebuilt 2026-11-16 (owner-approved).

League (every Impect league) -> Club -> the squad: every player with minutes for THAT club this
season (`impect_squad_minutes`: a January mover is listed at both clubs, with his minutes at
each), united with the Transfermarkt-registered players who have none. Contract and loan are
joined by PLAYER, so they follow him whichever club row he is on. Views: Squad, Loans in, Loans
out (minutes at the loan club). Nothing here is scored.

Honesty rules: a rating is shown only in the league of the row it sits on (his own league), with
the not-rated line for a thin pool and the midfield-pool tag; the Rating column sorts only when
every rating on the list comes from one league (no cross-league ordering).

`build_rows` takes frames (`Sources`) and builds every row of the season once; `build_page` picks
a request's rows. The SQL loaders are at the bottom; the web API caches them.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field

import pandas as pd

from lofc.dashboard.search import fold
from lofc.dashboard.seasons import calendar_months_left

ALL = "All"
VIEWS = {"squad": "Squad", "in": "Loans in", "out": "Loans out"}
CONTRACT = {"Any": None, "Under 6 months": 6, "Under 12 months": 12}
LOAN = ["Any", "On loan", "Not on loan"]
FOOT = ["Any", "Left", "Right"]
MAX_AGE = 40
STALE_DAYS = 30
DASH = "—"

TM_ONLY = "TM only, no minutes"
NOT_ON_TM = "Not on TM list ({date})"
NOW_AT = "Now at {club}"
NO_TM = "No Transfermarkt data"

MINUTES_COLUMNS = ["player_id", "competition_id", "team_name", "minutes", "position_group"]
TM_COLUMNS = ["competition_id", "club_name", "tm_player_id", "player_name", "date_of_birth",
              "contract_until", "tm_position", "scraped_at", "player_id", "foot"]
PLAYER_COLUMNS = ["player_id", "player_name", "birth_date", "contract_until", "tm_player_id",
                  "foot"]
LOAN_COLUMNS = ["player_id", "tm_player_id", "player_name", "club_name", "parent_club",
                "loan_ends"]
CARD_COLUMNS = ["player_id", "competition_id", "season_id", "position_group",
                "objective_composite", "peer_pool", "peer_pool_size"]


@dataclass
class Sources:
    season_id: int
    minutes: pd.DataFrame       # MINUTES_COLUMNS: this season, one row per player per club
    tm: pd.DataFrame            # TM_COLUMNS: the Transfermarkt squad list, linked to player_id
    players: pd.DataFrame       # PLAYER_COLUMNS
    loans: pd.DataFrame         # LOAN_COLUMNS: this season's loans, player_id resolved
    current: pd.DataFrame       # player_id, club_name (player_current_club, overrides applied)
    cards: pd.DataFrame         # CARD_COLUMNS: this season's All-Metrics scorecards
    crosswalk: dict             # Transfermarkt club name -> Impect squad name
    league_names: dict          # competition_id -> league name


def _blank(v) -> bool:
    return v is None or (not isinstance(v, str) and pd.isna(v))


def _day(d) -> str:
    d = pd.Timestamp(d)
    return f"{d.day} {d:%b}"


def _month(d) -> str:
    return pd.Timestamp(d).strftime("%b %Y")


def _ids(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").astype("Int64")


def _unique_lookup(frame: pd.DataFrame, key: str) -> pd.DataFrame:
    """`frame` indexed by `key`, keys claimed by more than one row dropped (never picked)."""
    f = frame.dropna(subset=[key])
    return f[~f[key].duplicated(keep=False)].set_index(key)


# --- every row of the season, once ----------------------------------------------------------
def build_rows(src: Sources, today: datetime.date | None = None) -> pd.DataFrame:
    """One row per (view, club, player): `view` is squad / in / out."""
    from lofc.core.card import not_rated_line, pool_tag
    from lofc.core.squads import registered_position
    from lofc.model.scorecard import peer_pool_scopes, peer_pool_sizes, pool_is_thin

    today = today or datetime.date.today()

    def xw(name):
        return None if _blank(name) else src.crosswalk.get(name, name)

    m = src.minutes.rename(columns={"team_name": "club"}).copy()
    m["player_id"] = _ids(m["player_id"])
    tm = src.tm.copy()
    tm["player_id"] = _ids(tm["player_id"])
    tm["tm_player_id"] = _ids(tm["tm_player_id"])
    tm["club"] = tm["club_name"].map(xw)

    # Each club's league: where its minutes are; a club with none yet, Transfermarkt's.
    league_of: dict = {}
    if len(m):
        league_of = (m.groupby("club")["competition_id"]
                      .agg(lambda s: int(s.value_counts().index[0])).to_dict())
    for club, comp in zip(tm["club"], tm["competition_id"]):
        league_of.setdefault(club, int(comp))
    tm_clubs = set(tm["club"].dropna())
    tm_date = tm.groupby("club")["scraped_at"].max().to_dict() if len(tm) else {}

    # Squad: minutes here, outer-joined with the registered list on (player, club).
    mm = m[["player_id", "club", "minutes", "position_group"]].assign(in_impect=True)
    reg = tm.rename(columns={"player_name": "tm_name", "date_of_birth": "tm_dob",
                             "contract_until": "tm_contract"})
    reg = reg[["player_id", "tm_player_id", "club", "tm_name", "tm_dob", "tm_position",
               "tm_contract"]].assign(in_tm=True)
    linked = reg[reg["player_id"].notna()].drop_duplicates(["player_id", "club"])
    squad = mm.merge(linked, on=["player_id", "club"], how="outer")
    squad = pd.concat([squad, reg[reg["player_id"].isna()]], ignore_index=True)
    squad["view"] = "squad"
    squad["competition_id"] = squad["club"].map(league_of)
    squad["rating_comp"] = squad["competition_id"]
    squad["minutes_at"] = squad["club"]

    # Loans in (at the loan club) and out (at the parent club; minutes at the loan club).
    loans = src.loans.copy()
    loans["player_id"] = _ids(loans["player_id"])
    loans["tm_player_id"] = _ids(loans["tm_player_id"])
    loans["loan_club"] = loans["club_name"].map(xw)
    loans["parent"] = loans["parent_club"].map(xw)
    base = loans[["player_id", "tm_player_id", "player_name", "loan_club", "parent"]].rename(
        columns={"player_name": "tm_name"})
    inn = base[base["loan_club"].isin(league_of)].assign(view="in")
    inn["club"] = inn["loan_club"]
    inn["competition_id"] = inn["club"].map(league_of)
    inn["rating_comp"] = inn["competition_id"]
    inn["minutes_at"] = inn["club"]
    out = base[base["parent"].isin(league_of)].assign(view="out")
    out["club"] = out["parent"]
    out["competition_id"] = out["club"].map(league_of)
    out["rating_comp"] = out["loan_club"].map(league_of)
    out["minutes_at"] = out["loan_club"]
    at = m.drop_duplicates(["player_id", "club"]).set_index(["player_id", "club"])
    for part in (inn, out):
        keys = list(zip(part["player_id"], part["minutes_at"]))
        part["minutes"] = [at["minutes"].get(k) if not _blank(k[0]) else None for k in keys]
        part["position_group"] = [at["position_group"].get(k) if not _blank(k[0]) else None
                                  for k in keys]
        part["in_impect"] = part["minutes"].notna()
        part["in_tm"] = False

    rows = pd.concat([squad, inn.drop(columns=["loan_club", "parent"]),
                      out.drop(columns=["loan_club", "parent"])], ignore_index=True)
    rows["in_impect"] = rows["in_impect"].fillna(False).astype(bool)
    rows["in_tm"] = rows["in_tm"].fillna(False).astype(bool)
    rows["minutes"] = pd.to_numeric(rows["minutes"], errors="coerce").fillna(0.0)

    # --- by player: name, birth, Transfermarkt id, contract, registered position --------
    players = src.players.copy()
    players["player_id"] = _ids(players["player_id"])
    players["tm_player_id"] = _ids(players["tm_player_id"])
    bio = _unique_lookup(players, "player_id")
    pid = rows["player_id"]
    rows["tm_player_id"] = rows["tm_player_id"].where(
        rows["tm_player_id"].notna(), pid.map(bio["tm_player_id"]))
    rows["tm_player_id"] = _ids(rows["tm_player_id"])
    by_tm = tm.dropna(subset=["tm_player_id"]).groupby("tm_player_id")
    tm_contract = by_tm["contract_until"].agg(
        lambda s: s.dropna().iloc[0] if s.dropna().nunique() == 1 else pd.NaT)
    tm_dob = by_tm["date_of_birth"].first()
    tm_pos = by_tm["tm_position"].first()
    tm_foot = by_tm["foot"].first() if "foot" in tm.columns else pd.Series(dtype=object)
    tid = rows["tm_player_id"]
    rows["player"] = pid.map(bio["player_name"]).where(pid.map(bio["player_name"]).notna(),
                                                       rows["tm_name"])
    rows["birth_date"] = pd.to_datetime(pid.map(bio["birth_date"]), errors="coerce")
    for alt in (rows["tm_dob"], tid.map(tm_dob)):
        rows["birth_date"] = rows["birth_date"].fillna(pd.to_datetime(alt, errors="coerce"))
    contract = pd.to_datetime(rows["tm_contract"], errors="coerce")
    for alt in (tid.map(tm_contract), pid.map(bio["contract_until"])):
        contract = contract.fillna(pd.to_datetime(alt, errors="coerce"))
    rows["contract_until"] = contract
    # Preferred foot (filter only): our players table, else Transfermarkt's list.
    foot = pid.map(bio["foot"]) if "foot" in bio.columns else pd.Series(None, index=rows.index)
    rows["foot"] = foot.where(foot.notna(), tid.map(tm_foot)).map(
        lambda v: None if _blank(v) else str(v).strip().lower())
    registered = rows["tm_position"].where(rows["tm_position"].notna(), tid.map(tm_pos))
    marked = registered.map(lambda v: f"{g} (registered)" if (g := registered_position(v))
                            else None)
    rows["position"] = rows["position_group"].where(rows["position_group"].notna(), marked)

    # --- the loan, by player (player_id, else Transfermarkt id) -------------------------
    lp = _unique_lookup(loans, "player_id")
    lt = _unique_lookup(loans, "tm_player_id")
    for col in ("club_name", "parent_club", "loan_ends", "loan_club", "parent"):
        a, b = pid.map(lp[col]), tid.map(lt[col])
        rows[f"l_{col}"] = a.where(a.notna(), b)
    rows["on_loan"] = rows["l_club_name"].notna()

    def loan_text(r) -> str | None:
        if not r.on_loan:
            return None
        if r.l_loan_club == r.club:
            text = f"From {r.l_parent_club}" if not _blank(r.l_parent_club) else "On loan"
        elif r.l_parent == r.club:
            text = f"To {r.l_club_name}"
        else:
            text = f"At {r.l_club_name}" + ("" if _blank(r.l_parent_club)
                                            else f" from {r.l_parent_club}")
        return text + ("" if _blank(r.l_loan_ends) else f" · until {_month(r.l_loan_ends)}")

    rows["loan_text"] = [loan_text(r) for r in rows.itertuples()]

    # --- markers ------------------------------------------------------------------------
    now = (_unique_lookup(src.current.assign(player_id=_ids(src.current["player_id"])),
                          "player_id")["club_name"] if len(src.current) else pd.Series(dtype=object))
    rows["now_club"] = pid.map(now)
    rows["club_has_tm"] = rows["club"].isin(tm_clubs)

    def marks(r) -> list:
        out = []
        if r.view == "squad" and r.in_tm and not r.in_impect:
            out.append(TM_ONLY)
        if r.view == "squad" and r.in_impect and not r.in_tm and r.club_has_tm:
            out.append(NOT_ON_TM.format(date=_day(tm_date[r.club])))
        if not _blank(r.now_club) and r.now_club not in (r.club, r.l_loan_club):
            out.append(NOW_AT.format(club=r.now_club))
        return out

    rows["marks"] = [marks(r) for r in rows.itertuples()]

    # --- this season's rating, in the row's own league ----------------------------------
    cards = src.cards.copy()
    sizes, scopes = peer_pool_sizes(cards), peer_pool_scopes(cards)
    one = cards.drop_duplicates(["player_id", "competition_id"])
    card = {(int(p), int(c)): (g, v) for p, c, g, v in zip(
        one["player_id"], one["competition_id"], one["position_group"],
        one["objective_composite"])}
    ratings, notes, tags, has_card = [], [], [], []
    for p, comp in zip(rows["player_id"], rows["rating_comp"]):
        hit = None if _blank(p) or _blank(comp) else card.get((int(p), int(comp)))
        has_card.append(hit is not None)
        if hit is None or _blank(hit[1]):
            ratings.append(None), notes.append(None), tags.append(None)
            continue
        key = (int(comp), int(src.season_id), hit[0])
        n = sizes.get(key)
        if n is None:
            ratings.append(None), notes.append(None), tags.append(None)
        elif pool_is_thin(n):
            league = src.league_names.get(int(comp), f"League {int(comp)}")
            ratings.append(None), notes.append(not_rated_line(int(n), hit[0], league))
            tags.append(None)
        else:
            ratings.append(float(hit[1])), notes.append(None), tags.append(pool_tag(scopes.get(key)))
    rows["rating"], rows["rating_note"], rows["rating_tag"] = ratings, notes, tags
    rows["has_card"] = has_card

    # --- age, months left, names ----------------------------------------------------------
    stamp = pd.Timestamp(today)
    born = rows["birth_date"]
    rows["age"] = [None if pd.isna(b) else stamp.year - b.year - ((stamp.month, stamp.day)
                                                                  < (b.month, b.day))
                   for b in born]
    rows["months_left"] = rows["contract_until"].map(lambda d: calendar_months_left(d, today))
    rows["league"] = rows["competition_id"].map(
        lambda c: None if _blank(c) else src.league_names.get(int(c), f"League {int(c)}"))
    rows["season_id"] = int(src.season_id)
    keep = ["view", "league", "competition_id", "club", "club_has_tm", "player_id",
            "tm_player_id", "player", "position", "age", "minutes", "in_impect", "in_tm",
            "rating", "rating_note", "rating_tag", "rating_comp", "has_card", "contract_until",
            "months_left", "on_loan", "loan_text", "marks", "season_id", "foot"]
    return rows[keep].reset_index(drop=True)


# --- one request -----------------------------------------------------------------------------
def bare_position(v) -> str | None:
    if _blank(v):
        return None
    text = str(v)
    return text[: -len(" (registered)")] if text.endswith(" (registered)") else text


@dataclass
class PageView:
    frame: pd.DataFrame
    columns: list
    league: str = ALL
    club: str = ALL
    view: str = "squad"
    position: str = ALL
    max_age: int = MAX_AGE
    contract: str = "Any"
    loan: str = "Any"
    foot: str = "Any"
    q: str = ""
    sort: str | None = None
    descending: bool = True
    options: dict = field(default_factory=dict)
    tiles: list = field(default_factory=list)
    tm_in_scope: bool = True
    season_name: str = ""


def _filtered(frame, position, max_age, contract, loan, q, foot="Any"):
    f = frame
    if position != ALL:
        f = f[f["position"].map(bare_position) == position]
    if max_age < MAX_AGE:
        f = f[f["age"].isna() | (pd.to_numeric(f["age"], errors="coerce") <= max_age)]
    months = CONTRACT.get(contract)
    if months is not None:
        f = f[f["months_left"].notna() & (pd.to_numeric(f["months_left"], errors="coerce")
                                           < months)]
    if loan == "On loan":
        f = f[f["on_loan"]]
    elif loan == "Not on loan":
        f = f[~f["on_loan"]]
    if foot in ("Left", "Right"):
        # Left or Right includes two-footed players; unknown is left out (the Players rule).
        f = f[f["foot"].isin([foot.lower(), "both"])]
    key = fold(q)
    if key:
        f = f[f["player"].map(lambda n: key in fold(n or ""))]
    return f


def _sort_key(frame: pd.DataFrame, key: str) -> pd.Series:
    if key in ("Age", "Minutes", "Rating"):
        return pd.to_numeric(frame[{"Age": "age", "Minutes": "minutes", "Rating": "rating"}[key]],
                             errors="coerce")
    if key == "Contract to":
        return pd.to_datetime(frame["contract_until"], errors="coerce")
    col = {"Player": "player", "Position": "position", "Loan": "loan_text", "Club": "club",
           "League": "league"}[key]
    return frame[col].map(lambda v: None if _blank(v) else fold(str(v)))


def rating_sortable(league: str, frame: pd.DataFrame) -> bool:
    """The Rating column sorts only within ONE league: a league is chosen and every rating
    on the list was earned in it (Loans out mixes the loan clubs' leagues)."""
    if league == ALL:
        return False
    return frame.loc[frame["rating"].notna(), "rating_comp"].nunique() <= 1


def build_page(rows: pd.DataFrame, league: str = ALL, club: str = ALL, view: str = "squad",
               position: str = ALL, max_age: int = MAX_AGE, contract: str = "Any",
               loan: str = "Any", q: str = "", sort: str | None = None,
               descending: bool = True, season_name: str = "", foot: str = "Any") -> PageView:
    """The rows one request shows, its columns, option lists and tiles. A choice not on offer
    falls back to All (a stale shared URL still opens)."""
    leagues = [ALL] + sorted(rows["league"].dropna().unique())
    league = league if league in leagues else ALL
    scope = rows if league == ALL else rows[rows["league"] == league]
    clubs = [ALL] + sorted(scope["club"].dropna().unique())
    club = club if club in clubs else ALL
    scope = scope if club == ALL else scope[scope["club"] == club]
    view = view if view in VIEWS else "squad"
    positions = [ALL] + sorted({p for p in map(bare_position, scope["position"]) if p})
    position = position if position in positions else ALL
    contract = contract if contract in CONTRACT else "Any"
    loan = loan if loan in LOAN else "Any"
    foot = foot if foot in FOOT else "Any"
    max_age = int(min(MAX_AGE, max(16, max_age)))
    q = (q or "")[:100]
    args = (position, max_age, contract, loan, q, foot)
    per_view = {v: _filtered(scope[scope["view"] == v], *args) for v in VIEWS}
    frame = per_view[view]
    tm_in_scope = bool(rows["club_has_tm"].any()) if league == ALL else bool(
        scope["club_has_tm"].any())

    sortable = rating_sortable(league, frame)
    columns = page_columns(league, club, view, tm_in_scope, sortable, season_name)
    keys = {c["key"]: c for c in columns}
    if sort not in keys or not keys[sort]["sortable"]:
        sort = None
    if sort is None:
        order = frame.assign(_m=-frame["minutes"], _n=frame["player"].map(
            lambda v: fold(v or ""))).sort_values(["_m", "_n"], kind="mergesort")
        frame = frame.loc[order.index]
    else:
        k = _sort_key(frame, sort)
        frame = frame.loc[k.sort_values(ascending=not descending, na_position="last",
                                        kind="mergesort").index]
    squad = per_view["squad"]
    tiles = [("Players", len(squad)), ("Played", int((squad["minutes"] > 0).sum())),
             ("Loans in", len(per_view["in"])), ("Loans out", len(per_view["out"]))]
    options = {"league": leagues, "club": clubs, "position": positions,
               "view": [{"code": k, "label": v} for k, v in VIEWS.items()],
               "contract": list(CONTRACT), "loan": list(LOAN), "foot": list(FOOT),
               "max_age": {"min": 16, "max": MAX_AGE, "default": MAX_AGE}}
    return PageView(frame=frame.reset_index(drop=True), columns=columns, league=league,
                    club=club, view=view, position=position, max_age=max_age,
                    contract=contract, loan=loan, foot=foot, q=q, sort=sort, descending=descending,
                    options=options, tiles=tiles, tm_in_scope=tm_in_scope,
                    season_name=season_name)


HELP = {
    "Minutes": "This season, for this club (Impect).",
    "Minutes (loan club)": "This season, at the loan club (Impect).",
    "Rating": "This season, in his own league.",
}


def page_columns(league, club, view, tm_in_scope, rating_ok, season_name="") -> list[dict]:
    def col(key, label=None, kind="text", sortable=True, help=None):
        return {"key": key, "label": label or key, "kind": kind, "sortable": sortable,
                "help": help}
    cols = []
    if league == ALL:
        cols.append(col("League"))
    if club == ALL:
        cols.append(col("Club"))
    minutes = "Minutes (loan club)" if view == "out" else "Minutes"
    cols += [col("Player"), col("Position"), col("Age", kind="num"),
             col("Minutes", minutes, "num", help=HELP[minutes]),
             col("Rating", f"Rating {season_name}".strip(), "rating", rating_ok, HELP["Rating"])]
    if tm_in_scope:
        cols += [col("Contract to", kind="tm"), col("Loan", kind="tm")]
    return cols


# --- cells, CSV, links -------------------------------------------------------------------
def _cell(key: str, r) -> object:
    if key == "Player":
        return {"t": r.player if not _blank(r.player) else DASH, "marks": list(r.marks)}
    if key == "Rating":
        if not _blank(r.rating_note):
            return {"t": DASH, "note": r.rating_note}
        if _blank(r.rating):
            return DASH
        text = f"{r.rating:.2f}"
        return {"t": text, "tag": r.rating_tag} if not _blank(r.rating_tag) else text
    if key == "Minutes":
        return f"{int(float(r.minutes) + 0.5):,}"
    if key == "Age":
        return DASH if _blank(r.age) else str(int(r.age))
    if key == "Contract to":
        return DASH if _blank(r.contract_until) else _month(r.contract_until)
    value = {"League": r.league, "Club": r.club, "Position": r.position,
             "Loan": r.loan_text}[key]
    return DASH if _blank(value) else str(value)


def web_cells(view: PageView, today=None) -> list[list]:
    keys = [c["key"] for c in view.columns]
    return [[_cell(k, r) for k in keys] for r in view.frame.itertuples(index=False)]


def csv_table(view: PageView, today=None) -> pd.DataFrame:
    """The table on screen, as text, plus the markers in a Note column."""
    out = []
    for r, cells in zip(view.frame.itertuples(index=False), web_cells(view, today)):
        row = [c["t"] if isinstance(c, dict) else c for c in cells]
        out.append(row + ["; ".join(r.marks)])
    return pd.DataFrame(out, columns=[c["label"] for c in view.columns] + ["Note"])


NO_RECORD = "{player}: no performance record in our data, so no profile to open."
NO_RATING = "{player}: no rating in any season yet (450 minutes needed), so no profile to open."


def links(view: PageView, targets: dict) -> tuple[list, list]:
    """Per row: the card to open -- this league-season where he has a scorecard in it, else his
    most recent rated league-season (`squads.best_profile_target`) -- or why there is none."""
    hrefs, messages = [], []
    for r in view.frame.itertuples(index=False):
        name = r.player if not _blank(r.player) else DASH
        if _blank(r.player_id):
            hrefs.append(None), messages.append(NO_RECORD.format(player=name))
        elif r.has_card:
            hrefs.append(f"/player/{int(r.player_id)}/{int(r.rating_comp)}/{int(r.season_id)}")
            messages.append(None)
        elif int(r.player_id) in targets:
            c, s = targets[int(r.player_id)]
            hrefs.append(f"/player/{int(r.player_id)}/{c}/{s}"), messages.append(None)
        else:
            hrefs.append(None), messages.append(NO_RATING.format(player=name))
    return hrefs, messages


def date_line(impect, contracts, loans, today, tm_in_scope) -> list[dict]:
    """"Minutes: Impect 9 Nov · Contracts & loans: Transfermarkt 7 Sep (70 days)", as parts;
    a Transfermarkt part older than STALE_DAYS is marked stale (amber)."""
    def tm(label, d):
        days = (today - d).days
        return {"t": f"{label}: Transfermarkt {_day(d)} ({days} day{'' if days == 1 else 's'})",
                "stale": days > STALE_DAYS}
    parts = [{"t": f"Minutes: Impect {_day(impect) if impect else DASH}", "stale": False}]
    if not tm_in_scope or not (contracts or loans):
        return parts + [{"t": NO_TM, "stale": False}]
    if contracts and loans and contracts != loans:
        return parts + [tm("Contracts", contracts), tm("Loans", loans)]
    return parts + [tm("Contracts & loans", contracts or loans)]


def export_filename(league: str, club: str, view: str) -> str:
    name = club if club != ALL else league
    suffix = "" if view == "squad" else f"_loans_{view}"
    return f"lofc_squads_{name.lower().replace(' ', '_')}{suffix}.csv"


def is_stale(d, today) -> bool:
    return d is not None and (today - d).days > STALE_DAYS


# --- loaders (SQL); the web API caches them --------------------------------------------------
def load_sources(engine, season_id: int, league_names: dict) -> Sources:
    """Every frame `build_rows` needs for one season. Reads no market value."""
    return Sources(season_id=season_id, minutes=load_minutes(engine, season_id),
                   tm=load_tm(engine), players=load_players(engine),
                   loans=load_loans(engine, season_id), current=load_current(engine),
                   cards=load_cards(engine, season_id), crosswalk=load_crosswalk(engine),
                   league_names=league_names)


STALE_SHARE = 0.02


def stale_leagues(per: pd.DataFrame, neutral: pd.DataFrame) -> list[int]:
    """Leagues whose per-club minutes do not add up to the combined table's league minutes for
    more than STALE_SHARE of its players: the per-club rows are older than the ratings beside
    them (the step failed for that league, or ran on older files)."""
    if per.empty:
        return []
    sums = per.groupby(["competition_id", "player_id"], as_index=False)["minutes"].sum()
    both = neutral[["competition_id", "player_id", "minutes"]].merge(
        sums, on=["competition_id", "player_id"], how="left", suffixes=("", "_per"))
    both = both[both["competition_id"].isin(set(per["competition_id"]))]
    off = (both["minutes_per"].isna() | ((both["minutes"] - both["minutes_per"]).abs() > 1))
    share = off.groupby(both["competition_id"]).mean()
    return sorted(int(c) for c, x in share.items() if x > STALE_SHARE)


def merge_minutes(per: pd.DataFrame, neutral: pd.DataFrame) -> pd.DataFrame:
    """Per-club minutes where they agree with the combined table; the combined table (one club
    per player, the one he played most for) for a league with no per-club rows yet or with
    stale ones -- never minutes that contradict the ratings shown beside them."""
    stale = set(stale_leagues(per, neutral))
    if stale:
        import logging
        logging.getLogger("lofc.web.squads").warning(
            "per-club minutes stale for competition(s) %s; using the combined table", sorted(stale))
    use = per[~per["competition_id"].isin(stale)]
    rest = neutral[~neutral["competition_id"].isin(set(use["competition_id"]))]
    return pd.concat([use, rest], ignore_index=True)[MINUTES_COLUMNS]


def load_minutes(engine, season_id: int) -> pd.DataFrame:
    """Per-club minutes (`impect_squad_minutes`), checked against `player_metrics_neutral`
    (`merge_minutes`)."""
    try:
        per = pd.read_sql("SELECT player_id, competition_id, team_name, minutes, position_group "
                          "FROM impect_squad_minutes WHERE season_id = %(s)s", engine,
                          params={"s": season_id})
    except Exception:                                   # noqa: BLE001 (not migrated yet)
        per = pd.DataFrame(columns=MINUTES_COLUMNS)
    neutral = pd.read_sql("SELECT player_id, competition_id, team_name, minutes, position_group "
                          "FROM player_metrics_neutral WHERE season_id = %(s)s", engine,
                          params={"s": season_id})
    return merge_minutes(per, neutral)


def load_tm(engine) -> pd.DataFrame:
    """The Transfermarkt squad list, linked to our players (Transfermarkt id, then name + date
    of birth; an ambiguous key is dropped -- `squads.link_squad_players`)."""
    from lofc.core.squads import link_squad_players
    tm = pd.read_sql("SELECT competition_id, club_name, tm_player_id, player_name, date_of_birth, "
                     "contract_until, position AS tm_position, scraped_at, foot "
                     "FROM transfermarkt_squads", engine)
    if tm.empty:
        return pd.DataFrame(columns=TM_COLUMNS)
    tm["date_of_birth"] = pd.to_datetime(tm["date_of_birth"], errors="coerce")
    tm["contract_until"] = pd.to_datetime(tm["contract_until"], errors="coerce")
    tm["player_id"] = link_squad_players(tm, engine).to_numpy()
    return tm[TM_COLUMNS]


def load_players(engine) -> pd.DataFrame:
    return pd.read_sql("SELECT player_id, player_name, birth_date, contract_until, tm_player_id, foot "
                       "FROM players", engine)


def load_loans(engine, season_id: int) -> pd.DataFrame:
    from lofc.core.squads import resolve_loan_player_ids
    loans = pd.read_sql("SELECT player_id, tm_player_id, player_name, club_name, parent_club, "
                        "loan_ends FROM player_loans WHERE season_id = %(s)s", engine,
                        params={"s": season_id})
    if loans.empty:
        return pd.DataFrame(columns=LOAN_COLUMNS)
    ours = pd.read_sql("SELECT player_id, tm_player_id FROM players "
                       "WHERE tm_player_id IS NOT NULL", engine)
    return resolve_loan_player_ids(loans, ours)[LOAN_COLUMNS]


def load_current(engine) -> pd.DataFrame:
    return pd.read_sql("SELECT player_id, club_name FROM player_current_club "
                       "WHERE club_name IS NOT NULL", engine)


def load_cards(engine, season_id: int) -> pd.DataFrame:
    return pd.read_sql("SELECT player_id, competition_id, season_id, position_group, "
                       "objective_composite, peer_pool, peer_pool_size FROM player_scorecards "
                       "WHERE season_id = %(s)s AND archetype = 'All Metrics' "
                       "AND objective_composite IS NOT NULL", engine, params={"s": season_id})


def load_crosswalk(engine) -> dict:
    """Transfermarkt club -> Impect squad name, for every club both sides know
    (`model.club_crosswalk`; a clash fails loudly)."""
    from lofc.model import club_crosswalk as cw
    tm = pd.read_sql("SELECT DISTINCT club_name FROM transfermarkt_squads UNION "
                     "SELECT DISTINCT club_name FROM player_loans UNION "
                     "SELECT DISTINCT parent_club FROM player_loans WHERE parent_club IS NOT NULL",
                     engine)["club_name"].tolist()
    try:
        names = cw.impect_names(engine)
    except Exception:                                   # noqa: BLE001 (not migrated yet)
        names = pd.read_sql("SELECT DISTINCT team_name FROM player_metrics_neutral",
                            engine)["team_name"].tolist()
    return cw.resolve(tm, names, cw.load())


def tm_club_dates(engine) -> tuple:
    """(contracts date, loans date): the latest Transfermarkt squad and loan scrapes."""
    from sqlalchemy import text
    with engine.connect() as conn:
        a = conn.execute(text("SELECT MAX(scraped_at) FROM transfermarkt_squads")).scalar()
        b = conn.execute(text("SELECT MAX(scraped_at) FROM player_loans")).scalar()
    return (pd.Timestamp(a).date() if a is not None else None,
            pd.Timestamp(b).date() if b is not None else None)
