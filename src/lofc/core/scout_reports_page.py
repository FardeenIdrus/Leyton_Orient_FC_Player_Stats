"""Scout reports page logic, shared by the Streamlit page (`dashboard/tabs/scout_reports.py`,
which now calls these) and the web page (`web/api/scout_reports.py`).

The comparison itself (`model_view`, `filter_reports`, `scout_activity`, `sync_status`, the
display table) stays in the Streamlit module and is called from here unchanged; this module
holds what `render()` used to do inline: which seasons, the labels, the counts and captions, the
filter lists, and the report card's content.

Web only (owner decision D1, 2026-11-09): `thin_sizes` + `prepare(thin=)` withhold a last-season
rating whose league-position pool is below MIN_PEERS_FOR_RANKING (the live-season rating already
is, in the SQL), and `best_targets` resolves, for every linked player at once, the card the
Streamlit "Open in Players" button opens. Nothing here touches a score.
"""
from __future__ import annotations

import datetime as dt

import pandas as pd

TABS = ("all", "disagree", "activity")
NOT_LINKED = ("This player is not in the platform's data — no rating, percentile or peer "
              "comparison exists for him. The report above is the whole record.")
NO_RATED_SEASON = "Matched to our data, but he has no rated season yet — nothing to open."

# The query-string keys of the web page, in the Streamlit widget order, -> filter_reports arg.
FILTER_KEYS = {"q": "search", "league": "league", "max_age": "max_age", "foot": "foot",
               "scout": "scout", "verdict": "verdict", "grade": "grade", "position": "position",
               "club": "club", "seen": "observation", "data": "in_our_data",
               "dvs": "data_vs_scout"}
MAX_AGE_MIN, MAX_AGE_MAX = 16, 40          # the Streamlit number input; 40 = no filter
# Web only (owner, 2026-11-13): Squad role, ?role=. The scouting form's own values, in its
# order; a value the form gains later is listed after them (the list is built from the data).
SQUAD_ROLE_ORDER = ("Core (>70% of Minutes)", "Support (21-69% of Minutes)",
                    "Fringe (<20% of Minutes)", "Emerging Talent (Ready in Next 12-18 Months)",
                    "Below the Required Standard for LOFC")


def _sr():
    from lofc.dashboard.tabs import scout_reports as sr
    return sr


def rating_seasons(seasons) -> tuple[int, int]:
    """(rating season, current season): reports are current-season observations; the rating
    beside them is the last COMPLETE season (`dashboard/app.py::_scout_reports_page`)."""
    cur = max(seasons)
    prev = max((s for s in seasons if s < cur), default=cur)
    return prev, cur


def live_label(rating_season_id: int, rating_label: str, live_id) -> str:
    from lofc.dashboard.seasons import season_name_for
    return season_name_for(live_id) if live_id and live_id != rating_season_id else rating_label


def short_label(label: str) -> str:
    """2025/26 -> 25/26."""
    return label[2:] if len(label) == 7 else label


def thin_sizes(frame: pd.DataFrame, scorecards: pd.DataFrame, season_id: int) -> pd.Series:
    """Per report: the size of the league-position pool his last-season rating comes from, when
    it is below MIN_PEERS_FOR_RANKING; NaN otherwise (or no rating). Pools are counted over the
    season's full scorecard set (`scorecard.peer_pool_sizes`), as the Players page and card do."""
    from lofc.model.scorecard import peer_pool_sizes, pool_is_thin
    sizes = peer_pool_sizes(scorecards)
    pos = {(int(p), int(c)): g for p, c, g in zip(scorecards["player_id"],
                                                    scorecards["competition_id"],
                                                    scorecards["position_group"])}
    out = []
    for pid, cid, comp in zip(frame["player_id"], frame["rated_in"], frame["composite"]):
        if pd.isna(pid) or pd.isna(cid) or pd.isna(comp):
            out.append(float("nan"))
            continue
        group = pos.get((int(pid), int(cid)))
        n = sizes.get((int(cid), int(season_id), group)) if group is not None else None
        # no scorecard row found: leave the rating as Streamlit shows it (cannot tell)
        out.append(float(n) if n is not None and pool_is_thin(n) else float("nan"))
    return pd.Series(out, index=frame.index, dtype="float64")


