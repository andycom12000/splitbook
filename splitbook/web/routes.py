"""全部路由。薄層：解析表單 → repo/domain → 模板。"""
from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from splitbook.domain.ledger import compute_balances
from splitbook.web.app import templates
from splitbook.web.auth import hash_pin, make_token, parse_token, verify_pin

router = APIRouter()


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
