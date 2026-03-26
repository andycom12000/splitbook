from fastapi import APIRouter, Request
from deps import templates

router = APIRouter()


@router.get("/")
def members_page(request: Request):
    try:
        from services.notion import get_all_members, get_all_expenses
        from services.settlement import compute_settlement
        members = get_all_members()
        expenses = get_all_expenses()
    except Exception as e:
        return templates.TemplateResponse("members.html", {
            "request": request, "members": [], "error": str(e),
            "needs_payment": [], "paid": [],
            "total": 0, "total_expense": 0, "paid_count": 0, "expense_count": 0,
            "active_tab": "members",
        })

    # Compute settlement to get net balances
    result = compute_settlement(members, expenses) if expenses else None

    if result:
        for m in members:
            totals = result["member_totals"].get(m["id"], {})
            m["owes"] = totals.get("owes", 0)
            m["owed"] = totals.get("owed", 0)
            m["net"] = totals.get("net", 0)
            m["details"] = totals.get("details", [])
    else:
        for m in members:
            m["owes"] = m["owed"] = m["net"] = 0
            m["details"] = []

    needs_payment = [m for m in members if m["payment_status"] != "已繳"]
    paid = [m for m in members if m["payment_status"] == "已繳"]
    total_expense = sum(e["amount"] for e in expenses) if expenses else 0

    return templates.TemplateResponse("members.html", {
        "request": request,
        "members": members,
        "needs_payment": needs_payment,
        "paid": paid,
        "total": len(members),
        "total_expense": total_expense,
        "paid_count": len(paid),
        "expense_count": len(expenses) if expenses else 0,
        "active_tab": "members",
    })


@router.get("/htmx/members")
def htmx_members(request: Request, filter: str = "all"):
    try:
        from services.notion import get_all_members
        members = get_all_members()
    except Exception:
        members = []
    if filter == "unpaid":
        members = [m for m in members if m["payment_status"] != "已繳"]
    elif filter == "paid":
        members = [m for m in members if m["payment_status"] == "已繳"]
    return templates.TemplateResponse("partials/member_list.html", {
        "request": request,
        "members": members,
    })


@router.get("/expenses")
def expenses_page(request: Request):
    try:
        from services.notion import get_all_members, get_all_expenses
        members = get_all_members()
        expenses = get_all_expenses()
    except Exception as e:
        return templates.TemplateResponse("expenses.html", {
            "request": request, "expenses": [], "members": [], "error": str(e),
            "active_tab": "expenses",
        })

    # Resolve payer names
    members_by_id = {m["id"]: m for m in members}
    for exp in expenses:
        payer = members_by_id.get(exp["payer_id"])
        exp["payer_name"] = payer["name"] if payer else "未知"
        # Compute per-person split for display
        from services.settlement import compute_settlement
        # Simple: count members matching expense tags
        participant_count = len(set(
            mid for m in members for mid in [m["id"]]
            if any(t in m["tags"] for t in exp["tags"])
        ))
        exp["per_person"] = exp["amount"] // participant_count if participant_count > 0 else 0
        exp["participant_count"] = participant_count

    # Sort by date descending
    expenses.sort(key=lambda x: x.get("date", ""), reverse=True)

    return templates.TemplateResponse("expenses.html", {
        "request": request,
        "expenses": expenses,
        "members": members,
        "active_tab": "expenses",
    })


@router.get("/settlement")
def settlement_page(request: Request):
    written = request.query_params.get("written")
    return templates.TemplateResponse("settlement.html", {
        "request": request,
        "active_tab": "settlement",
        "written": written,
    })


@router.get("/htmx/expense-form")
def htmx_expense_form(request: Request, id: str = None):
    try:
        from services.notion import get_all_members, get_all_expenses
        members = get_all_members()
        expense = None
        if id:
            expenses = get_all_expenses()
            expense = next((e for e in expenses if e["id"] == id), None)
    except Exception:
        members = []
        expense = None
    # Get unique tags from all members
    all_tags = sorted(set(t for m in members for t in m["tags"]))
    return templates.TemplateResponse("partials/expense_form.html", {
        "request": request,
        "members": members,
        "expense": expense,
        "all_tags": all_tags,
        "categories": ["民宿", "餐費", "保險", "酒水", "雜支"],
    })
