"""全部路由。薄層：解析表單 → repo/domain → 模板。"""
import sqlite3
from datetime import date

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from splitbook.domain.ledger import compute_balances, simplify_debts
from splitbook.domain.reconcile import by_collector, reconcile
from splitbook.domain.split import (
    SplitError, split_equal, split_exact, split_weights)
from splitbook.web.app import templates
from splitbook.web.auth import hash_pin, make_token, parse_token, verify_pin

router = APIRouter()

CATEGORIES = ["餐食", "日用", "交通", "居住", "醫療", "教育", "娛樂", "其他"]
MEMBER_COLORS = ["member-1", "member-2", "member-3", "member-4", "member-5"]
CYCLE_LABELS = {"monthly": "每月", "bimonthly": "每兩月", "yearly": "每年"}
WEEKDAYS = "一二三四五六日"
SAFE_BACK = {"/", "/expenses", "/recurring", "/list"}


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


def member_views(members) -> list[dict]:
    """成員列 → {id, name, color, initial}；沒設定識別色時依序補預設。"""
    out = []
    for i, m in enumerate(members):
        color = m["color"] or MEMBER_COLORS[i % len(MEMBER_COLORS)]
        out.append({"id": m["id"], "name": m["name"], "color": color,
                    "initial": m["name"][0]})
    return out


def _colors(mviews) -> dict[int, str]:
    return {v["id"]: v["color"] for v in mviews}


def _today() -> str:
    return date.today().isoformat()


def _shift_month(month: str, delta: int) -> str:
    total = int(month[:4]) * 12 + int(month[5:7]) - 1 + delta
    return f"{total // 12:04d}-{total % 12 + 1:02d}"


def _date_label(d: str) -> str:
    wd = WEEKDAYS[date.fromisoformat(d).weekday()]
    return f"{int(d[5:7])}/{int(d[8:10])}（週{wd}）"


def _days_overdue(next_due: str, today: str) -> int:
    return (date.fromisoformat(today) - date.fromisoformat(next_due)).days


# -- setup ------------------------------------------------------------
@router.get("/setup")
def setup_page(request: Request):
    return templates.TemplateResponse(
        request, "setup.html",
        {"request": request, "member_colors": MEMBER_COLORS})


@router.post("/setup")
def setup_submit(request: Request, group_name: str = Form(...),
                 member1: str = Form(""), member2: str = Form(""),
                 member3: str = Form(""), member4: str = Form(""),
                 member5: str = Form("")):
    repo = request.app.state.repo
    names = [n.strip() for n in
             (member1, member2, member3, member4, member5) if n.strip()]
    if not group_name.strip() or not names:
        return templates.TemplateResponse(request, "setup.html", {
            "request": request, "member_colors": MEMBER_COLORS,
            "error": "請填寫家庭名稱與至少一位成員"})
    gid = repo.create_group(group_name.strip())
    for i, n in enumerate(names):
        repo.add_member(gid, n, color=MEMBER_COLORS[i % len(MEMBER_COLORS)])
    return _redirect("/login")


# -- login ------------------------------------------------------------
def _login_context(request, repo, error=""):
    groups = []
    for g in repo.list_groups():
        groups.append({"group": g,
                       "members": member_views(repo.list_members(g["id"])),
                       "rows": repo.list_members(g["id"])})
    return {"request": request, "groups": groups, "error": error}


@router.get("/login")
def login_page(request: Request):
    repo = request.app.state.repo
    return templates.TemplateResponse(
        request, "login.html", _login_context(request, repo))


@router.post("/login")
def login_submit(request: Request, member_id: int = Form(...),
                 pin: str = Form("")):
    repo = request.app.state.repo
    member = repo.get_member(member_id)
    if member is None or not member["active"]:
        return templates.TemplateResponse(
            request, "login.html", _login_context(request, repo, "找不到成員"))
    if member["pin_hash"] is None:
        if len(pin) < 4:
            return templates.TemplateResponse(
                request, "login.html",
                _login_context(request, repo, "第一次登入請設定 PIN（至少 4 碼）"))
        repo.set_pin_hash(member_id, hash_pin(pin))
    elif not verify_pin(pin, member["pin_hash"]):
        return templates.TemplateResponse(
            request, "login.html", _login_context(request, repo, "PIN 錯誤"))
    token = make_token(member["group_id"], member_id,
                       request.app.state.secret)
    resp = _redirect("/")
    resp.set_cookie("session", token, httponly=True, samesite="lax",
                    max_age=2592000)
    return resp