def prepare(frame: pd.DataFrame, rating_label: str, live_label_: str, names: dict,
            thin: pd.Series | None = None) -> pd.DataFrame:
    """The reports with the "Data vs scout" comparison and the League column, as the page shows
    them. `thin` (web only): per-row thin pool size from `thin_sizes`; such a last-season
    rating is blanked BEFORE the comparison, and a report left with no rating says why."""
    from lofc.core.card import thin_pool_caption
    sr = _sr()
    if thin is not None:
        frame = frame.copy()
        thin = thin.reindex(frame.index)
        frame["composite"] = pd.to_numeric(frame["composite"], errors="coerce").mask(thin.notna())
    out = sr.model_view(frame, season=short_label(rating_label),
                        live_season=short_label(live_label_))
    if thin is not None:
        why = thin.notna() & out["rating_used"].isna()
        out.loc[why, sr.MODEL_VIEW] = [thin_pool_caption(int(n)) for n in thin[why]]
    out["league"] = out["league_id"].map(names)
    return out


def counts(frame: pd.DataFrame) -> dict:
    sr = _sr()
    return {"total": int(len(frame)), "players": int(frame["player_name"].nunique()),
            "scouts": int(frame["scout"].nunique()),
            "linked": int(frame["player_id"].notna().sum()),
            "disagree": int(sr.disagrees(frame[sr.MODEL_VIEW]).sum())}


def tab_labels(c: dict) -> list[str]:
    return [f"All reports ({c['total']:,})", f"Data disagrees ({c['disagree']})", "Scout activity"]


def browse_caption(shown: int, c: dict) -> str:
    """Players / scouts / linked are of ALL reports, not the filtered view (as Streamlit)."""
    return (f"{shown:,} of {c['total']:,} reports · {c['players']:,} players · "
            f"{c['scouts']} scouts · {c['linked']:,} matched to our data")


def disagree_caption(n: int) -> str:
    sr = _sr()
    return (f"{n} reports: Sign but rated under {sr.WEAK:.1f}, or Don't sign "
            f"but rated {sr.STRONG:.1f}+.")


def disagree_view(frame: pd.DataFrame) -> pd.DataFrame:
    sr = _sr()
    return frame[sr.disagrees(frame[sr.MODEL_VIEW])].sort_values("rating_used")


def sync_line(synced_at, done: dict | None, now: dt.datetime | None = None) -> tuple[str, bool]:
    """(status line, shown as a warning?) -- the suffix after a Refresh included."""
    sr = _sr()
    status = sr.sync_status(synced_at, now=now)
    line = status
    if done is not None:
        line += (" · sheet unchanged" if not done["changed"]
                 else f" · {done['written']} reports updated")
    return line, ("not updating" in status or "Never" in status)


def filter_options(frame: pd.DataFrame) -> dict[str, list[str]]:
    """Every filter's options, in the Streamlit widgets' order."""
    sr = _sr()
    return {
        "League": ["All"] + sorted(frame["league"].dropna().unique()),
        "Foot": ["All", "Left", "Right"],
        "Scout": sr._options(frame, "scout"),
        "Verdict": sr._options(frame, "verdict"),
        "Grade": sr._options(frame, "grade"),
        "Position": sr._position_options(frame),
        "Club": sr._options(frame, "club_name"),
        "Seen": sr._options(frame, "observation"),
        "Our data": ["All", "In our data", "Not in our data"],
        "Data vs scout": list(sr.DATA_VS_SCOUT_GROUPS),
        "Squad role": squad_role_options(frame),
    }


def squad_role_options(frame: pd.DataFrame) -> list[str]:
    """"All" + the squad roles present, in the form's order (unknown ones after, A-Z)."""
    have = ({str(v) for v in frame["squad_role"].dropna() if str(v).strip()}
            if "squad_role" in frame.columns else set())
    known = [r for r in SQUAD_ROLE_ORDER if r in have]
    return ["All"] + known + sorted(have - set(known))


def parse_max_age(value) -> int | None:
    """The web query's max age -> filter_reports' `max_age` (None = no filter, as the widget's
    40; anything outside the widget's 16-40 is ignored)."""
    try:
        n = int(str(value))
    except (TypeError, ValueError):
        return None
    if n < MAX_AGE_MIN or n >= MAX_AGE_MAX:
        return None
    return n


