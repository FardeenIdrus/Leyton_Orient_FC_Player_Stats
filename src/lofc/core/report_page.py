"""The Report page as plain data (TASKS 2.36).

Two halves:

  * Helpers lifted out of the Streamlit page (`dashboard/tabs/report.py`), which now calls
    them: the download file names, the URL pre-select, the Psychological band caption and the
    three variants (shown / downloaded / data-only).
  * The web page's view of one `report.data.ReportData`: every figure the downloaded document
    prints, as text formatted here in Python (the browser computes nothing), plus the form's
    criteria. The report itself is `report.data.build` -- called, never copied -- and the
    document is `report.render.to_html`.

Honesty rule (owner D1, 2026-11-09): a peer pool below MIN_PEERS_FOR_RANKING shows no
composite, rank or Performance / Physical band; the percentiles stay, with the pool size in
each heading, and the note "Not rated: only N comparable players (needs 10)".
"""
from __future__ import annotations

import datetime
import re

from lofc.model import club_criteria as cc
from lofc.report import data as D
from lofc.report import render as R

DASH = "—"
SCREEN_CHOICES = {"Meets": "meets", "Does not meet": "does_not_meet"}
_SCORES = (1, 2, 3, 4, 5)


# =============================== lifted from tabs/report.py ===============================
def safe_filename(name: str, season_label: str) -> str:
    """A filename that survives being emailed: no spaces, no punctuation, no accents lost."""
    stem = re.sub(r"[^A-Za-z0-9]+", "_", f"{name}_{season_label}").strip("_")
    return f"{stem}_report.html"


def data_only_filename(report_filename: str) -> str:
    return report_filename.replace("_report", "_data_only_report")


def preselected_label(search_index, by_label, params):
    """The label for ?player_id=&competition_id=[&season_id=] in the URL, or None. Lets a
    link (e.g. a "Write report" button on the player card) open this page on that player.
    The index is already scoped to the selected season, so a season_id that disagrees with it
    matches nothing rather than showing another season's player."""
    try:
        pid, comp = int(params.get("player_id")), int(params.get("competition_id"))
        season = int(params["season_id"]) if "season_id" in params else None
    except (TypeError, ValueError):
        return None
    hit = search_index[(search_index["player_id"] == pid)
                       & (search_index["competition_id"] == comp)]
    if season is not None:
        hit = hit[hit["season_id"] == season]
    return hit.iloc[0]["label"] if not hit.empty and hit.iloc[0]["label"] in by_label else None


def psych_band_caption(scores: dict) -> str:
    """"Band: 3.50" -- the mean of the criteria actually scored -- or "Band: —"."""
    scored = [v for v in scores.values() if v is not None]
    return f"Band: {sum(scored) / len(scored):.2f}" if scored else "Band: —"


def variants(base: D.ReportData, authored: D.Authored | None, not_rated: str | None = None):
    """(the report shown, its HTML, the data-only HTML). Derived from the one base report (no
    further database read); all-blank inputs (`authored` None) leave the report as built."""
    shown = D.with_authored(base, authored) if authored else base
    if not_rated is None:     # Streamlit's call: exactly to_html(d), as it always was
        return shown, R.to_html(shown), R.to_html(D.as_data_only(base))
    return (shown, R.to_html(shown, not_rated=not_rated),
            R.to_html(D.as_data_only(base), not_rated=not_rated))


# =============================== the web view ===============================
def not_rated_note(d: D.ReportData) -> str | None:
    """The thin-pool note when his composite rests on fewer than MIN_PEERS_FOR_RANKING rated
    peers (his league, season and position), else None. The card's own wording."""
    from lofc.core.card import thin_pool_caption
    from lofc.model.scorecard import MIN_PEERS_FOR_RANKING
    if d.composite is None or d.peer_count >= MIN_PEERS_FOR_RANKING:
        return None
    return thin_pool_caption(d.peer_count)


