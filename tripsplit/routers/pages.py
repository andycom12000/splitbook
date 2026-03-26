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
