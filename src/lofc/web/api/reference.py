"""The three Reference pages: "What goes into each rating", "How playing styles work" and the
Glossary. Every word and figure comes from the Streamlit pages' own builders
(`dashboard.rating_reference`, `dashboard.style_reference`, `dashboard.glossary_data`), which
are built from the scoring and style code, so the pages cannot disagree with the ratings.

    GET /rating-reference   /api/rating-reference?position=   /api/rating-reference.xlsx
    GET /playing-styles     /api/playing-styles?group=
    GET /glossary           /api/glossary            (search runs in the page, on this list)
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, Response

from lofc.core import webcache
from lofc.web.security import WebUser, current_user

router = APIRouter()
RR_DEFAULT, PS_DEFAULT = "Centre Back", "Winger"
RR_SCALE = " · each metric is a percentile against the same position in the same league"
RR_NOTE = "Archetypes come from the club's positional workbook. A blank means the archetype leaves that metric out."


# --- What goes into each rating -----------------------------------------------------------------
def rating_reference(position: str | None) -> dict:
    from lofc.dashboard import rating_reference as rr
    from lofc.model import club_framework as cf
    positions = list(cf.PERFORMANCE_METRICS)
    pos = position if position in positions else RR_DEFAULT
    t = rr.rating_ingredients(pos)
    cols = [c for c in t.columns if c != "key"]
    archetypes = cf.archetypes_for(pos)[1:]
    return {"positions": positions, "position": pos,
            "weights_line": rr.weights_line(pos), "scale": RR_SCALE,
            "columns": cols, "rows": t[cols].astype(str).values.tolist(),
            "archetypes": archetypes, "note": RR_NOTE if archetypes else None}


@router.get("/api/rating-reference")
async def rating_reference_json(request: Request, user: WebUser = Depends(current_user)):
    return await run_in_threadpool(rating_reference, request.query_params.get("position"))


@router.get("/api/rating-reference.xlsx")
async def rating_reference_xlsx(user: WebUser = Depends(current_user)):
    from lofc.dashboard import rating_reference as rr
    data = await run_in_threadpool(rr.ingredients_workbook)
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": 'attachment; filename="LOFC - what goes into each rating.xlsx"'})


# --- How playing styles work ---------------------------------------------------------------------
@webcache.versioned(maxsize=8)
def _example(group: str):
    """The worked example (League One, the last complete season), as the Streamlit page picks it."""
    from lofc.config import settings
    from lofc.dashboard import loaders as L
    from lofc.dashboard import style_reference as sr
    from lofc.dashboard.seasons import last_complete_season_id, season_name_for
    sid = last_complete_season_id(L.available_seasons(), settings.live_season_id)
    ex = sr.worked_example(L.load_style_inputs(sid), group)
    return None if ex is None else dict(ex, season_id=sid, season=season_name_for(sid))


def playing_styles(group: str | None) -> dict:
    from lofc.dashboard import style_reference as sr
    from lofc.model import styles as st
    groups = list(st.STYLES)
    g = group if group in groups else PS_DEFAULT
    t = sr.style_table(g)
    cols = [c for c in ["Style", "Label", "Signals", "In plain words"]
            if not (c == "Label" and not t["Label"].any())]
    rules = sr.label_rules()
    return {"groups": groups, "group": g,
            "steps": [{"title": a, "text": b} for a, b in sr.STEPS],
            "label_rules": rules,
            "labels": [{"kind": "s", "pill": "Wide", "title": "Strong", "text": rules["Strong"]},
                       {"kind": "l", "pill": "Wide", "title": "Leans", "text": rules["Leans"]},
                       {"kind": "n", "pill": st.NO_STYLE, "title": "No label", "text": rules[st.NO_STYLE]}],
            "table": {"columns": cols, "rows": t[cols].values.tolist()},
            "example": _example(g)}


@router.get("/api/playing-styles")
async def playing_styles_json(request: Request, user: WebUser = Depends(current_user)):
    return await run_in_threadpool(playing_styles, request.query_params.get("group"))


# --- Glossary ------------------------------------------------------------------------------------
@webcache.versioned(maxsize=1)
def _glossary_entries():
    from lofc.dashboard.glossary_data import glossary_entries
    return glossary_entries()


def glossary() -> dict:
    from lofc.dashboard import glossary_data as gd
    from lofc.dashboard.tabs import glossary as g
    scored = g.rating_metrics()
    entries = sorted(_glossary_entries(), key=lambda e: e["label"].lower())
    from lofc.core.club_vs_league import TERMS
    out = [{"key": e["key"], "label": e["label"], "group": e["group"],
            "source": e["source"], "text": e["text"], "in_rating": e["key"] in scored}
           for e in entries]
    # the Club vs League One page's terms (owner 2026-11-09), in the page's own words
    out += [{"key": f"cvl:{k}", "label": k, "group": "Club vs League One", "source": "Platform",
             "text": v, "in_rating": False} for k, v in sorted(TERMS.items())]
    return {"intro": g.intro_caption(), "groups": list(gd.GROUPS) + ["Club vs League One"],
            "entries": out}


@router.get("/api/glossary")
async def glossary_json(user: WebUser = Depends(current_user)):
    return await run_in_threadpool(glossary)


def mount(app, render, shell) -> None:
    app.include_router(router)
    from lofc.web import pages

    def page(key: str, template: str):
        async def view(request: Request, user: WebUser = Depends(current_user)):
            return render(request, template, **shell(request, user, key, page=pages.PAGES[key]))
        app.add_api_route(pages.PAGES[key].path, view, methods=["GET"],
                          response_class=HTMLResponse, name=f"page_{key}")
    page("rating-reference", "rating_reference.html")
    page("playing-styles", "playing_styles.html")
    page("glossary", "glossary.html")