def _txt(v, fmt: str = "{}") -> str:
    if v is None or (isinstance(v, float) and v != v):
        return DASH
    return fmt.format(v)


def _bio(d: D.ReportData) -> list[dict]:
    return [{"label": "Age", "text": _txt(d.age or None, "{:.1f}")},
            {"label": "Foot", "text": d.foot.capitalize() if d.foot else DASH},
            {"label": "Height", "text": f"{d.height_cm}cm" if d.height_cm else DASH},
            {"label": "Nationality", "text": d.nationality or DASH},
            {"label": "Contract to", "text": d.contract_until or DASH}]


def _splits(d: D.ReportData) -> str | None:
    """"Winger 45% · Full Back 35% · …" -- only when he played more than one position; three
    named at most, the rest counted (the document's own rule)."""
    shares = d.position_shares
    if len(shares) <= 1:
        return None
    text = " · ".join(f"{g} {share * 100:.0f}%" for g, _m, share, _g, _a in shares[:3])
    return text + (f" · +{len(shares) - 3} more" if len(shares) > 3 else "")


def _verdict(d: D.ReportData, note: str | None) -> dict:
    bands = []
    for name, band in d.dimension_bands.items():
        theirs = bool(d.authored) and name in ("Psychological", "Medical")
        withheld = note is not None and name in ("Performance", "Physical")
        if withheld:
            value, text = None, DASH
        elif band is not None:
            value, text = float(band), f"{band:.2f}"
        else:
            value, text = None, DASH if theirs else "not assessed"
        bands.append({"name": name, "value": value, "text": text, "author": theirs})
    flags = [f for f in d.flags
             if not (note and f.startswith(("Composite ", "Performance ", "Physical ")))]
    screening = ([{"ok": a == "Meets", "text": t} for t, a in d.authored.screening.items()]
                 if d.authored and d.authored.screening else [])
    rated = note is None and d.composite is not None
    return {
        "composite": f"{d.composite:.2f}" if rated else None,
        "value": float(d.composite) if rated else None,
        "not_rated": note,
        "rank": (f"{d.rank}{R.ordinal(d.rank)} of {d.peer_count} {d.league} {d.position}s"
                 if d.rank and note is None else None),
        "bands": bands, "screening": screening, "flags": flags}


def _lines(text: str | None) -> list[str]:
    return [x for x in (text or "").split("\n") if x.strip()]


def _narrative(d: D.ReportData) -> dict:
    n = d.narrative
    summary = _lines(n.summary) if n else []
    byline = None
    if n and n.assessor:
        byline = f"Assessed by {n.assessor}"
        if n.assessor_role:
            byline += f" ({n.assessor_role})"
        if n.approver:
            byline += f" · signed off by {n.approver}"
    absent = None
    if not summary:
        absent = ("No summary written." if d.authored else
                  "No scout assessment recorded — this report presents data only.")
    return {"summary": summary, "absent": absent, "why_sign": _lines(n.why_sign if n else None),
            "considerations": _lines(n.considerations if n else None), "byline": byline}


def _vs(d: D.ReportData, note: str | None) -> str:
    """"League Two Wingers", or "8 League Two Wingers" for a thin pool (the card's heading)."""
    base = f"{d.league} {d.position}s"
    return f"{d.peer_count} {base}" if note else base


def _technical(d: D.ReportData, vs: str) -> dict:
    count = lambda v: DASH if v is None else f"{R.half_up(v):,}"
    bars = [{"label": b["label"], "value": b["shown"],
             "text": None if b["shown"] is None else f"{b['shown']:.1f}", "orient": b["orient"]}
            for b in R.bar_inputs(d)]
    cross = (d.benchmark_n and d.benchmark_league and d.benchmark_league != d.league)
    whence = R.goals_by_position(d.position_shares)
    return {
        "vs": vs,
        "counts": [{"label": "Minutes", "text": count(d.minutes or None)},
                   {"label": "Goals", "text": count(d.goals)},
                   {"label": "Assists", "text": count(d.assists), "help": D.ASSIST_DEFINITION},
                   {"label": "Chances created", "text": count(d.chances_created)}],
        "whence": " · ".join(whence) if whence else None,
        "bars": bars,
        "orient": ({"n": d.benchmark_n, "label": f"Leyton Orient median (n={d.benchmark_n})"}
                   if d.benchmark_n else None),
        "orient_note": (f"Orient median is within {d.benchmark_league}; his percentiles are "
                        f"within {d.league}." if cross else None)}