def apply_filters(frame: pd.DataFrame, query: dict) -> pd.DataFrame:
    """`filter_reports` with the web page's query string (keys of FILTER_KEYS)."""
    sr = _sr()
    kw = {arg: (query.get(key) or None) for key, arg in FILTER_KEYS.items()}
    kw["max_age"] = parse_max_age(query.get("max_age"))
    out = sr.filter_reports(frame, **kw)
    role = query.get("role")
    if role and role != "All" and "squad_role" in out.columns:
        out = out[out["squad_role"] == role]
    return out


def display_table(view: pd.DataFrame, names: dict) -> pd.DataFrame:
    """The table as shown ("—" blanks, ratings "x.xx"), row order = `view`'s."""
    sr = _sr()
    return sr.report_display(sr._table(view, names).reset_index(drop=True))


def column_help(rating_label: str, live_label_: str) -> dict[str, str]:
    """The Streamlit column help texts (the web page uses them as hover tips)."""
    sr = _sr()
    return {
        "Rating": ("The platform's 1-5 composite from the last complete season. Blank is not a "
                   "poor rating — Data vs scout says why there is none."),
        "This season": ("This season's rating, where he has 450+ minutes and at least 10 "
                        "league-position peers do too. Updates every Monday."),
        "Player": "† = name read from the report text.",
        sr.MODEL_VIEW: (f"The scout's verdict against the player's rating (this season's where "
                        f"he has one). Agrees: Sign and {sr.STRONG:.1f}+, or Don't sign and "
                        f"under {sr.WEAK:.1f}. Monitor is not compared."),
    }


def _plain(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value)


def report_card(row: pd.Series) -> dict:
    """One report's card content, unescaped (each surface escapes it): tone + accent colour,
    name, club, meta line, verdict, the facts present, the scout's words."""
    sr = _sr()
    tone = sr.verdict_tone(row.get("verdict"))
    fixture = sr.fixture_label(row.get("home_team"), row.get("away_team"),
                               row.get("fixture_date"))
    played = row.get("positions_played")
    played = ", ".join(played) if isinstance(played, list) else ""
    wanted = row.get("recommended_positions")
    wanted = ", ".join(wanted) if isinstance(wanted, list) else ""
    meta_parts = [b for b in [row.get("scout"), row.get("observation"),
                              f"Grade {row.get('grade')}" if pd.notna(row.get("grade")) else None]
                  if b]
    facts = []
    if fixture:
        facts.append(["Fixture", fixture])
    if played:
        facts.append(["Played", played])
    if wanted:
        facts.append(["Recommended", wanted])
    if pd.notna(row.get("squad_role")):
        facts.append(["Squad role", row.get("squad_role")])
    return {"tone": tone, "accent": sr.TONE_COLOURS[tone][0],
            "player": row.get("player_name"), "club": row.get("club_name"),
            "meta_parts": meta_parts, "meta": " · ".join(_plain(b) for b in meta_parts),
            "verdict": row.get("verdict") or "—", "facts": facts,
            "body": _plain(row.get("comments"))}


def best_targets(rows: pd.DataFrame) -> dict[int, tuple[int, int]]:
    """player_id -> (competition_id, season_id) of the card to open: `squads.best_profile_target`
    over each player's rated rows (the Streamlit "Open in Players" rule)."""
    from lofc.dashboard.tabs.squads import best_profile_target
    out = {}
    if rows is None or rows.empty:
        return out
    for pid, group in rows.groupby("player_id"):
        target = best_profile_target(group)
        if target:
            out[int(pid)] = target
    return out


def rated_rows_for(engine, player_ids) -> pd.DataFrame:
    """`squads.player_rated_rows` for many players in one query (same SELECT)."""
    ids = sorted({int(p) for p in player_ids})
    cols = ["player_id", "competition_id", "season_id", "minutes", "objective_composite"]
    if not ids:
        return pd.DataFrame(columns=cols)
    return pd.read_sql(
        "SELECT s.player_id, s.competition_id, s.season_id, m.minutes, s.objective_composite "
        "FROM player_scorecards s "
        "JOIN player_metrics_neutral m ON m.player_id = s.player_id "
        " AND m.competition_id = s.competition_id AND m.season_id = s.season_id "
        "WHERE s.archetype = 'All Metrics' AND s.player_id = ANY(%(ids)s)",
        engine, params={"ids": ids})
