"""全部路由。薄層：解析表單 → repo/domain → 模板。"""
from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from splitbook.domain.ledger import compute_balances
from splitbook.domain.split import (
    SplitError, split_equal, split_exact, split_weights)
from splitbook.web.app import templates
from splitbook.web.auth import hash_pin, make_token, parse_token, verify_pin

router = APIRouter()

CATEGORIES = ["住宿", "餐費", "交通", "票券", "雜支"]


def current(request: Request):
    """回傳 (repo, group_id, member_row)；未登入回 None。"""
    repo = request.app.state.repo
    token = request.cookies.get("session", "")
    parsed = parse_token(token, request.app.state.secret)
    if parsed is None:
        return None
    gid, mid = parsed
    member = repo.get_member(mid)
    if member is None or member["group_id"] != gid or not member["active"]:
        return None
    return repo, gid, member


def _redirect(path: str) -> RedirectResponse:
    return RedirectResponse(path, status_code=303)


# -- setup ------------------------------------------------------------
@router.get("/setup")
def setup_page(request: Request):
    return templates.TemplateResponse(
        "setup.html", {"request": request})


@router.post("/setup")
def setup_submit(request: Request, group_name: str = Form(...),
                 member1: str = Form(""), member2: str = Form(""),
                 member3: str = Form(""), member4: str = Form(""),
                 member5: str = Form("")):
    repo = request.app.state.repo
    names = [n.strip() for n in
             (member1, member2, member3, member4, member5) if n.strip()]
    if not group_name.strip() or not names:
        return templates.TemplateResponse("setup.html", {
            "request": request, "error": "請填寫帳本名稱與至少一位成員"})
    gid = repo.create_group(group_name.strip())
    for n in names:
        repo.add_member(gid, n)
    return _redirect("/login")


# -- login ------------------------------------------------------------
def _login_context(request, repo, error=""):
    groups = []
    for g in repo.list_groups():
        groups.append({"group": g, "members": repo.list_members(g["id"])})
    return {"request": request, "groups": groups, "error": error}


@router.get("/login")
def login_page(request: Request):
    repo = request.app.state.repo
    return templates.TemplateResponse(
        "login.html", _login_context(request, repo))


@router.post("/login")
def login_submit(request: Request, member_id: int = Form(...),
                 pin: str = Form("")):
    repo = request.app.state.repo
    member = repo.get_member(member_id)
    if member is None or not member["active"]:
        return templates.TemplateResponse(
            "login.html", _login_context(request, repo, "找不到成員"))
    if member["pin_hash"] is None:
        if len(pin) < 4:
            return templates.TemplateResponse(
                "login.html",
                _login_context(request, repo, "第一次登入請設定 PIN（至少 4 碼）"))
        repo.set_pin_hash(member_id, hash_pin(pin))
    elif not verify_pin(pin, member["pin_hash"]):
        return templates.TemplateResponse(
            "login.html", _login_context(request, repo, "PIN 錯誤"))
    token = make_token(member["group_id"], member_id,
                       request.app.state.secret)
    resp = _redirect("/")
    resp.set_cookie("session", token, httponly=True, max_age=2592000)
    return resp


@router.post("/logout")
def logout():
    resp = _redirect("/login")
    resp.delete_cookie("session")
    return resp


# -- home（成員與餘額）--------------------------------------------------
@router.get("/")
def home(request: Request):
    repo = request.app.state.repo
    if not repo.list_groups():
        return _redirect("/setup")
    session = current(request)
    if session is None:
        return _redirect("/login")
    repo, gid, me = session
    members = repo.list_members(gid)
    entries = repo.list_entries(gid)
    error = ""
    balances = {}
    try:
        balances = compute_balances({m["id"] for m in members}, entries)
    except Exception as e:
        error = str(e)
    total_expense = sum(e.amount for e in entries if e.kind == "expense")
    return templates.TemplateResponse("home.html", {
        "request": request, "me": me, "members": members,
        "balances": balances, "error": error,
        "group": repo.get_group(gid), "total_expense": total_expense,
        "active_tab": "home",
    })


# -- expenses -----------------------------------------------------------
def parse_split(form, member_ids: list[int], amount: int,
                payer_id: int) -> dict[int, int]:
    kind = form.get("split_kind", "equal")
    if kind == "equal":
        participants = [mid for mid in member_ids if form.get(f"p_{mid}")]
        if not participants:
            participants = list(member_ids)
        return split_equal(amount, participants, payer_id=payer_id)
    if kind == "weights":
        weights = {mid: int(form.get(f"w_{mid}") or 0) for mid in member_ids}
        return split_weights(amount, {k: v for k, v in weights.items() if v > 0})
    if kind == "exact":
        amounts = {mid: int(form.get(f"x_{mid}") or 0) for mid in member_ids}
        return split_exact(amount, {k: v for k, v in amounts.items() if v != 0})
    raise SplitError(f"未知的分攤規則 {kind!r}")


def _expenses_context(request, repo, gid, me, error="", editing_id=None):
    members = repo.list_members(gid)
    names = {m["id"]: m["name"] for m in members}
    expenses = [e for e in repo.list_entries(gid) if e.kind == "expense"]
    expenses.sort(key=lambda e: (e.date, e.id), reverse=True)
    if editing_id is not None:
        editing = repo.get_entry(editing_id, gid)
    else:
        edit_id = request.query_params.get("edit")
        editing = None
        if edit_id is not None:
            try:
                editing = repo.get_entry(int(edit_id), gid)
            except (TypeError, ValueError):
                editing = None
    return {"request": request, "me": me, "members": members, "names": names,
            "expenses": expenses, "editing": editing, "error": error,
            "categories": CATEGORIES, "active_tab": "expenses"}


@router.get("/expenses")
def expenses_page(request: Request):
    session = current(request)
    if session is None:
        return _redirect("/login")
    repo, gid, me = session
    return templates.TemplateResponse(
        "expenses.html", _expenses_context(request, repo, gid, me))


async def _handle_expense_form(request, entry_id: int | None):
    session = current(request)
    if session is None:
        return _redirect("/login")
    repo, gid, me = session
    form = await request.form()
    try:
        amount = int(form["amount"])
        payer_id = int(form["payer_id"])
        member_ids = [m["id"] for m in repo.list_members(gid)]
        alloc = parse_split(form, member_ids, amount, payer_id)
        kwargs = dict(
            name=form["name"], amount=amount, payer_id=payer_id,
            allocations=alloc, category=form.get("category", ""),
            date=form.get("date", ""), note=form.get("note", ""))
        if entry_id is None:
            repo.record_expense(gid, created_by=me["id"], **kwargs)
        else:
            repo.update_expense(entry_id, group_id=gid, **kwargs)
    except (SplitError, ValueError, KeyError) as e:
        return templates.TemplateResponse(
            "expenses.html",
            _expenses_context(request, repo, gid, me, error=str(e),
                              editing_id=entry_id))
    return _redirect("/expenses")


@router.post("/expenses")
async def create_expense_route(request: Request):
    return await _handle_expense_form(request, None)


@router.post("/expenses/{eid}/update")
async def update_expense_route(request: Request, eid: int):
    return await _handle_expense_form(request, eid)


@router.post("/expenses/{eid}/delete")
def delete_expense_route(request: Request, eid: int):
    session = current(request)
    if session is None:
        return _redirect("/login")
    repo, gid, me = session
    try:
        repo.soft_delete_entry(eid, gid)
    except ValueError as e:
        return templates.TemplateResponse(
            "expenses.html",
            _expenses_context(request, repo, gid, me, error=str(e)))
    return _redirect("/expenses")