def _style(d: D.ReportData, vs: str) -> dict | None:
    from lofc.model import styles as sm
    sv = R.style_view(d)
    if sv is None:
        return None
    return {"label": sv["label"], "vs": vs, "strong": sm.STRONG, "floor": sm.FLOOR,
            "help": ("Fit = average percentile of the style's signals vs the same position, "
                     f"league and season. Strong ≥ {sm.STRONG:.0f}, Leans ≥ {sm.FLOOR:.0f}. "
                     "⚑ = quality signal."),
            "groups": [{"title": g["title"] or None,
                        "rows": [{"name": r["name"], "fit": float(r["fit"]), "tag": r["tag"],
                                  "level": ("Strong" if r["fit"] >= sm.STRONG else
                                            "Leans" if r["fit"] >= sm.FLOOR else None),
                                  "signals": r["signals"]} for r in g["rows"]]}
                       for g in sv["groups"]]}


def _physical(d: D.ReportData, vs: str) -> dict:
    from lofc.dashboard.glossary_data import PHYSICAL
    keys = [k for k, _label in R._PHYSICAL_AXES]
    player = [d.physical.get(k) for k in keys]
    orient = [d.benchmark.get(k) for k in keys] if d.benchmark_n else None
    if orient is not None and not any(v is not None for v in orient):
        orient = None
    return {"vs": vs, "axes": [PHYSICAL[k][0] if k in PHYSICAL else lab
                               for k, lab in R._PHYSICAL_AXES],
            "player": player, "orient": orient,
            "orient_label": f"Leyton Orient median (n={d.benchmark_n})" if orient else None,
            "has_data": any(v is not None for v in player)}


def _availability(d: D.ReportData) -> dict:
    if d.availability is not None:
        return {"figure": f"{d.availability * 100:.0f}%",
                "note": f"{d.matches_missed} matches missed through injury, last two seasons."}
    return {"figure": "Not known",
            "note": "No injury record; minutes do not confirm availability either way."}


def view(d: D.ReportData, ids: dict | None = None) -> dict:
    """Everything the Report page draws for one report, as text and plain numbers."""
    note = not_rated_note(d)
    vs = _vs(d, note)
    shares = d.position_shares
    return {
        "ids": ids or {},
        "name": d.player_name, "position": d.position, "club": d.club or DASH,
        "league": d.league, "season_label": d.season_label,
        "stamp": d.stamp, "authored": d.authored is not None,
        "data_as_at": f"Data as at {d.snapshot_date}",
        "comparison": d.comparison_text,
        "splits": _splits(d),
        "minority_note": (f"Scored as {d.position}, his largest position, though under half "
                          "his minutes." if shares and shares[0][2] < 0.5 else None),
        "bio": _bio(d),
        "verdict": _verdict(d, note),
        "narrative": _narrative(d),
        "technical": _technical(d, vs),
        "style": _style(d, vs),
        "physical": _physical(d, vs),
        "availability": _availability(d),
        "author_note": (f"Psychological, Medical and medical checks are "
                        f"{d.authored.author_name}'s assessment and do not change any rating."
                        if d.authored else None),
        "psych_caption": (f"Band: {d.authored.psych_band:.2f}" if d.authored
                          and d.authored.psych_band is not None else "Band: —"),
        "filename": safe_filename(d.player_name, d.season_label),
    }


