"""The Similar players page (owner 2026-11-20): page shell + JSON. Every figure comes from
`lofc.core.similar` (the same pool and method as the card's "Similar players" section); this
module only turns the URL into a request and the result into JSON. Not in the navigation:
reached from the player card.

    GET /similar/{player_id}/{competition_id}/{season_id}?scope=&max_age=&league=&min_minutes=&contract=&match=
    GET /api/similar/{player_id}/{competition_id}/{season_id}?(same)

scope = league (default) | all; max_age = a whole age 15-45; league = a competition id (All
leagues only); min_minutes and contract = one of core.similar's options; match = "pid-cid".
Anything else is ignored (a stale URL still opens).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse

from lofc.web.security import WebUser, current_user

router = APIRouter()


def _similar():
    from lofc.core import similar
    return similar


def _int(v) -> int | None:
    try:
        return int(str(v))
    except (TypeError, ValueError):
        return None


def parse_filters(q) -> dict:
    """The list's filters from a query string; junk -> no filter."""
    from lofc.core import similar as S
    scope = q.get("scope") if q.get("scope") in S.SCOPES else "league"
    age = _int(q.get("max_age"))
    league = _int(q.get("league"))
    mins = _int(q.get("min_minutes"))
    contract = _int(q.get("contract"))
    return {"scope": scope,
            "max_age": age if age is not None and 15 <= age <= 45 else None,
            "league": league if league is not None and league > 0 else None,
            "min_minutes": mins if mins in S.MIN_MINUTES_OPTIONS else None,
            "contract": contract if contract in dict(S.CONTRACT_OPTIONS) else None}


def parse_match(v) -> str | None:
    from lofc.core import similar as S
    got = S.parse_key(v)
    return f"{got[0]}-{got[1]}" if got else None


@router.get("/api/similar/{player_id}/{competition_id}/{season_id}")
async def similar_page_json(player_id: int, competition_id: int, season_id: int, request: Request,
                            user: WebUser = Depends(current_user)):
    q = request.query_params
    f = parse_filters(q)
    data = await run_in_threadpool(
        _similar().page, player_id, competition_id, season_id, f["scope"], f["max_age"],
        f["league"], f["min_minutes"], f["contract"], parse_match(q.get("match")))
    from lofc.core.card import clean
    return JSONResponse(clean(data))


def mount(app, render, shell) -> None:
    app.include_router(router)

    @app.get("/similar/{player_id}/{competition_id}/{season_id}", response_class=HTMLResponse,
             name="page_similar")
    async def similar_page(player_id: int, competition_id: int, season_id: int, request: Request,
                           user: WebUser = Depends(current_user)):
        from lofc.web import pages
        # Highlighted under Players, as the player card it is reached from.
        return render(request, "similar.html", **shell(
            request, user, "players", page=pages.PAGES["players"],
            ids=dict(player=player_id, competition=competition_id, season=season_id)))
