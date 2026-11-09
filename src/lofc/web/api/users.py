"""The Users page (admin only): every account, and create / reset password / clear lockout /
deactivate / reactivate -- through the app's user store, i.e. the same `lofc.store.users`
functions the Streamlit Users page and the `lofc.admin` CLI call, with the same rules
(`auth.password_problems`, `model.user_admin.guard_deactivate`). Deactivate, never delete.
No password is ever returned.

    GET  /users                          page shell (403 page for other roles)
    GET  /api/users                      the accounts, in words
    POST /api/users                      {username, full_name, role, password, confirm}
    POST /api/users/{id}/reset           {password, confirm}
    POST /api/users/{id}/unlock
    POST /api/users/{id}/active          {active: bool}
Every write needs the session AND the X-LOFC-Request header (`write_user`).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse

from lofc.dashboard import auth
from lofc.model import user_admin
from lofc.web.security import WebUser, current_user, write_user

router = APIRouter()


def _admin(user: WebUser) -> None:
    if not auth.can(user.role, "manage_users"):
        raise HTTPException(status_code=403, detail="restricted_to_administrators")


def _bad(msg: str) -> JSONResponse:
    return JSONResponse({"ok": False, "error": msg}, status_code=400)


async def _json(request: Request) -> dict:
    try:
        body = await request.json()
    except Exception:
        body = None
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="bad_request")
    return body


def _row(r, actor_id: int) -> dict:
    reason = user_admin.guard_deactivate(actor_id, r.id) if r.is_active else None
    return {"id": r.id, "username": r.username, "full_name": r.full_name, "role": r.role,
            "role_label": r.role.replace("_", " ").capitalize(),
            "active": bool(r.is_active), "status": user_admin.account_status_label(r.is_active),
            "locked": bool(r.locked),
            "lockout": user_admin.lockout_label(r.locked, r.locked_seconds_remaining),
            "created": r.created_at.strftime("%d %b %Y"),
            "can_deactivate": bool(r.is_active) and reason is None, "deactivate_reason": reason}


def _known(store, user_id: int, now) -> None:
    if not any(r.id == user_id for r in store.list_users(now)):
        raise HTTPException(status_code=404, detail="no_such_user")


@router.get("/api/users")
async def users_json(request: Request, user: WebUser = Depends(current_user)):
    _admin(user)
    store, now = request.app.state.users, request.app.state.clock()
    rows = await run_in_threadpool(store.list_users, now)
    return {"users": [_row(r, user.id) for r in rows], "roles": list(auth.ROLES),
            "role_labels": {r: r.replace("_", " ").capitalize() for r in auth.ROLES}}


@router.post("/api/users")
async def create(request: Request, user: WebUser = Depends(write_user)):
    _admin(user)
    b = await _json(request)
    username, full_name = str(b.get("username") or "").strip(), str(b.get("full_name") or "").strip()
    role, pw, confirm = str(b.get("role") or ""), str(b.get("password") or ""), str(b.get("confirm") or "")
    if not username or not full_name:
        return _bad("Username and full name are both required.")
    if pw != confirm:
        return _bad("The two passwords do not match.")
    problems = auth.password_problems(pw)
    if problems:
        return _bad("Password rejected: " + "; ".join(problems))
    try:
        await run_in_threadpool(request.app.state.users.create_user, username, full_name, role, pw)
    except ValueError as exc:
        return _bad(str(exc))
    return {"ok": True, "message": f"Created {role} account '{username}'. "
                                   "They must change their password at first sign-in."}


@router.post("/api/users/{user_id}/reset")
async def reset(user_id: int, request: Request, user: WebUser = Depends(write_user)):
    _admin(user)
    b = await _json(request)
    store, now = request.app.state.users, request.app.state.clock()
    await run_in_threadpool(_known, store, user_id, now)
    pw, confirm = str(b.get("password") or ""), str(b.get("confirm") or "")
    if pw != confirm:
        return _bad("The two passwords do not match.")
    problems = auth.password_problems(pw)
    if problems:
        return _bad("Password rejected: " + "; ".join(problems))
    try:
        await run_in_threadpool(store.reset_password, user_id, pw)
    except ValueError as exc:
        return _bad(str(exc))
    return {"ok": True, "message": "Password reset. They must change it at their next sign-in."}


@router.post("/api/users/{user_id}/unlock")
async def unlock(user_id: int, request: Request, user: WebUser = Depends(write_user)):
    _admin(user)
    store, now = request.app.state.users, request.app.state.clock()
    await run_in_threadpool(_known, store, user_id, now)
    await run_in_threadpool(store.clear_lockout, user_id)
    return {"ok": True, "message": "Lockout cleared."}


@router.post("/api/users/{user_id}/active")
async def activate(user_id: int, request: Request, user: WebUser = Depends(write_user)):
    _admin(user)
    b = await _json(request)
    active = b.get("active")
    if not isinstance(active, bool):
        raise HTTPException(status_code=400, detail="active must be true or false")
    store, now = request.app.state.users, request.app.state.clock()
    await run_in_threadpool(_known, store, user_id, now)
    if not active:
        reason = user_admin.guard_deactivate(user.id, user_id)
        if reason:
            return _bad(reason)
    await run_in_threadpool(store.set_active, user_id, active)
    return {"ok": True, "message": "Reactivated." if active else "Deactivated."}


def mount(app, render, shell) -> None:
    app.include_router(router)

    @app.get("/users", response_class=HTMLResponse, name="page_users")
    async def users_page(request: Request, user: WebUser = Depends(current_user)):
        from lofc.web import pages
        page = pages.PAGES["users"]
        if not auth.can(user.role, "manage_users"):
            return render(request, "forbidden.html", status=403, **shell(request, user, "users", page=page))
        return render(request, "users.html", **shell(request, user, "users", page=page))