# =============================== the "Write your report" form ===============================
def form_spec(position: str) -> dict:
    """The form's fields for this position: the three text areas, the Psychological criteria
    (each 1-5 or blank) and the Medical criteria (screening ones answered Meets / Does not
    meet; the others shown as text), then the Medical band."""
    return {
        "text_areas": [{"key": "summary", "label": "Summary", "rows": 4},
                       {"key": "why_sign", "label": "Why sign?", "rows": 3},
                       {"key": "considerations", "label": "Considerations", "rows": 3}],
        "psychological": [{"text": t} for t in cc.PSYCHOLOGICAL_CRITERIA.get(position, [])],
        "medical": [{"text": c.text, "kind": c.kind}
                    for c in cc.MEDICAL_CRITERIA.get(position, [])],
        "scores": list(_SCORES), "screen_choices": list(SCREEN_CHOICES),
    }


def _score(v) -> int | None:
    try:
        x = int(v)
    except (TypeError, ValueError):
        return None
    return x if x in _SCORES else None


def authored_from_body(position: str, body: dict, author_name: str, author_role: str | None,
                       now: datetime.datetime | None = None) -> D.Authored | None:
    """The web form's JSON as `report.data.authored_from_inputs` (the Streamlit form's call):
    only this position's criteria, scores 1-5, screening answers Meets / Does not meet;
    anything else is ignored. None when every field is blank."""
    body = body if isinstance(body, dict) else {}
    psych_texts = cc.PSYCHOLOGICAL_CRITERIA.get(position, [])
    screen_texts = {c.text for c in cc.MEDICAL_CRITERIA.get(position, [])
                    if c.kind == "screening"}
    given = body.get("psych") if isinstance(body.get("psych"), dict) else {}
    scores = {t: _score(given.get(t)) for t in psych_texts}
    answers = body.get("screening") if isinstance(body.get("screening"), dict) else {}
    screening = {t: a for t, a in answers.items() if t in screen_texts and a in SCREEN_CHOICES}
    text = lambda k: body.get(k) if isinstance(body.get(k), str) else None
    return D.authored_from_inputs(author_name=author_name, author_role=author_role,
                                  summary=text("summary"), why_sign=text("why_sign"),
                                  considerations=text("considerations"), psych_scores=scores,
                                  medical_band=_score(body.get("medical_band")),
                                  screening=screening, now=now)


# =============================== cached reads (web only) ===============================
def _engine():
    from lofc.dashboard import loaders as L
    return L.get_engine()


def _webcache():
    from lofc.core import webcache
    return webcache


def _cached():
    """The version-keyed caches, created on first use so importing this module (Streamlit,
    tests) never touches the web cache registry."""
    global _CACHES
    if _CACHES is None:
        wc = _webcache()

        @wc.versioned(maxsize=3)
        def season(season_id: int):
            return D.season_inputs(_engine(), int(season_id))

        @wc.versioned(maxsize=1)
        def resolved():
            return D.resolved_bands(_engine())

        @wc.versioned(maxsize=96)
        def base(player_id: int, competition_id: int, season_id: int):
            return D.build(_engine(), player_id, competition_id, season_id,
                           season=season(season_id), resolved=resolved())
        _CACHES = {"season": season, "resolved": resolved, "base": base}
    return _CACHES


_CACHES: dict | None = None


def base_report(player_id: int, competition_id: int, season_id: int) -> D.ReportData:
    """`report.data.build` for one player-season, with the season-wide frames and the resolved
    bands read once per data version. Raises ValueError for an unknown player-season."""
    return _cached()["base"](int(player_id), int(competition_id), int(season_id))


def warm(season_ids) -> None:
    """Fill the season-wide frames (newest season first) and one report per season."""
    c = _cached()
    c["resolved"]()
    for sid in season_ids:
        s = c["season"](int(sid))
        n = s.neutral
        if len(n):
            r = n.iloc[0]
            try:
                base_report(int(r["player_id"]), int(r["competition_id"]), int(sid))
            except ValueError:
                pass