@router.post("/logout")
def logout():
    resp = _redirect("/login")
    resp.delete_cookie("session")
    return resp


# -- 總覽 ---------------------------------------------------------------
@router.get("/")
def home(request: Request):
    repo = request.app.state.repo
    if not repo.list_groups():
        return _redirect("/setup")
    session = current(request)
    if session is None:
        return _redirect("/login")
    repo, gid, me = session
    today = _today()
    month = today[:7]
    members = repo.list_members(gid)
    mviews = member_views(members)
    entries = repo.list_entries(gid)
    error = ""
    balances = {}
    try:
        balances = compute_balances({m["id"] for m in members}, entries)
    except Exception as e:
        error = str(e)
    month_total = sum(e.amount for e in entries
                      if e.kind == "expense" and e.date[:7] == month)
    my_net = balances[me["id"]].net if balances else 0
    member_nets = [
        {"v": v, "net": balances[v["id"]].net if balances else None}
        for v in mviews]
    due = repo.due_templates(gid, today)
    shopping = repo.list_open_items(gid)
    recent = sorted((e for e in entries if e.kind == "expense"),
                    key=lambda e: (e.date, e.id), reverse=True)[:5]
    return templates.TemplateResponse(request, "home.html", {
        "request": request, "me": me, "group": repo.get_group(gid),
        "members": mviews, "colors": _colors(mviews),
        "names": {m["id"]: m["name"] for m in members},
        "error": error, "month_num": int(month[5:7]),
        "month_total": month_total, "my_net": my_net,
        "member_nets": member_nets,
        "due": due, "today": today,
        "due_days": {t["id"]: _days_overdue(t["next_due"], today)
                     for t in due},
        "shopping": shopping[:4], "shopping_more": max(0, len(shopping) - 4),
        "recent": recent, "date_label": _date_label,
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


def _form_context(request, repo, gid, me, editing=None, template=None,
                  error="", back=""):
    mviews = member_views(repo.list_members(gid))
    return {"request": request, "me": me, "members": mviews,
            "colors": _colors(mviews), "categories": CATEGORIES,
            "editing": editing, "template": template, "error": error,
            "back": back if back in SAFE_BACK else "",
            "today": _today(), "show_fab": False, "active_tab": "expenses"}


@router.get("/expenses")
def expenses_page(request: Request):
    session = current(request)
    if session is None:
        return _redirect("/login")
    repo, gid, me = session
    edit_id = request.query_params.get("edit")
    if edit_id is not None:
        try:
            editing = repo.get_entry(int(edit_id), gid)
        except (TypeError, ValueError):
            editing = None
        return templates.TemplateResponse(
            request, "expense_form.html",
            _form_context(request, repo, gid, me, editing=editing))
    month = request.query_params.get("month") or _today()[:7]
    members = repo.list_members(gid)
    mviews = member_views(members)
    expenses = [e for e in repo.list_entries(gid)
                if e.kind == "expense" and e.date[:7] == month]
    expenses.sort(key=lambda e: (e.date, e.id), reverse=True)
    day_groups: list[tuple[str, list]] = []
    for e in expenses:
        if day_groups and day_groups[-1][0] == e.date:
            day_groups[-1][1].append(e)
        else:
            day_groups.append((e.date, [e]))
    return templates.TemplateResponse(request, "expenses.html", {
        "request": request, "me": me, "members": mviews,
        "colors": _colors(mviews),
        "names": {m["id"]: m["name"] for m in members},
        "day_groups": day_groups, "date_label": _date_label,
        "month": month, "month_num": int(month[5:7]),
        "prev_month": _shift_month(month, -1),
        "next_month": _shift_month(month, 1),
        "is_current": month == _today()[:7],
        "month_total": sum(e.amount for e in expenses),
        "error": "", "active_tab": "expenses",
    })


@router.get("/expenses/new")
def expense_new_page(request: Request):
    session = current(request)
    if session is None:
        return _redirect("/login")
    repo, gid, me = session
    template = None
    tid = request.query_params.get("template")
    if tid is not None:
        try:
            template = repo.get_template(int(tid), gid)
        except (TypeError, ValueError):
            template = None
    back = request.query_params.get("back", "")
    return templates.TemplateResponse(
        request, "expense_form.html",
        _form_context(request, repo, gid, me, template=template, back=back))


async def _handle_expense_form(request, entry_id: int | None):
    session = current(request)
    if session is None:
        return _redirect("/login")
    repo, gid, me = session
    form = await request.form()
    back = form.get("back", "")

    def _fail(msg, template=None):
        editing = repo.get_entry(entry_id, gid) if entry_id else None
        return templates.TemplateResponse(
            request, "expense_form.html",
            _form_context(request, repo, gid, me, editing=editing,
                          template=template, error=msg, back=back))

    try:
        amount = int(form["amount"])
        payer_id = int(form["payer_id"])
        member_ids = [m["id"] for m in repo.list_members(gid)]
        alloc = parse_split(form, member_ids, amount, payer_id)
        raw_tid = form.get("template_id", "")
        template_id = int(raw_tid) if raw_tid else None
        if template_id is not None and repo.get_template(template_id, gid) is None:
            raise ValueError(f"找不到定期項目 {template_id}")
        kwargs = dict(
            name=form["name"], amount=amount, payer_id=payer_id,
            allocations=alloc, category=form.get("category", ""),
            date=form.get("date", ""), note=form.get("note", ""))
        if entry_id is None:
            repo.record_expense(gid, created_by=me["id"],
                                template_id=template_id, **kwargs)
            if template_id is not None:
                repo.advance_template(template_id, gid)
        else:
            repo.update_expense(entry_id, group_id=gid, **kwargs)
    except (SplitError, ValueError, KeyError, sqlite3.IntegrityError) as e:
        return _fail(str(e))
    return _redirect(back if back in SAFE_BACK else "/expenses")


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
            request, "expense_form.html",
            _form_context(request, repo, gid, me, error=str(e)))
    return _redirect("/expenses")


# -- 清單（購物清單）------------------------------------------------------
def _shopping_context(request, repo, gid, me, error=""):
    members = repo.list_members(gid)
    mviews = member_views(members)
    open_items = repo.list_open_items(gid)
    bought = repo.list_bought_items(gid)
    bought_entries = {}
    for it in bought:
        if it["entry_id"] and it["entry_id"] not in bought_entries:
            bought_entries[it["entry_id"]] = repo.get_entry(it["entry_id"], gid)
    buy_ids = []
    for raw in request.query_params.getlist("buy"):
        try:
            buy_ids.append(int(raw))
        except ValueError:
            pass
    sheet_items = repo.get_items(gid, buy_ids) if buy_ids else []
    return {"request": request, "me": me, "members": mviews,
            "colors": _colors(mviews),
            "names": {m["id"]: m["name"] for m in members},
            "open_items": open_items, "bought": bought,
            "bought_entries": bought_entries,
            "sheet_items": sheet_items,
            "sheet_total": sum(i["estimate"] or 0 for i in sheet_items),
            "categories": CATEGORIES, "today": _today(),
            "error": error, "active_tab": "list"}


@router.get("/list")
def shopping_page(request: Request):
    session = current(request)
    if session is None:
        return _redirect("/login")
    repo, gid, me = session
    return templates.TemplateResponse(
        request, "shopping.html", _shopping_context(request, repo, gid, me))


@router.post("/list/add")
def shopping_add(request: Request, name: str = Form(...),
                 estimate: str = Form(""), note: str = Form("")):
    session = current(request)
    if session is None:
        return _redirect("/login")
    repo, gid, me = session
    try:
        est = int(estimate) if estimate.strip() else None
        repo.add_shopping_item(gid, name.strip(), me["id"],
                               estimate=est, note=note.strip())
    except (ValueError, sqlite3.IntegrityError) as e:
        return templates.TemplateResponse(
            request, "shopping.html",
            _shopping_context(request, repo, gid, me, error=str(e)))
    return _redirect("/list")


@router.post("/list/buy")
async def shopping_buy(request: Request):
    session = current(request)
    if session is None:
        return _redirect("/login")
    repo, gid, me = session
    form = await request.form()
    try:
        item_ids = [int(x) for x in form.get("item_ids", "").split(",") if x]
        items = repo.get_items(gid, item_ids)
        if len(items) != len(item_ids) or not items:
            raise ValueError("清單項目已變動，請重新勾選")
        amount = int(form["amount"])
        payer_id = int(form["payer_id"])
        member_ids = [m["id"] for m in repo.list_members(gid)]
        alloc = parse_split(form, member_ids, amount, payer_id)
        name = (items[0]["name"] if len(items) == 1
                else f"採買 {len(items)} 項")
        detail = "、".join(i["name"] for i in items)
        note = form.get("note", "").strip()
        if len(items) > 1:
            note = f"{detail}{'；' + note if note else ''}"
        eid = repo.record_expense(
            gid, name=name, amount=amount, payer_id=payer_id,
            allocations=alloc, category=form.get("category", "日用"),
            note=note, created_by=me["id"])
        repo.mark_items_bought(gid, item_ids, eid)
    except (SplitError, ValueError, KeyError, sqlite3.IntegrityError) as e:
        return templates.TemplateResponse(
            request, "shopping.html",
            _shopping_context(request, repo, gid, me, error=str(e)))
    return _redirect("/list")


@router.post("/list/{iid}/delete")
def shopping_delete(request: Request, iid: int):
    session = current(request)
    if session is None:
        return _redirect("/login")
    repo, gid, me = session
    try:
        repo.delete_shopping_item(iid, gid)
    except ValueError as e:
        return templates.TemplateResponse(
            request, "shopping.html",
            _shopping_context(request, repo, gid, me, error=str(e)))
    return _redirect("/list")


# -- 定期項目 -------------------------------------------------------------
def _recurring_context(request, repo, gid, me, error=""):
    members = repo.list_members(gid)
    mviews = member_views(members)
    today = _today()
    all_tpl = repo.list_templates(gid, include_inactive=True)
    due, upcoming, inactive = [], [], []
    for t in all_tpl:
        if not t["active"]:
            inactive.append(t)
        elif t["next_due"] <= today:
            due.append(t)
        else:
            upcoming.append(t)
    return {"request": request, "me": me, "members": mviews,
            "colors": _colors(mviews),
            "names": {m["id"]: m["name"] for m in members},
            "due": due, "upcoming": upcoming, "inactive": inactive,
            "due_days": {t["id"]: _days_overdue(t["next_due"], today)
                         for t in due},
            "cycle_labels": CYCLE_LABELS, "categories": CATEGORIES,
            "today": today, "error": error, "active_tab": "recurring"}


@router.get("/recurring")
def recurring_page(request: Request):
    session = current(request)
    if session is None:
        return _redirect("/login")
    repo, gid, me = session
    return templates.TemplateResponse(
        request, "recurring.html", _recurring_context(request, repo, gid, me))


@router.post("/recurring/add")
def recurring_add(request: Request, name: str = Form(...),
                  amount: str = Form(""), category: str = Form(""),
                  payer_id: int = Form(...), cycle: str = Form(...),
                  next_due: str = Form(...)):
    session = current(request)
    if session is None:
        return _redirect("/login")
    repo, gid, me = session
    try:
        amt = int(amount) if amount.strip() else None
        due_date = date.fromisoformat(next_due)
        repo.add_template(gid, name.strip(), payer_id, cycle,
                          due_date.day, next_due, amount=amt,
                          category=category)
    except (ValueError, sqlite3.IntegrityError) as e:
        return templates.TemplateResponse(
            request, "recurring.html",
            _recurring_context(request, repo, gid, me, error=str(e)))
    return _redirect("/recurring")


@router.post("/recurring/{tid}/skip")
def recurring_skip(request: Request, tid: int, back: str = Form("")):
    session = current(request)
    if session is None:
        return _redirect("/login")
    repo, gid, me = session
    try:
        repo.advance_template(tid, gid)
    except ValueError as e:
        return templates.TemplateResponse(
            request, "recurring.html",
            _recurring_context(request, repo, gid, me, error=str(e)))
    return _redirect(back if back in SAFE_BACK else "/recurring")


@router.post("/recurring/{tid}/toggle")
def recurring_toggle(request: Request, tid: int):
    session = current(request)
    if session is None:
        return _redirect("/login")
    repo, gid, me = session
    tpl = repo.get_template(tid, gid)
    if tpl is None:
        return _redirect("/recurring")
    repo.set_template_active(tid, gid, not tpl["active"])
    return _redirect("/recurring")


# -- transfers（結算的子頁：轉帳與預付）-----------------------------------
def _transfers_context(request, repo, gid, me, error=""):
    members = repo.list_members(gid)
    mviews = member_views(members)
    transfers = [e for e in repo.list_entries(gid) if e.kind == "transfer"]
    transfers.sort(key=lambda e: e.id, reverse=True)
    return {"request": request, "me": me, "members": mviews,
            "colors": _colors(mviews),
            "names": {m["id"]: m["name"] for m in members},
            "transfers": transfers, "error": error,
            "active_tab": "settlement"}


@router.get("/transfers")
def transfers_page(request: Request):
    session = current(request)
    if session is None:
        return _redirect("/login")
    repo, gid, me = session
    return templates.TemplateResponse(
        request, "transfers.html", _transfers_context(request, repo, gid, me))


@router.post("/transfers")
def create_transfer_route(request: Request, from_id: int = Form(...),
                          to_id: int = Form(...), amount: int = Form(...),
                          note: str = Form("")):
    session = current(request)
    if session is None:
        return _redirect("/login")
    repo, gid, me = session
    try:
        repo.record_transfer(gid, amount, from_id, to_id, "prepay",
                             name="預付款", note=note, created_by=me["id"])
    except (ValueError, sqlite3.IntegrityError) as e:
        return templates.TemplateResponse(
            request, "transfers.html",
            _transfers_context(request, repo, gid, me, error=str(e)))
    return _redirect("/transfers")


@router.post("/transfers/{eid}/delete")
def delete_transfer_route(request: Request, eid: int):
    session = current(request)
    if session is None:
        return _redirect("/login")
    repo, gid, me = session
    try:
        repo.soft_delete_entry(eid, gid)
    except ValueError as e:
        return templates.TemplateResponse(
            request, "transfers.html",
            _transfers_context(request, repo, gid, me, error=str(e)))
    return _redirect("/transfers")


# -- settlement -----------------------------------------------------------
def _live_plan(repo, gid):
    members = repo.list_members(gid)
    entries = repo.list_entries(gid)
    balances = compute_balances({m["id"] for m in members}, entries)
    return simplify_debts({mid: b.net for mid, b in balances.items()})


@router.get("/settlement")
def settlement_page(request: Request):
    session = current(request)
    if session is None:
        return _redirect("/login")
    repo, gid, me = session
    members = repo.list_members(gid, include_inactive=True)
    mviews = member_views(members)
    names = {m["id"]: m["name"] for m in members}
    error = ""
    plan = []
    try:
        plan = _live_plan(repo, gid)
    except Exception as e:
        error = str(e)
    snap = repo.latest_snapshot(gid)
    snapshot_view = None
    if snap is not None:
        payments = repo.payments_for_snapshot(snap.id)
        progress, unplanned = reconcile(snap.lines, payments)
        snapshot_view = {
            "snap": snap,
            "stale": repo.snapshot_is_stale(snap),
            "collectors": by_collector(progress),
            "unplanned": unplanned,
            "payments": payments,
        }
    return templates.TemplateResponse(request, "settlement.html", {
        "request": request, "me": me, "names": names,
        "colors": _colors(mviews), "plan": plan,
        "snapshot": snapshot_view, "error": error,
        "active_tab": "settlement",
    })


@router.post("/settlement/snapshot")
def create_snapshot_route(request: Request):
    session = current(request)
    if session is None:
        return _redirect("/login")
    repo, gid, me = session
    try:
        plan = _live_plan(repo, gid)
    except Exception:
        return _redirect("/settlement")
    repo.create_snapshot(gid, plan, created_by=me["id"])
    return _redirect("/settlement")


@router.post("/settlement/pay")
def record_payment_route(request: Request, from_id: int = Form(...),
                         to_id: int = Form(...), amount: int = Form(...),
                         snapshot_id: int = Form(...)):
    session = current(request)
    if session is None:
        return _redirect("/login")
    repo, gid, me = session
    member_ids = {m["id"] for m in repo.list_members(gid)}
    latest = repo.latest_snapshot(gid)
    if (from_id not in member_ids or to_id not in member_ids
            or latest is None or snapshot_id != latest.id):
        return _redirect("/settlement")
    try:
        repo.record_transfer(gid, amount, from_id, to_id, "settlement",
                             name="結算轉帳", created_by=me["id"],
                             snapshot_id=snapshot_id)
    except ValueError:
        return _redirect("/settlement")
    return _redirect("/settlement")


@router.post("/payments/{eid}/undo")
def undo_payment_route(request: Request, eid: int):
    session = current(request)
    if session is None:
        return _redirect("/login")
    repo, gid, me = session
    try:
        repo.soft_delete_entry(eid, gid)
    except ValueError:
        pass
    return _redirect("/settlement")
